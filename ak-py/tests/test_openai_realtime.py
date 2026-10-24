"""The OpenAI realtime adapter over the Agents SDK's own ``RealtimeRunner`` / ``RealtimeSession`` (#810).

The model is a scripted ``RealtimeModel`` (the SDK's public transport interface), so the real
session runs: its tool execution, handoffs, approval and guardrail paths are the SDK's, and what is
asserted is what Agent Kernel reports from them. No test here reaches the network.
"""

import asyncio
import base64
import json
from typing import Any

import pytest
from agents import Agent as SDKAgent
from agents import function_tool
from agents.realtime import (
    RealtimeAgent,
    RealtimeModel,
    RealtimeModelAudioEvent,
    RealtimeModelAudioInterruptedEvent,
    RealtimeModelInputAudioTranscriptionCompletedEvent,
    RealtimeModelToolCallEvent,
    RealtimeModelTranscriptDeltaEvent,
    RealtimeModelTurnEndedEvent,
    RealtimeModelTurnStartedEvent,
    realtime_handoff,
)
from agents.realtime.model_inputs import RealtimeModelSendToolOutput, RealtimeModelSendUserInput

from agentkernel.core import Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.config import AKConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import SystemToolFactory
from agentkernel.framework.openai.openai import OpenAIAgent, OpenAIModule, OpenAIRealtimeRunner, OpenAIRunner

# --- a scripted model ---------------------------------------------------------------------------


class ScriptedModel(RealtimeModel):
    """A ``RealtimeModel`` that plays one scripted response whenever the session asks for one.

    A script step is a coroutine function taking the model; it emits the response's events through
    :meth:`emit`. A response is requested by a user message, or by the last tool output of the
    previous response (the SDK marks each output ``start_response``; the real transport collapses
    them into one ``response.create``, so this does too).
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.sent: list[Any] = []
        self.listeners: list[Any] = []
        self.connected = False
        self.closed = False
        self._open_calls: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    async def connect(self, options):
        self.connected = True

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    async def send_event(self, event):
        self.sent.append(event)
        if isinstance(event, RealtimeModelSendUserInput):
            self._respond()
        elif isinstance(event, RealtimeModelSendToolOutput):
            self._open_calls.discard(event.tool_call.call_id)
            if event.start_response and not self._open_calls:
                self._respond()

    def _respond(self):
        if not self.steps:
            return
        step = self.steps.pop(0)

        async def after_send():
            # A real model responds after the SDK has finished sending and recording the tool
            # output. Running a scripted response in that same send call is re-entrant.
            await asyncio.sleep(0.01)
            await step(self)

        task = asyncio.create_task(after_send())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def emit(self, event):
        for listener in list(self.listeners):
            await listener.on_event(event)

    async def close(self):
        self.closed = True
        pending = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def tool_outputs(self) -> dict[str, str]:
        return {e.tool_call.name: e.output for e in self.sent if isinstance(e, RealtimeModelSendToolOutput)}


def speak(text: str, response_id: str, item_id: str = "item", audio: bytes = b"\x01\x00" * 8):
    """The events of a response that says ``text``."""
    return [
        RealtimeModelAudioEvent(data=audio, response_id=response_id, item_id=item_id, content_index=0),
        RealtimeModelTranscriptDeltaEvent(item_id=item_id, delta=text, response_id=response_id),
    ]


def response(response_id: str, *, say: str | None = None, calls: tuple[tuple[str, str, str], ...] = ()):
    """A scripted response: optionally speech, then function calls ``(name, call_id, arguments)``, then its end."""

    async def step(model: ScriptedModel):
        await model.emit(RealtimeModelTurnStartedEvent(response_id=response_id))
        if say:
            for event in speak(say, response_id, item_id=f"item-{response_id}"):
                await model.emit(event)
        for name, call_id, arguments in calls:
            model._open_calls.add(call_id)
            await model.emit(RealtimeModelToolCallEvent(name=name, call_id=call_id, arguments=arguments))
        await model.emit(RealtimeModelTurnEndedEvent(response_id=response_id))

    return step


class Recorder:
    """The pool's callback: every event the adapter reports, in order."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.changed = asyncio.Event()

    async def __call__(self, kind: str, data: dict):
        self.events.append((kind, data))
        self.changed.set()

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]

    def of(self, kind: str) -> list[dict]:
        return [data for k, data in self.events if k == kind]

    def speakers(self) -> list[str]:
        return [data["agent"] for data in self.of("agent_changed")]

    async def until(self, kind: str, count: int = 1, timeout: float = 5.0):
        async def wait():
            while len(self.of(kind)) < count:
                self.changed.clear()
                await self.changed.wait()

        await asyncio.wait_for(wait(), timeout)


