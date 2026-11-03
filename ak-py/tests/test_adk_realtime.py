"""Native ADK live run and speaker mapping."""

import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.adk.events import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.base_llm_connection import BaseLlmConnection
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner as ADKRunner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.tools.tool_confirmation import ToolConfirmation
from google.adk.workflow import Workflow
from google.genai import types

from agentkernel.core import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import SystemToolFactory
from agentkernel.core.tool import ToolContext as AKToolContext
from agentkernel.framework.adk.adk import GoogleADKAgent, GoogleADKModule, GoogleADKRealtimeRunner, GoogleADKRunner, GoogleADKToolBuilder


def team():
    billing = LlmAgent(name="billing", model="gemini-2.5-flash", mode="chat")
    coordinator = LlmAgent(name="coordinator", model="gemini-2.5-flash", mode="chat", sub_agents=[billing])
    return coordinator, billing


def test_realtime_agent_keeps_native_tools_without_loading_ak_system_tools(monkeypatch):
    monkeypatch.setattr(AKConfig.get().execution, "mode", ExecutionMode.REALTIME)

    def unexpected(*args):
        raise AssertionError("AK system tools and prompt guidance must not be loaded for realtime")

    def native_tool(value: str) -> str:
        """Echo a value."""
        return value

    monkeypatch.setattr(SystemToolFactory, "get_all", unexpected)
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", unexpected)
    native = LlmAgent(name="voice", model="gemini-2.5-flash", description="A voice agent.", tools=[FunctionTool(native_tool)])

    GoogleADKAgent("voice", GoogleADKRunner(), native)

    assert [tool.name for tool in native.tools] == ["native_tool"]
    assert native.description == "A voice agent."


class NativeRun:
    latest = None

    def __init__(self, **kwargs):
        self.events = asyncio.Queue()
        self.calls = []
        self.closed = False
        NativeRun.latest = self

    async def run_live(self, **kwargs):
        self.calls.append(kwargs)
        while True:
            event = await self.events.get()
            if event is None:
                return
            yield event

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_one_native_run_reports_a_b_a(monkeypatch):
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", NativeRun)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([coordinator, billing])
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(Session("call-1"), module.get_agent("coordinator"), collect)
        native = NativeRun.latest
        queue = runner._queue
        await runner.send_text("billing please")
        for _ in range(100):
            if native.calls:
                break
            await asyncio.sleep(0.01)
        assert len(native.calls) == 1 and native.calls[0]["live_request_queue"] is queue
        for author, message in [("coordinator", "Asking billing"), ("billing", "Your invoice is 42"), ("coordinator", "Anything else")]:
            await native.events.put(
                Event(author=author, invocation_id="i", content=types.Content(parts=[types.Part(text=message)]), turn_complete=True)
            )

        async def wait_for_turns():
            while sum(kind == "done" for kind, _ in seen) < 3:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_turns(), 3)
        await runner.disconnect()
        assert native.closed
        assert [data["agent"] for kind, data in seen if kind == "agent_changed"] == ["billing", "coordinator"]
        assert [data["delta"] for kind, data in seen if kind == "transcript_delta"] == ["Asking billing", "Your invoice is 42", "Anything else"]


@pytest.mark.asyncio
async def test_a_live_tool_resolves_its_session_through_tool_context(monkeypatch):
    """A live tool has no Session.current(); it finds its session through ToolContext.get() instead."""
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", NativeRun)
    coordinator, billing = team()

    def read_session() -> str:
        return AKToolContext.get().session.id

    tool = GoogleADKToolBuilder.bind([read_session])[0]
    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([coordinator, billing])
        runner = GoogleADKRealtimeRunner()

        async def collect(kind, data):
            pass

        session = Session("call-ctx")
        await runner.connect(session, module.get_agent("coordinator"), collect)
        assert Session.current() is None

        ak_tool_context = runner._tool_context
        state = SimpleNamespace(state={"ak_tool_context": ak_tool_context.id})
        assert tool.func(tool_context=state) == "call-ctx"
        assert AKToolContext.fetch(ak_tool_context.id) is ak_tool_context

        await runner.disconnect()
        with pytest.raises(KeyError):  # disconnect() must not leak the connection's tool context
            AKToolContext.fetch(ak_tool_context.id)


