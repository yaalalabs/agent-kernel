"""
Tracing a realtime call (#928): a traced realtime runner opens one span when ``connect`` starts and ends it in
``disconnect``; the ``Module`` picks it in realtime mode when tracing is enabled.

Spans are recorded on a local SDK ``TracerProvider`` with an ``InMemorySpanExporter``: the global provider is settable once
per process, so no test installs one.
"""

import asyncio
from contextlib import contextmanager

import pytest
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentkernel.core import Agent, Session
from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.trace.base import BaseTrace, RealtimeCallSpan, TracedRealtimeRunner
from agentkernel.trace.otel import OTelRealtimeCallSpan
from agentkernel.trace.trace import Trace

# --- a recording span and a fake framework runner -------------------------------------------------


class RecordingSpan(RealtimeCallSpan):
    def __init__(self):
        self.events: list[str] = []
        self.active = False

    @contextmanager
    def opened(self):
        self.events.append("opened")
        self.active = True
        try:
            yield
        finally:
            self.active = False
            self.events.append("closed-block")

    def fail(self, message):
        self.events.append(f"fail:{message}")

    def end(self):
        self.events.append("end")


class FakeFrameworkRunner(RealtimeRunner):
    """Stands in for the framework's realtime runner; records what the span looked like while it connected."""

    connect_error: BaseException | None = None
    close_itself_on_failure = False

    def __init__(self):
        super().__init__("fake")
        self.seen_active: bool | None = None
        self.callback = None

    async def connect(self, session, agent, callback):
        self.callback = callback
        self.seen_active = TracedFake.span.active
        if self.connect_error is not None:
            if self.close_itself_on_failure:
                await self.disconnect()  # the adapters close what they opened before they raise
            raise self.connect_error

    async def append_audio(self, base64_audio):
        pass

    async def send_text(self, text):
        pass

    async def disconnect(self):
        pass


class TracedFake(TracedRealtimeRunner, FakeFrameworkRunner):
    SPAN_NAME = "Agent Kernel Fake realtime"
    span: RecordingSpan

    def _start_call_span(self, session, agent):
        return TracedFake.span


@pytest.fixture
def runner():
    TracedFake.span = RecordingSpan()
    TracedFake.connect_error = None
    TracedFake.close_itself_on_failure = False
    return TracedFake()


async def _noop(event_type, data):
    pass


class TestTracedRealtimeRunner:
    def test_the_framework_runners_init_runs_through_the_mro(self, runner):
        assert runner.name == "fake"
        assert runner._call_span is None

    @pytest.mark.asyncio
    async def test_the_span_is_open_while_the_native_session_connects_and_stays_open_after(self, runner):
        await runner.connect(Session("s1"), None, _noop)

        assert runner.seen_active is True
        assert TracedFake.span.active is False
        assert TracedFake.span.events == ["opened", "closed-block"]  # not ended: the call is still going

    @pytest.mark.asyncio
    async def test_disconnect_ends_the_span_once_even_when_called_twice(self, runner):
        await runner.connect(Session("s1"), None, _noop)

        await runner.disconnect()
        await runner.disconnect()

        assert TracedFake.span.events.count("end") == 1

    @pytest.mark.asyncio
    async def test_disconnect_without_connect_is_safe(self, runner):
        await runner.disconnect()

        assert TracedFake.span.events == []

    @pytest.mark.asyncio
    async def test_a_failed_connect_marks_the_span_failed_ends_it_and_reraises(self, runner):
        TracedFake.connect_error = ConnectionError("no route")

        with pytest.raises(ConnectionError):
            await runner.connect(Session("s1"), None, _noop)

        assert [e for e in TracedFake.span.events if e != "closed-block"] == ["opened", "fail:ConnectionError('no route')", "end"]

    @pytest.mark.asyncio
    async def test_a_cancelled_connect_is_failed_and_ended_too(self, runner):
        TracedFake.connect_error = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await runner.connect(Session("s1"), None, _noop)

        assert TracedFake.span.events[-1] == "end"
        assert any(e.startswith("fail:") for e in TracedFake.span.events)

    @pytest.mark.asyncio
    async def test_an_adapter_that_closes_itself_when_connect_fails_still_gets_fail_before_end(self, runner):
        TracedFake.connect_error = ConnectionError("no route")
        TracedFake.close_itself_on_failure = True

        with pytest.raises(ConnectionError):
            await runner.connect(Session("s1"), None, _noop)

        events = [e for e in TracedFake.span.events if e != "closed-block"]
        assert events == ["opened", "fail:ConnectionError('no route')", "end"]  # one end, after the failure was recorded

    @pytest.mark.asyncio
    async def test_an_error_event_marks_the_span_failed_and_still_reaches_the_callback(self, runner):
        received = []

        async def callback(event_type, data):
            received.append((event_type, data))

        await runner.connect(Session("s1"), None, callback)
        await runner.callback("audio_delta", {"delta": "QUFB"})
        await runner.callback("error", {"message": "native session failed"})

        assert received == [("audio_delta", {"delta": "QUFB"}), ("error", {"message": "native session failed"})]
        assert "fail:native session failed" in TracedFake.span.events
        assert "end" not in TracedFake.span.events  # the pool closes the call, which ends it