# --- agents --------------------------------------------------------------------------------------


@pytest.fixture
def runtime():
    with Runtime(SessionStoreBuilder.build()) as rt:
        yield rt


def _no_system_tools(monkeypatch):
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))


def _team(*, billing_tools=(), coordinator_tools=()):
    """Coordinator and billing, each handing the turn to the other, each with a native tool of its own."""
    coordinator = RealtimeAgent(name="coordinator", instructions="Greet and route.", tools=list(coordinator_tools))
    billing = RealtimeAgent(name="billing", instructions="Answer billing.", tools=list(billing_tools))
    coordinator.handoffs = [billing]
    billing.handoffs = [coordinator]
    return coordinator, billing


@function_tool
async def lookup_invoice(invoice: str) -> str:
    """Look up an invoice."""
    return f"invoice {invoice}: 42.00"


@function_tool
async def note_greeting() -> str:
    """Note that the caller was greeted."""
    return "greeted"


def test_realtime_agent_keeps_native_tools_without_loading_ak_system_tools(monkeypatch):
    monkeypatch.setattr(AKConfig.get().execution, "mode", ExecutionMode.REALTIME)

    def unexpected(*args):
        raise AssertionError("AK system tools and prompt guidance must not be loaded for realtime")

    monkeypatch.setattr(SystemToolFactory, "get_all", unexpected)
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", unexpected)
    native = RealtimeAgent(name="voice", instructions="Speak clearly.", tools=[note_greeting])

    OpenAIAgent("voice", OpenAIRunner(), native)

    assert [tool.name for tool in native.tools] == ["note_greeting"]
    assert native.instructions == "Speak clearly."


async def _connect(runtime, module: OpenAIModule, root_name: str, model: ScriptedModel, session_id="s1", recorder=None):
    agent = module.get_agent(root_name)
    session = Session(session_id)
    recorder = recorder or Recorder()
    runner = OpenAIRealtimeRunner()
    # The model is a native RealtimeRunner setting, declared where any other native setting is.
    agent.run_options.update(model=model)
    await runner.connect(session, agent, recorder)
    return runner, recorder, session


# --- the conversation: A -> B -> A, each agent's own tools ---------------------------------------


