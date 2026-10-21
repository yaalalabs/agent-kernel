"""Run the real Agents SDK realtime engine against an offline model transport."""

import asyncio
import base64
import json

import pytest
import pytest_asyncio
from agents import Agent as TextAgent
from agents import GuardrailFunctionOutput, OutputGuardrail, RunContextWrapper, function_tool, handoff
from agents.realtime import RealtimeAgent, RealtimeSession
from agents.realtime.model import RealtimeModel
from agents.realtime.model_events import (
    RealtimeModelAudioEvent,
    RealtimeModelAudioInterruptedEvent,
    RealtimeModelExceptionEvent,
    RealtimeModelInputAudioTranscriptionCompletedEvent,
    RealtimeModelOutputTextDeltaEvent,
    RealtimeModelRawServerEvent,
    RealtimeModelToolCallEvent,
    RealtimeModelTranscriptDeltaEvent,
    RealtimeModelTurnEndedEvent,
    RealtimeModelTurnStartedEvent,
)
from agents.realtime.model_inputs import RealtimeModelSendAudio, RealtimeModelSendInterrupt, RealtimeModelSendToolOutput, RealtimeModelSendUserInput
from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel
from agents.tool_guardrails import ToolGuardrailFunctionOutput, ToolInputGuardrail, ToolOutputGuardrail

from agentkernel import Agent, Session
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.framework.openai.openai import OpenAIModule, OpenAIToolBuilder
from agentkernel.pipeline.realtime_pool import RealtimeConnection
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


class _Model(RealtimeModel):
    def __init__(self):
        self.listeners = []
        self.options = None
        self.sent = []
        self.closed = False

    async def connect(self, options):
        self.options = options

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    async def send_event(self, event):
        self.sent.append(event)

    async def send_event_if(self, event, send_if):
        if not send_if():
            return False
        await self.send_event(event)
        return True

    async def close(self):
        self.closed = True

    async def emit(self, event):
        for listener in list(self.listeners):
            await listener.on_event(event)

    def outputs(self):
        return [event for event in self.sent if isinstance(event, RealtimeModelSendToolOutput)]


class _Call:
    def __init__(self, agent, *, session_id="call", context=None, config=None, model=None, model_config=None):
        self.model = model or _Model()
        self.runtime = Runtime(InMemorySessionStore())
        with self.runtime:
            self.module = OpenAIModule([agent]).run_options(
                agent, model=self.model, config={"tracing_disabled": True, **(config or {})}, model_config=model_config
            )
        wrapped = self.module.get_agent(agent.name)
        self.session = Session(session_id)
        if context is not None:
            self.session.set_framework_context(context)
        self.connection = RealtimeConnection(session_id, wrapped, self.runtime, self.session, asyncio.get_running_loop())
        self.events = []
        self.chunks = []
        report = self.connection.handle_framework_event

        async def record(kind, data):
            self.events.append((kind, data))
            await report(kind, data)

        async def emit(chunk):
            self.chunks.append(chunk)

        self.connection.handle_framework_event = record
        self.connection._emit = emit

    def kinds(self):
        return [kind for kind, _ in self.events]

    async def until(self, condition):
        async def wait():
            while not condition():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait(), timeout=3)


@pytest_asyncio.fixture
async def call_factory():
    calls = []

    async def start(agent, **options):
        call = _Call(agent, **options)
        calls.append(call)
        await call.connection.connect()
        return call

    yield start
    for call in calls:
        await call.connection.close()
    InMemoryTransport.reset()