# --- the OpenTelemetry call span -------------------------------------------------------------------


@pytest.fixture
def otel():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def _by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


class TestOTelRealtimeCallSpan:
    @pytest.mark.asyncio
    async def test_spans_started_inside_the_block_and_by_tasks_created_there_are_its_children(self, otel):
        tracer, exporter = otel
        span = OTelRealtimeCallSpan(tracer, "Agent Kernel ADK realtime", {"session_id": "s1"})

        async def native_task():
            await asyncio.sleep(0.01)  # runs after the block exited, as a native session's tasks do
            with tracer.start_as_current_span("from-task"):
                pass

        with span.opened():
            with tracer.start_as_current_span("inside"):
                pass
            task = asyncio.create_task(native_task())
        assert not trace.get_current_span().get_span_context().is_valid  # not current after the block
        await task
        await asyncio.create_task(asyncio.sleep(0))  # ended from another task than the one that opened it
        span.end()

        spans = _by_name(exporter)
        call = spans["Agent Kernel ADK realtime"]
        assert call.attributes["session_id"] == "s1"
        assert call.parent is None
        assert spans["inside"].parent.span_id == call.context.span_id
        assert spans["from-task"].parent.span_id == call.context.span_id
        assert call.end_time >= spans["from-task"].end_time

    def test_the_span_stays_open_until_end_and_end_is_idempotent(self, otel):
        tracer, exporter = otel
        span = OTelRealtimeCallSpan(tracer, "call", {})

        with span.opened():
            pass
        assert exporter.get_finished_spans() == ()
        span.end()
        span.end()

        assert len(exporter.get_finished_spans()) == 1

    def test_fail_sets_an_error_status_with_the_message(self, otel):
        tracer, exporter = otel
        span = OTelRealtimeCallSpan(tracer, "call", {})
        with span.opened():
            pass

        span.fail("native session failed")
        span.end()

        status = _by_name(exporter)["call"].status
        assert (status.status_code, status.description) == (StatusCode.ERROR, "native session failed")

    def test_an_exception_in_the_block_is_recorded_on_the_span(self, otel):
        tracer, exporter = otel
        span = OTelRealtimeCallSpan(tracer, "call", {})

        with pytest.raises(RuntimeError):
            with span.opened():
                raise RuntimeError("connect failed")
        span.end()

        call = _by_name(exporter)["call"]
        assert call.status.status_code == StatusCode.ERROR
        assert any(e.name == "exception" for e in call.events)

    def test_end_and_fail_before_opened_are_safe(self, otel):
        tracer, exporter = otel
        span = OTelRealtimeCallSpan(tracer, "call", {})

        span.fail("never started")
        span.end()

        assert exporter.get_finished_spans() == ()


# --- per provider ---------------------------------------------------------------------------------


