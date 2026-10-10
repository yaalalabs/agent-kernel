from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

import httpx

from ...core.util.factory import AKConfigError
from ..fetch import FetchedSpan, OTelSpanClassifier, SpanKind, TraceQuery


class TraceloopTraceFetcher:
    """
    Fetches spans from Traceloop through its warehouse REST API (``GET /v2/warehouse/spans``), with the
    same ``TRACELOOP_API_KEY`` / ``TRACELOOP_BASE_URL`` the SDK sends with. The SDK has no read client.

    Traceloop's free plan keeps spans for 24 hours only.
    """

    DEFAULT_BASE_URL = "https://api.traceloop.com"
    _PATH = "/v2/warehouse/spans"
    _PAGE_SIZE = 500
    _TIMEOUT = 60.0
    _SESSION_ATTRIBUTE = "traceloop.association.properties.session_id"
    # gen_ai.operation.name is set by both Traceloop's own and Pydantic AI's instrumentation
    _OPERATIONS = {
        SpanKind.AGENT: ["invoke_agent", "create_agent"],
        SpanKind.LLM: ["chat", "text_completion", "generate_content"],
        SpanKind.TOOL: ["execute_tool"],
    }

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        """
        :param api_key: Traceloop API key; defaults to ``TRACELOOP_API_KEY``.
        :param base_url: API base URL; defaults to ``TRACELOOP_BASE_URL`` or the Traceloop cloud.
        :param transport: Optional httpx transport (tests).
        """
        self._api_key = api_key or os.getenv("TRACELOOP_API_KEY")
        self._base_url = base_url or os.getenv("TRACELOOP_BASE_URL") or self.DEFAULT_BASE_URL
        self._transport = transport
        self._log = logging.getLogger("ak.trace.openllmetry.fetch")

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetches the spans matching the query, oldest first. When more than ``limit`` match, the most
        recent ones are kept.
        """
        if not self._api_key:
            raise AKConfigError("fetching Traceloop traces needs an API key; set TRACELOOP_API_KEY")
        start, end = query.window()
        spans: dict[str, FetchedSpan] = {}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=self._TIMEOUT, transport=self._transport) as client:
            for item in self._pages(client, self._params(query, start, end)):
                span = self._to_span(item)
                # server-side filters are best effort (attribute ids may be renamed by the backend), so re-check here
                if not query.accepts(span.kind) or (query.session_id and span.session_id != query.session_id):
                    continue
                spans.setdefault(span.span_id, span)
                if len(spans) >= query.limit:
                    break
        return FetchedSpan.oldest_first(spans.values())

    def _params(self, query: TraceQuery, start: datetime, end: datetime) -> dict[str, Any]:
        filters: list[dict[str, Any]] = []
        if query.kinds is not None and SpanKind.SPAN not in query.kinds:
            operations = [operation for kind in query.kinds for operation in self._OPERATIONS[kind]]
            filters.append({"id": "gen_ai.operation.name", "operator": "in", "value": operations})
        if query.session_id:
            filters.append({"id": self._SESSION_ATTRIBUTE, "operator": "equals", "value": query.session_id})
        if query.trace_ids:
            filters.append({"id": "trace_id", "operator": "in", "value": query.trace_ids})
        params: dict[str, Any] = {
            "from_timestamp_sec": int(start.timestamp()),
            "to_timestamp_sec": int(end.timestamp()),
            "limit": min(self._PAGE_SIZE, query.limit),
            "sort_by": "timestamp",
            "sort_order": "desc",
        }
        if query.name:
            params["span_name"] = query.name
        if filters:
            params["filters"] = json.dumps(filters)
        return params

    def _pages(self, client: httpx.Client, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        while True:
            response = client.get(self._PATH, params=params)
            response.raise_for_status()
            body = response.json()
            page = body.get("spans", body)
            yield from page.get("data") or []
            cursor = page.get("next_cursor")
            if not cursor or not page.get("data"):
                return
            params = {**params, "cursor": cursor}

    def _to_span(self, item: dict[str, Any]) -> FetchedSpan:
        attributes = item.get("span_attributes") or {}
        if isinstance(attributes, str):
            attributes = json.loads(attributes)
        start_time = self._timestamp(item.get("timestamp"))
        duration_ms = item.get("duration_ms") or item.get("duration")
        span_input, span_output = OTelSpanClassifier.io(attributes)
        return FetchedSpan(
            provider="traceloop",
            trace_id=item["trace_id"],
            span_id=item["span_id"],
            parent_span_id=item.get("parent_span_id") or None,
            name=item.get("span_name"),
            kind=OTelSpanClassifier.classify(attributes, item.get("span_name")),
            start_time=start_time,
            end_time=start_time + timedelta(milliseconds=float(duration_ms)) if start_time and duration_ms is not None else None,
            session_id=OTelSpanClassifier.session_id(attributes),
            usage=OTelSpanClassifier.usage(attributes),
            input=item.get("input") if item.get("input") is not None else span_input,
            output=item.get("output") if item.get("output") is not None else span_output,
            attributes=attributes,
            raw=item,
        )

    @staticmethod
    def _timestamp(value: Any) -> Optional[datetime]:
        """The warehouse timestamp format is undocumented: accept ISO strings and epoch s/ms/us/ns."""
        if value is None or value == "":
            return None
        if isinstance(value, str) and not value.lstrip("-").replace(".", "", 1).isdigit():
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        number = float(value)
        for threshold, divisor in ((1e17, 1e9), (1e14, 1e6), (1e11, 1e3)):
            if number > threshold:
                return datetime.fromtimestamp(number / divisor, tz=timezone.utc)
        return datetime.fromtimestamp(number, tz=timezone.utc)