async def _run_user_events(monkeypatch, events):
    """Connect a runner over a scripted native run, feed it ``events`` and return what it reported."""
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", NativeRun)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([coordinator, billing])
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(Session("call-t"), module.get_agent("coordinator"), collect)
        for event in events:
            await NativeRun.latest.events.put(event)
        # A marker turn after them: once it is reported, every earlier event has been handled.
        await NativeRun.latest.events.put(
            Event(author="coordinator", invocation_id="i", content=types.Content(parts=[types.Part(text="x")]), turn_complete=True)
        )
        for _ in range(300):
            if any(kind == "done" for kind, _ in seen):
                break
            await asyncio.sleep(0.01)
        await runner.disconnect()
        return seen


def _heard(text, finished, partial=False, event_id="u-1"):
    return Event(
        id=event_id,
        author="user",
        invocation_id="i",
        partial=partial,
        input_transcription=types.Transcription(text=text, finished=finished),
    )


@pytest.mark.asyncio
async def test_a_finished_caller_transcription_is_reported_once(monkeypatch):
    seen = await _run_user_events(monkeypatch, [_heard("we ", False, partial=True), _heard("we have 2000 patients ", True)])

    assert [data for kind, data in seen if kind == "input_transcript"] == [{"text": "we have 2000 patients", "message_id": "u-1"}]


@pytest.mark.asyncio
async def test_partial_empty_and_history_user_events_are_not_reported(monkeypatch):
    replayed = Event(author="user", invocation_id="i", content=types.Content(parts=[types.Part(text="earlier words")]))
    seen = await _run_user_events(monkeypatch, [_heard("par", False, partial=True), _heard("   ", True), replayed])

    assert [kind for kind, _ in seen if kind == "input_transcript"] == []


@pytest.mark.asyncio
async def test_workflow_announces_its_first_speaking_node(monkeypatch):
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", NativeRun)
    first = LlmAgent(name="first", model="gemini-2.5-flash", mode="chat")
    workflow = Workflow(name="flow", edges=[("START", first)])
    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([workflow])
        owner = module.get_agent("flow")
        runner = GoogleADKRealtimeRunner()
        assert runner.initial_speaker(owner) is None
        assert runner.team(owner) == ["first"]
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(Session("call-2"), owner, collect)
        await NativeRun.latest.events.put(Event(author="first", invocation_id="i", content=types.Content(parts=[types.Part(text="Hello")])))

        async def wait_for_output():
            while len(seen) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_output(), 3)
        await runner.disconnect()
        assert seen[0] == ("agent_changed", {"agent": "first", "previous_agent": None, "agents": ["first"]})
        assert seen[1][0] == "transcript_delta" and seen[1][1]["delta"] == "Hello"


def test_workflow_single_turn_node_is_rejected(monkeypatch):
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    first = LlmAgent(name="first", model="gemini-2.5-flash")
    workflow = Workflow(name="flow", edges=[("START", first)])
    with Runtime(InMemorySessionStore()):
        owner = GoogleADKModule([workflow]).get_agent("flow")
        with pytest.raises(ValueError, match="set mode='chat' or mode='task'"):
            GoogleADKRealtimeRunner()._check_graph(owner, workflow)


# -- the adapter's mapping of ADK events onto the pool's events -----------------------------------


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda agent_name=None: []))
    monkeypatch.setattr(SystemToolFactory, "get_system_prompt_suffix", staticmethod(lambda agent_name=None: ""))
    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", NativeRun)
    NativeRun.latest = None


async def open_call(agents, start="coordinator", session="call"):
    """Connect a realtime runner to the fake native run; return it, the events it reported, and the fake run."""
    runner = GoogleADKRealtimeRunner()
    seen = []

    async def collect(kind, data):
        seen.append((kind, data))

    await runner.connect(Session(session), GoogleADKModule(agents).get_agent(start), collect)
    return runner, seen, NativeRun.latest


async def wait_until(predicate, timeout=3):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


def model_event(author, **kwargs):
    return Event(author=author, invocation_id="i", **kwargs)


def audio_event(author, mime_type="audio/pcm;rate=24000", data=b"\x01\x02\x03\x04"):
    return model_event(author, content=types.Content(parts=[types.Part(inline_data=types.Blob(data=data, mime_type=mime_type))]))


