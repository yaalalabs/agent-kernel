"""TraceFetchContract runs against a bring-your-own tracer and the built-in fetchers whose backends can be
faked faithfully (Langfuse, Traceloop). Logfire (SQL) and CloudWatch (Logs Insights) are not run here: a
faithful fake would re-implement their query languages, so test_trace_fetch.py checks their query
translation instead."""

import json
import types

import httpx
import pytest

from agentkernel.trace import FetchedSpan, SpanKind, TraceQuery
from agentkernel.trace.base import BaseTrace
from agentkernel.trace.openllmetry.fetch import TraceloopTraceFetcher
from agentkernel.trace.testing import TraceFetchContract

# --- bring your own --------------------------------------------------------------------------------------


class InMemoryTrace(BaseTrace):
    """A minimal bring-your-own tracer that keeps its spans in memory and supports fetch."""

    def __init__(self):
        self.spans: list[FetchedSpan] = []

    def init(self):
        pass

    def openai(self):
        return None

    def langgraph(self):
        return None

    def crewai(self):
        return None

    def adk(self):
        return None

    def smolagents(self):
        return None

    def pydanticai(self):
        return None

    def fetch(self, query: TraceQuery) -> list[FetchedSpan]:
        return FetchedSpan.oldest_first(span for span in self.spans if query.matches(span))[-query.limit :]


class TestInMemoryTraceContract(TraceFetchContract):
    @pytest.fixture
    def tracer(self):
        return InMemoryTrace()

    def seed(self, tracer, spans):
        tracer.spans = list(spans)


# --- Langfuse ---------------------------------------------------------------------------------------------


class _FakeObservations:
    """Langfuse's v2 get_many: single-value filters, newest first, cursor pages."""

    _TYPES = {SpanKind.AGENT: "AGENT", SpanKind.LLM: "GENERATION", SpanKind.TOOL: "TOOL", SpanKind.SPAN: "SPAN"}

    def __init__(self):
        self.observations = []

    def load(self, spans):
        self.observations = [
            types.SimpleNamespace(
                id=span.span_id,
                trace_id=span.trace_id,
                parent_observation_id=span.parent_span_id,
                name=span.name,
                type=self._TYPES[span.kind],
                start_time=span.start_time,
                end_time=span.end_time,
                session_id=span.session_id,
            )
            for span in spans
        ]

    def get_many(self, *, limit, cursor=None, type=None, trace_id=None, session_id=None, name=None, from_start_time=None, to_start_time=None, **_):
        matched = [
            observation
            for observation in self.observations
            if (type is None or observation.type == type)
            and (trace_id is None or observation.trace_id == trace_id)
            and (session_id is None or observation.session_id == session_id)
            and (name is None or observation.name == name)
            # both bounds inclusive: the fetcher must apply the exclusive end itself
            and (from_start_time is None or observation.start_time >= from_start_time)
            and (to_start_time is None or observation.start_time <= to_start_time)
        ]
        matched.sort(key=lambda observation: observation.start_time, reverse=True)
        offset = int(cursor or 0)
        page = matched[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(matched) else None
        return types.SimpleNamespace(data=page, meta=types.SimpleNamespace(cursor=next_cursor))


class TestLangfuseFetchContract(TraceFetchContract):
    @pytest.fixture
    def tracer(self):
        from agentkernel.trace.langfuse.langfuse import LangFuse

        tracer = LangFuse()
        tracer._client = types.SimpleNamespace(api=types.SimpleNamespace(observations=_FakeObservations()))
        return tracer

    def seed(self, tracer, spans):
        tracer._client.api.observations.load(spans)


# --- Traceloop --------------------------------------------------------------------------------------------


class _FakeWarehouse:
    """Traceloop's warehouse spans API: whole-second bounds, JSON filters, newest first, cursor pages."""

    _OPERATIONS = {SpanKind.AGENT: "invoke_agent", SpanKind.LLM: "chat", SpanKind.TOOL: "execute_tool"}

    def __init__(self):
        self.items = []

    def load(self, spans):
        self.items = []
        for span in spans:
            attributes = {"traceloop.association.properties.session_id": span.session_id}
            if span.kind in self._OPERATIONS:
                attributes["gen_ai.operation.name"] = self._OPERATIONS[span.kind]
            self.items.append(
                {
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "parent_span_id": "",
                    "span_name": span.name,
                    "timestamp": int(span.start_time.timestamp() * 1000),
                    "duration_ms": 30_000,
                    "span_attributes": attributes,
                }
            )

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        low, high = int(params["from_timestamp_sec"]) * 1000, int(params["to_timestamp_sec"]) * 1000
        matched = [item for item in self.items if low <= item["timestamp"] <= high]
        if "span_name" in params:
            matched = [item for item in matched if item["span_name"] == params["span_name"]]
        for condition in json.loads(params.get("filters", "[]")):
            matched = [item for item in matched if self._passes(item, condition)]
        matched.sort(key=lambda item: item["timestamp"], reverse=True)
        offset, limit = int(params.get("cursor", 0)), int(params["limit"])
        page = matched[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(matched) else None
        return httpx.Response(200, json={"spans": {"data": page, "next_cursor": next_cursor}})

    @staticmethod
    def _passes(item, condition):
        value = item.get(condition["id"], item["span_attributes"].get(condition["id"]))
        if condition["operator"] == "in":
            return value in condition["value"]
        return value == condition["value"]


class TestTraceloopFetchContract(TraceFetchContract):
    @pytest.fixture
    def tracer(self):
        warehouse = _FakeWarehouse()
        fetcher = TraceloopTraceFetcher(api_key="key", base_url="https://tl.test", transport=httpx.MockTransport(warehouse.handle))
        fetcher.warehouse = warehouse
        return fetcher  # the contract only calls fetch(query), which the fetcher has

    def seed(self, tracer, spans):
        tracer.warehouse.load(spans)
