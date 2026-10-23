from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Iterable, Optional

from ...core.util.factory import AKConfigError
from ..fetch import FetchedSpan, OTelSpanClassifier, SpanKind, SpanStatus, TraceFetcher, TraceQuery


class CloudWatchTraceFetcher(TraceFetcher):
    """
    Fetches spans from the ``aws/spans`` log group, where Transaction Search stores every span sent to
    X-Ray as OpenTelemetry JSON, through CloudWatch Logs Insights. Credentials and region come from the
    standard AWS chain; the identity needs ``logs:StartQuery``, ``logs:GetQueryResults`` and
    ``logs:StopQuery`` on the log group.

    Logs Insights returns at most 10,000 rows per query and has no cursor, so larger fetches page
    backwards on ``@timestamp``.
    """

    provider = "cloudwatch"
    LOG_GROUP = "aws/spans"
    _MAX_ROWS = 10_000
    _POLL_INTERVAL = 1.0
    # @timestamp is not documented as the span start, so the query range runs past the window end and the
    # window is applied to startTimeUnixNano locally
    _END_PADDING = timedelta(minutes=15)
    _FAILED = {"Failed", "Cancelled", "Timeout", "Unknown"}

    # Logs Insights equivalents of OTelSpanClassifier for the conventions CloudWatch runners emit
    # (OpenInference instrumentors, Pydantic AI GenAI spans), so kind filtering happens server side.
    # Traceloop (traceloop.span.kind) and Logfire (message template, tags) kinds are not matched: a
    # kinds= fetch skips such spans, which only custom instrumentation sends to CloudWatch
    _KIND_FILTERS = {
        SpanKind.TOOL: '(attributes.gen_ai.operation.name = "execute_tool" or attributes.openinference.span.kind = "TOOL")',
        SpanKind.LLM: '(attributes.gen_ai.operation.name in ["chat", "text_completion", "generate_content"] '
        'or attributes.openinference.span.kind = "LLM")',
        SpanKind.AGENT: '(attributes.gen_ai.operation.name in ["invoke_agent", "create_agent"] or attributes.openinference.span.kind = "AGENT")',
    }

    def __init__(self, client: Any = None, region: Optional[str] = None, log_group: str = LOG_GROUP, timeout: float = 120.0):
        """
        :param client: A botocore CloudWatch Logs client; defaults to one built from the standard AWS chain.
        :param region: The AWS region to query; defaults to AWS_REGION, then the botocore chain.
        :param log_group: The log group holding the spans.
        :param timeout: Seconds to wait for one Logs Insights query before stopping it.
        """
        self._client = client
        self._region = region
        self._log_group = log_group
        self._timeout = timeout
        self._log = logging.getLogger("ak.trace.cloudwatch.fetch")

    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]:
        client = self._client or self._create_client()
        _, end = query.window()
        # each query's endTime is ceil(upper_bound), so rows in the boundary second are re-read and dropped as seen
        upper_bound = max(end, min(end + self._END_PADDING, datetime.now(timezone.utc)))
        return self._fetch_by_time_window(
            query, upper_bound=upper_bound, max_rows_per_request=self._MAX_ROWS, fetch_page=partial(self._fetch_page, client, query)
        )

    def _fetch_page(self, client: Any, query: TraceQuery, page_size: int, upper_bound: datetime) -> list[tuple[Optional[datetime], FetchedSpan]]:
        start, _ = query.window()
        return [self._to_span(row) for row in self._run(client, self._insights(query, page_size), start, upper_bound)]

    def _create_client(self) -> Any:
        from botocore.session import Session as BotocoreSession

        from .cloudwatch import CloudWatch

        botocore_session = BotocoreSession()
        region = self._region or CloudWatch.region(botocore_session)
        if not region:
            raise AKConfigError("fetching CloudWatch traces needs an AWS region; set AWS_REGION")
        return botocore_session.create_client("logs", region_name=region)

    def _run(self, client: Any, query_string: str, start: datetime, end: datetime) -> list[dict[str, str]]:
        """
        Runs one Logs Insights query and waits for its rows, each as a {field: value} dict.
        """
        from botocore.exceptions import ClientError

        try:
            query_id = client.start_query(
                logGroupName=self._log_group,
                startTime=math.floor(start.timestamp()),
                endTime=math.ceil(end.timestamp()),
                queryString=query_string,
            )["queryId"]
        except ClientError as exc:
            # aws/spans exists only once Transaction Search is on and spans have reached X-Ray
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                raise AKConfigError(
                    f"CloudWatch log group {self._log_group!r} not found in this account and region; enable CloudWatch "
                    "Transaction Search so spans sent to X-Ray are stored there, and make sure the spans reach X-Ray "
                    "(the default trace.type: cloudwatch export does; a collector must forward to X-Ray)"
                ) from exc
            raise
        deadline = time.monotonic() + self._timeout
        while True:
            result = client.get_query_results(queryId=query_id)
            status = result.get("status")
            if status == "Complete":
                return [{cell["field"]: cell.get("value") for cell in row} for row in result.get("results", [])]
            if status in self._FAILED:
                raise RuntimeError(f"CloudWatch Logs Insights query on {self._log_group} ended with status {status}")
            if time.monotonic() >= deadline:
                client.stop_query(queryId=query_id)
                raise TimeoutError(f"CloudWatch Logs Insights query on {self._log_group} did not finish within {self._timeout}s")
            time.sleep(self._POLL_INTERVAL)

    def _insights(self, query: TraceQuery, limit: int) -> str:
        filters = []
        if query.kinds is not None and SpanKind.OTHER not in query.kinds:
            filters.append(" or ".join(self._KIND_FILTERS[kind] for kind in query.kinds))
        if query.name:
            filters.append(f"name = {self._literal(query.name)}")
        if query.trace_ids:
            filters.append(f"traceId in [{', '.join(map(self._literal, query.trace_ids))}]")
        if query.session_id:
            # the CloudWatch tracer stamps session.id onto every span of a run (cloudwatch.SessionSpanProcessor)
            filters.append(f"attributes.session.id = {self._literal(query.session_id)}")
        lines = ["fields @timestamp, @message", *(f"filter {condition}" for condition in filters), "sort @timestamp desc", f"limit {limit}"]
        return " | ".join(lines)

    @staticmethod
    def _literal(value: str) -> str:
        return json.dumps(str(value))

    def _to_span(self, row: dict[str, str]) -> tuple[Optional[datetime], FetchedSpan]:
        record = json.loads(row["@message"])
        attributes = self._flatten(record.get("attributes") or {})
        span_input, span_output = OTelSpanClassifier.io(attributes)
        span = FetchedSpan(
            provider=self.provider,
            trace_id=record["traceId"],
            span_id=record["spanId"],
            parent_span_id=record.get("parentSpanId") or None,
            name=record.get("name"),
            kind=OTelSpanClassifier.classify(attributes, record.get("name")),
            status=SpanStatus.of((record.get("status") or {}).get("code") if isinstance(record.get("status"), dict) else record.get("status")),
            start_time=self._nanos(record.get("startTimeUnixNano")),
            end_time=self._nanos(record.get("endTimeUnixNano")),
            session_id=OTelSpanClassifier.session_id(attributes),
            usage=OTelSpanClassifier.usage(attributes),
            input=span_input,
            output=span_output,
            attributes=attributes,
            raw=record,
        )
        return self._stamp(row.get("@timestamp")), span

    @classmethod
    def _flatten(cls, attributes: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """
        Dotted attribute keys, whether the record stores them flat ("session.id") or nested.
        """
        flat: dict[str, Any] = {}
        for key, value in attributes.items():
            if isinstance(value, dict):
                flat.update(cls._flatten(value, f"{prefix}{key}."))
            else:
                flat[f"{prefix}{key}"] = value
        return flat

    @staticmethod
    def _nanos(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        return datetime.fromtimestamp(int(value) / 1e9, tz=timezone.utc)

    @staticmethod
    def _stamp(value: Optional[str]) -> Optional[datetime]:
        """
        Logs Insights reports @timestamp in UTC as "YYYY-MM-DD HH:MM:SS.mmm".
        """
        if not value:
            return None
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