@pytest.mark.asyncio
async def test_audio_is_forwarded_and_attributed_to_the_agent_that_produced_it(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        event = audio_event("billing")
        await run.events.put(event)
        await wait_until(lambda: len(seen) >= 2)
        await runner.disconnect()
    assert seen[0] == ("agent_changed", {"agent": "billing", "previous_agent": "coordinator"})
    assert seen[1] == ("audio_delta", {"delta": base64.b64encode(b"\x01\x02\x03\x04").decode(), "message_id": event.id})


@pytest.mark.asyncio
async def test_audio_at_an_unexpected_rate_fails_the_connection_instead_of_playing_wrong(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(audio_event("coordinator", mime_type="audio/pcm;rate=16000"))
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert not any(kind == "audio_delta" for kind, _ in seen)
    assert "16000" in next(data["message"] for kind, data in seen if kind == "error")


@pytest.mark.asyncio
async def test_a_live_error_is_reported_and_stops_listening(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(model_event("coordinator", error_code="MODEL_ERROR", error_message="The live request failed"))
        await wait_until(lambda: seen)
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="ignored after failure")])))
        await asyncio.sleep(0.05)
        await runner.disconnect()

    assert seen == [("error", {"message": "ADK live run failed: MODEL_ERROR: The live request failed"})]


