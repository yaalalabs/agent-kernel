"""Tests for fetching spans back from the tracing providers' clouds (trace/fetch.py and the per-provider fetchers).

No provider SDK is needed: Langfuse gets a fake client, Logfire a fake query client module (``logfire.query_client``,
or ``logfire.experimental.query_client`` before logfire 5), and Traceloop an ``httpx.MockTransport``.
"""

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.secret import SecretManager
from agentkernel.trace import FetchedSpan, FetchedTrace, SpanKind, SpanStatus, SpanUsage, TraceQuery
from agentkernel.trace.base import BaseTrace
from agentkernel.trace.cloudwatch.fetch import CloudWatchTraceFetcher
from agentkernel.trace.fetch import OTelSpanClassifier, TraceFetcher
from agentkernel.trace.langfuse.fetch import LangfuseTraceFetcher
from agentkernel.trace.logfire.fetch import LogfireTraceFetcher
from agentkernel.trace.openllmetry.fetch import TraceloopTraceFetcher
from agentkernel.trace.trace import Trace

END = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
START = END - timedelta(hours=1)


def _ts(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


class _SecretStub:
    """Stands in for SecretManager.current(): resolves only the given keys."""

    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


# --- TraceQuery -------------------------------------------------------------------------------------------


class TestTraceQuery:
    def test_window_defaults_to_last_hour(self):
        start, end = TraceQuery(end=END).window()
        assert (start, end) == (START, END)

    def test_window_treats_naive_datetimes_as_utc(self):
        start, end = TraceQuery(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)).window()
        assert start.tzinfo == timezone.utc and end.tzinfo == timezone.utc

    def test_window_rejects_inverted_range(self):
        with pytest.raises(ValueError):
            TraceQuery(start=END, end=START).window()

    def test_matches_applies_every_filter(self):
        query = TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1", trace_ids=["t1"], name="get_weather")
        span = FetchedSpan(provider="x", trace_id="t1", span_id="a", name="get_weather", kind=SpanKind.TOOL, start_time=_ts(5), session_id="s-1")

        assert query.matches(span)
        assert not query.matches(span.model_copy(update={"start_time": END}))  # end is exclusive
        assert query.matches(span.model_copy(update={"start_time": START}))  # start is inclusive
        assert not query.matches(span.model_copy(update={"kind": SpanKind.LLM}))
        assert not query.matches(span.model_copy(update={"session_id": "s-2"}))
        assert not query.matches(span.model_copy(update={"trace_id": "t2"}))
        assert not query.matches(span.model_copy(update={"name": "other"}))

    def test_matches_rejects_a_span_missing_a_filtered_value(self):
        span = FetchedSpan(provider="x", trace_id="t1", span_id="a", start_time=_ts(5))

        assert not TraceQuery(start=START, end=END).matches(span.model_copy(update={"start_time": None}))
        assert not TraceQuery(start=START, end=END, session_id="s-1").matches(span)  # no session id reported
        assert not TraceQuery(start=START, end=END, name="get_weather").matches(span)  # no name reported

    def test_matches_accepts_missing_values_when_their_filter_is_unset(self):
        span = FetchedSpan(provider="x", trace_id="t1", span_id="a", start_time=_ts(5))
        assert TraceQuery(start=START, end=END).matches(span)  # no session id or name, neither filtered

    def test_kinds_accept_strings(self):
        query = TraceQuery(kinds=["tool"])
        assert query.kinds == [SpanKind.TOOL]

    @pytest.mark.parametrize("filters", [{"kinds": []}, {"trace_ids": []}, {"session_id": ""}, {"name": ""}])
    def test_rejects_empty_filters(self, filters):
        with pytest.raises(ValueError, match="non-empty"):
            TraceQuery(**filters)

    def test_rejects_unknown_filters(self):
        with pytest.raises(ValueError, match="session"):
            TraceQuery(session="s-1")


# --- OTelSpanClassifier (attribute shapes taken from captured AK runs) ------------------------------------


