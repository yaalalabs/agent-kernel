"""Public testing helpers for tracers that fetch. Imports pytest, so import it from test code only."""

from datetime import datetime, timedelta, timezone

import pytest

from .base import BaseTrace
from .fetch import FetchedSpan, SpanKind, TraceQuery

_END = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
_START = _END - timedelta(hours=1)


class TraceFetchContract:
    """Conformance suite for ``BaseTrace.fetch``. Override the ``tracer`` fixture and ``seed``.

    Built-in fetchers and bring-your-own tracers that override ``fetch`` subclass it, so every one of them
    honours the same result contract: spans oldest first, unique span ids, the window applied to span start
    time (start inclusive, end exclusive), the most recent spans kept when more than ``limit`` match, and the
    kind, session, trace-id and name filters, including that a span missing the filtered value is excluded.

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    @pytest.fixture
    def tracer(self) -> BaseTrace:
        """The tracer under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `tracer` fixture")

    def seed(self, tracer: BaseTrace, spans: list[FetchedSpan]) -> None:
        """Make these spans exist in the tracer's backend; every subclass must override this.

        Each span carries ``trace_id``, ``span_id``, ``parent_span_id``, ``name``, ``kind``, ``start_time``,
        ``end_time`` and ``session_id``. A backend that stores kinds in its own vocabulary maps them on the
        way in, the way the real instrumentation would.
        """
        raise NotImplementedError("subclasses must override `seed`")

    @staticmethod
    def contract_span(
        span_id: str, minute: float, kind: SpanKind = SpanKind.SPAN, trace_id: str = "t1", session_id: str | None = "s1", name: str | None = None
    ) -> FetchedSpan:
        """A span starting ``minute`` minutes after the contract window's start, lasting 30 seconds."""
        start = _START + timedelta(minutes=minute)
        return FetchedSpan(
            provider="contract",
            trace_id=trace_id,
            span_id=span_id,
            name=name or f"{kind.value}-{span_id}",
            kind=kind,
            start_time=start,
            end_time=start + timedelta(seconds=30),
            session_id=session_id,
        )

    @staticmethod
    def window(**filters) -> TraceQuery:
        """A query over the contract window, plus any filters."""
        return TraceQuery(start=_START, end=_END, **filters)

    def test_contract_returns_spans_oldest_first(self, tracer):
        self.seed(tracer, [self.contract_span("b", 20), self.contract_span("a", 10), self.contract_span("c", 30)])

        spans = tracer.fetch(self.window())

        assert [span.span_id for span in spans] == ["a", "b", "c"]
        assert len({span.span_id for span in spans}) == len(spans)

    def test_contract_window_is_start_inclusive_end_exclusive(self, tracer):
        self.seed(
            tracer,
            [
                self.contract_span("before", -1),
                self.contract_span("at-start", 0),
                self.contract_span("inside", 30),
                self.contract_span("at-end", 60),
            ],
        )

        spans = tracer.fetch(self.window())

        assert [span.span_id for span in spans] == ["at-start", "inside"]

    def test_contract_limit_keeps_the_most_recent(self, tracer):
        self.seed(tracer, [self.contract_span(f"s{minute:02d}", minute) for minute in range(10, 15)])

        spans = tracer.fetch(self.window(limit=2))

        assert [span.span_id for span in spans] == ["s13", "s14"]

    def test_contract_kind_filter(self, tracer):
        self.seed(
            tracer,
            [
                self.contract_span("tool", 10, SpanKind.TOOL),
                self.contract_span("llm", 11, SpanKind.LLM),
                self.contract_span("agent", 12, SpanKind.AGENT),
                self.contract_span("plain", 13, SpanKind.SPAN),
            ],
        )

        assert [span.span_id for span in tracer.fetch(self.window(kinds=[SpanKind.TOOL]))] == ["tool"]
        assert [span.span_id for span in tracer.fetch(self.window(kinds=[SpanKind.LLM, SpanKind.AGENT]))] == ["llm", "agent"]
        assert [span.span_id for span in tracer.fetch(self.window(kinds=[SpanKind.SPAN]))] == ["plain"]

    def test_contract_session_filter(self, tracer):
        self.seed(
            tracer,
            [
                self.contract_span("mine", 10, session_id="s1"),
                self.contract_span("other", 11, trace_id="t2", session_id="s2"),
                self.contract_span("no-session", 12, trace_id="t3", session_id=None),
            ],
        )

        spans = tracer.fetch(self.window(session_id="s1"))

        assert [span.span_id for span in spans] == ["mine"]
        assert spans[0].session_id == "s1"

    def test_contract_trace_id_filter(self, tracer):
        self.seed(
            tracer,
            [
                self.contract_span("one", 10, trace_id="t1"),
                self.contract_span("two", 11, trace_id="t2"),
                self.contract_span("three", 12, trace_id="t3"),
            ],
        )

        spans = tracer.fetch(self.window(trace_ids=["t1", "t3"]))

        assert [span.span_id for span in spans] == ["one", "three"]

    def test_contract_name_filter(self, tracer):
        self.seed(
            tracer,
            [
                self.contract_span("wanted", 10, name="get_weather"),
                self.contract_span("other", 11, name="get_time"),
                self.contract_span("unnamed", 12).model_copy(update={"name": None}),
            ],
        )

        spans = tracer.fetch(self.window(name="get_weather"))

        assert [span.span_id for span in spans] == ["wanted"]

    def test_contract_empty_backend_returns_nothing(self, tracer):
        self.seed(tracer, [])

        assert tracer.fetch(self.window()) == []