@pytest.mark.asyncio
async def test_an_interruption_is_reported(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(model_event("coordinator", interrupted=True))
        await wait_until(lambda: seen)
        await runner.disconnect()
    assert seen == [("interrupt", {})]


@pytest.mark.asyncio
async def test_a_microphone_filler_does_not_cut_the_agent_off(native):
    """Live, "and" and "Mhm" were detected as turns and stopped the agent mid-sentence."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(_heard("and", True))
        await run.events.put(model_event("coordinator", interrupted=True))
        await wait_until(lambda: any(kind == "input_transcript" for kind, _ in seen))
        await asyncio.sleep(0.05)
        assert not any(kind == "interrupt" for kind, _ in seen)
        await runner.disconnect()


@pytest.mark.asyncio
async def test_real_words_still_interrupt_the_agent(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(_heard("wait, stop", True))
        await run.events.put(model_event("coordinator", interrupted=True))
        await wait_until(lambda: any(kind == "interrupt" for kind, _ in seen))
        await runner.disconnect()
    assert any(kind == "interrupt" for kind, _ in seen)


@pytest.mark.asyncio
async def test_only_partial_transcription_deltas_are_reported_not_the_finished_aggregate(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        for text, finished, partial in [("Hel", False, True), ("lo", False, True), ("Hello", True, False)]:
            await run.events.put(model_event("coordinator", partial=partial, output_transcription=types.Transcription(text=text, finished=finished)))
        await wait_until(lambda: len(seen) >= 2)
        await asyncio.sleep(0.05)
        await runner.disconnect()
    assert [data["delta"] for kind, data in seen if kind == "transcript_delta"] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_a_transfer_ends_the_turn_as_transferred(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(model_event("coordinator", actions=EventActions(transfer_to_agent="billing")))
        await wait_until(lambda: seen)
        await runner.disconnect()
    assert seen == [("done", {"status": "transferred"})]


@pytest.mark.asyncio
async def test_a_confirmation_request_fails_the_connection_and_stops_listening(native):
    coordinator, billing = team()
    confirmation = EventActions(requested_tool_confirmations={"call-1": ToolConfirmation(hint="Refund 40?")})
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(model_event("coordinator", actions=confirmation))
        await wait_until(lambda: seen)
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="ignored after failure")])))
        await asyncio.sleep(0.1)
        await runner.disconnect()
    assert [kind for kind, _ in seen] == ["error"]
    assert "require confirmation" in seen[0][1]["message"] and "coordinator" in seen[0][1]["message"]


@pytest.mark.asyncio
async def test_a_run_that_ends_by_itself_is_reported_as_an_error(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(None)
        await wait_until(lambda: seen)
        await runner.disconnect()
    assert seen == [("error", {"message": "ADK live run ended"})]


@pytest.mark.asyncio
async def test_the_callers_own_events_are_not_reported_back(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(model_event("user", content=types.Content(parts=[types.Part(text="what the caller said")])))
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="reply")])))
        await wait_until(lambda: seen)
        await runner.disconnect()
    assert [data["delta"] for kind, data in seen if kind == "transcript_delta"] == ["reply"]


@pytest.mark.asyncio
async def test_caller_audio_and_text_reach_the_native_queue(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, _, _ = await open_call([coordinator, billing])
        await runner.append_audio(base64.b64encode(b"\x00\x01\x02\x03").decode())
        await runner.send_text("hello")
        queue = runner._queue
        audio = await asyncio.wait_for(queue.get(), 1)
        text = await asyncio.wait_for(queue.get(), 1)
        await runner.disconnect()
    assert audio.blob.data == b"\x00\x01\x02\x03" and audio.blob.mime_type == "audio/pcm;rate=16000"
    assert text.content.role == "user" and text.content.parts[0].text == "hello"


@pytest.mark.asyncio
async def test_a_failed_startup_leaves_nothing_open(monkeypatch, native):
    class BrokenRunner:
        def __init__(self, **kwargs):
            raise RuntimeError("cannot build the ADK runner")

    monkeypatch.setattr("agentkernel.framework.adk.adk.Runner", BrokenRunner)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner = GoogleADKRealtimeRunner()
        with pytest.raises(RuntimeError, match="cannot build"):
            await runner.connect(Session("call"), GoogleADKModule([coordinator, billing]).get_agent("coordinator"), lambda *args: None)
    assert runner._queue is None and runner._runner is None and runner._listen_task is None


@pytest.mark.asyncio
async def test_disconnect_can_repeat_and_a_normal_close_is_not_an_error(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await runner.disconnect()
        await runner.disconnect()
    assert run.closed and seen == []


def test_parallel_and_loop_agents_are_rejected_before_connecting(native):
    for kind in (ParallelAgent, LoopAgent):
        child = LlmAgent(name="child", model="gemini-2.5-flash", mode="chat")
        root = kind(name="multi", sub_agents=[child])
        with Runtime(InMemorySessionStore()):
            owner = GoogleADKModule([root]).get_agent("multi")
            with pytest.raises(ValueError, match="does not run live"):
                GoogleADKRealtimeRunner()._check_graph(owner, root)


def test_only_transport_drops_are_restarted():
    runner = GoogleADKRealtimeRunner()

    assert runner._restartable(ConnectionError("1006 abnormal closure"))
    assert runner._restartable(TimeoutError("socket timed out"))
    assert runner._restartable(Exception("1008 None. BidiGenerateContent session not found or expired"))
    assert not runner._restartable(ValueError("ADK produced audio at 16000 Hz"))


def test_an_expired_resumption_handle_is_dropped_so_the_retry_does_not_repeat_the_same_failure():
    """Live: Gemini rejected a stale saved handle with 1008, and every retry resent the same handle and failed
    the same way again, the backoff doubling each time instead of just reconnecting once with none."""
    runner = GoogleADKRealtimeRunner()
    session = Session("call")
    session.get_volatile_cache().set(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY, "stale-handle")
    runner._session = session
    runner._live_options = {"run_config": RunConfig(session_resumption=types.SessionResumptionConfig(handle="stale-handle"))}

    runner._drop_expired_resumption(Exception("1008 None. BidiGenerateContent session not found or expired"))

    assert session.get_volatile_cache().get(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY) is None
    assert runner._live_options["run_config"].session_resumption.handle is None


def test_an_unrelated_failure_leaves_the_resumption_handle_alone():
    runner = GoogleADKRealtimeRunner()
    session = Session("call")
    session.get_volatile_cache().set(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY, "good-handle")
    runner._session = session
    runner._live_options = {"run_config": RunConfig(session_resumption=types.SessionResumptionConfig(handle="good-handle"))}

    runner._drop_expired_resumption(ConnectionError("1006 abnormal closure"))

    assert session.get_volatile_cache().get(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY) == "good-handle"
    assert runner._live_options["run_config"].session_resumption.handle == "good-handle"


@pytest.mark.asyncio
async def test_only_a_completed_turn_resets_the_restart_budget():
    runner = GoogleADKRealtimeRunner()

    async def collect(kind, data):
        pass

    runner._callback = collect
    runner._restart_attempt = 2
    await runner._handle_event(model_event("coordinator", content=types.Content(parts=[types.Part(text="still alive")])))
    assert runner._restart_attempt == 2  # one event is not a healthy run
    await runner._handle_event(model_event("coordinator", turn_complete=True))
    assert runner._restart_attempt == 0


@pytest.mark.asyncio
async def test_the_connection_has_a_total_restart_cap():
    runner = GoogleADKRealtimeRunner()
    runner._runner = object()
    runner._session_id = "call"
    runner._total_restarts = runner.MAX_TOTAL_RESTARTS

    assert await runner._restart(ConnectionError("1006 abnormal closure")) is False


@pytest.mark.asyncio
async def test_a_client_turn_with_no_model_event_fails_the_run(monkeypatch, native):
    """Gemini can accept a turn and then stay silent with the socket open; the watchdog reports it as stalled at
    once, with no in-place restart attempt first (one is rarely still stuck the same way moments later)."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_TIMEOUT_SECONDS", 0.05)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(_heard("are you there", True))
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1  # no in-place restart: the caller reconnects instead
    message = next(data["message"] for kind, data in seen if kind == "error")
    assert "stalled" in message


