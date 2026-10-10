"""Tests for fetching traces back from the tracing providers' clouds (trace/fetch.py and the per-provider fetchers).

No provider SDK is needed: Langfuse gets a fake client, Logfire a fake ``logfire.experimental.query_client``
module, and Traceloop an ``httpx.MockTransport``.
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
from agentkernel.trace import FetchedSpan, SpanKind, SpanUsage, TraceQuery
from agentkernel.trace.base import BaseTrace
from agentkernel.trace.cloudwatch.fetch import CloudWatchTraceFetcher
from agentkernel.trace.fetch import OTelSpanClassifier
from agentkernel.trace.langfuse.fetch import LangfuseTraceFetcher
from agentkernel.trace.logfire.fetch import LogfireTraceFetcher
from agentkernel.trace.openllmetry.fetch import TraceloopTraceFetcher
from agentkernel.trace.trace import Trace

END = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
START = END - timedelta(hours=1)


def _ts(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


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
        assert query.accepts(SpanKind.TOOL) and not query.accepts(SpanKind.LLM)


# --- OTelSpanClassifier (attribute shapes taken from captured AK runs) ------------------------------------


class TestOTelSpanClassifier:
    @pytest.mark.parametrize(
        "attributes, name, expected",
        [
            ({"openinference.span.kind": "TOOL"}, "get_weather", SpanKind.TOOL),
            ({"openinference.span.kind": "LLM"}, "generation", SpanKind.LLM),
            ({"openinference.span.kind": "CHAIN"}, "turn", SpanKind.SPAN),
            ({"traceloop.span.kind": "tool", "gen_ai.operation.name": "execute_tool"}, "get_weather.tool", SpanKind.TOOL),
            ({"traceloop.span.kind": "workflow"}, "Agent Workflow", SpanKind.SPAN),
            ({"gen_ai.operation.name": "chat"}, "openai.chat", SpanKind.LLM),
            ({"gen_ai.operation.name": "invoke_agent"}, "invoke_agent weather-agent", SpanKind.AGENT),
            ({"logfire.msg_template": "Function: {name}"}, "Function: {name}", SpanKind.TOOL),
            ({"logfire.msg_template": "Agent run: {name!r}"}, "Agent run: {name!r}", SpanKind.AGENT),
            ({"logfire.tags": ["LLM"]}, "Chat completion with {gen_ai.request.model!r}", SpanKind.LLM),
            ({}, "Agent Kernel OpenAI", SpanKind.SPAN),
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


# --- Trace facade -----------------------------------------------------------------------------------------


class _FetchingTrace(BaseTrace):
    def __init__(self):
        self.queries = []

    def init(self):
        pass

    def openai(self):
        return None

    langgraph = crewai = adk = smolagents = pydanticai = openai

    def fetch(self, query):
        self.queries.append(query)
        return []


class TestTraceFetch:
    def test_disabled_tracing_raises(self):
        cfg = Mock()
        cfg.trace.enabled = False
        with patch.object(AKConfig, "get", return_value=cfg):
            with pytest.raises(AKConfigError):
                Trace.get().fetch()

    def test_keyword_filters_build_a_query(self):
        tracer = _FetchingTrace()
        Trace(tracer).fetch(last=timedelta(hours=6), kinds=[SpanKind.TOOL], session_id="s-1")
        (query,) = tracer.queries
        assert query.last == timedelta(hours=6) and query.kinds == [SpanKind.TOOL] and query.session_id == "s-1"

    def test_explicit_query_is_passed_through(self):
        tracer = _FetchingTrace()
        query = TraceQuery(limit=5)
        Trace(tracer).fetch(query)
        assert tracer.queries == [query]

    def test_query_with_keyword_filters_raises(self):
        tracer = _FetchingTrace()
        with pytest.raises(ValueError, match="not both"):
            Trace(tracer).fetch(TraceQuery(limit=5), session_id="s-1")
        assert tracer.queries == []

    def test_base_trace_without_fetch_raises_not_implemented(self):
        class SendOnly(_FetchingTrace):
            fetch = BaseTrace.fetch

        with pytest.raises(NotImplementedError):
            Trace(SendOnly()).fetch()


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

        spans = LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        assert [span.span_id for span in spans] == ["a", "b"]  # oldest first
        first = spans[0]
        assert first.provider == "langfuse" and first.kind == SpanKind.TOOL and first.attributes == {"tool.name": "get_weather"}
        calls = client.api.observations.get_many.call_args_list
        assert calls[0].kwargs["type"] == "TOOL" and calls[0].kwargs["session_id"] == "s-1"
        assert calls[0].kwargs["from_start_time"] == START and calls[0].kwargs["to_start_time"] == END
        assert calls[1].kwargs["cursor"] == "c1"

    def test_requests_full_attribute_metadata(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([])

        LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END))

        assert client.api.observations.get_many.call_args.kwargs["expand_metadata"] == "attributes"

    def test_maps_langfuse_usage_and_cost(self):
        observation = _observation("g", type_="GENERATION", usage_details={"input": 42, "output": 7, "total": 49}, total_cost=1.05e-05)
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([observation, _observation("t")])

        spans = LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END))

        usage = {span.span_id: span.usage for span in spans}
        assert usage["g"] == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49, cost=1.05e-05)
        assert usage["t"] is None

    def test_one_request_per_kind_and_trace_id(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([])

        LangfuseTraceFetcher(client).fetch(TraceQuery(kinds=[SpanKind.TOOL, SpanKind.LLM], trace_ids=["t1", "t2"]))

        requested = {(c.kwargs["type"], c.kwargs["trace_id"]) for c in client.api.observations.get_many.call_args_list}
        assert requested == {("TOOL", "t1"), ("TOOL", "t2"), ("GENERATION", "t1"), ("GENERATION", "t2")}

    def test_span_kind_fetches_unfiltered_and_filters_locally(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("tool"), _observation("chain", type_="CHAIN")])

        spans = LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END, kinds=[SpanKind.SPAN]))

        assert client.api.observations.get_many.call_args.kwargs["type"] is None
        assert [span.span_id for span in spans] == ["chain"]

    def test_limit_keeps_most_recent(self):
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("new", minute=9), _observation("old", minute=1)], cursor="more")

        spans = LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END, limit=1))

        assert [span.span_id for span in spans] == ["new"]
        assert client.api.observations.get_many.call_count == 1

    def test_stops_when_the_cursor_repeats(self):
        # every observation is outside the window, so limit is never reached; a repeated cursor must end the loop
        client = MagicMock()
        client.api.observations.get_many.return_value = _page([_observation("old", minute=-30)], cursor="same")

        assert LangfuseTraceFetcher(client).fetch(TraceQuery(start=START, end=END)) == []
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


@pytest.fixture
def fake_query_client(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    module = types.ModuleType("logfire.experimental.query_client")
    module.LogfireQueryClient = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "logfire", types.ModuleType("logfire"))
    monkeypatch.setitem(sys.modules, "logfire.experimental", types.ModuleType("logfire.experimental"))
    monkeypatch.setitem(sys.modules, "logfire.experimental.query_client", module)
    return client


class TestLogfireFetcher:
    def test_missing_read_token_raises(self, monkeypatch):
        monkeypatch.delenv(LogfireTraceFetcher.READ_TOKEN_ENV, raising=False)
        with pytest.raises(AKConfigError, match="LOGFIRE_READ_TOKEN"):
            LogfireTraceFetcher().fetch(TraceQuery())

    def test_queries_window_and_maps_rows(self, fake_query_client):
        fake_query_client.query_json_rows.return_value = {"rows": [_row("b", 5), _row("a", 1, session_id="s-1")]}

        spans = LogfireTraceFetcher(read_token="tok").fetch(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        assert [span.span_id for span in spans] == ["a", "b"]
        assert all(span.kind == SpanKind.TOOL and span.session_id == "s-1" for span in spans)
        kwargs = fake_query_client.query_json_rows.call_args.kwargs
        assert kwargs["min_timestamp"] == START and kwargs["max_timestamp"] == END
        assert "execute_tool" in kwargs["sql"] and "attributes->>'session_id' = 's-1'" in kwargs["sql"]

    def test_pages_backwards_past_row_cap(self, fake_query_client, monkeypatch):
        monkeypatch.setattr(LogfireTraceFetcher, "_MAX_ROWS", 2)
        fake_query_client.query_json_rows.side_effect = [{"rows": [_row("d", 4), _row("c", 3)]}, {"rows": [_row("c", 3), _row("b", 2)]}, {"rows": []}]

        spans = LogfireTraceFetcher(read_token="tok").fetch(TraceQuery(start=START, end=END, limit=10))

        assert [span.span_id for span in spans] == ["b", "c", "d"]
        second_sql = fake_query_client.query_json_rows.call_args_list[1].kwargs["sql"]
        assert f"start_timestamp <= '{_ts(3).isoformat()}'" in second_sql

    def test_maps_usage_from_attributes(self, fake_query_client):
        row = _row("llm", 1, span_name="chat gpt-4o-mini", **{"gen_ai.usage.input_tokens": 42, "gen_ai.usage.output_tokens": 7})
        fake_query_client.query_json_rows.return_value = {"rows": [row]}

        (span,) = LogfireTraceFetcher(read_token="tok").fetch(TraceQuery(start=START, end=END))

        assert span.usage == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49)

    def test_sql_escapes_literals_and_handles_span_kind(self):
        sql = LogfireTraceFetcher(read_token="tok")._sql(TraceQuery(name="it's", kinds=[SpanKind.SPAN]), 10, None)
        assert "'it''s'" in sql
        assert "NOT COALESCE(" in sql


# --- Traceloop --------------------------------------------------------------------------------------------


def _item(span_id, minute, operation="execute_tool", session="s-1"):
    return {
        "trace_id": "t1",
        "span_id": span_id,
        "parent_span_id": "",
        "span_name": f"{span_id}.tool",
        "timestamp": int(_ts(minute).timestamp() * 1000),
        "duration_ms": 1500,
        "span_attributes": {
            "gen_ai.operation.name": operation,
            "gen_ai.tool.call.arguments": '{"city": "Colombo"}',
            "traceloop.association.properties.session_id": session,
        },
    }


class TestTraceloopFetcher:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("TRACELOOP_API_KEY", raising=False)
        with pytest.raises(AKConfigError, match="TRACELOOP_API_KEY"):
            TraceloopTraceFetcher().fetch(TraceQuery())

    def test_paginates_filters_and_maps(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if "cursor" not in request.url.params:
                return httpx.Response(200, json={"spans": {"data": [_item("b", 5), _item("llm", 4, operation="chat")], "next_cursor": "c1"}})
            return httpx.Response(200, json={"spans": {"data": [_item("a", 1), _item("other", 2, session="s-2")], "next_cursor": None}})

        fetcher = TraceloopTraceFetcher(api_key="key", base_url="https://tl.test", transport=httpx.MockTransport(handler))
        spans = fetcher.fetch(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

        # the LLM span and the other session's span are dropped client side even if the server returns them
        assert [span.span_id for span in spans] == ["a", "b"]
        first = spans[0]
        assert first.start_time == _ts(1) and first.end_time == _ts(1) + timedelta(milliseconds=1500)
        assert first.parent_span_id is None and first.input == '{"city": "Colombo"}'
        params = requests[0].url.params
        assert requests[0].headers["Authorization"] == "Bearer key"
        assert params["from_timestamp_sec"] == str(int(START.timestamp())) and params["to_timestamp_sec"] == str(int(END.timestamp()))
        filters = json.loads(params["filters"])
        assert {"id": "gen_ai.operation.name", "operator": "in", "value": ["execute_tool"]} in filters
        assert requests[1].url.params["cursor"] == "c1"

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
            CloudWatchTraceFetcher().fetch(TraceQuery())

    def test_queries_window_and_maps_records(self):
        client = _logs_client([_cw_row("b", 5), _cw_row("llm", 4, kind="LLM"), _cw_row("a", 1)])

        spans = CloudWatchTraceFetcher(client=client).fetch(TraceQuery(start=START, end=END, kinds=[SpanKind.TOOL], session_id="s-1"))

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

    def test_maps_usage_from_nested_attributes(self):
        row = _cw_row("llm", 1, kind="LLM")
        record = json.loads(row[1]["value"])
        record["attributes"]["llm"] = {"token_count": {"prompt": 42, "completion": 7, "total": 49}}
        row[1]["value"] = json.dumps(record)

        (span,) = CloudWatchTraceFetcher(client=_logs_client([row])).fetch(TraceQuery(start=START, end=END))

        assert span.usage == SpanUsage(input_tokens=42, output_tokens=7, total_tokens=49)

    def test_drops_spans_started_outside_the_window(self):
        client = _logs_client([_cw_row("late", 70, stamp_minute=50), _cw_row("a", 1)])
        spans = CloudWatchTraceFetcher(client=client).fetch(TraceQuery(start=START, end=END))
        assert [span.span_id for span in spans] == ["a"]

    def test_pages_backwards_past_row_cap(self, monkeypatch):
        monkeypatch.setattr(CloudWatchTraceFetcher, "_MAX_ROWS", 2)
        client = _logs_client([_cw_row("d", 4), _cw_row("c", 3)], [_cw_row("c", 3), _cw_row("b", 2)], [])

        spans = CloudWatchTraceFetcher(client=client).fetch(TraceQuery(start=START, end=END, limit=10))

        assert [span.span_id for span in spans] == ["b", "c", "d"]
        assert client.start_query.call_args_list[1].kwargs["endTime"] == int(_ts(3).timestamp())

    def test_missing_log_group_raises_a_config_error(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.start_query.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}}, "StartQuery")
        with pytest.raises(AKConfigError, match="Transaction Search"):
            CloudWatchTraceFetcher(client=client).fetch(TraceQuery())

    def test_other_client_errors_propagate(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.start_query.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "StartQuery")
        with pytest.raises(ClientError):
            CloudWatchTraceFetcher(client=client).fetch(TraceQuery())

    def test_failed_query_raises(self):
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q"}
        client.get_query_results.return_value = {"status": "Failed"}
        with pytest.raises(RuntimeError, match="Failed"):
            CloudWatchTraceFetcher(client=client).fetch(TraceQuery())

    def test_slow_query_is_stopped(self, monkeypatch):
        monkeypatch.setattr(CloudWatchTraceFetcher, "_POLL_INTERVAL", 0)
        client = MagicMock()
        client.start_query.return_value = {"queryId": "q"}
        client.get_query_results.return_value = {"status": "Running"}
        with pytest.raises(TimeoutError):
            CloudWatchTraceFetcher(client=client, timeout=0).fetch(TraceQuery())
        client.stop_query.assert_called_once_with(queryId="q")

    def test_insights_escapes_literals_and_handles_span_kind(self):
        insights = CloudWatchTraceFetcher(client=MagicMock())._insights(
            TraceQuery(name='say "hi"', kinds=[SpanKind.SPAN], trace_ids=["t1", "t2"]), 10
        )
        assert 'name = "say \\"hi\\""' in insights
        assert 'traceId in ["t1", "t2"]' in insights
        assert "openinference" not in insights  # SPAN is everything else, so kinds are filtered locally


def test_oldest_first_handles_missing_start_times():
    spans = [FetchedSpan(provider="x", trace_id="t", span_id="b", start_time=_ts(1)), FetchedSpan(provider="x", trace_id="t", span_id="a")]
    assert [span.span_id for span in FetchedSpan.oldest_first(spans)] == ["a", "b"]
