from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional

from ..fetch import FetchedSpan, SpanKind, SpanUsage, TraceQuery

if TYPE_CHECKING:
    from langfuse import Langfuse


class LangfuseTraceFetcher:
    """
    Fetches observations from Langfuse through the v2 observations API (``GET /api/public/v2/observations``).

    The v1 trace/observation read endpoints are being removed from Langfuse Cloud, so only v2 is used.
    """

    _PAGE_SIZE = 100  # Langfuse caps a response at 5 MB, and io fields can be large
    _FIELDS = "core,basic,time,io,metadata,model,usage,metrics"
    _TYPES = {SpanKind.AGENT: "AGENT", SpanKind.LLM: "GENERATION", SpanKind.TOOL: "TOOL"}
    _KINDS = {langfuse_type: kind for kind, langfuse_type in _TYPES.items()}

    def __init__(self, client: Langfuse):
        """
        :param client: The authenticated Langfuse client the tracer already sends with.
        """
        self._client = client
        self._log = logging.getLogger("ak.trace.langfuse.fetch")

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        """
        Fetches the observations matching the query, oldest first. Langfuse pages newest first, so a
        ``limit`` cut keeps the most recent observations.

        Each requested kind and trace id is a separate paginated request, because the v2 API's direct
        parameters take a single value each.
        """
        start, end = query.window()
        spans: dict[str, FetchedSpan] = {}
        for langfuse_type in self._types(query):
            for trace_id in query.trace_ids or [None]:
                matched = 0
                for observation in self._pages(query, start, end, langfuse_type, trace_id):
                    span = self._to_span(observation)
                    if not query.accepts(span.kind):
                        continue
                    spans.setdefault(span.span_id, span)
                    matched += 1
                    if matched >= query.limit:
                        break
        return FetchedSpan.oldest_first(spans.values())[-query.limit :]

    def _types(self, query: TraceQuery) -> list[Optional[str]]:
        # SPAN means "everything Langfuse doesn't type as agent/llm/tool", which no single type covers
        if query.kinds is None or SpanKind.SPAN in query.kinds:
            return [None]
        return [self._TYPES[kind] for kind in query.kinds]

    def _pages(self, query: TraceQuery, start, end, langfuse_type: Optional[str], trace_id: Optional[str]) -> Iterator[Any]:
        cursor = None
        while True:
            response = self._client.api.observations.get_many(
                fields=self._FIELDS,
                limit=min(self._PAGE_SIZE, query.limit),
                cursor=cursor,
                type=langfuse_type,
                trace_id=trace_id,
                session_id=query.session_id,
                name=query.name,
                from_start_time=start,
                to_start_time=end,
            )
            yield from response.data
            cursor = response.meta.cursor
            if not cursor or not response.data:
                return

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
            provider="langfuse",
            trace_id=observation.trace_id,
            span_id=observation.id,
            parent_span_id=observation.parent_observation_id,
            name=observation.name,
            kind=self._KINDS.get(observation.type, SpanKind.SPAN),
            start_time=observation.start_time,
            end_time=observation.end_time,
            session_id=getattr(observation, "session_id", None),
            usage=self._usage(observation),
            input=getattr(observation, "input", None),
            output=getattr(observation, "output", None),
            attributes=attributes if isinstance(attributes, dict) else {},
            raw=observation.model_dump(mode="json", exclude_none=True) if hasattr(observation, "model_dump") else {},
        )