@pytest.mark.asyncio
async def test_a_turn_with_no_audible_output_fails_the_run(monkeypatch, native):
    """Tool/control events count as progress for the no-event watchdog, but not for the no-speech watchdog."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "NO_SPEECH_TIMEOUT_SECONDS", 0.1)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await runner.send_text("please answer")
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="only text, no voice")])))
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_text_output_gets_time_to_start_speaking(monkeypatch, native):
    """Text can arrive before generated speech; that gap must not use the shorter no-event timeout."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(GoogleADKRealtimeRunner, "NO_SPEECH_TIMEOUT_SECONDS", 0.3)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await runner.send_text("please answer")
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="thinking aloud")])))
        await wait_until(lambda: any(kind == "transcript_delta" for kind, _ in seen))
        await asyncio.sleep(0.12)
        assert not any(kind == "error" for kind, _ in seen)

        audio = model_event("coordinator", turn_complete=True)
        audio.content = types.Content(parts=[types.Part(inline_data=types.Blob(data=b"\x01\x02", mime_type="audio/pcm;rate=24000"))])
        await run.events.put(audio)
        await wait_until(lambda: any(kind == "done" for kind, _ in seen))
        assert not any(kind == "error" for kind, _ in seen)
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_a_completed_turn_with_audio_stops_the_no_speech_watchdog(monkeypatch, native):
    monkeypatch.setattr(GoogleADKRealtimeRunner, "NO_SPEECH_TIMEOUT_SECONDS", 0.1)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, _, run = await open_call([coordinator, billing])
        await runner.send_text("please answer")
        audio = model_event("coordinator", turn_complete=True)
        audio.content = types.Content(parts=[types.Part(inline_data=types.Blob(data=b"\x01\x02", mime_type="audio/pcm;rate=24000"))])
        await run.events.put(audio)
        await asyncio.sleep(0.2)
        assert len(run.calls) == 1
        await runner.disconnect()


@pytest.mark.asyncio
async def test_audio_that_never_completes_the_turn_still_rearms_the_no_speech_watchdog(monkeypatch, native):
    """A socket that dies after some audio must not leave the turn unfinished forever: the clock restarts from the
    audio, not from before it, and still ends the run once the window passes with nothing more."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "NO_SPEECH_TIMEOUT_SECONDS", 0.1)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await runner.send_text("please answer")
        await run.events.put(audio_event("coordinator"))
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_a_handover_that_never_speaks_fails_the_run(monkeypatch, native):
    """A transfer starts the same flat stall clock; the receiving agent is expected to make progress within it."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_TIMEOUT_SECONDS", 0.1)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(Event(author="coordinator", invocation_id="i", actions=EventActions(transfer_to_agent="billing")))
        await asyncio.sleep(0.05)
        assert not any(kind == "error" for kind, _ in seen)  # still inside the stall window
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_the_old_agents_tail_audio_does_not_end_the_handover_grace(monkeypatch, native):
    """A handoff can be followed by the old agent's queued audio; only the receiving agent's words end the wait."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_TIMEOUT_SECONDS", 0.1)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(Event(author="coordinator", invocation_id="i", actions=EventActions(transfer_to_agent="billing")))
        await asyncio.sleep(0.07)
        await run.events.put(model_event("coordinator", content=types.Content(parts=[types.Part(text="one last thing")])))
        await asyncio.sleep(0.07)
        assert not any(kind == "error" for kind, _ in seen)  # the old agent's tail reset the clock
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_a_running_tool_is_not_mistaken_for_model_silence(monkeypatch, native):
    """A tool can run longer than the first-token budget; only its response starts the watchdog clock."""
    monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_TIMEOUT_SECONDS", 0.05)
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, seen, run = await open_call([coordinator, billing])
        await run.events.put(
            model_event(
                "coordinator",
                content=types.Content(parts=[types.Part(function_call=types.FunctionCall(id="t1", name="slow", args={}))]),
            )
        )
        await asyncio.sleep(0.2)
        assert not seen
        await run.events.put(
            model_event(
                "coordinator",
                content=types.Content(parts=[types.Part(function_response=types.FunctionResponse(id="t1", name="slow", response={}))]),
            )
        )
        await wait_until(lambda: any(kind == "error" for kind, _ in seen))
        await runner.disconnect()
    assert len(run.calls) == 1


@pytest.mark.asyncio
async def test_session_resumption_is_enabled_with_no_handle_by_default(native):
    """Gemini's own live session resumption is always on, so ADK's built-in reconnect-on-drop can restore the
    model's memory for a real socket error, even before any handle has been issued."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        runner, _, run = await open_call([coordinator, billing])
        await runner.disconnect()
    config = run.calls[0]["run_config"].session_resumption
    assert config is not None and config.handle is None