class TestOTelSpanClassifier:
    @pytest.mark.parametrize(
        "attributes, name, expected",
        [
            ({"openinference.span.kind": "TOOL"}, "get_weather", SpanKind.TOOL),
            ({"openinference.span.kind": "LLM"}, "generation", SpanKind.LLM),
            ({"openinference.span.kind": "CHAIN"}, "turn", SpanKind.OTHER),
            ({"traceloop.span.kind": "tool", "gen_ai.operation.name": "execute_tool"}, "get_weather.tool", SpanKind.TOOL),
            ({"traceloop.span.kind": "workflow"}, "Agent Workflow", SpanKind.OTHER),
            ({"gen_ai.operation.name": "chat"}, "openai.chat", SpanKind.LLM),
            ({"gen_ai.operation.name": "invoke_agent"}, "invoke_agent weather-agent", SpanKind.AGENT),
            ({"logfire.msg_template": "Function: {name}"}, "Function: {name}", SpanKind.TOOL),
            ({"logfire.msg_template": "Agent run: {name!r}"}, "Agent run: {name!r}", SpanKind.AGENT),
            ({"logfire.tags": ["LLM"]}, "Chat completion with {gen_ai.request.model!r}", SpanKind.LLM),
            ({}, "Agent Kernel OpenAI", SpanKind.OTHER),
        ],
    )
    def test_classify(self, attributes, name, expected):
        assert OTelSpanClassifier.classify(attributes, name) == expected

    def test_io_prefers_tool_call_attributes(self):
        attributes = {"gen_ai.tool.call.arguments": '{"city": "Colombo"}', "gen_ai.tool.call.result": "sunny", "input": "ignored"}
        assert OTelSpanClassifier.io(attributes) == ('{"city": "Colombo"}', "sunny")

    def test_session_id(self):
        assert OTelSpanClassifier.session_id({"traceloop.association.properties.session_id": "s-1"}) == "s-1"
        assert OTelSpanClassifier.session_id({}) is None

    # attribute shapes from research/span-formats.md's captured runs
    @pytest.mark.parametrize(
        "attributes, expected",
        [
            ({"llm.token_count.prompt": 42, "llm.token_count.completion": 7}, SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49)),
            (
                {"gen_ai.usage.input_tokens": 42, "gen_ai.usage.output_tokens": 7, "operation.cost": 1.05e-05},
                SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49, cost=1.05e-05),
            ),
            (
                {"gen_ai.usage.input_tokens": "42", "gen_ai.usage.output_tokens": "7", "gen_ai.usage.total_tokens": "50"},
                SpanUsage(input_tokens=42, output_tokens=7, total_tokens=50),
            ),
            ({"gen_ai.aggregated_usage.input_tokens": 84}, None),  # Pydantic AI agent-run roll-up
            ({"usage": '{"input_tokens": 84, "output_tokens": 14}'}, None),  # OpenAI Agents workflow roll-up on Logfire
            ({"gen_ai.usage.input_tokens": "n/a"}, None),
        ],
    )
    def test_usage_reads_only_per_call_values(self, attributes, expected):
        assert OTelSpanClassifier.usage(attributes) == expected

    def test_usage_keeps_partial_values_without_inventing_a_total(self):
        assert SpanUsage.of(input_tokens=5) == SpanUsage(input_tokens=5)

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e400", float("nan"), float("inf")])
    def test_usage_ignores_non_finite_values(self, value):
        assert SpanUsage.of(input_tokens=value, output_tokens=value, total_tokens=value, cost=value) is None
        assert SpanUsage.of(input_tokens=3, cost=value) == SpanUsage(input_tokens=3)


# --- Trace facade -----------------------------------------------------------------------------------------


class _FetchingTrace(BaseTrace):
    def __init__(self):
        self.queries = []

    def init(self):
        pass

    def openai(self):
        return None

    langgraph = crewai = adk = smolagents = pydanticai = openai

    def fetch_spans(self, query):
        self.queries.append(query)
        return []


class TestTraceFetch:
    def test_disabled_tracing_raises(self):
        cfg = Mock()
        cfg.trace.enabled = False
        with patch.object(AKConfig, "get", return_value=cfg):
            with pytest.raises(AKConfigError):
                Trace.get().fetch_spans()

    def test_keyword_filters_build_a_query(self):
        tracer = _FetchingTrace()
        Trace(tracer).fetch_spans(last=timedelta(hours=6), kinds=[SpanKind.TOOL], session_id="s-1")
        (query,) = tracer.queries
        assert query.last == timedelta(hours=6) and query.kinds == [SpanKind.TOOL] and query.session_id == "s-1"

    def test_explicit_query_is_passed_through(self):
        tracer = _FetchingTrace()
        query = TraceQuery(limit=5)
        Trace(tracer).fetch_spans(query)
        assert tracer.queries == [query]

    def test_query_with_keyword_filters_raises(self):
        tracer = _FetchingTrace()
        with pytest.raises(ValueError, match="not both"):
            Trace(tracer).fetch_spans(TraceQuery(limit=5), session_id="s-1")
        assert tracer.queries == []

    def test_unknown_keyword_filter_raises(self):
        tracer = _FetchingTrace()
        with pytest.raises(ValueError, match="session"):
            Trace(tracer).fetch_spans(session="s-1")
        assert tracer.queries == []

    def test_base_trace_without_fetch_raises_not_implemented(self):
        class SendOnly(_FetchingTrace):
            fetch_spans = BaseTrace.fetch_spans

        with pytest.raises(NotImplementedError):
            Trace(SendOnly()).fetch_spans()


class TestSpanStatus:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("ERROR", SpanStatus.ERROR),
            ("STATUS_CODE_ERROR", SpanStatus.ERROR),
            (2, SpanStatus.ERROR),
            ("OK", SpanStatus.OK),
            (1, SpanStatus.OK),
            ("UNSET", SpanStatus.UNSET),
            (0, SpanStatus.UNSET),
            (None, SpanStatus.UNSET),
            (True, SpanStatus.UNSET),
            ("weird", SpanStatus.UNSET),
        ],
    )
    def test_of(self, value, expected):
        assert SpanStatus.of(value) is expected


def _tspan(span_id, minute, parent=None, kind=SpanKind.OTHER, trace_id="t1", usage=None, **extra):
    return FetchedSpan(
        provider="fake", trace_id=trace_id, span_id=span_id, parent_span_id=parent, start_time=_ts(minute), kind=kind, usage=usage, **extra
    )