class TestLangfuseCallSpan:
    def test_observation_is_kept_open_tagged_with_the_session_and_ended_once(self, monkeypatch):
        pytest.importorskip("langfuse")
        from agentkernel.trace.langfuse import langfuse as module

        calls = []

        class Observation:
            def update(self, **kwargs):
                calls.append(("update", kwargs))

            def end(self):
                calls.append(("end",))

        class Client:
            @contextmanager
            def start_as_current_observation(self, **kwargs):
                calls.append(("start", kwargs))
                yield Observation()

        @contextmanager
        def propagate(**kwargs):
            calls.append(("propagate", kwargs))
            yield

        monkeypatch.setattr(module, "propagate_attributes", propagate)
        span = module.LangFuseRealtimeCallSpan(Client(), "Agent Kernel OpenAI realtime", "s1")

        with span.opened():
            pass
        span.fail("native session failed")
        span.end()
        span.end()

        assert calls == [
            ("propagate", {"session_id": "s1", "tags": ["agentkernel"]}),
            ("start", {"name": "Agent Kernel OpenAI realtime", "as_type": "span", "end_on_exit": False}),
            ("update", {"level": "ERROR", "status_message": "native session failed"}),
            ("end",),
        ]


class TestOpenLLMetryCallSpan:
    def test_the_session_association_property_is_set_before_the_span_starts_and_detached_after(self, monkeypatch, otel):
        pytest.importorskip("traceloop")
        from agentkernel.trace.openllmetry import openllmetry as module

        tracer, exporter = otel
        order = []

        class FakeTraceloop:
            @staticmethod
            def set_association_properties(props):
                order.append(("associate", props, len(exporter.get_finished_spans())))

        monkeypatch.setattr(module, "Traceloop", FakeTraceloop)
        monkeypatch.setattr(module.trace, "get_tracer", lambda name: tracer)
        span = module.OpenLLMetryRealtimeCallSpan("call", "s1")

        with span.opened():
            order.append(("inside", None, None))
        span.end()

        assert order == [("associate", {"session_id": "s1"}, 0), ("inside", None, None)]
        assert "call" in _by_name(exporter)


class TestCloudWatchCallSpan:
    def test_session_id_is_an_attribute_and_baggage_for_the_block_only(self, monkeypatch, otel):
        pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        from agentkernel.trace.cloudwatch import cloudwatch as module

        tracer, exporter = otel
        monkeypatch.setattr(module.trace_api, "get_tracer", lambda name: tracer)
        span = module.CloudWatchRealtimeCallSpan("Agent Kernel ADK realtime", "s1")
        seen = {}

        with span.opened():
            seen["inside"] = baggage.get_baggage("session.id")
        seen["after"] = baggage.get_baggage("session.id")
        span.end()

        assert seen == {"inside": "s1", "after": None}
        assert _by_name(exporter)["Agent Kernel ADK realtime"].attributes["session.id"] == "s1"


@pytest.mark.parametrize(
    "module, provider, prefix, sdk",
    [
        ("agentkernel.trace.langfuse.langfuse", "LangFuse", "LangFuse", "langfuse"),
        ("agentkernel.trace.openllmetry.openllmetry", "OpenLLMetry", "OpenLLMetry", "traceloop"),
        ("agentkernel.trace.logfire.logfire", "Logfire", "Logfire", "logfire"),
        ("agentkernel.trace.cloudwatch.cloudwatch", "CloudWatch", "CloudWatch", "opentelemetry.exporter.otlp.proto.http.trace_exporter"),
    ],
)
def test_each_builtin_provider_returns_its_two_traced_realtime_runner_classes(module, provider, prefix, sdk):
    import importlib

    pytest.importorskip(sdk)
    tracer = getattr(importlib.import_module(module), provider)()
    openai, adk = tracer.openai_realtime(), tracer.adk_realtime()

    assert (openai.__name__, adk.__name__) == (f"{prefix}OpenAIRealtimeRunner", f"{prefix}ADKRealtimeRunner")
    for cls in (openai, adk):
        assert issubclass(cls, TracedRealtimeRunner) and not cls.__abstractmethods__
        assert cls.SPAN_NAME.startswith("Agent Kernel ") and cls.SPAN_NAME.endswith(" realtime")


# --- Module selection -----------------------------------------------------------------------------


class _OpenAIRealtime(RealtimeRunner):
    pass


class _ADKRealtime(RealtimeRunner):
    pass


