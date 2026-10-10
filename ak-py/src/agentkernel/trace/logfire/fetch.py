from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from ...core.util.factory import AKConfigError
from ..fetch import FetchedSpan, OTelSpanClassifier, SpanKind, TraceQuery


class LogfireTraceFetcher:
    """
    Fetches spans from Logfire through its SQL Query API, using a project read token
    (``LOGFIRE_READ_TOKEN``; the write token used for sending cannot read).

    Logfire returns at most 10,000 rows per query and has no cursor, so larger fetches page
    backwards on ``start_timestamp``. Data becomes queryable a few minutes after ingestion.
    """

    READ_TOKEN_ENV = "LOGFIRE_READ_TOKEN"
    _MAX_ROWS = 10_000
    _COLUMNS = "trace_id, span_id, parent_span_id, span_name, message, start_timestamp, end_timestamp, attributes, tags, otel_scope_name"

    # SQL equivalents of OTelSpanClassifier, so kind filtering happens server side
    _KIND_SQL = {
        SpanKind.TOOL: "(attributes->>'gen_ai.operation.name' = 'execute_tool' OR attributes->>'openinference.span.kind' = 'TOOL' "
        "OR span_name LIKE 'Function:%')",
        SpanKind.LLM: "(attributes->>'gen_ai.operation.name' IN ('chat', 'text_completion', 'generate_content') "
        "OR attributes->>'openinference.span.kind' = 'LLM' OR array_has(tags, 'LLM'))",
        SpanKind.AGENT: "(attributes->>'gen_ai.operation.name' IN ('invoke_agent', 'create_agent') "
        "OR attributes->>'openinference.span.kind' = 'AGENT' OR span_name LIKE 'Agent run:%')",
    }

    def __init__(self, read_token: Optional[str] = None, base_url: Optional[str] = None):
        """
        :param read_token: Logfire read token; defaults to ``LOGFIRE_READ_TOKEN``.
        :param base_url: Query API base URL; defaults to the region encoded in the token.
        """
        self._read_token = read_token or os.getenv(self.READ_TOKEN_ENV)
        self._base_url = base_url
        self._log = logging.getLogger("ak.trace.logfire.fetch")

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetches the spans matching the query, oldest first. When more than ``limit`` match, the most
        recent ones are kept.
        """
        if not self._read_token:
            raise AKConfigError(f"fetching Logfire traces needs a read token; set {self.READ_TOKEN_ENV} (logfire read-tokens create)")
        from logfire.experimental.query_client import LogfireQueryClient

        start, end = query.window()
        spans: dict[str, FetchedSpan] = {}
        seen: set[str] = set()
        before: Optional[datetime] = None
        with LogfireQueryClient(read_token=self._read_token, base_url=self._base_url) as client:
            while len(spans) < query.limit:
                page = min(self._MAX_ROWS, query.limit - len(spans))
                rows = client.query_json_rows(sql=self._sql(query, page, before), min_timestamp=start, max_timestamp=end, limit=page)["rows"]
                fresh = [span for span in map(self._to_span, rows) if span.span_id not in seen]
                seen.update(span.span_id for span in fresh)
                for span in fresh:
                    if query.accepts(span.kind):
                        span.session_id = span.session_id or query.session_id
                        spans[span.span_id] = span
                # rows sharing the boundary timestamp are re-read on the next page and skipped by span id
                before = min((span.start_time for span in fresh if span.start_time), default=None)
                if len(rows) < page or before is None:
                    break
        return FetchedSpan.oldest_first(spans.values())[-query.limit :]

    def _sql(self, query: TraceQuery, limit: int, before: Optional[datetime]) -> str:
        conditions = ["kind = 'span'"]
        if query.kinds is not None and SpanKind.SPAN not in query.kinds:
            conditions.append("(" + " OR ".join(self._KIND_SQL[kind] for kind in query.kinds) + ")")
        elif query.kinds is not None:
            others = " OR ".join(self._KIND_SQL.values())
            wanted = [self._KIND_SQL[kind] for kind in query.kinds if kind != SpanKind.SPAN]
            conditions.append("(" + " OR ".join([f"NOT COALESCE({others}, false)", *wanted]) + ")")
        if query.name:
            conditions.append(f"(span_name = {self._literal(query.name)} OR message = {self._literal(query.name)})")
        if query.trace_ids:
            conditions.append(f"trace_id IN ({', '.join(map(self._literal, query.trace_ids))})")
        if query.session_id:
            # AK sets session_id on its wrapper span only, so match every span of those traces
            conditions.append(f"trace_id IN (SELECT trace_id FROM records WHERE attributes->>'session_id' = {self._literal(query.session_id)})")
        if before is not None:
            conditions.append(f"start_timestamp <= {self._literal(before.isoformat())}")
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
            provider="logfire",
            trace_id=row["trace_id"],
            span_id=row["span_id"],
            parent_span_id=row.get("parent_span_id"),
            name=row.get("message") or row.get("span_name"),
            kind=OTelSpanClassifier.classify(classify_attributes, row.get("span_name")),
            start_time=row.get("start_timestamp"),
            end_time=row.get("end_timestamp"),
            session_id=OTelSpanClassifier.session_id(attributes),
            usage=OTelSpanClassifier.usage(attributes),
            input=span_input,
            output=span_output,
            attributes=attributes,
            raw=row,
        )