class TestFetchedTrace:
    def test_group_keeps_span_order_and_orders_traces_by_first_span(self):
        spans = [_tspan("a1", 1, trace_id="a"), _tspan("b1", 2, trace_id="b"), _tspan("a2", 3, parent="a1", trace_id="a")]

        traces = FetchedTrace.group(spans)

        assert [trace.trace_id for trace in traces] == ["a", "b"]
        assert [span.span_id for span in traces[0].spans] == ["a1", "a2"]

    def test_root_inputs_and_times(self):
        root = _tspan("root", 1, input="question", output="answer", end_time=_ts(5), session_id="s-1")
        (trace,) = FetchedTrace.group([root, _tspan("child", 2, parent="root")])

        assert trace.root is root and trace.user_input == "question" and trace.output == "answer"
        assert trace.started_at == _ts(1) and trace.ended_at == _ts(5) and trace.session_id == "s-1"

    def test_no_root_when_every_span_has_a_parent(self):
        (trace,) = FetchedTrace.group([_tspan("child", 2, parent="lost")])

        assert trace.root is None and trace.user_input is None and trace.output is None
        assert trace.started_at is None and trace.ended_at is None

    def test_no_root_when_two_spans_have_no_parent(self):
        (trace,) = FetchedTrace.group([_tspan("one", 1), _tspan("two", 2)])

        assert trace.root is None

    def test_tool_spans_and_agent_names(self):
        spans = [
            _tspan("root", 1),
            _tspan("a1", 2, "root", SpanKind.AGENT, name="Triage"),
            _tspan("t1", 3, "a1", SpanKind.TOOL, name="get_weather"),
            _tspan("a2", 4, "root", SpanKind.AGENT, name="Triage"),
            _tspan("a3", 5, "root", SpanKind.AGENT, name="Weather"),
        ]
        (trace,) = FetchedTrace.group(spans)

        assert [span.span_id for span in trace.tool_spans] == ["t1"]
        assert trace.agent_names == ["Triage", "Weather"]

    def test_usage_sums_and_leaves_unreported_fields_none(self):
        spans = [
            _tspan("a", 1, usage=SpanUsage(input_tokens=10, output_tokens=2, total_tokens=12, cost=0.5)),
            _tspan("b", 2, usage=SpanUsage(input_tokens=5, total_tokens=5)),
            _tspan("c", 3),
        ]
        (trace,) = FetchedTrace.group(spans)

        assert trace.usage == SpanUsage(input_tokens=15, output_tokens=2, total_tokens=17, cost=0.5)
        assert FetchedTrace.group([_tspan("x", 1)])[0].usage == SpanUsage()


class TestTraceFetchTraces:
    def test_groups_the_fetched_spans(self):
        class Tracer(_FetchingTrace):
            def fetch_spans(self, query):
                return [_tspan("r", 1), _tspan("c", 2, "r")]

        (trace,) = Trace(Tracer()).fetch_traces(session_id="s-1")

        assert trace.root.span_id == "r" and len(trace.spans) == 2

    @pytest.mark.parametrize("filters", [{"kinds": [SpanKind.TOOL]}, {"name": "x"}])
    def test_rejects_per_span_filters(self, filters):
        with pytest.raises(ValueError, match="kinds or name"):
            Trace(_FetchingTrace()).fetch_traces(**filters)

    def test_query_with_keyword_filters_raises(self):
        tracer = _FetchingTrace()
        with pytest.raises(ValueError, match="not both"):
            Trace(tracer).fetch_traces(TraceQuery(), session_id="s-1", limit=1)
        assert tracer.queries == []

    def test_unknown_keyword_filter_raises(self):
        tracer = _FetchingTrace()
        with pytest.raises(ValueError, match="session"):
            Trace(tracer).fetch_traces(session="s-1")
        assert tracer.queries == []

    def test_disabled_tracing_raises(self):
        with pytest.raises(AKConfigError):
            Trace().fetch_traces()


# --- TraceFetcher (the built-ins' shared paging and merge) ---------------------------------------------------


def _span(span_id, minute, session_id=None, kind=SpanKind.TOOL, trace_id="t1"):
    return FetchedSpan(provider="fake", trace_id=trace_id, span_id=span_id, start_time=_ts(minute), session_id=session_id, kind=kind)


class _ScriptedFetcher(TraceFetcher):
    """Collects whatever the test scripts, recording the query it was given."""

    provider = "fake"

    def __init__(self, spans=()):
        self.spans = list(spans)
        self.queries = []

    def _query_provider(self, query):
        self.queries.append(query)
        return self.spans