@pytest.mark.asyncio
async def test_session_resumption_does_not_override_an_agent_configured_one(native):
    """An agent that already set its own session_resumption (e.g. transparent=True) keeps it untouched."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([coordinator, billing])
        module.run_options(coordinator, run_config=RunConfig(session_resumption=types.SessionResumptionConfig(handle="agent-own")))
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(Session("call"), module.get_agent("coordinator"), collect)
        run = NativeRun.latest
        await runner.disconnect()
    assert run.calls[0]["run_config"].session_resumption.handle == "agent-own"


@pytest.mark.asyncio
async def test_session_resumption_seeds_the_handle_saved_from_an_earlier_connection(native):
    """A handle saved on the session by a previous connection (see `_handle_event`) seeds the next one, so the
    server can restore the conversation it already knows instead of starting the model over blind."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        session = Session("call")
        session.get_volatile_cache().set(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY, "saved-handle")
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(session, GoogleADKModule([coordinator, billing]).get_agent("coordinator"), collect)
        run = NativeRun.latest
        await runner.disconnect()
    assert run.calls[0]["run_config"].session_resumption.handle == "saved-handle"


@pytest.mark.asyncio
async def test_session_resumption_seeds_the_saved_handle_even_when_the_agent_already_set_an_empty_config(native):
    """An agent's own run_config can already set session_resumption with no handle of its own (e.g. for other live
    settings in the same config) - the saved handle still gets filled in, not skipped just because the config
    object already exists."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        session = Session("call")
        session.get_volatile_cache().set(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY, "saved-handle")
        module = GoogleADKModule([coordinator, billing])
        module.run_options(coordinator, run_config=RunConfig(session_resumption=types.SessionResumptionConfig()))
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(session, module.get_agent("coordinator"), collect)
        run = NativeRun.latest
        await runner.disconnect()
    assert run.calls[0]["run_config"].session_resumption.handle == "saved-handle"


@pytest.mark.asyncio
async def test_a_resumable_handle_from_the_root_agent_is_saved_on_the_session(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        session = Session("call")
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(session, GoogleADKModule([coordinator, billing]).get_agent("coordinator"), collect)
        run = NativeRun.latest
        await run.events.put(
            model_event("coordinator", live_session_resumption_update=types.LiveServerSessionResumptionUpdate(newHandle="h2", resumable=True))
        )
        await asyncio.sleep(0.05)
        await runner.disconnect()
    assert session.get_volatile_cache().get(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY) == "h2"


@pytest.mark.asyncio
async def test_a_handle_from_a_transferred_to_agent_is_not_saved(native):
    """Handed-off sub-agents run their own, separate connections (ADK's own mechanism, not ours): a handle from
    one of those does not describe the root agent's conversation, which is the one our own restart resumes as."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        session = Session("call")
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(session, GoogleADKModule([coordinator, billing]).get_agent("coordinator"), collect)
        run = NativeRun.latest
        await run.events.put(
            model_event("billing", live_session_resumption_update=types.LiveServerSessionResumptionUpdate(newHandle="h3", resumable=True))
        )
        await asyncio.sleep(0.05)
        await runner.disconnect()
    assert session.get_volatile_cache().get(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY) is None


@pytest.mark.asyncio
async def test_an_unresumable_update_is_not_saved(native):
    """Gemini sends an empty/unresumable update while mid function-call or generating; using it would lose data."""
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        session = Session("call")
        runner = GoogleADKRealtimeRunner()
        seen = []

        async def collect(kind, data):
            seen.append((kind, data))

        await runner.connect(session, GoogleADKModule([coordinator, billing]).get_agent("coordinator"), collect)
        run = NativeRun.latest
        await run.events.put(
            model_event("coordinator", live_session_resumption_update=types.LiveServerSessionResumptionUpdate(newHandle=None, resumable=False))
        )
        await asyncio.sleep(0.05)
        await runner.disconnect()
    assert session.get_volatile_cache().get(GoogleADKRealtimeRunner.RESUMPTION_HANDLE_KEY) is None


def test_a_run_option_the_adapter_owns_is_rejected_by_name(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        owner = GoogleADKModule([coordinator, billing]).get_agent("coordinator")
        with pytest.raises(ValueError, match="session_id"):
            GoogleADKRealtimeRunner()._split_options(owner, {"session_id": "mine"})


def test_app_options_are_split_out_before_the_runner_and_live_options(native):
    coordinator, billing = team()
    with Runtime(InMemorySessionStore()):
        owner = GoogleADKModule([coordinator, billing]).get_agent("coordinator")
        cache = object()

        constructor, live, app = GoogleADKRealtimeRunner()._split_options(owner, {"context_cache_config": cache, "run_config": "live"})

    assert app == {"context_cache_config": cache}
    assert live == {"run_config": "live"} and constructor == {}


# -- ADK's own transfer flow, offline: a fake Live model, no credentials -------------------------
# These run google-adk's real ``run_live`` against a scripted connection. They pin the reason for the
# ``google-adk>=2.7.0`` floor: on 2.6 a refused ``transfer_to_agent`` still closed the live connection.

OPENED: list["FakeConnection"] = []


class FakeConnection(BaseLlmConnection):
    def __init__(self, name, script, tool_names=()):
        self.name, self.script, self.closed = name, script, False
        self.tool_names = tuple(tool_names)

    async def send_history(self, history):
        pass

    async def send_content(self, content):
        pass

    async def send_realtime(self, blob):
        pass

    async def receive(self):
        for response in self.script:
            yield response
        while not self.closed:
            await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True


class FakeLiveModel(BaseLlm):
    """A Live model that opens a recorded connection and, when asked to, calls ``transfer_to_agent``."""

    model: str = "fake-live"
    label: str = "agent"
    transfers: bool = False
    transfer_target: str = "billing"
    says_hello: bool = False

    async def generate_content_async(self, llm_request, stream=False):
        raise NotImplementedError("live only")
        yield

    @asynccontextmanager
    async def connect(self, llm_request):
        call = types.FunctionCall(id="call-1", name="transfer_to_agent", args={"agent_name": self.transfer_target})
        script = [LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"Hello from {self.label}")]))] if self.says_hello else []
        if self.transfers:
            script.append(LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)])))
        connection = FakeConnection(self.label, script, llm_request.tools_dict)
        OPENED.append(connection)
        try:
            yield connection
        finally:
            connection.closed = True