class _StubTracer(BaseTrace):
    """A bring-your-own tracer that traces realtime calls."""

    def init(self):
        pass

    def openai(self):
        return "traced-openai-runner"

    def adk(self):
        return "traced-adk-runner"

    def langgraph(self):
        return None

    crewai = smolagents = pydanticai = maf = claude = langgraph

    def openai_realtime(self):
        return _OpenAIRealtime

    def adk_realtime(self):
        return _ADKRealtime


class _PlainTracer(_StubTracer):
    """A tracer that predates the realtime methods: it inherits the ``None`` defaults."""

    openai_realtime = BaseTrace.openai_realtime
    adk_realtime = BaseTrace.adk_realtime


def _configure(monkeypatch, *, tracing: bool, mode: ExecutionMode | None, tracer: type[BaseTrace] = _StubTracer):
    class Trace_:
        enabled = tracing
        type = "stub"

    class Cfg:
        trace = Trace_
        execution = _ExecutionConfig(mode=mode)

    built = []

    def build(trace_type):
        built.append(trace_type)
        return tracer()

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: Cfg))
    monkeypatch.setattr(Trace, "_build", staticmethod(build))
    return built


@pytest.fixture(params=["openai", "adk"])
def module_cls(request):
    from agentkernel.framework.adk.adk import GoogleADKModule, GoogleADKRealtimeRunner, GoogleADKRunner
    from agentkernel.framework.openai.openai import OpenAIModule, OpenAIRealtimeRunner, OpenAIRunner

    if request.param == "openai":
        return OpenAIModule, OpenAIRunner, OpenAIRealtimeRunner, _OpenAIRealtime, "traced-openai-runner"
    return GoogleADKModule, GoogleADKRunner, GoogleADKRealtimeRunner, _ADKRealtime, "traced-adk-runner"


class TestModuleSelection:
    def test_realtime_mode_with_tracing_gets_the_traced_realtime_class_and_one_tracer(self, monkeypatch, module_cls):
        module, _, _, traced_realtime, traced_runner = module_cls
        built = _configure(monkeypatch, tracing=True, mode=ExecutionMode.REALTIME)

        m = module([])

        assert m.realtime_runner_cls is traced_realtime
        assert m.runner == traced_runner
        assert built == ["stub"]  # Trace.get() once per module

    def test_text_mode_with_tracing_keeps_the_default_realtime_class(self, monkeypatch, module_cls):
        module, _, default_realtime, _, traced_runner = module_cls
        _configure(monkeypatch, tracing=True, mode=ExecutionMode.REST_SYNC)

        m = module([])

        assert m.realtime_runner_cls is default_realtime
        assert m.runner == traced_runner  # the text runner is traced as before

    def test_no_tracing_builds_no_tracer_and_uses_the_defaults(self, monkeypatch, module_cls):
        module, default_runner, default_realtime, _, _ = module_cls
        built = _configure(monkeypatch, tracing=False, mode=ExecutionMode.REALTIME)

        m = module([])

        assert built == []
        assert m.realtime_runner_cls is default_realtime
        assert isinstance(m.runner, default_runner)

    def test_a_class_the_app_passes_is_used_as_is(self, monkeypatch, module_cls):
        module, _, _, _, _ = module_cls
        _configure(monkeypatch, tracing=True, mode=ExecutionMode.REALTIME)

        class Mine(RealtimeRunner):
            pass

        assert module([], realtime_runner_cls=Mine).realtime_runner_cls is Mine

    def test_a_runner_the_app_passes_is_kept_and_the_realtime_class_is_still_traced(self, monkeypatch, module_cls):
        module, _, _, traced_realtime, _ = module_cls
        _configure(monkeypatch, tracing=True, mode=ExecutionMode.REALTIME)
        mine = object()

        m = module([], runner=mine)

        assert m.runner is mine
        assert m.realtime_runner_cls is traced_realtime

    def test_a_tracer_without_the_realtime_methods_leaves_the_untraced_default(self, monkeypatch, module_cls):
        module, _, default_realtime, _, _ = module_cls
        _configure(monkeypatch, tracing=True, mode=ExecutionMode.REALTIME, tracer=_PlainTracer)

        assert module([]).realtime_runner_cls is default_realtime

    def test_trace_delegates_and_returns_none_without_an_instance(self):
        assert Trace(None).openai_realtime() is None and Trace(None).adk_realtime() is None
        assert Trace(_StubTracer()).openai_realtime() is _OpenAIRealtime
        assert Trace(_StubTracer()).adk_realtime() is _ADKRealtime