class TestHandoffsAndTools:
    @pytest.mark.asyncio
    async def test_a_conversation_moves_to_billing_and_back_with_each_agents_own_tools(self, runtime, monkeypatch):
        coordinator, billing = _team(billing_tools=[lookup_invoice], coordinator_tools=[note_greeting])
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator, billing])
        model = ScriptedModel(
            response("r1", say="Let me get billing.", calls=(("transfer_to_billing", "c1", "{}"),)),
            response("r2", calls=(("lookup_invoice", "c2", '{"invoice": "7"}'),)),
            response("r3", say="Invoice seven is forty-two.", calls=(("transfer_to_coordinator", "c4", "{}"),)),
            response("r4", say="Anything else?", calls=(("note_greeting", "c5", "{}"),)),
        )
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("I have a billing question")
            await recorder.until("done", 4)
            await asyncio.sleep(0.05)

            # The native SDK ran every tool and handoff; AK reports speakers in the order the turn moved.
            assert recorder.speakers() == ["billing", "coordinator"]
            outputs = model.tool_outputs()
            assert outputs["lookup_invoice"] == "invoice 7: 42.00"
            assert outputs["note_greeting"] == "greeted"
            assert set(outputs) >= {"transfer_to_billing", "transfer_to_coordinator"}

            # A change is reported before the new speaker's first output, and after the previous one's last.
            kinds = recorder.kinds()
            first_billing_change = kinds.index("agent_changed")
            assert kinds[:first_billing_change].count("audio_delta") == 1  # the coordinator's "Let me get billing."
            assert kinds[first_billing_change + 1 :].index("audio_delta") >= 0
            transcript = "".join(d["delta"] for d in recorder.of("transcript_delta"))
            assert transcript == "Let me get billing.Invoice seven is forty-two.Anything else?"
        finally:
            await runner.disconnect()

    @pytest.mark.asyncio
    async def test_closing_one_session_leaves_the_other_running(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model_a = ScriptedModel(response("r1", say="a"))
        model_b = ScriptedModel(response("r1", say="b"))
        runner_a, rec_a, _ = await _connect(runtime, module, "coordinator", model_a, session_id="call-a")
        runner_b, rec_b, _ = await _connect(runtime, module, "coordinator", model_b, session_id="call-b")
        try:
            await runner_a.disconnect()
            assert model_a.closed and not model_b.closed
            await runner_b.send_text("still there?")
            await rec_b.until("done", 1)
            assert rec_a.of("error") == [] and rec_b.of("error") == []
        finally:
            await runner_b.disconnect()
        assert runtime is not None


# --- what the adapter reports ---------------------------------------------------------------------


def heard(transcript: str, then, *, item_id: str = "item-in-1"):
    """A scripted step: the model transcribes the caller's speech, then plays ``then``."""

    async def step(model: ScriptedModel):
        await model.emit(RealtimeModelInputAudioTranscriptionCompletedEvent(item_id=item_id, transcript=transcript))
        await then(model)

    return step


class TestEventMapping:
    @pytest.mark.asyncio
    async def test_a_finished_caller_utterance_is_reported_before_the_reply_that_answers_it(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model = ScriptedModel(heard("  we have 2000 patients ", response("r1", say="Noted.")))
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("hi")
            await recorder.until("done")
        finally:
            await runner.disconnect()

        assert recorder.kinds()[0] == "input_transcript"
        assert recorder.of("input_transcript") == [{"text": "we have 2000 patients", "message_id": "item-in-1"}]
        assert recorder.kinds().index("input_transcript") < recorder.kinds().index("transcript_delta")

    @pytest.mark.asyncio
    async def test_an_empty_caller_transcript_is_not_reported(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model = ScriptedModel(heard("   ", response("r1", say="Hi.")))
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("hi")
            await recorder.until("done")
        finally:
            await runner.disconnect()

        assert recorder.of("input_transcript") == []

    @pytest.mark.asyncio
    async def test_audio_text_and_the_end_of_a_turn_are_reported_in_order(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model = ScriptedModel(response("r1", say="Hello there."))
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("hi")
            await recorder.until("done")
        finally:
            await runner.disconnect()

        assert recorder.kinds() == ["audio_delta", "transcript_delta", "done"]
        audio, text = recorder.of("audio_delta")[0], recorder.of("transcript_delta")[0]
        # PCM16 bytes reach the pool as base64, tagged with the item they belong to.
        assert base64.b64decode(audio["delta"]) == b"\x01\x00" * 8
        assert audio["message_id"] == text["message_id"] == "item-r1"
        assert text["delta"] == "Hello there."

    @pytest.mark.asyncio
    async def test_the_users_text_and_audio_reach_the_native_session(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model = ScriptedModel(response("r1", say="ok"))
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.append_audio(base64.b64encode(b"\x02\x00\x03\x00").decode())
            await runner.send_text("typed")
            await recorder.until("done")
        finally:
            await runner.disconnect()

        sent_audio = [e for e in model.sent if type(e).__name__ == "RealtimeModelSendAudio"]
        assert [e.audio for e in sent_audio] == [b"\x02\x00\x03\x00"]
        assert [e.user_input for e in model.sent if isinstance(e, RealtimeModelSendUserInput)] == ["typed"]

    @pytest.mark.asyncio
    async def test_a_barge_in_during_a_response_is_an_interrupt_and_afterwards_only_a_speech_start(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])

        async def talk_then_get_cut_off(model: ScriptedModel):
            await model.emit(RealtimeModelTurnStartedEvent(response_id="r1"))
            for event in speak("Long answer", "r1", item_id="i1"):
                await model.emit(event)
            await model.emit(RealtimeModelAudioInterruptedEvent(item_id="i1", content_index=0))
            await model.emit(RealtimeModelAudioInterruptedEvent(item_id="i1", content_index=0))  # the same barge-in, reported again
            await model.emit(RealtimeModelTurnEndedEvent(response_id="r1"))
            # The user speaks again after the turn is over, over audio the pool may still be pacing.
            await model.emit(RealtimeModelAudioInterruptedEvent(item_id="i1", content_index=0))

        model = ScriptedModel(talk_then_get_cut_off)
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("hi")
            await recorder.until("speech_started")
        finally:
            await runner.disconnect()

        assert recorder.kinds() == ["audio_delta", "transcript_delta", "interrupt", "speech_started", "done", "speech_started"]

    @pytest.mark.asyncio
    async def test_an_sdk_error_event_is_not_fatal_but_a_failed_session_is(self, runtime, monkeypatch):
        from agents.realtime import RealtimeModelErrorEvent
        from agents.realtime.model_events import RealtimeModelExceptionEvent

        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        model = ScriptedModel()
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await model.emit(RealtimeModelErrorEvent(error={"message": "response_cancel_not_active"}))
            await asyncio.sleep(0.05)
            assert recorder.of("error") == []  # the SDK keeps going after one of these

            await model.emit(RealtimeModelExceptionEvent(exception=RuntimeError("socket dropped"), context="listener"))
            await recorder.until("error")
        finally:
            await runner.disconnect()

        assert "socket dropped" in recorder.of("error")[0]["message"]

    @pytest.mark.asyncio
    async def test_a_session_that_ends_on_its_own_is_a_failure_and_a_disconnect_is_not(self, runtime, monkeypatch):
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        ended, closed = ScriptedModel(), ScriptedModel()
        runner_ended, rec_ended, _ = await _connect(runtime, module, "coordinator", ended, session_id="a")
        runner_closed, rec_closed, _ = await _connect(runtime, module, "coordinator", closed, session_id="b")
        try:
            await runner_ended._session.close()  # the SDK session ends under the adapter
            await rec_ended.until("error")
            await runner_closed.disconnect()
            await asyncio.sleep(0.05)
        finally:
            await runner_ended.disconnect()
            await runner_closed.disconnect()

        assert "ended" in rec_ended.of("error")[0]["message"]
        assert rec_closed.of("error") == []

    @pytest.mark.asyncio
    async def test_the_sdks_default_playback_estimate_is_kept(self, runtime, monkeypatch):
        """Queue delivery is not playout, so no playback tracker is handed to the SDK."""
        coordinator, _ = _team()
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator])
        captured = {}

        class Capturing(ScriptedModel):
            async def connect(self, options):
                captured.update(options)

        runner, _, _ = await _connect(runtime, module, "coordinator", Capturing())
        await runner.disconnect()
        assert "playback_tracker" not in captured


class TestSpeakerRoster:
    def test_the_team_is_what_the_graph_names_publicly(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        billing = RealtimeAgent(name="billing")
        refunds = RealtimeAgent(name="refunds")
        coordinator = RealtimeAgent(name="coordinator", handoffs=[billing, realtime_handoff(refunds)])
        billing.handoffs = [coordinator]
        module = OpenAIModule([coordinator])
        assert OpenAIRealtimeRunner().team(module.get_agent("coordinator")) == ["coordinator", "billing", "refunds"]

    @pytest.mark.asyncio
    async def test_an_agent_the_roster_did_not_hold_is_announced_with_the_roster_when_it_first_speaks(self, runtime, monkeypatch):
        """A hand-built handoff names the agent it expects; the agent it returns at run time may be another."""
        from agents.handoffs import Handoff

        _no_system_tools(monkeypatch)
        late = RealtimeAgent(name="late-specialist", instructions="x")

        async def route(context, arguments):
            return late

        router = Handoff(
            tool_name="route_call",
            tool_description="Route the call",
            input_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
            on_invoke_handoff=route,
            agent_name="expected-specialist",
        )
        coordinator = RealtimeAgent(name="coordinator", handoffs=[router])
        module = OpenAIModule([coordinator])
        model = ScriptedModel(
            response("r1", calls=(("route_call", "c1", "{}"),)),
            response("r2", say="I am the specialist."),
        )
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            assert runner.team(module.get_agent("coordinator")) == ["coordinator", "expected-specialist"]
            await runner.send_text("hi")
            await recorder.until("done", 2)
        finally:
            await runner.disconnect()

        change = recorder.of("agent_changed")[0]
        assert change["agent"] == "late-specialist" and change["previous_agent"] == "coordinator"
        assert change["agents"] == ["coordinator", "expected-specialist", "late-specialist"]


# --- what is rejected, and when ------------------------------------------------------------------


class TestPreflight:
    @pytest.mark.asyncio
    async def test_an_ordinary_agent_is_rejected_before_anything_opens(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        module = OpenAIModule([SDKAgent(name="plain", instructions="x")])
        model = ScriptedModel()
        with pytest.raises(TypeError, match="plain.*RealtimeAgent"):
            await _connect(runtime, module, "plain", model)
        assert not model.connected

    @pytest.mark.asyncio
    async def test_a_tool_that_needs_approval_is_rejected_by_name_before_connecting(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)

        @function_tool(needs_approval=True)
        def wire_money(amount: int) -> str:
            """Move money."""
            return "sent"

        coordinator, billing = _team(billing_tools=[wire_money])
        module = OpenAIModule([coordinator, billing])
        model = ScriptedModel()
        with pytest.raises(ValueError, match="'wire_money' of agent 'billing' needs approval"):
            await _connect(runtime, module, "coordinator", model)
        assert not model.connected

    @pytest.mark.asyncio
    async def test_an_approval_the_graph_did_not_reveal_is_rejected_and_fails_the_call_without_running_the_tool(self, runtime, monkeypatch):
        """The target of a ``realtime_handoff`` is private to the SDK, so its tools are only met at run time."""
        _no_system_tools(monkeypatch)
        ran = []

        @function_tool(needs_approval=True)
        def wire_money(amount: int) -> str:
            """Move money."""
            ran.append(amount)
            return "sent"

        treasury = RealtimeAgent(name="treasury", tools=[wire_money])
        coordinator = RealtimeAgent(name="coordinator", handoffs=[realtime_handoff(treasury)])
        module = OpenAIModule([coordinator])
        model = ScriptedModel(
            response("r1", calls=(("transfer_to_treasury", "c1", "{}"),)),
            response("r2", calls=(("wire_money", "c2", '{"amount": 5}'),)),
        )
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("send five")
            await recorder.until("error")
            await asyncio.sleep(0.05)
        finally:
            await runner.disconnect()

        assert ran == []  # never approved, never run
        assert "'wire_money' of agent 'treasury' needs approval" in recorder.of("error")[0]["message"]
        assert "wire_money" in model.tool_outputs()  # the model was told it was refused, not left waiting

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["context", "starting_agent", "max_turns", "hooks"])
    async def test_a_run_option_the_realtime_session_cannot_take_is_rejected_naming_agent_and_key(self, runtime, monkeypatch, key):
        _no_system_tools(monkeypatch)
        coordinator, _ = _team()
        module = OpenAIModule([coordinator])
        module.get_agent("coordinator").run_options[key] = object()
        model = ScriptedModel()
        with pytest.raises(ValueError, match=rf"agent 'coordinator'.*'{key}'"):
            await _connect(runtime, module, "coordinator", model)
        assert not model.connected

    @pytest.mark.asyncio
    async def test_native_settings_reach_the_native_calls(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        coordinator, _ = _team()
        module = OpenAIModule([coordinator])
        captured = {}

        class Capturing(ScriptedModel):
            async def connect(self, options):
                captured.update(options)

        module.get_agent("coordinator").run_options.update(model_config={"initial_model_settings": {"voice": "verse", "model_name": "gpt-realtime"}})
        runner, _, _ = await _connect(runtime, module, "coordinator", Capturing())
        await runner.disconnect()
        assert captured["initial_model_settings"]["voice"] == "verse"
        assert captured["initial_model_settings"]["model_name"] == "gpt-realtime"
        assert captured["initial_model_settings"]["instructions"] == "Greet and route."


class TestStartupAndShutdown:
    @pytest.mark.asyncio
    async def test_a_session_that_fails_to_open_closes_everything_it_opened(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        coordinator, _ = _team()
        module = OpenAIModule([coordinator])

        class Refusing(ScriptedModel):
            async def connect(self, options):
                raise ConnectionError("no route to the model")

        model = Refusing()
        runner = OpenAIRealtimeRunner()
        module.get_agent("coordinator").run_options.update(model=model)
        with pytest.raises(ConnectionError):
            await runner.connect(Session("s"), module.get_agent("coordinator"), Recorder())
        assert model.listeners == [] and runner._listen_task is None
        await runner.disconnect()  # idempotent after a failed connect

    @pytest.mark.asyncio
    async def test_a_cancelled_connect_cleans_up_and_stays_cancelled(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        coordinator, _ = _team()
        module = OpenAIModule([coordinator])

        class Hanging(ScriptedModel):
            async def connect(self, options):
                await asyncio.sleep(30)

        model = Hanging()
        runner = OpenAIRealtimeRunner()
        module.get_agent("coordinator").run_options.update(model=model)
        task = asyncio.create_task(runner.connect(Session("s"), module.get_agent("coordinator"), Recorder()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert model.listeners == []

    @pytest.mark.asyncio
    async def test_disconnecting_twice_is_harmless(self, runtime, monkeypatch):
        _no_system_tools(monkeypatch)
        coordinator, _ = _team()
        module = OpenAIModule([coordinator])
        model = ScriptedModel()
        runner, _, _ = await _connect(runtime, module, "coordinator", model)
        await runner.disconnect()
        await runner.disconnect()
        assert model.closed


# --- guardrails and MCP stay native ---------------------------------------------------------------


class TestNativeFeatures:
    @pytest.mark.asyncio
    async def test_a_tripped_output_guardrail_interrupts_through_the_sdk(self, runtime, monkeypatch):
        from agents import GuardrailFunctionOutput, output_guardrail
        from agents.realtime.model_inputs import RealtimeModelSendInterrupt

        @output_guardrail
        async def no_secrets(context, agent, output):
            return GuardrailFunctionOutput(output_info=None, tripwire_triggered="secret" in output)

        _no_system_tools(monkeypatch)
        coordinator = RealtimeAgent(name="coordinator", instructions="x", output_guardrails=[no_secrets])
        module = OpenAIModule([coordinator])

        class InterruptingModel(ScriptedModel):
            async def send_event(self, event):
                await super().send_event(event)
                if isinstance(event, RealtimeModelSendInterrupt):  # what the real transport answers with
                    await self.emit(RealtimeModelAudioInterruptedEvent(item_id="item-r1", content_index=0))

        leak = "the secret is " + "x" * 120  # past the SDK's debounce, so the guardrail runs mid-response

        async def leak_then_end(model: ScriptedModel):
            await model.emit(RealtimeModelTurnStartedEvent(response_id="r1"))
            for event in speak(leak, "r1", item_id="item-r1"):
                await model.emit(event)
            await asyncio.sleep(0.1)  # the guardrail trips while the response is still in flight
            await model.emit(RealtimeModelTurnEndedEvent(response_id="r1"))

        model = InterruptingModel(leak_then_end)
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("tell me")
            await recorder.until("done")
        finally:
            await runner.disconnect()

        assert any(isinstance(e, RealtimeModelSendInterrupt) for e in model.sent)
        # One interrupt clears the unheard output; the SDK's own interruption event that follows is the same cut, not a second one.
        assert recorder.kinds() == ["audio_delta", "transcript_delta", "interrupt", "speech_started", "done"]
        assert recorder.of("error") == []

    @pytest.mark.asyncio
    async def test_mcp_tools_stay_on_the_native_agent_and_run_through_the_sdk(self, runtime, monkeypatch):
        import mcp.types as mcp_types
        from agents.mcp import MCPServer

        calls = []

        class FakeMCP(MCPServer):
            def __init__(self):
                super().__init__()

            @property
            def name(self):
                return "fake-mcp"

            async def connect(self):
                pass

            async def cleanup(self):
                pass

            async def list_tools(self, run_context=None, agent=None):
                schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
                return [mcp_types.Tool(name="weather", description="Weather", inputSchema=schema)]

            async def call_tool(self, tool_name, arguments, meta=None):
                calls.append((tool_name, arguments))
                return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text="sunny")])

            async def list_prompts(self):
                return mcp_types.ListPromptsResult(prompts=[])

            async def get_prompt(self, name, arguments=None):
                raise NotImplementedError

        _no_system_tools(monkeypatch)
        coordinator = RealtimeAgent(name="coordinator", instructions="x", mcp_servers=[FakeMCP()])
        module = OpenAIModule([coordinator])
        model = ScriptedModel(response("r1", calls=(("weather", "c1", '{"city": "Oslo"}'),)), response("r2", say="Sunny."))
        runner, recorder, _ = await _connect(runtime, module, "coordinator", model)
        try:
            await runner.send_text("weather in Oslo?")
            await recorder.until("done", 2)
        finally:
            await runner.disconnect()

        assert calls == [("weather", {"city": "Oslo"})]
        assert "sunny" in model.tool_outputs()["weather"]
        assert not hasattr(coordinator, "ak_scoped")  # AK attached nothing to it


# --- through the real pool ----------------------------------------------------------------------


class TestThroughThePool:
    @pytest.mark.asyncio
    async def test_the_pool_queues_the_native_conversation_in_order(self, runtime, monkeypatch):
        from agentkernel.pipeline.envelope import QueueName
        from agentkernel.pipeline.realtime_pool import RealtimeConnection
        from agentkernel.pipeline.transport.base import QueueTransportFactory
        from agentkernel.pipeline.transport.in_memory import InMemoryTransport

        async def send_inline(send, *args):
            return send(*args)

        monkeypatch.setattr("agentkernel.pipeline.realtime_pool.asyncio.to_thread", send_inline)
        InMemoryTransport.reset()
        coordinator, billing = _team(billing_tools=[lookup_invoice])
        _no_system_tools(monkeypatch)
        module = OpenAIModule([coordinator, billing])
        model = ScriptedModel(
            response("r1", say="One moment.", calls=(("transfer_to_billing", "c1", "{}"),)),
            response("r2", calls=(("lookup_invoice", "c2", '{"invoice": "9"}'),)),
            response("r3", say="Nine is forty-two.", calls=(("transfer_to_coordinator", "c4", "{}"),)),
            response("r4", say="Anything else?"),
        )
        agent = module.get_agent("coordinator")
        agent.run_options.update(model=model)
        conn = RealtimeConnection("call-1", agent, runtime, Session("call-1"), asyncio.get_running_loop())
        conn.update_delivery_context("req", None, None, {})
        await conn.connect()
        try:
            conn.send_text("billing please")  # on the pool loop: scheduled, not awaited
            deadline = asyncio.get_running_loop().time() + 5
            consumer = QueueTransportFactory.create().create_consumer(QueueName.OUTPUT)
            seen: list[dict] = []
            while asyncio.get_running_loop().time() < deadline and sum(1 for c in seen if c.get("done")) < 4:
                for message in consumer.fetch(10, 0):
                    seen.append(json.loads(message.body))
                    consumer.ack(message)
                await asyncio.sleep(0.01)
            assert sum(1 for c in seen if c.get("done")) == 4
        finally:
            await conn.close()
            InMemoryTransport.reset()

        events = [(c["event"]["type"] if "event" in c else "done") for c in seen]
        changed = [c["event"] for c in seen if c.get("event", {}).get("type") == "agent_changed"]
        # Announced first by the pool, then by the SDK's handoffs; speakers move coordinator -> billing -> coordinator.
        assert [c["agent"] for c in changed] == ["coordinator", "billing", "coordinator"]
        assert changed[0]["agents"] == ["coordinator", "billing"]
        assert events[0] == "agent_changed"
        spoken = "".join(c["event"]["content"] for c in seen if c.get("event", {}).get("type") == "text_delta")
        assert spoken == "One moment.Nine is forty-two.Anything else?"