def refuse_transfer(tool, args, tool_context):
    return {"error": "transfer refused by policy"} if tool.name == "transfer_to_agent" else None


async def run_transfer_scenario(before_tool_callback, until=None):
    """Run ADK's live flow for a coordinator that asks to transfer to billing; report what ADK did.

    ``until`` is polled (up to 10 s) so a slow machine is waited for; without it the run gets a fixed 1.5 s."""
    OPENED.clear()
    billing = LlmAgent(name="billing", model=FakeLiveModel(label="billing"))
    coordinator = LlmAgent(
        name="coordinator",
        model=FakeLiveModel(label="coordinator", transfers=True),
        sub_agents=[billing],
        before_tool_callback=before_tool_callback,
    )
    runner = ADKRunner(app_name="probe", agent=coordinator, session_service=InMemorySessionService(), auto_create_session=True)
    queue = LiveRequestQueue()

    async def consume():
        async for _ in runner.run_live(user_id="u", session_id="s", live_request_queue=queue, run_config=RunConfig(response_modalities=["AUDIO"])):
            pass

    task = asyncio.create_task(consume())
    for _ in range(1000 if until else 150):
        await asyncio.sleep(0.01)
        if until and until():
            break
    await asyncio.sleep(0.2)
    state = {"opened": [c.name for c in OPENED], "closed": {c.name: c.closed for c in OPENED}}
    queue.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await runner.close()
    return state