class TestLogfireCallSpan:
    def test_the_call_span_carries_the_session_id_attribute_the_run_span_uses(self):
        pytest.importorskip("logfire")
        from agentkernel.trace.logfire.openai import LogfireOpenAIRealtimeRunner

        span = LogfireOpenAIRealtimeRunner()._start_call_span(Session("s1"), None)

        assert isinstance(span, OTelRealtimeCallSpan)
        assert span._attributes == {"session_id": "s1"}


class TestADKSpansNestUnderTheCallSpan:
    """With real ADK ``run_live()``: its own spans become children of the call span, because the native session's tasks
    start inside ``connect``, which the call span wraps. ADK reads its tracer from ``google.adk.telemetry.tracing.tracer`` at call
    time, so it is swapped for a local one; no global provider is installed."""

    @pytest.mark.asyncio
    async def test_invoke_agent_and_execute_tool_are_descendants_of_the_call_span(self, monkeypatch, otel):
        from contextlib import asynccontextmanager

        from google.adk.agents import LlmAgent
        from google.adk.agents.run_config import RunConfig
        from google.adk.models.base_llm import BaseLlm
        from google.adk.models.base_llm_connection import BaseLlmConnection
        from google.adk.models.llm_response import LlmResponse
        from google.adk.telemetry import tracing
        from google.genai import types

        from agentkernel.core.runtime import Runtime
        from agentkernel.core.session.in_memory import InMemorySessionStore
        from agentkernel.core.tool import SystemToolFactory
        from agentkernel.framework.adk.adk import GoogleADKModule, GoogleADKRealtimeRunner

        tracer, exporter = otel
        monkeypatch.setattr(tracing, "tracer", tracer)
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
        monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))

        class Connection(BaseLlmConnection):
            closed = False

            async def send_history(self, history):
                pass

            async def send_content(self, content):
                pass

            async def send_realtime(self, blob):
                pass

            async def receive(self):
                call = types.FunctionCall(id="c1", name="lookup_order", args={"order": "7"})
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
                while not self.closed:
                    await asyncio.sleep(0.01)

            async def close(self):
                self.closed = True

        class Model(BaseLlm):
            model: str = "fake-live"

            async def generate_content_async(self, llm_request, stream=False):
                raise NotImplementedError("live only")
                yield

            @asynccontextmanager
            async def connect(self, llm_request):
                connection = Connection()
                try:
                    yield connection
                finally:
                    connection.closed = True

        def lookup_order(order: str) -> str:
            """Look up an order."""
            return f"order {order}: shipped"

        class TracedADK(TracedRealtimeRunner, GoogleADKRealtimeRunner):
            SPAN_NAME = "Agent Kernel ADK realtime"

            def _start_call_span(self, session, agent):
                return OTelRealtimeCallSpan(tracer, self.SPAN_NAME, {"session_id": session.id})

        with Runtime(InMemorySessionStore()):
            module = GoogleADKModule([LlmAgent(name="voice", model=Model(), tools=[lookup_order])])
            agent = module.get_agent("voice")
            module.run_options(agent.agent, run_config=RunConfig(response_modalities=["AUDIO"]))
            runner = TracedADK()
            await runner.connect(Session("call-n"), agent, _noop)
            for _ in range(300):
                if any(s.name.startswith("execute_tool") for s in exporter.get_finished_spans()):
                    break
                await asyncio.sleep(0.01)
            await runner.disconnect()

        spans = _by_name(exporter)
        call = spans["Agent Kernel ADK realtime"]
        invoke = spans["invoke_agent voice"]
        tool = spans["execute_tool lookup_order"]
        assert invoke.parent.span_id == call.context.span_id
        assert tool.parent.span_id == invoke.context.span_id
        assert call.attributes["session_id"] == "call-n"
        assert call.end_time >= invoke.end_time  # the call span ends last, in disconnect
