from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import partial
from typing import Any, Iterable, Optional

from ...core.util.factory import AKConfigError
from ..fetch import FetchedSpan, OTelSpanClassifier, SpanKind, SpanStatus, TraceFetcher, TraceQuery


class LogfireTraceFetcher(TraceFetcher):
    """
    Fetches spans from Logfire through its SQL Query API, using a project read token
    (``LOGFIRE_READ_TOKEN``; the write token used for sending cannot read).

    Logfire returns at most 10,000 rows per query and has no cursor, so larger fetches page
    backwards on ``start_timestamp``. Data becomes queryable a few minutes after ingestion.
    """

    provider = "logfire"
    READ_TOKEN_ENV = "LOGFIRE_READ_TOKEN"
    _MAX_ROWS = 10_000
    _COLUMNS = (
        "trace_id, span_id, parent_span_id, span_name, message, start_timestamp, end_timestamp, attributes, tags, otel_status_code, otel_scope_name"
    )

    # SQL equivalents of OTelSpanClassifier, so kind filtering happens server side
    _KIND_SQL = {
        SpanKind.TOOL: "(attributes->>'gen_ai.operation.name' = 'execute_tool' OR attributes->>'openinference.span.kind' = 'TOOL' "
        "OR span_name LIKE 'Function:%')",
        SpanKind.LLM: "(attributes->>'gen_ai.operation.name' IN ('chat', 'text_completion', 'generate_content') "
        "OR attributes->>'openinference.span.kind' = 'LLM' OR array_has(tags, 'LLM'))",
        SpanKind.AGENT: "(attributes->>'gen_ai.operation.name' IN ('invoke_agent', 'create_agent') "
        "OR attributes->>'openinference.span.kind' = 'AGENT' OR span_name LIKE 'Agent run:%')",
    }

    def __init__(self, read_token: Optional[str], base_url: Optional[str] = None):
        """
        :param read_token: Logfire read token (``LOGFIRE_READ_TOKEN``, which the tracer resolves).
        :param base_url: Query API base URL; defaults to the region encoded in the token.
        :raises AKConfigError: If the read token is missing.
        """
        if not read_token:
            raise AKConfigError(f"fetching Logfire traces needs a read token; set {self.READ_TOKEN_ENV} (logfire read-tokens create)")
        self._read_token = read_token
        self._base_url = base_url
        self._log = logging.getLogger("ak.trace.logfire.fetch")

    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]:
        _, end = query.window()
        with self._query_client_class()(read_token=self._read_token, base_url=self._base_url) as client:
            return self._fetch_by_time_window(
                query, upper_bound=end, max_rows_per_request=self._MAX_ROWS, fetch_page=partial(self._fetch_page, client, query)
            )

    @staticmethod
    def _query_client_class() -> type:
        """
        Logfire's query client: ``logfire.query_client`` from logfire 5, ``logfire.experimental.query_client`` before.
        """
        try:
            from logfire.query_client import LogfireQueryClient
        except ImportError:
            from logfire.experimental.query_client import LogfireQueryClient
        return LogfireQueryClient

    def _fetch_page(self, client: Any, query: TraceQuery, page_size: int, upper_bound: datetime) -> list[tuple[Optional[datetime], FetchedSpan]]:
        # whether max_timestamp is inclusive is undocumented; matches() applies the exclusive end either way
        start, end = query.window()
        rows = client.query_json_rows(sql=self._sql(query, page_size, upper_bound), min_timestamp=start, max_timestamp=end, limit=page_size)["rows"]
        return [(span.start_time, span) for span in map(self._to_span, rows)]

    def _sql(self, query: TraceQuery, limit: int, upper_bound: datetime) -> str:
        conditions = ["kind = 'span'"]
        if query.kinds is not None and SpanKind.OTHER not in query.kinds:
            conditions.append("(" + " OR ".join(self._KIND_SQL[kind] for kind in query.kinds) + ")")
        elif query.kinds is not None:
            others = " OR ".join(self._KIND_SQL.values())
            wanted = [self._KIND_SQL[kind] for kind in query.kinds if kind != SpanKind.OTHER]
            conditions.append("(" + " OR ".join([f"NOT COALESCE({others}, false)", *wanted]) + ")")
        if query.name:
            # the same value _to_span writes to name, so matches() keeps every row this selects
            conditions.append(f"COALESCE(message, span_name) = {self._literal(query.name)}")
        if query.trace_ids:
            conditions.append(f"trace_id IN ({', '.join(map(self._literal, query.trace_ids))})")
        if query.session_id:
            # AK sets session_id on its wrapper span only, so match every span of those traces
            conditions.append(f"trace_id IN (SELECT trace_id FROM records WHERE attributes->>'session_id' = {self._literal(query.session_id)})")
        conditions.append(f"start_timestamp <= {self._literal(upper_bound.isoformat())}")
        return f"SELECT {self._COLUMNS} FROM records WHERE {' AND '.join(conditions)} ORDER BY start_timestamp DESC LIMIT {limit}"

    @staticmethod
    def _literal(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _to_span(self, row: dict[str, Any]) -> FetchedSpan:
        attributes = row.get("attributes") or {}
        if isinstance(attributes, str):
            attributes = json.loads(attributes)
        # Logfire stores the message template as span_name and tags in their own column
        classify_attributes = {**attributes, "logfire.msg_template": row.get("span_name"), "logfire.tags": row.get("tags") or []}
        span_input, span_output = OTelSpanClassifier.io(attributes)
        return FetchedSpan(
            provider=self.provider,
            trace_id=row["trace_id"],
            span_id=row["span_id"],
            parent_span_id=row.get("parent_span_id"),
            name=row.get("message") or row.get("span_name"),
            kind=OTelSpanClassifier.classify(classify_attributes, row.get("span_name")),
            status=SpanStatus.of(row.get("otel_status_code")),
            start_time=row.get("start_timestamp"),
            end_time=row.get("end_timestamp"),
            session_id=OTelSpanClassifier.session_id(attributes),
            usage=OTelSpanClassifier.usage(attributes),
            input=span_input,
            output=span_output,
            attributes=attributes,
            raw=row,
        )