@pytest.mark.asyncio
class TestNativeOpenAIRealtime:
    async def test_native_session_configuration_and_instructions(self, call_factory):
        async def instructions(context, agent):
            return f"Help {context.context['customer']} as {agent.name}"

        agent = RealtimeAgent(name="support", instructions=instructions)
        config = {"model_settings": {"model_name": "gpt-realtime", "voice": "alloy", "turn_detection": {"type": "semantic_vad"}}}
        call = await call_factory(agent, context={"customer": "Pat"}, config=config)

        assert isinstance(call.connection.adapter._connection, RealtimeSession)
        assert call.connection.adapter.runs_tools is True
        settings = call.model.options["initial_model_settings"]
        assert settings["instructions"] == "Help Pat as support"
        assert settings["voice"] == "alloy" and settings["turn_detection"] == {"type": "semantic_vad"}
        assert config["model_settings"]["turn_detection"] == {"type": "semantic_vad"}

    async def test_regular_text_agents_are_not_silently_converted(self, call_factory):
        with pytest.raises(TypeError, match="RealtimeAgent"):
            await call_factory(TextAgent(name="text"))

    async def test_audio_text_and_transcripts_use_native_session(self, call_factory):
        call = await call_factory(RealtimeAgent(name="support"))
        adapter = call.connection.adapter
        await adapter.append_audio(base64.b64encode(b"\x01\x00" * 4).decode())
        await adapter.send_text("Hello")
        assert any(isinstance(event, RealtimeModelSendAudio) and event.audio == b"\x01\x00" * 4 for event in call.model.sent)
        assert any(isinstance(event, RealtimeModelSendUserInput) and event.user_input == "Hello" for event in call.model.sent)

        await call.model.emit(RealtimeModelInputAudioTranscriptionCompletedEvent(item_id="user", transcript="Hello"))
        await call.model.emit(RealtimeModelTurnStartedEvent(response_id="response"))
        await call.model.emit(RealtimeModelTranscriptDeltaEvent(item_id="answer", delta="Hi", response_id="response"))
        await call.model.emit(RealtimeModelAudioEvent(data=b"\x01\x00" * 8, response_id="response", item_id="answer", content_index=1))
        await call.model.emit(RealtimeModelTurnEndedEvent(response_id="response"))
        await call.until(lambda: any(chunk.done for chunk in call.chunks))

        assert call.kinds() == ["caller_transcript", "transcript_delta", "audio_delta", "done"]
        assert [chunk.event.type for chunk in call.chunks if chunk.event] == ["agent_changed", "text_delta", "audio_delta"]
        assert adapter._playback.get_state()["current_item_content_index"] == 1

    @pytest.mark.parametrize("responding", [False, True])
    async def test_speech_events_and_native_interrupt_are_not_reported_twice(self, call_factory, responding):
        call = await call_factory(RealtimeAgent(name="support"))
        if responding:
            await call.model.emit(RealtimeModelTurnStartedEvent(response_id="r"))
        await call.model.emit(RealtimeModelRawServerEvent(data={"type": "input_audio_buffer.speech_started"}))
        if responding:
            await call.model.emit(RealtimeModelAudioInterruptedEvent(item_id="answer", content_index=0))
        await call.model.emit(RealtimeModelRawServerEvent(data={"type": "input_audio_buffer.speech_stopped"}))
        await call.until(lambda: "speech_stopped" in call.kinds())
        assert call.kinds() == ["interrupt" if responding else "speech_started", "speech_stopped"]

    async def test_tools_run_once_with_native_and_ak_context(self, call_factory):
        seen = []

        async def researcher(context: RunContextWrapper[dict], topic: str) -> str:
            seen.append((Session.current().id, Agent.current().name, ToolContext.get().session.id, context.context["customer"], topic))
            return "Research complete"

        tool = OpenAIToolBuilder.bind([researcher])[0]
        original = tool.on_invoke_tool
        agent = RealtimeAgent(name="support", tools=[tool])
        call = await call_factory(agent, context={"customer": "Pat"})
        await call.model.emit(RealtimeModelToolCallEvent(name="researcher", call_id="tool-1", arguments='{"topic":"billing"}'))
        await call.until(lambda: len(call.model.outputs()) == 1)

        assert seen == [("call", "support", "call", "Pat", "billing")]
        assert call.model.outputs()[0].output == "Research complete"
        assert "tool_call" not in call.kinds()
        assert tool.on_invoke_tool is original and agent.tools == [tool]

    async def test_native_tool_input_guardrails_are_applied(self, call_factory):
        invoked = []
        checked = []

        def check(data):
            checked.append(data.context.context["customer"])
            return ToolGuardrailFunctionOutput.reject_content("Blocked by reviewer")

        @function_tool(tool_input_guardrails=[ToolInputGuardrail(check)])
        async def confidential() -> str:
            invoked.append(True)
            return "Private result"

        call = await call_factory(RealtimeAgent(name="support", tools=[confidential]), context={"customer": "Pat"})
        await call.model.emit(RealtimeModelToolCallEvent(name="confidential", call_id="guarded", arguments="{}"))
        await call.until(lambda: bool(call.model.outputs()))
        assert checked == ["Pat"]
        assert invoked == []
        assert call.model.outputs()[0].output == "Blocked by reviewer"

    async def test_output_guardrail_clears_playback(self, call_factory):
        checked = []

        async def check(context, agent, text):
            checked.append(text)
            return GuardrailFunctionOutput(output_info="blocked", tripwire_triggered=True)

        agent = RealtimeAgent(name="support", output_guardrails=[OutputGuardrail(check)])
        call = await call_factory(agent, config={"guardrails_settings": {"debounce_text_length": 1}})
        await call.model.emit(RealtimeModelTurnStartedEvent(response_id="r"))
        await call.model.emit(RealtimeModelOutputTextDeltaEvent(item_id="answer", delta="Blocked answer", response_id="r"))
        await call.until(lambda: "interrupt" in call.kinds())
        assert checked == ["Blocked answer"]
        await call.until(lambda: any(isinstance(event, RealtimeModelSendInterrupt) for event in call.model.sent))

    @pytest.mark.parametrize("explicit", [False, True])
    async def test_native_handoff_and_return_preserve_context(self, call_factory, explicit):
        transferred = []
        supervisor = RealtimeAgent(name="supervisor")
        specialist = RealtimeAgent(name="specialist", instructions="Help with billing", handoffs=[supervisor])

        async def on_handoff(context):
            transferred.append((context.context["customer"], Session.current().id))

        supervisor.handoffs = [handoff(specialist, on_handoff=on_handoff)] if explicit else [specialist]
        call = await call_factory(supervisor, context={"customer": "Pat"})
        assert call.connection.adapter.team(call.connection.agent) == ["supervisor", "specialist"]
        await call.model.emit(RealtimeModelToolCallEvent(name="transfer_to_specialist", call_id="handoff-1", arguments="{}"))
        await call.until(lambda: "agent_changed" in call.kinds())
        await call.model.emit(RealtimeModelToolCallEvent(name="transfer_to_supervisor", call_id="handoff-2", arguments="{}"))
        await call.until(lambda: call.kinds().count("agent_changed") == 2)
        assert transferred == ([("Pat", "call")] if explicit else [])
        assert [data["agent"] for kind, data in call.events if kind == "agent_changed"] == ["specialist", "supervisor"]
        assert supervisor.handoffs[0] is not call.model.options["initial_model_settings"]["handoffs"][0]

    async def test_long_tool_is_busy_and_cancelled_when_the_call_closes(self, call_factory):
        started, cancelled = asyncio.Event(), asyncio.Event()

        @function_tool
        async def researcher() -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        call = await call_factory(RealtimeAgent(name="support", tools=[researcher]))
        await call.model.emit(RealtimeModelToolCallEvent(name="researcher", call_id="slow", arguments="{}"))
        await asyncio.wait_for(started.wait(), timeout=3)
        assert call.connection.is_responding and call.session._lock.locked()
        await call.connection.close()
        assert cancelled.is_set() and not call.session._lock.locked()
        assert call.model.outputs() == [] and call.model.closed

    async def test_native_tool_timeout_is_preserved(self, call_factory):
        @function_tool
        async def researcher() -> str:
            await asyncio.Event().wait()

        researcher.timeout_seconds = 0.01
        researcher.timeout_error_function = lambda context, error: "Research timed out"
        call = await call_factory(RealtimeAgent(name="support", tools=[researcher]))
        await call.model.emit(RealtimeModelToolCallEvent(name="researcher", call_id="slow", arguments="{}"))
        await call.until(lambda: bool(call.model.outputs()))
        assert call.model.outputs()[0].output == "Research timed out"
        await call.until(lambda: not call.session._lock.locked())

    async def test_slow_input_guardrail_is_scoped_and_keeps_the_call_busy(self, call_factory):
        entered, release = asyncio.Event(), asyncio.Event()

        async def check(data):
            assert Session.current().id == "call"
            entered.set()
            await release.wait()
            return ToolGuardrailFunctionOutput.allow()

        @function_tool(tool_input_guardrails=[ToolInputGuardrail(check)])
        async def researcher() -> str:
            return "complete"

        researcher.timeout_seconds = 0.5
        call = await call_factory(RealtimeAgent(name="support", tools=[researcher]))
        await call.model.emit(RealtimeModelToolCallEvent(name="researcher", call_id="guarded", arguments="{}"))
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert call.connection.is_responding and call.session._lock.locked()
        release.set()
        await call.until(lambda: bool(call.model.outputs()))
        assert call.model.outputs()[0].output == "complete"
        await call.until(lambda: not call.session._lock.locked())

    async def test_synchronous_bound_tool_and_duplicate_dispatch(self, call_factory):
        seen = []

        def weather(location: str) -> str:
            seen.append(ToolContext.get().session.id)
            return f"{location}:{Session.current().id}"

        call = await call_factory(RealtimeAgent(name="support", tools=OpenAIToolBuilder.bind([weather])))
        event = RealtimeModelToolCallEvent(name="weather", call_id="weather", arguments='{"location":"Paris"}')
        await call.model.emit(event)
        await call.until(lambda: bool(call.model.outputs()))
        await call.model.emit(event)
        await asyncio.sleep(0.01)
        assert seen == ["call"]
        assert len(call.model.outputs()) == 1 and call.model.outputs()[0].output == "Paris:call"

    async def test_native_websocket_transport_parses_audio_and_sends_tool_results(self, call_factory, monkeypatch):
        class Socket:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.sent = []
                self.closed = False

            async def send(self, message):
                self.sent.append(json.loads(message))

            def __aiter__(self):
                return self

            async def __anext__(self):
                return json.dumps(await self.incoming.get())

            async def close(self):
                self.closed = True

        socket = Socket()

        async def connect(url, **options):
            return socket

        monkeypatch.setattr("websockets.connect", connect)

        @function_tool
        async def weather() -> str:
            return "Sunny"

        call = await call_factory(
            RealtimeAgent(name="support", tools=[weather]), model=OpenAIRealtimeWebSocketModel(), model_config={"api_key": "offline-test"}
        )
        assert socket.sent[0]["type"] == "session.update"
        await socket.incoming.put(
            {
                "type": "response.output_audio.delta",
                "event_id": "audio",
                "response_id": "r",
                "item_id": "answer",
                "output_index": 0,
                "content_index": 0,
                "delta": base64.b64encode(b"\0\0" * 240).decode(),
            }
        )
        await call.until(lambda: "audio_delta" in call.kinds())
        await socket.incoming.put(
            {
                "type": "response.output_item.done",
                "event_id": "tool",
                "response_id": "r",
                "output_index": 0,
                "item": {
                    "id": "tool-item",
                    "type": "function_call",
                    "call_id": "weather",
                    "name": "weather",
                    "arguments": "{}",
                    "status": "completed",
                },
            }
        )
        await socket.incoming.put({"type": "response.done", "event_id": "done", "response": {"id": "r", "status": "completed", "output": []}})
        await call.until(lambda: any(message.get("item", {}).get("type") == "function_call_output" for message in socket.sent))
        result = next(message["item"] for message in socket.sent if message.get("item", {}).get("type") == "function_call_output")
        assert result["call_id"] == "weather" and result["output"] == "Sunny"
        await call.connection.close()
        assert socket.closed

    async def test_two_calls_do_not_share_native_tool_scope(self, call_factory):
        seen = []

        @function_tool
        async def identify() -> str:
            seen.append(Session.current().id)
            return Session.current().id

        agent = RealtimeAgent(name="support", tools=[identify])
        first = await call_factory(agent, session_id="first")
        second = await call_factory(agent, session_id="second")
        await asyncio.gather(
            first.model.emit(RealtimeModelToolCallEvent(name="identify", call_id="same-id", arguments="{}")),
            second.model.emit(RealtimeModelToolCallEvent(name="identify", call_id="same-id", arguments="{}")),
        )
        await first.until(lambda: bool(first.model.outputs()) and bool(second.model.outputs()))
        assert sorted(seen) == ["first", "second"]
        assert first.model.outputs()[0].output == "first" and second.model.outputs()[0].output == "second"

    async def test_errors_fail_the_call_and_disconnect_is_idempotent(self, call_factory):
        call = await call_factory(RealtimeAgent(name="support"))
        await call.model.emit(RealtimeModelExceptionEvent(exception=ConnectionError("connection lost")))
        await call.until(lambda: call.connection.closed)
        assert any(chunk.error and "connection lost" in chunk.error for chunk in call.chunks)
        await call.connection.adapter.disconnect()
        await call.connection.adapter.disconnect()
        assert call.model.closed and not call.model.listeners

    async def test_recoverable_sdk_errors_do_not_end_the_call(self, call_factory, caplog):
        @function_tool
        async def weather() -> str:
            return "Sunny"

        call = await call_factory(RealtimeAgent(name="support", tools=[weather]))
        await call.model.emit(RealtimeModelToolCallEvent(name="unknown", call_id="unknown", arguments="{}"))
        await call.until(lambda: "Tool unknown not found" in caplog.text)
        assert not call.connection.closed
        await call.model.emit(RealtimeModelToolCallEvent(name="weather", call_id="weather", arguments="{}"))
        await call.until(lambda: len(call.model.outputs()) == 2)
        assert call.model.outputs()[-1].output == "Sunny"

    async def test_native_handoff_callback_failure_fails_the_call(self, call_factory):
        target = RealtimeAgent(name="specialist")

        async def refuse(context):
            raise ValueError("Transfer refused")

        source = RealtimeAgent(name="support", handoffs=[handoff(target, on_handoff=refuse)])
        call = await call_factory(source)
        await call.model.emit(RealtimeModelToolCallEvent(name="transfer_to_specialist", call_id="transfer", arguments="{}"))
        await call.until(lambda: call.connection.closed)
        assert any(chunk.error and "Transfer refused" in chunk.error for chunk in call.chunks)
        assert "agent_changed" not in call.kinds()

    async def test_failed_connect_releases_the_native_model(self, call_factory):
        class Refused(_Model):
            async def connect(self, options):
                raise ConnectionError("refused")

        model = Refused()
        with pytest.raises(ConnectionError, match="refused"):
            await call_factory(RealtimeAgent(name="support"), model=model)
        assert model.closed and not model.listeners

    async def test_connect_does_not_report_ready_before_the_native_model_connects(self, call_factory):
        entered, release = asyncio.Event(), asyncio.Event()

        class Delayed(_Model):
            async def connect(self, options):
                entered.set()
                await release.wait()
                await super().connect(options)

        task = asyncio.create_task(call_factory(RealtimeAgent(name="support"), model=Delayed()))
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert not task.done()
        release.set()
        call = await task
        assert call.connection.is_ready

    @pytest.mark.parametrize("option", ["approval", "output_guardrail", "sync_dispatch", "codec", "settings_tools"])
    async def test_unmapped_native_features_fail_explicitly(self, call_factory, option):
        agent = RealtimeAgent(name="support")
        config = {}
        if option == "approval":

            @function_tool(needs_approval=True)
            async def gated() -> str:
                return "approved"

            agent.tools = [gated]
        elif option == "output_guardrail":

            @function_tool(tool_output_guardrails=[ToolOutputGuardrail(lambda data: ToolGuardrailFunctionOutput.reject_content("blocked"))])
            async def guarded() -> str:
                return "private"

            agent.tools = [guarded]
        elif option == "sync_dispatch":
            config = {"async_tool_calls": False}
        elif option == "codec":
            config = {"model_settings": {"output_audio_format": "g711_ulaw"}}
        else:
            config = {"model_settings": {"tools": []}}
        with pytest.raises((NotImplementedError, ValueError)):
            await call_factory(agent, config=config)

    async def test_paced_output_is_the_playback_estimate(self, call_factory):
        call = await call_factory(RealtimeAgent(name="support"))
        released, emitted = asyncio.Event(), asyncio.Event()

        async def blocked_emit(chunk):
            if chunk.event and chunk.event.type == "audio_delta":
                emitted.set()
                await released.wait()

        call.connection._emit = blocked_emit
        await call.model.emit(RealtimeModelAudioEvent(data=b"\0\0" * 240, response_id="r", item_id="answer", content_index=2))
        await asyncio.wait_for(emitted.wait(), timeout=3)
        tracker = call.model.options["playback_tracker"]
        assert tracker.get_state()["elapsed_ms"] is None
        released.set()
        await call.until(lambda: tracker.get_state()["elapsed_ms"] is not None)
        assert tracker.get_state() == {"current_item_id": "answer", "current_item_content_index": 2, "elapsed_ms": 10.0}
