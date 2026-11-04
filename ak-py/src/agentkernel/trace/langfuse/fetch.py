from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Any, Iterable, Optional

from ..fetch import FetchedSpan, SpanKind, SpanStatus, SpanUsage, TraceFetcher, TraceQuery

if TYPE_CHECKING:
    from langfuse import Langfuse


class LangfuseTraceFetcher(TraceFetcher):
    """
    Fetches observations from Langfuse through the v2 observations API (``GET /api/public/v2/observations``).

    The v1 trace/observation read endpoints are being removed from Langfuse Cloud, so only v2 is used.
    """

    provider = "langfuse"
    _PAGE_SIZE = 100  # Langfuse caps a response at 5 MB, and io fields can be large
    _FIELDS = "core,basic,time,io,metadata,model,usage,metrics"
    # metadata values over 200 characters come back truncated unless their key is listed here
    _EXPAND_METADATA = "attributes"
    _TYPES = {SpanKind.AGENT: "AGENT", SpanKind.LLM: "GENERATION", SpanKind.TOOL: "TOOL"}
    _KINDS = {langfuse_type: kind for kind, langfuse_type in _TYPES.items()}

    def __init__(self, client: Langfuse):
        """
        :param client: The authenticated Langfuse client the tracer already sends with.
        """
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.fetch")

    def _query_provider(self, query: TraceQuery) -> Iterable[FetchedSpan]:
        """
        Each requested kind and trace id is a separate paginated request, because the v2 API's direct
        parameters take a single value each. Langfuse pages newest first, so each request keeps the most
        recent observations.
        """
        spans: list[FetchedSpan] = []
        for langfuse_type in self._types(query):
            for trace_id in query.trace_ids or [None]:
                spans.extend(self._fetch_by_cursor(query, partial(self._fetch_page, query, langfuse_type, trace_id), self._to_span))
        return spans

    def _types(self, query: TraceQuery) -> list[Optional[str]]:
        # OTHER means "everything Langfuse doesn't type as agent/llm/tool", which no single type covers
        if query.kinds is None or SpanKind.OTHER in query.kinds:
            return [None]
        return [self._TYPES[kind] for kind in query.kinds]

    def _fetch_page(
        self, query: TraceQuery, langfuse_type: Optional[str], trace_id: Optional[str], cursor: Optional[str]
    ) -> tuple[list[Any], Optional[str]]:
        start, end = query.window()
        response = self._client.api.observations.get_many(
            fields=self._FIELDS,
            expand_metadata=self._EXPAND_METADATA,
            limit=min(self._PAGE_SIZE, query.limit),
            cursor=cursor,
            type=langfuse_type,
            trace_id=trace_id,
            session_id=query.session_id,
            name=query.name,
            from_start_time=start,
            to_start_time=end,
        )
        return list(response.data), response.meta.cursor

    @staticmethod
    def _usage(observation: Any) -> Optional[SpanUsage]:
        """Langfuse's own usage and cost (``fields=usage``): it prices model calls server side."""
        usage = getattr(observation, "usage_details", None) or {}
        costs = getattr(observation, "cost_details", None) or {}
        total_cost = getattr(observation, "total_cost", None)
        return SpanUsage.of(
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
            total_tokens=usage.get("total"),
            cost=total_cost if total_cost is not None else costs.get("total"),
        )

    def _to_span(self, observation: Any) -> FetchedSpan:
        metadata = getattr(observation, "metadata", None)
        attributes = metadata.get("attributes", metadata) if isinstance(metadata, dict) else {}
        return FetchedSpan(
            provider=self.provider,
            trace_id=observation.trace_id,
            span_id=observation.id,
            parent_span_id=observation.parent_observation_id,
            name=observation.name,
            kind=self._KINDS.get(observation.type, SpanKind.OTHER),
            status=SpanStatus.ERROR if str(getattr(observation, "level", None)).upper().endswith("ERROR") else SpanStatus.UNSET,
            start_time=observation.start_time,
            end_time=observation.end_time,
            session_id=getattr(observation, "session_id", None),
            usage=self._usage(observation),
            input=getattr(observation, "input", None),
            output=getattr(observation, "output", None),
            attributes=attributes if isinstance(attributes, dict) else {},
            raw=observation.model_dump(mode="json", exclude_none=True) if hasattr(observation, "model_dump") else {},
        )