class TestTraceFetcher:
    def test_fetch_pins_a_defaulted_window(self, monkeypatch):
        class AdvancingClock(datetime):
            ticks = 0

            @classmethod
            def now(cls, tz=None):
                cls.ticks += 1
                return END + timedelta(seconds=cls.ticks)

        monkeypatch.setattr("agentkernel.trace.fetch.datetime", AdvancingClock)
        windows = []

        class WindowRecorder(_ScriptedFetcher):
            def _query_provider(self, query):
                windows.extend([query.window(), query.window()])
                return [_span("edge", 59)] if query.matches(_span("edge", 59)) else []

        spans = WindowRecorder().fetch_spans(TraceQuery(last=timedelta(minutes=5)))
        # the clock moved on every now() call, yet every window seen inside the fetch is the first one
        assert windows[0] == windows[1] == (END - timedelta(minutes=5) + timedelta(seconds=1), END + timedelta(seconds=1))
        assert AdvancingClock.ticks == 1 and [span.span_id for span in spans] == ["edge"]

    def test_fetch_keeps_the_first_span_per_id_and_the_newest_limit(self):
        first_a = _span("a", 1)
        fetcher = _ScriptedFetcher([_span("c", 3), first_a, _span("b", 2), _span("a", 9)])
        spans = fetcher.fetch_spans(TraceQuery(start=START, end=END, limit=2))
        assert [span.span_id for span in spans] == ["b", "c"]
        assert fetcher.fetch_spans(TraceQuery(start=START, end=END))[0] is first_a

    def test_fetch_warns_only_when_the_limit_is_reached(self, caplog):
        fetcher = _ScriptedFetcher([_span("a", 1), _span("b", 2), _span("c", 3)])
        with caplog.at_level("WARNING", logger="ak.trace.fetch"):
            fetcher.fetch_spans(TraceQuery(start=START, end=END, limit=4))
        assert "reached its limit" not in caplog.text
        with caplog.at_level("WARNING", logger="ak.trace.fetch"):
            spans = fetcher.fetch_spans(TraceQuery(start=START, end=END, limit=2))
        assert [span.span_id for span in spans] == ["b", "c"]
        assert "fake fetch reached its limit of 2 spans" in caplog.text

    def test_fetch_keeps_spans_sharing_an_id_across_traces(self):
        fetcher = _ScriptedFetcher([_span("a", 1, trace_id="t1"), _span("a", 2, trace_id="t2")])
        spans = fetcher.fetch_spans(TraceQuery(start=START, end=END))
        assert [span.trace_id for span in spans] == ["t1", "t2"]

    @pytest.mark.parametrize(
        "pages, limit, expected_calls",
        [
            ({None: ([1], "c1"), "c1": ([2], None)}, 10, 2),  # empty cursor
            ({None: ([1], "c1"), "c1": ([], "c2")}, 10, 2),  # empty page
            ({None: ([1], "c1"), "c1": ([2], "c1")}, 10, 2),  # repeated cursor
            ({None: ([1, 2], "c1")}, 2, 1),  # limit reached
        ],
    )
    def test_fetch_by_cursor_stop_rules(self, pages, limit, expected_calls):
        calls = []

        def page(cursor):
            calls.append(cursor)
            return pages[cursor]

        query = TraceQuery(start=START, end=END, limit=limit)
        spans = _ScriptedFetcher()._fetch_by_cursor(query, page, lambda minute: _span(f"s{minute}", minute))
        assert len(calls) == expected_calls and len(spans) <= limit

    def test_fetch_by_cursor_keeps_only_matching_spans(self):
        query = TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL])
        items = [_span("tool", 1), _span("llm", 2, kind=SpanKind.LLM), _span("late", 61)]
        spans = _ScriptedFetcher()._fetch_by_cursor(query, lambda cursor: (items, None), lambda span: span)
        assert [span.span_id for span in spans] == ["tool"]

    def test_fetch_by_time_window_dedupes_the_boundary_and_backfills_the_session(self):
        pages = [[(_ts(4), _span("d", 4)), (_ts(3), _span("c", 3))], [(_ts(3), _span("c", 3)), (_ts(2), _span("b", 2, session_id="s-1"))], []]
        befores = []

        def page(size, before):
            befores.append(before)
            return pages[len(befores) - 1]

        query = TraceQuery(start=START, end=END, session_id="s-1", limit=10)
        spans = _ScriptedFetcher()._fetch_by_time_window(query, upper_bound=END, max_rows_per_request=2, fetch_page=page)
        assert [span.span_id for span in spans] == ["d", "c", "b"]
        assert all(span.session_id == "s-1" for span in spans)
        assert befores == [END, _ts(3), _ts(2)]

    def test_fetch_by_time_window_stops_on_a_short_page_or_the_limit(self):
        calls = []

        def page(size, before):
            calls.append(size)
            return [(_ts(5 - i), _span(f"s{len(calls)}-{i}", 5 - i)) for i in range(size)]

        query = TraceQuery(start=START, end=END, limit=3)
        spans = _ScriptedFetcher()._fetch_by_time_window(query, upper_bound=END, max_rows_per_request=2, fetch_page=page)
        assert len(spans) == 3 and calls == [2, 2]

        short = _ScriptedFetcher()._fetch_by_time_window(
            TraceQuery(start=START, end=END), upper_bound=END, max_rows_per_request=5, fetch_page=lambda size, before: [(_ts(1), _span("a", 1))]
        )
        assert [span.span_id for span in short] == ["a"]

    def test_fetch_by_time_window_sizes_pages_past_the_reread_boundary(self):
        # an inclusive upper bound re-reads the previous page's oldest row; it must not fill the last page
        rows = [(_ts(minute), _span(f"s{minute}", minute)) for minute in (10, 9, 8, 7)]

        def page(size, before):
            return [row for row in rows if row[0] <= before][:size]

        query = TraceQuery(start=START, end=END, limit=3)
        spans = _ScriptedFetcher()._fetch_by_time_window(query, upper_bound=END, max_rows_per_request=2, fetch_page=page)
        assert [span.span_id for span in spans] == ["s10", "s9", "s8"]

    def test_fetch_by_time_window_grows_the_page_when_more_rows_are_reread_than_expected(self):
        # like CloudWatch, which re-reads the whole boundary second rather than the boundary timestamp only
        rows = [(_ts(minute), _span(f"s{minute}", minute)) for minute in (5, 4, 3, 2, 1)]
        sizes = []

        def page(size, before):
            sizes.append(size)
            return [row for row in rows if row[0] <= before + timedelta(minutes=1)][:size]

        query = TraceQuery(start=START, end=END, limit=4)
        spans = _ScriptedFetcher()._fetch_by_time_window(query, upper_bound=END, max_rows_per_request=3, fetch_page=page)
        assert [span.span_id for span in spans] == ["s5", "s4", "s3", "s2"]
        assert sizes == [3, 2, 3]

    def test_fetch_by_time_window_stops_on_rows_without_a_cursor_timestamp(self):
        calls = []

        def page(size, before):
            calls.append(before)
            return [(None, _span("a", 1)), (None, _span("b", 2))]

        spans = _ScriptedFetcher()._fetch_by_time_window(TraceQuery(start=START, end=END), upper_bound=END, max_rows_per_request=2, fetch_page=page)
        assert len(spans) == 2 and len(calls) == 1

    def test_fetch_by_time_window_warns_on_a_full_page_with_no_fresh_rows(self, caplog):
        rows = [(_ts(3), _span("a", 3)), (_ts(3), _span("b", 3))]
        fetcher = _ScriptedFetcher()
        with caplog.at_level("WARNING", logger="ak.trace.fetch"):
            spans = fetcher._fetch_by_time_window(
                TraceQuery(start=START, end=END), upper_bound=END, max_rows_per_request=2, fetch_page=lambda size, before: rows
            )
        assert [span.span_id for span in spans] == ["a", "b"]
        assert "share one timestamp" in caplog.text