@pytest.fixture
def fast_transfer(monkeypatch):
    import google.adk.flows.llm_flows.base_llm_flow as flow

    monkeypatch.setattr(flow, "DEFAULT_TRANSFER_AGENT_DELAY", 0.05)


@pytest.mark.asyncio
async def test_adk_closes_the_first_connection_and_opens_the_next_for_an_accepted_transfer(fast_transfer):
    state = await run_transfer_scenario(None, until=lambda: len(OPENED) >= 2)
    assert state["opened"] == ["coordinator", "billing"]
    assert state["closed"]["coordinator"] is True


@pytest.mark.asyncio
async def test_adk_keeps_the_connection_and_starts_no_one_for_a_refused_transfer(fast_transfer):
    state = await run_transfer_scenario(refuse_transfer)
    assert state["opened"] == ["coordinator"]
    assert state["closed"]["coordinator"] is False


@pytest.mark.asyncio
async def test_adk_live_transfers_from_one_sub_agent_to_its_peer(fast_transfer):
    OPENED.clear()
    ba = LlmAgent(name="ba", model=FakeLiveModel(label="ba", transfers=True, transfer_target="architect"))
    architect = LlmAgent(name="architect", model=FakeLiveModel(label="architect"))
    pm = LlmAgent(
        name="pm",
        model=FakeLiveModel(label="pm", transfers=True, transfer_target="ba"),
        sub_agents=[ba, architect],
    )
    runner = ADKRunner(app_name="probe", agent=pm, session_service=InMemorySessionService(), auto_create_session=True)
    queue = LiveRequestQueue()

    async def consume():
        async for _ in runner.run_live(user_id="u", session_id="s", live_request_queue=queue, run_config=RunConfig(response_modalities=["AUDIO"])):
            pass

    task = asyncio.create_task(consume())
    try:
        for _ in range(1000):
            await asyncio.sleep(0.01)
            if len(OPENED) >= 3:
                break
        assert [connection.name for connection in OPENED] == ["pm", "ba", "architect"]
        assert "transfer_to_agent" in OPENED[1].tool_names
        assert OPENED[0].closed and OPENED[1].closed
    finally:
        queue.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.close()


@pytest.mark.asyncio
async def test_realtime_adapter_reports_native_peer_handoff(fast_transfer, monkeypatch):
    monkeypatch.setattr(AKConfig.get().execution, "mode", ExecutionMode.REALTIME)
    OPENED.clear()
    ba = LlmAgent(name="ba", model=FakeLiveModel(label="ba", transfers=True, transfer_target="architect", says_hello=True))
    architect = LlmAgent(name="architect", model=FakeLiveModel(label="architect", says_hello=True))
    pm = LlmAgent(name="pm", model=FakeLiveModel(label="pm", transfers=True, transfer_target="ba"), sub_agents=[ba, architect])
    seen = []

    async def collect(kind, data):
        seen.append((kind, data))

    with Runtime(InMemorySessionStore()):
        module = GoogleADKModule([pm])
        module.run_options(pm, run_config=RunConfig(response_modalities=["AUDIO"]))
        adapter = GoogleADKRealtimeRunner()
        await adapter.connect(Session("peer-call"), module.get_agent("pm"), collect)
        try:
            await adapter.send_text("Start the call")
            for _ in range(1000):
                await asyncio.sleep(0.01)
                if len([kind for kind, _ in seen if kind == "agent_changed"]) >= 2:
                    break
            assert [data["agent"] for kind, data in seen if kind == "agent_changed"] == ["ba", "architect"]
            assert [connection.name for connection in OPENED] == ["pm", "ba", "architect"]
        finally:
            await adapter.disconnect()
