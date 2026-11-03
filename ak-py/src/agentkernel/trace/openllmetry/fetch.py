from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any, Iterable, Optional

import httpx

from ...core.util.factory import AKConfigError
from ..fetch import FetchedSpan, OTelSpanClassifier, SpanStatus, TraceFetcher, TraceQuery


class TraceloopTraceFetcher(TraceFetcher):
    """
    Fetches spans from Traceloop through its warehouse REST API (``GET /v2/warehouse/spans``), with the
    same ``TRACELOOP_API_KEY`` / ``TRACELOOP_BASE_URL`` the SDK sends with. The SDK has no read client.

    Kinds are filtered locally only: a span's kind can come from ``gen_ai.operation.name`` or
    ``traceloop.span.kind``, and the ``filters`` API has no OR across attribute ids.

    Traceloop's free plan keeps spans for 24 hours only.
    """

    provider = "openllmetry"
    DEFAULT_BASE_URL = "https://api.traceloop.com"
    _PATH = "/v2/warehouse/spans"
    _PAGE_SIZE = 500
    _TIMEOUT = 60.0
    _SESSION_ATTRIBUTE = "traceloop.association.properties.session_id"

    def __init__(self, api_key: Optional[str], base_url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        """
        :param api_key: Traceloop API key (``TRACELOOP_API_KEY``, which the tracer resolves).
        :param base_url: API base URL; defaults to the Traceloop cloud.
        :param transport: Optional httpx transport (tests).
        :raises AKConfigError: If the API key is missing.
        """
        if not api_key:
            raise AKConfigError("fetching Traceloop traces needs an API key; set TRACELOOP_API_KEY")
        self._api_key = api_key
        self._base_url = base_url or self.DEFAULT_BASE_URL
        self._transport = transport
        self._log = logging.getLogger("ak.trace.openllmetry.fetch")

    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        with httpx.Client(base_url=self._base_url, headers=headers, timeout=self._TIMEOUT, transport=self._transport) as client:
            return self._fetch_by_cursor(query, partial(self._fetch_page, client, self._params(query)), self._to_span)

    def _params(self, query: TraceQuery) -> dict[str, Any]:
        start, end = query.window()
        filters: list[dict[str, Any]] = []
        if query.session_id:
            filters.append({"id": self._SESSION_ATTRIBUTE, "operator": "equals", "value": query.session_id})
        if query.trace_ids:
            # The API reference puts an "in" list in "value", but the API rejects that (400) and reads "values"
            filters.append({"id": "trace_id", "operator": "in", "values": query.trace_ids})
        params: dict[str, Any] = {
            "from_timestamp_sec": int(start.timestamp()),
            "to_timestamp_sec": math.ceil(end.timestamp()),  # whole seconds; the exact end is applied locally
            "limit": min(self._PAGE_SIZE, query.limit),
            # Newest first. No sort_by: although documented, every sort_by value (timestamp included) makes the
            # API return no spans, while sort_order alone orders by timestamp (both checked live, 2026-10).
            "sort_order": "DESC",
        }
        if query.name:
            params["span_name"] = query.name
        if filters:
            params["filters"] = json.dumps(filters)
        return params

    def _fetch_page(self, client: httpx.Client, params: dict[str, Any], cursor: Optional[str]) -> tuple[list[dict[str, Any]], Optional[str]]:
        response = client.get(self._PATH, params={**params, "cursor": cursor} if cursor else params)
        response.raise_for_status()
        body = response.json()
        spans_page = body.get("spans", body)
        return spans_page.get("data") or [], spans_page.get("next_cursor")

    def _to_span(self, item: dict[str, Any]) -> FetchedSpan:
        attributes = item.get("span_attributes") or {}
        if isinstance(attributes, str):
            attributes = json.loads(attributes)
        start_time = self._timestamp(item.get("timestamp"))
        duration_ms = item.get("duration_ms")
        if duration_ms is None:
            duration_ms = item.get("duration")
        span_input, span_output = OTelSpanClassifier.io(attributes)
        return FetchedSpan(
            provider=self.provider,
            trace_id=item["trace_id"],
            span_id=item["span_id"],
            parent_span_id=item.get("parent_span_id") or None,
            name=item.get("span_name"),
            kind=OTelSpanClassifier.classify(attributes, item.get("span_name")),
            # the warehouse's status field name is undocumented: accept the OTel-style names
            status=SpanStatus.of(item.get("status_code") or item.get("status")),
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