# --- Langfuse ---------------------------------------------------------------------------------------------


def _observation(id_, type_="TOOL", minute=0, **extra):
    return types.SimpleNamespace(
        id=id_,
        trace_id="t1",
        parent_observation_id="p",
        name=f"obs-{id_}",
        type=type_,
        start_time=_ts(minute),
        end_time=_ts(minute + 1),
        session_id="s-1",
        input='{"city": "Colombo"}',
        output="sunny",
        metadata={"attributes": {"tool.name": "get_weather"}},
        model_dump=lambda **_: {"id": id_},
        **extra,
    )


def _page(data, cursor=None):
    return types.SimpleNamespace(data=data, meta=types.SimpleNamespace(cursor=cursor))


class TestLangfuseFetcher:
    def test_follows_cursor_and_maps_observations(self):
        client = MagicMock()
        client.api.observations.get_many.side_effect = [_page([_observation("b", minute=5)], cursor="c1"), _page([_observation("a", minute=1)])]

        spans = LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        assert [span.span_id for span in spans] == ["a", "b"]  # oldest first
        first = spans[0]
        assert first.provider == "langfuse" and first.kind == SpanKind.TOOL and first.attributes == {"tool.name": "get_weather"}
        calls = client.api.observations.get_many.call_args_list
        assert calls[0].kwargs["type"] == "TOOL" and calls[0].kwargs["session_id"] == "s-1"
        assert calls[0].kwargs["from_start_time"] == START and calls[0].kwargs["to_start_time"] == END
        assert calls[1].kwargs["cursor"] == "c1"

    def test_maps_level_error_to_status(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("bad", level="ERROR"), _observation("fine", minute=2, level="DEFAULT")])

        spans = LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL]))

        assert {span.span_id: span.status for span in spans} == {"bad": SpanStatus.ERROR, "fine": SpanStatus.UNSET}

    def test_requests_full_attribute_metadata(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([])

        LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END))

        assert client.api.observations.get_many.call_args.kwargs["expand_metadata"] == "attributes"

    def test_maps_langfuse_usage_and_cost(self):
        observation = _observation("g", type_="GENERATION", usage_details={"input": 42, "output": 7, "total": 49}, total_cost=1.05e-05)
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([observation, _observation("t")])

        spans = LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END))

        usage = {span.span_id: span.usage for span in spans}
        assert usage["g"] == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49, cost=1.05e-05)
        assert usage["t"] is None

    def test_one_request_per_kind_and_trace_id(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([])

        LangfuseTraceFetcher(client).fetch_spans(TraceQuery(kinds=[SpanKind.TOOL, SpanKind.LLM], trace_ids=["t1", "t2"]))

        requested = {(c.kwargs["type"], c.kwargs["trace_id"]) for c in client.api.observations.get_many.call_args_list}
        assert requested == {("TOOL", "t1"), ("TOOL", "t2"), ("GENERATION", "t1"), ("GENERATION", "t2")}

    def test_span_kind_fetches_unfiltered_and_filters_locally(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("tool"), _observation("chain", type_="CHAIN")])

        spans = LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.OTHER]))

        assert client.api.observations.get_many.call_args.kwargs["type"] is None
        assert [span.span_id for span in spans] == ["chain"]

    def test_limit_keeps_most_recent(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("new", minute=9), _observation("old", minute=1)], cursor="more")

        spans = LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END, limit=1))

        assert [span.span_id for span in spans] == ["new"]
        assert client.api.observations.get_many.call_count == 1

    def test_stops_when_the_cursor_repeats(self):
        # every observation is outside the window, so limit is never reached; a repeated cursor must end the loop
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("old", minute=-30)], cursor="same")

        assert LangfuseTraceFetcher(client).fetch_spans(TraceQuery(start=START, end=END)) == []
        assert client.api.observations.get_many.call_count == 2


# --- Logfire ----------------------------------------------------------------------------------------------


def _row(span_id, minute, span_name="execute_tool get_weather", **attributes):
    return {
        "trace_id": "t1",
        "span_id": span_id,
        "parent_span_id": None,
        "span_name": span_name,
        "message": span_name,
        "start_timestamp": _ts(minute).isoformat(),
        "end_timestamp": _ts(minute + 1).isoformat(),
        "attributes": {"gen_ai.operation.name": "execute_tool", **attributes},
        "tags": [],
    }


@pytest.fixture(params=["logfire.query_client", "logfire.experimental.query_client"])
def fake_query_client(monkeypatch, request):
    """A fake query client at logfire 5's module path, then at logfire 4's (where 5 no longer has it)."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    module = types.ModuleType(request.param)
    module.LogfireQueryClient = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "logfire", types.ModuleType("logfire"))
    monkeypatch.delitem(sys.modules, "logfire.query_client", raising=False)
    if request.param == "logfire.experimental.query_client":
        monkeypatch.setitem(sys.modules, "logfire.experimental", types.ModuleType("logfire.experimental"))
    monkeypatch.setitem(sys.modules, request.param, module)
    return client


class TestLogfireFetcher:
    def test_missing_read_token_raises(self):
        with pytest.raises(AKConfigError, match="LOGFIRE_READ_TOKEN"):
            LogfireTraceFetcher(None)

    def test_queries_window_and_maps_rows(self, fake_query_client):
        fake_query_client.query_json_rows.return_value = {"rows": [_row("b", 5), _row("a", 1, session_id="s-1")]}

        spans = LogfireTraceFetcher(read_token="tok").fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        assert [span.span_id for span in spans] == ["a", "b"]
        assert all(span.kind == SpanKind.TOOL and span.session_id == "s-1" for span in spans)
        kwargs = fake_query_client.query_json_rows.call_args.kwargs
        assert kwargs["min_timestamp"] == START and kwargs["max_timestamp"] == END
        assert "execute_tool" in kwargs["sql"] and "attributes->>'session_id' = 's-1'" in kwargs["sql"]

    def test_pages_backwards_past_row_cap(self, fake_query_client, monkeypatch):
        monkeypatch.setattr(LogfireTraceFetcher, "_MAX_ROWS", 2)
        fake_query_client.query_json_rows.side_effect = [{"rows": [_row("d", 4), _row("c", 3)]}, {"rows": [_row("c", 3), _row("b", 2)]}, {"rows": []}]

        spans = LogfireTraceFetcher(read_token="tok").fetch_spans(TraceQuery(start=START, end=END, limit=10))

        assert [span.span_id for span in spans] == ["b", "c", "d"]
        second_sql = fake_query_client.query_json_rows.call_args_list[1].kwargs["sql"]
        assert f"start_timestamp <= '{_ts(3).isoformat()}'" in second_sql

    def test_maps_otel_status_code(self, fake_query_client):
        failed = {**_row("bad", 1), "otel_status_code": "ERROR"}
        fake_query_client.query_json_rows.return_value = {"rows": [failed, _row("fine", 2)]}

        spans = LogfireTraceFetcher(read_token="tok").fetch_spans(TraceQuery(start=START, end=END))

        assert [span.status for span in spans] == [SpanStatus.ERROR, SpanStatus.UNSET]

    def test_maps_usage_from_attributes(self, fake_query_client):
        row = _row("llm", 1, span_name="chat gpt-4o-mini", **{"gen_ai.usage.input_tokens": 42, "gen_ai.usage.output_tokens": 7})
        fake_query_client.query_json_rows.return_value = {"rows": [row]}

        (span,) = LogfireTraceFetcher(read_token="tok").fetch_spans(TraceQuery(start=START, end=END))

        assert span.usage == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49)

    def test_sql_escapes_literals_and_handles_span_kind(self):
        sql = LogfireTraceFetcher(read_token="tok")._sql(TraceQuery(name="it's", kinds=[SpanKind.OTHER]), 10, END)
        assert "COALESCE(message, span_name) = 'it''s'" in sql
        assert "NOT COALESCE(" in sql

    def test_drops_a_row_at_the_window_end(self, fake_query_client):
        # an inclusive max_timestamp would return it; matches() applies the exclusive end
        fake_query_client.query_json_rows.return_value = {"rows": [_row("end", 60), _row("a", 1)]}

        spans = LogfireTraceFetcher(read_token="tok").fetch_spans(TraceQuery(start=START, end=END))

        assert [span.span_id for span in spans] == ["a"]


# --- Traceloop --------------------------------------------------------------------------------------------


def _item(span_id, minute, operation="execute_tool", session="s-1", attributes=None):
    return {
        "trace_id": "t1",
        "span_id": span_id,
        "parent_span_id": "",
        "span_name": f"{span_id}.tool",
        "timestamp": int(_ts(minute).timestamp() * 1000),
        "duration_ms": 1500,
        "span_attributes": attributes
        or {
            "gen_ai.operation.name": operation,
            "gen_ai.tool.call.arguments": '{"city": "Colombo"}',
            "traceloop.association.properties.session_id": session,
        },
    }


class TestTraceloopFetcher:
    def test_missing_api_key_raises(self):
        with pytest.raises(AKConfigError, match="TRACELOOP_API_KEY"):
            TraceloopTraceFetcher(None)

    def test_paginates_filters_and_maps(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if "cursor" not in request.url.params:
                return httpx.Response(200, json={"spans": {"data": [_item("b", 5), _item("llm", 4, operation="chat")], "next_cursor": "c1"}})
            return httpx.Response(200, json={"spans": {"data": [_item("a", 1), _item("other", 2, session="s-2")], "next_cursor": None}})

        fetcher = TraceloopTraceFetcher(api_key="key", base_url="https://tl.test", transport=httpx.MockTransport(handler))
        spans = fetcher.fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        # the LLM span and the other session's span are dropped client side even if the server returns them
        assert [span.span_id for span in spans] == ["a", "b"]
        first = spans[0]
        assert first.start_time == _ts(1) and first.end_time == _ts(1) + timedelta(milliseconds=1500)
        assert first.parent_span_id is None and first.input == '{"city": "Colombo"}'
        params = requests[0].url.params
        assert requests[0].headers["Authorization"] == "Bearer key"
        assert params["from_timestamp_sec"] == str(int(START.timestamp())) and params["to_timestamp_sec"] == str(int(END.timestamp()))
        # kinds are applied locally only: no kind filter is sent even when kinds is set
        assert json.loads(params["filters"]) == [{"id": "traceloop.association.properties.session_id", "operator": "equals", "value": "s-1"}]
        # verified live: sort_by=timestamp makes the warehouse API return no spans, so only sort_order is sent
        assert params["sort_order"] == "DESC" and "sort_by" not in params
        assert requests[1].url.params["cursor"] == "c1"

    def test_maps_status(self):
        data = [{**_item("bad", 1), "status_code": "STATUS_CODE_ERROR"}, _item("fine", 2)]
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"spans": {"data": data, "next_cursor": None}}))

        spans = TraceloopTraceFetcher(api_key="key", transport=transport).fetch_spans(TraceQuery(start=START, end=END))

        assert [span.status for span in spans] == [SpanStatus.ERROR, SpanStatus.UNSET]

    def test_maps_a_zero_duration_to_an_end_time(self):
        data = [{**_item("instant", 1), "duration_ms": 0}]
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"spans": {"data": data, "next_cursor": None}}))

        (span,) = TraceloopTraceFetcher(api_key="key", transport=transport).fetch_spans(TraceQuery(start=START, end=END))

        assert span.end_time == span.start_time == _ts(1)

    def test_trace_ids_filter_uses_values(self):
        # verified live: "in" rejects a "value" array ("cannot unmarshal array") and needs "values"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"spans": {"data": [], "next_cursor": None}})

        fetcher = TraceloopTraceFetcher(api_key="key", transport=httpx.MockTransport(handler))
        fetcher.fetch_spans(TraceQuery(start=START, end=END, trace_ids=["t-1", "t-2"]))

        assert json.loads(requests[0].url.params["filters"]) == [{"id": "trace_id", "operator": "in", "values": ["t-1", "t-2"]}]

    def test_returns_a_tool_span_typed_only_by_traceloop_span_kind(self):
        # the SDK's own @tool decorator sets traceloop.span.kind but no gen_ai.operation.name
        attributes = {"traceloop.span.kind": "tool", "traceloop.association.properties.session_id": "s-1"}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"spans": {"data": [_item("decorated", 1, attributes=attributes)], "next_cursor": None}})

        fetcher = TraceloopTraceFetcher(api_key="key", transport=httpx.MockTransport(handler))
        (span,) = fetcher.fetch_spans(TraceQuery(start=START, end=END, kinds=["tool"]))

        assert span.span_id == "decorated" and span.kind == SpanKind.TOOL

    def test_tracer_resolves_the_key_through_the_secret_manager(self, monkeypatch):
        monkeypatch.delenv("TRACELOOP_API_KEY", raising=False)
        monkeypatch.setenv("TRACELOOP_BASE_URL", "https://tl.test")
        sdk = types.ModuleType("traceloop.sdk")
        sdk.Traceloop = MagicMock()
        monkeypatch.setitem(sys.modules, "traceloop", types.ModuleType("traceloop"))
        monkeypatch.setitem(sys.modules, "traceloop.sdk", sdk)
        monkeypatch.delitem(sys.modules, "agentkernel.trace.openllmetry.openllmetry", raising=False)
        from agentkernel.trace.openllmetry.openllmetry import OpenLLMetry

        secrets = _SecretStub(TRACELOOP_API_KEY="from-store")
        with (
            patch.object(SecretManager, "current", return_value=secrets),
            patch.object(TraceloopTraceFetcher, "fetch_spans", autospec=True, return_value=[]) as fetch,
        ):
            OpenLLMetry.fetch_spans(MagicMock(), TraceQuery())
            fetcher = fetch.call_args.args[0]
            assert fetcher._api_key == "from-store" and fetcher._base_url == "https://tl.test"

            secrets.values.clear()
            with pytest.raises(AKConfigError, match="TRACELOOP_API_KEY"):
                OpenLLMetry.fetch_spans(MagicMock(), TraceQuery())
        monkeypatch.delitem(sys.modules, "agentkernel.trace.openllmetry.openllmetry", raising=False)

    @pytest.mark.parametrize("value", ["2026-10-08T11:00:00Z", 1791457200, 1791457200000, 1791457200000000, 1791457200000000000])
    def test_timestamp_formats(self, value):
        assert TraceloopTraceFetcher._timestamp(value) == datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)


# --- CloudWatch -------------------------------------------------------------------------------------------


def _cw_row(span_id, minute, kind="TOOL", session="s-1", stamp_minute=None):
    record = {
        "traceId": "t1",
        "spanId": span_id,
        "parentSpanId": "",
        "name": f"{span_id}.tool",
        "startTimeUnixNano": str(int(_ts(minute).timestamp() * 1e9)),
        "endTimeUnixNano": int(_ts(minute + 1).timestamp() * 1e9),
        "attributes": {"openinference": {"span": {"kind": kind}}, "input.value": "q", "session.id": session},
    }
    stamp = _ts(minute if stamp_minute is None else stamp_minute)
    return [{"field": "@timestamp", "value": stamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}, {"field": "@message", "value": json.dumps(record)}]


def _logs_client(*pages):
    client = MagicMock()
    client.start_query.side_effect = [{"queryId": f"q{i}"} for i in range(len(pages))]
    client.get_query_results.side_effect = [{"status": "Complete", "results": list(page)} for page in pages]
    return client


class TestCloudWatchFetcher:
    def test_missing_region_raises(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setattr("agentkernel.trace.cloudwatch.cloudwatch.CloudWatch.region", staticmethod(lambda session: None))
        with pytest.raises(AKConfigError, match="AWS_REGION"):
            CloudWatchTraceFetcher().fetch_spans(TraceQuery())

    def test_queries_window_and_maps_records(self):
        client = _logs_client([_cw_row("b", 5), _cw_row("llm", 4, kind="LLM"), _cw_row("a", 1)])

        spans = CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        # the LLM span is dropped client side even if the server returns it
        assert [span.span_id for span in spans] == ["a", "b"]
        first = spans[0]
        assert first.provider == "cloudwatch" and first.kind == SpanKind.TOOL and first.session_id == "s-1"
        assert first.start_time == _ts(1) and first.end_time == _ts(2) and first.parent_span_id is None
        assert first.attributes["openinference.span.kind"] == "TOOL" and first.input == "q"
        kwargs = client.start_query.call_args.kwargs
        assert kwargs["logGroupName"] == "aws/spans" and kwargs["startTime"] == int(START.timestamp())
        assert kwargs["endTime"] >= int(END.timestamp())
        assert 'attributes.openinference.span.kind = "TOOL"' in kwargs["queryString"]
        assert 'attributes.session.id = "s-1"' in kwargs["queryString"]

    def test_maps_status_code(self):
        row = _cw_row("bad", 1)
        record = json.loads(row[1]["value"])
        record["status"] = {"code": "ERROR"}
        row[1]["value"] = json.dumps(record)

        spans = CloudWatchTraceFetcher(client=_logs_client([row, _cw_row("fine", 2)])).fetch_spans(TraceQuery(start=START, end=END))

        assert [span.status for span in spans] == [SpanStatus.ERROR, SpanStatus.UNSET]

    def test_maps_usage_from_nested_attributes(self):
        row = _cw_row("llm", 1, kind="LLM")
        record = json.loads(row[1]["value"])
        record["attributes"]["llm"] = {"token_count": {"prompt": 42, "completion": 7, "total": 49}}
        row[1]["value"] = json.dumps(record)

        (span,) = CloudWatchTraceFetcher(client=_logs_client([row])).fetch_spans(TraceQuery(start=START, end=END))

        assert span.usage == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49)

    def test_drops_spans_started_outside_the_window(self):
        client = _logs_client([_cw_row("late", 70, stamp_minute=50), _cw_row("a", 1)])
        spans = CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery(start=START, end=END))
        assert [span.span_id for span in spans] == ["a"]

    def test_pages_backwards_past_row_cap(self, monkeypatch):
        monkeypatch.setattr(CloudWatchTraceFetcher, "_MAX_ROWS", 2)
        client = _logs_client([_cw_row("d", 4), _cw_row("c", 3)], [_cw_row("c", 3), _cw_row("b", 2)], [])

        spans = CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery(start=START, end=END, limit=10))

        assert [span.span_id for span in spans] == ["b", "c", "d"]
        assert client.start_query.call_args_list[1].kwargs["endTime"] == int(_ts(3).timestamp())

    def test_missing_log_group_raises_a_config_error(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.start_query.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "StartQuery")
        with pytest.raises(AKConfigError, match="Transaction Search"):
            CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery())

    def test_other_client_errors_propagate(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.start_query.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "StartQuery")
        with pytest.raises(ClientError):
            CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery())

    def test_failed_query_raises(self):
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q"}
        client.get_query_results.return_value = {"status": "Failed"}
        with pytest.raises(RuntimeError, match="Failed"):
            CloudWatchTraceFetcher(client=client).fetch_spans(TraceQuery())

    def test_slow_query_is_stopped(self, monkeypatch):
        monkeypatch.setattr(CloudWatchTraceFetcher, "_POLL_INTERVAL", 0)
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q"}
        client.get_query_results.return_value = {"status": "Running"}
        with pytest.raises(TimeoutError):
            CloudWatchTraceFetcher(client=client, timeout=0).fetch_spans(TraceQuery())
        client.stop_query.assert_called_once_with(queryId="q")

    def test_insights_escapes_literals_and_handles_span_kind(self):
        insights = CloudWatchTraceFetcher(client=MagicMock())._insights(
            TraceQuery(name='say "hi"', kinds=[SpanKind.OTHER], trace_ids=["t1", "t2"]), 10
        )
        assert 'name = "say \\"hi\\""' in insights
        assert 'traceId in ["t1", "t2"]' in insights
        assert "openinference" not in insights  # OTHER is everything else, so kinds are filtered locally


@pytest.mark.parametrize(
    "fetcher, provider",
    [
        (LangfuseTraceFetcher(MagicMock()), "langfuse"),
        (LogfireTraceFetcher("tok"), "logfire"),
        (TraceloopTraceFetcher("key"), "openllmetry"),
        (CloudWatchTraceFetcher(client=MagicMock()), "cloudwatch"),
    ],
)
def test_provider_is_the_trace_type_short_name(fetcher, provider):
    assert fetcher.provider == provider


def test_oldest_first_handles_missing_start_times():
    spans = [FetchedSpan(provider="x", trace_id="t", span_id="b", start_time=_ts(1)), FetchedSpan(provider="x", trace_id="t", span_id="a")]
    assert [span.span_id for span in FetchedSpan.oldest_first(spans)] == ["a", "b"]
