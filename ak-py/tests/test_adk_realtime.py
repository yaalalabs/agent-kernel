"""The Google ADK realtime adapter, on ADK's own live engine (``Runner.run_live``), driven through the realtime pool.

A scripted Gemini Live socket stands in for ``google.genai.Client``: ADK's own Gemini connection talks to it, so
ADK runs the tools, their callbacks, transfers and the history it gives a new socket, as it does live.
"""

import asyncio
import base64
import types

import pytest
from google.adk.agents import Agent as GoogleAgent
from google.adk.models import Gemini
from google.genai import types as genai_types

from agentkernel.core import Agent, Session, ToolContext
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.framework.adk.adk import GoogleADKModule, GoogleADKRealtimeRunner, GoogleADKToolBuilder
from agentkernel.pipeline import realtime_pool
from agentkernel.pipeline.realtime_pool import RealtimeConnection, RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport

MODEL = "gemini-3.1-flash-live-preview"


@pytest.fixture(autouse=True)
def _pipeline(monkeypatch):
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
    monkeypatch.setattr(RealtimeConnectionPool, "_observers", [])
    # ADK waits a second before opening the socket of the agent a transfer goes to; the module that reads it moved.
    for module in ("google.adk.flows.llm_flows.base_llm_flow", "google.adk.live._live_llm_flow"):
        try:
            monkeypatch.setattr(f"{module}.DEFAULT_TRANSFER_AGENT_DELAY", 0.01)
        except (ImportError, AttributeError):
            pass
    monkeypatch.setattr(GoogleADKRealtimeRunner, "RESTART_DELAYS_SECONDS", (0.01, 0.01, 0.01))
    yield
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()


# A scripted Gemini Live socket


class _Socket:
    """One Gemini Live session. ``receive()`` yields one scripted turn per call and waits when they are spent, as an
    open socket does. In a script, a callable is a wait until it returns True for the socket (a model answers a tool
    call only once given its result), a number a pause, and an exception the socket dropping."""

    def __init__(self, agent, config, script):
        self.agent = agent
        self.config = config
        # An empty turn is nothing yet: a socket's receive() never ends without a message unless it closed.
        self.script = [step for step in script if step != []]
        self.session_id = f"live-{agent}"
        self.history = []
        self.audio = []
        self.text = []
        self.tool_responses = []
        self.closed = False
        self._sent = asyncio.Event()

    async def receive(self):
        from websockets.exceptions import ConnectionClosedOK

        while self.script and (callable(self.script[0]) or isinstance(self.script[0], float)):
            step = self.script.pop(0)
            if isinstance(step, float):
                await asyncio.sleep(step)
                continue
            while not step(self) and not self.closed:
                self._sent.clear()
                await self._sent.wait()
        if self.script and isinstance(self.script[0], Exception):
            raise self.script.pop(0)
        while not self.script and not self.closed:
            self._sent.clear()
            await self._sent.wait()
        if self.closed:
            # A closed socket ends its stream, as the websocket's close does.
            raise ConnectionClosedOK(None, None)
        step = self.script.pop(0)
        for message in step if isinstance(step, list) else [step]:
            yield message

    async def send_client_content(self, turns=None, turn_complete=None):
        self.history.append((list(turns or []), turn_complete))
        self._sent.set()

    async def send_realtime_input(self, **kwargs):
        if kwargs.get("audio") is not None:
            self.audio.append(kwargs["audio"].data)
        if kwargs.get("text") is not None:
            self.text.append(kwargs["text"])
        self._sent.set()

    async def send(self, input=None, **kwargs):
        for content in getattr(input, "turns", None) or []:
            self.text.extend(part.text for part in content.parts if part.text)
        self._sent.set()

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(list(function_responses))
        self._sent.set()

    async def close(self):
        self.closed = True
        self._sent.set()

    def seen(self):
        """The text of the history this socket was given, one entry per part."""
        return [part.text for turns, _ in self.history for content in turns for part in content.parts if part.text]


class _Sockets(list):
    """The scripts of an agent's sockets, one per connect, where a plain list is its first socket's only."""

    def __init__(self, *scripts):
        super().__init__(list(script) for script in scripts)


class _GeminiClient:
    """Stands in for ``google.genai.Client``: each live connect opens a socket for the agent whose instruction the
    config carries, with that agent's next script; one with no script left says nothing."""

    vertexai = False

    def __init__(self, **scripts):
        self.scripts = {agent: list(script) if isinstance(script, _Sockets) else [list(script)] for agent, script in scripts.items()}
        self.sockets = []
        self.refuse = 0
        self.aio = types.SimpleNamespace(live=types.SimpleNamespace(connect=self._connect))

    def _connect(self, model, config):
        client = self
        instruction = config.system_instruction.parts[0].text if config.system_instruction else ""
        agent = next(name for name in self.scripts if f"You are {name}." in instruction)

        class _Connect:
            async def __aenter__(self):
                if client.refuse:
                    client.refuse -= 1
                    raise ConnectionError("Live connect refused")
                scripts = client.scripts[agent]
                socket = _Socket(agent, config, scripts.pop(0) if scripts else [])
                client.sockets.append(socket)
                return socket

            async def __aexit__(self, *exc):
                pass

        return _Connect()

    def of(self, agent):
        return [socket for socket in self.sockets if socket.agent == agent]


def _message(**server_content):
    return genai_types.LiveServerMessage(server_content=genai_types.LiveServerContent(**server_content))


def _says(text):
    return _message(output_transcription=genai_types.Transcription(text=text))


def _hears(text):
    return _message(input_transcription=genai_types.Transcription(text=text, finished=True))


def _audio(data=b"\x01\x00" * 8):
    return _message(
        model_turn=genai_types.Content(
            role="model", parts=[genai_types.Part(inline_data=genai_types.Blob(data=data, mime_type="audio/pcm;rate=24000"))]
        )
    )


def _done():
    return _message(turn_complete=True)


def _interrupted():
    return _message(interrupted=True)


def _calls(call_id, name, **args):
    return genai_types.LiveServerMessage(
        tool_call=genai_types.LiveServerToolCall(function_calls=[genai_types.FunctionCall(id=call_id, name=name, args=args)])
    )


def _answered(socket):
    return bool(socket.tool_responses)


def _voice(name):
    return genai_types.SpeechConfig(voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=name)))


def _agent(name, voice=None, **kwargs):
    return GoogleAgent(name=name, model=Gemini(model=MODEL, speech_config=_voice(voice) if voice else None), instruction=f"You are {name}.", **kwargs)


class _Call:
    """One live call through the pool: a ``RealtimeConnection`` for the module's first agent, recording what the
    adapter reports and what the observers see."""

    def __init__(self, monkeypatch, client, agents, session_id="s1"):
        monkeypatch.setattr("google.genai.Client", lambda *a, **k: client)
        self.client = client
        self.runtime = Runtime(InMemorySessionStore())
        with self.runtime:
            self.module = GoogleADKModule(agents)
        self.agent = self.module.get_agent(agents[0].name)
        self.session = Session(session_id)
        self.events = []
        self.observed = []
        self.connection = None
        self.session_id = session_id

    async def start(self):
        call = self

        class _Observer:
            async def on_event(self, session, agent, event):
                call.observed.append((event.type, event.agent, event.text))

            def name(self):
                return "observer"

        self.connection = RealtimeConnection(
            self.session_id, self.agent, self.runtime, self.session, asyncio.get_running_loop(), observers=[_Observer()]
        )
        report = self.connection.handle_framework_event

        async def recorded(event_type, data):
            self.events.append((event_type, data))
            await report(event_type, data)

        self.connection.handle_framework_event = recorded
        await self.connection.connect()
        return self

    def kinds(self):
        return [kind for kind, _ in self.events]

    async def until(self, condition, timeout=3.0):
        async def wait():
            while not condition():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait(), timeout)

    async def close(self):
        await self.connection.close()


# Talking: audio, transcripts and turns


class TestADKNativeConversation:
    """A single voice agent: the caller's audio goes to ADK's queue, the model's audio and words come back, as ADK reports them."""

    @pytest.mark.asyncio
    async def test_a_turn_reaches_the_pool_and_the_observers(self, monkeypatch):
        client = _GeminiClient(
            supervisor=[[_hears("My bill is higher this month."), _audio(), _says("Let me look, "), _says("one moment."), _done()]]
        )
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        call.connection.append_audio(base64.b64encode(b"\x00\x10" * 160).decode())
        await call.until(lambda: "done" in call.kinds() and client.sockets and client.sockets[0].audio)
        await asyncio.sleep(0.05)
        await call.close()

        assert call.kinds()[:5] == ["speech_started", "caller_transcript", "audio_delta", "transcript_delta", "transcript_delta"]
        assert ("done", {"status": "completed"}) in call.events
        assert ("caller_said", None, "My bill is higher this month.") in call.observed
        assert ("agent_said", "supervisor", "Let me look, one moment.") in call.observed
        # The caller's audio was resampled to the model's rate and reached ADK's socket.
        assert client.sockets[0].audio

    @pytest.mark.asyncio
    async def test_text_reaches_the_model_as_adk_sends_it(self, monkeypatch):
        client = _GeminiClient(supervisor=[[]])
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        call.connection.send_text("An update from the application.")
        await call.until(lambda: client.sockets and client.sockets[0].text)
        await call.close()

        assert client.sockets[0].text == ["An update from the application."]

    @pytest.mark.asyncio
    async def test_an_interruption_is_reported_once(self, monkeypatch):
        client = _GeminiClient(supervisor=[[_audio(), _says("A long answer")], [_interrupted(), _interrupted(), _done()]])
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert call.kinds().count("interrupt") == 1

    @pytest.mark.asyncio
    async def test_the_agents_own_voice_reaches_its_socket(self, monkeypatch):
        client = _GeminiClient(supervisor=[[]])
        call = await _Call(monkeypatch, client, [_agent("supervisor", voice="Aoede")]).start()

        await call.until(lambda: client.sockets)
        await call.close()

        assert client.sockets[0].config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Aoede"
        # The pool's transcripts need both transcriptions, which the adapter turns on.
        assert client.sockets[0].config.input_audio_transcription is not None
        assert client.sockets[0].config.output_audio_transcription is not None

    @pytest.mark.asyncio
    async def test_the_calls_run_config_reaches_every_socket(self, monkeypatch):
        from google.adk.agents.run_config import RunConfig

        detection = genai_types.RealtimeInputConfig(automatic_activity_detection=genai_types.AutomaticActivityDetection(silence_duration_ms=800))
        client = _GeminiClient(supervisor=[[]])
        call = _Call(monkeypatch, client, [_agent("supervisor")])
        call.module.run_options(call.agent.agent, run_config=RunConfig(realtime_input_config=detection))
        await call.start()

        await call.until(lambda: client.sockets)
        await call.close()

        assert client.sockets[0].config.realtime_input_config.automatic_activity_detection.silence_duration_ms == 800


# Tools: ADK runs them, in Agent Kernel's tool scope


class TestADKNativeTools:
    """ADK runs each tool once, between the calling agent's callbacks, with the call's session, agent and tool context."""

    @pytest.mark.asyncio
    async def test_a_bound_tool_runs_once_in_the_calls_scope(self, monkeypatch, caplog):
        caplog.set_level("INFO", logger="ak.adk.realtime")
        seen = []

        async def lookup(question: str) -> str:
            """Look something up."""
            seen.append((question, ToolContext.get().session.id, Session.current().id, Agent.current().name))
            return f"answer to {question}"

        client = _GeminiClient(supervisor=[[_calls("c1", "lookup", question="q")], _answered, [_says("Done."), _done()]])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=GoogleADKToolBuilder.bind([lookup]))]).start()

        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert seen == [("q", "s1", "s1", "supervisor")]
        assert "Tool lookup called by 'supervisor'" in caplog.text and "Tool lookup of 'supervisor' returned: answer to q" in caplog.text
        [[response]] = client.sockets[0].tool_responses
        assert response.name == "lookup" and response.response == {"result": "answer to q"}
        # Observed, never executed by the pool: the adapter reports no tool_call.
        assert "tool_call" not in call.kinds()
        assert call.connection.last_tool_result_at is not None and call.connection._tools_in_flight == 0

    @pytest.mark.asyncio
    async def test_an_adk_tool_gets_adks_tool_context(self, monkeypatch):
        from google.adk.tools import ToolContext as ADKToolContext

        seen = []

        def remember(tool_context: ADKToolContext) -> str:
            """Remember the call."""
            tool_context.state["remembered"] = True
            seen.append((tool_context.agent_name, Session.current().id))
            return "ok"

        client = _GeminiClient(supervisor=[[_calls("c1", "remember")], _answered, [_done()]])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=[remember])]).start()

        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert seen == [("supervisor", "s1")]

    @pytest.mark.asyncio
    async def test_the_calling_agents_callbacks_run_once_each(self, monkeypatch):
        calls = []

        def failing(question: str) -> str:
            """Fails."""
            calls.append("tool")
            raise ValueError("backend down")

        def before(tool, args, tool_context):
            calls.append(("before", tool.name, tool_context.agent_name, Session.current().id))

        def on_error(tool, args, tool_context, error):
            calls.append(("error", tool.name, str(error)))
            return {"result": "The backend is down."}

        def after(tool, args, tool_context, tool_response):
            calls.append(("after", tool.name, tool_response))

        client = _GeminiClient(supervisor=[[_calls("c1", "failing", question="q")], _answered, [_done()]])
        agent = _agent("supervisor", tools=[failing], before_tool_callback=before, after_tool_callback=after, on_tool_error_callback=on_error)
        call = await _Call(monkeypatch, client, [agent]).start()

        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert calls == [
            ("before", "failing", "supervisor", "s1"),
            "tool",
            ("error", "failing", "backend down"),
            ("after", "failing", {"result": "The backend is down."}),
        ]
        [[response]] = client.sockets[0].tool_responses
        assert response.response == {"result": "The backend is down."}

    @pytest.mark.asyncio
    async def test_a_tool_that_waits_keeps_the_call_busy_and_holds_the_session(self, monkeypatch):
        release = asyncio.Event()
        state = {}

        async def slow_lookup(question: str) -> str:
            """A slow lookup, which runs another agent in a session of its own."""
            state["running"] = True
            async with Session("s1-lookup"):
                await release.wait()
            return "result"

        client = _GeminiClient(supervisor=[[_calls("c1", "slow_lookup", question="q")], _answered, [_says("Here is what I found."), _done()]])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=GoogleADKToolBuilder.bind([slow_lookup]))]).start()

        await call.until(lambda: state.get("running"))
        assert call.connection.is_responding and call.connection._tools_in_flight == 1
        assert call.session._lock.locked()
        assert call.connection.last_tool_result_at is None

        release.set()
        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert not call.session._lock.locked() and call.connection._tools_in_flight == 0
        assert call.connection.last_tool_result_at is not None
        assert client.sockets[0].tool_responses[0][0].response == {"result": "result"}

    @pytest.mark.asyncio
    async def test_a_tool_asking_another_agent_runs_it_in_a_session_of_its_own(self, monkeypatch):
        from agentkernel.core import AgentService, Runner
        from agentkernel.core.model import AgentReplyText

        class _Specialist(Agent):
            def __init__(self):
                class _Run(Runner):
                    async def run(self, agent, session, requests):
                        return AgentReplyText(response=f"answered in {Session.current().id}")

                    async def stream(self, agent, session, requests):
                        raise NotImplementedError()
                        yield

                super().__init__("specialist", _Run("specialist-runner"))

            def get_description(self):
                return "specialist"

            def get_a2a_card(self):
                return None

            def attach_tool(self, tool):
                pass

            def override_system_prompt(self, prompt):
                pass

        state = {}

        async def ask_specialist(question: str) -> str:
            """Ask the specialist agent, and wait for its answer."""
            service = AgentService()
            service.select("s1-specialist", "specialist")
            reply = await service.run(question)
            state["after"] = (Session.current().id, Agent.current().name, ToolContext.get().session.id)
            return reply

        client = _GeminiClient(supervisor=[[_calls("c1", "ask_specialist", question="all")], _answered, [_done()]])
        call = _Call(monkeypatch, client, [_agent("supervisor", tools=GoogleADKToolBuilder.bind([ask_specialist]))])
        call.runtime.register(_Specialist())
        with call.runtime:
            await call.start()
            await call.until(lambda: "done" in call.kinds())
            await call.close()

        assert client.sockets[0].tool_responses[0][0].response == {"result": "answered in s1-specialist"}
        # Back in the call's session and agent once the nested run ends.
        assert state["after"] == ("s1", "supervisor", "s1")
        assert not call.session._lock.locked()

    @pytest.mark.asyncio
    async def test_the_applications_plugins_run_inside_the_calls_tool_scope(self, monkeypatch):
        from google.adk.plugins import BasePlugin

        seen = []

        class _Audit(BasePlugin):
            async def before_tool_callback(self, *, tool, tool_args, tool_context):
                seen.append((tool.name, Session.current().id, ToolContext.get().session.id))

        def lookup(question: str) -> str:
            """Look something up."""
            return "answer"

        client = _GeminiClient(supervisor=[[_calls("c1", "lookup", question="q")], _answered, [_done()]])
        call = _Call(monkeypatch, client, [_agent("supervisor", tools=[lookup])])
        call.module.run_options(call.agent.agent, plugins=[_Audit(name="audit")])
        await call.start()

        await call.until(lambda: "done" in call.kinds())
        await call.close()

        assert seen == [("lookup", "s1", "s1")]

    @pytest.mark.asyncio
    async def test_closing_the_call_cancels_a_waiting_tool_and_sends_nothing(self, monkeypatch):
        state = {}

        async def slow_lookup(question: str) -> str:
            """A lookup that never finishes."""
            state["running"] = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        client = _GeminiClient(supervisor=[[_calls("c1", "slow_lookup", question="q")]])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=GoogleADKToolBuilder.bind([slow_lookup]))]).start()
        await call.until(lambda: state.get("running"))

        await call.close()
        await asyncio.sleep(0.05)

        assert state.get("cancelled")
        assert client.sockets[0].tool_responses == []
        assert not call.session._lock.locked() and call.connection._tools_in_flight == 0 and call.connection._tool_tasks == set()
        assert call.connection.last_tool_result_at is None
        assert Session.current() is None and Agent.current() is None

    @pytest.mark.asyncio
    async def test_two_calls_at_once_each_run_tools_in_their_own_session(self, monkeypatch):
        seen = []
        both = asyncio.Event()

        async def whoami() -> str:
            """Say which call this is."""
            seen.append(Session.current().id)
            if len(seen) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            return ToolContext.get().session.id

        client = _GeminiClient(
            supervisor=_Sockets([[_calls("c1", "whoami")], _answered, [_done()]], [[_calls("c2", "whoami")], _answered, [_done()]])
        )
        agents = [_agent("supervisor", tools=GoogleADKToolBuilder.bind([whoami]))]
        first = _Call(monkeypatch, client, agents, session_id="call-1")
        await first.start()
        second = _Call(monkeypatch, client, agents, session_id="call-2")
        second.runtime, second.module, second.agent = first.runtime, first.module, first.agent
        await second.start()

        await first.until(lambda: "done" in first.kinds() and "done" in second.kinds())
        await first.close()
        await second.close()

        assert sorted(seen) == ["call-1", "call-2"]
        answers = sorted(socket.tool_responses[0][0].response["result"] for socket in client.sockets)
        assert answers == ["call-1", "call-2"]


# Handoffs: ADK's own transfer


class TestADKNativeHandoffs:
    """A transfer is ADK's: the agent taking the call gets a socket of its own, with the conversation so far."""

    @staticmethod
    def _team(before=None, tools=()):
        billing = _agent("billing", voice="Kore", before_tool_callback=before)
        support = _agent("support", voice="Charon", before_tool_callback=before)
        supervisor = _agent("supervisor", voice="Aoede", sub_agents=[billing, support], before_tool_callback=before, tools=list(tools))
        return supervisor, billing, support

    @pytest.mark.asyncio
    async def test_a_specialist_hands_the_call_on_and_the_next_one_hears_the_conversation(self, monkeypatch):
        client = _GeminiClient(
            supervisor=[
                [_hears("My bill is higher this month."), _says("Billing will take it."), _done()],
                [_calls("t1", "transfer_to_agent", agent_name="billing")],
            ],
            billing=[[_says("Which invoice?"), _done()], [_hears("The March one."), _calls("t2", "transfer_to_agent", agent_name="support")]],
            support=[[_says("The March invoice includes a late fee."), _done()]],
        )
        supervisor, billing, support = self._team()
        call = await _Call(monkeypatch, client, [supervisor, billing, support]).start()

        await call.until(lambda: client.of("support") and ("agent_said", "support", "The March invoice includes a late fee.") in call.observed)
        await call.close()

        changes = [data for kind, data in call.events if kind == "agent_changed"]
        assert changes == [{"agent": "billing", "previous_agent": "supervisor"}, {"agent": "support", "previous_agent": "billing"}]
        # A turn ends before the call changes hands, so the edge never credits one agent's words to another.
        index = call.kinds().index("agent_changed")
        assert call.events[index - 1] == ("done", {"status": "transferred"})
        seen = " ".join(client.of("support")[0].seen())
        assert "My bill is higher this month." in seen and "Which invoice?" in seen and "The March one." in seen
        # Each agent's socket speaks in its own voice.
        assert [socket.config.speech_config.voice_config.prebuilt_voice_config.voice_name for socket in client.sockets] == ["Aoede", "Kore", "Charon"]
        assert [agent for kind, agent, _ in call.observed if kind == "agent_changed"][-2:] == ["billing", "support"]

    @pytest.mark.asyncio
    async def test_a_refused_handoff_leaves_the_call_with_the_same_agent(self, monkeypatch):
        refusals = []

        def before(tool, args, tool_context):
            if tool.name == "transfer_to_agent":
                refusals.append(tool_context.agent_name)
                return {"result": "Not handed over: verify the account first."}

        client = _GeminiClient(
            supervisor=[[_calls("t1", "transfer_to_agent", agent_name="billing")], _answered, [_says("Let me check your account first."), _done()]]
        )
        supervisor, billing, support = self._team(before=before)
        call = await _Call(monkeypatch, client, [supervisor, billing, support]).start()

        await call.until(lambda: "done" in call.kinds())
        await asyncio.sleep(0.1)
        still_open = not client.sockets[0].closed
        await call.close()

        assert refusals == ["supervisor"]
        assert [socket.agent for socket in client.sockets] == ["supervisor"] and still_open
        assert "agent_changed" not in call.kinds() and "reconnected" not in call.kinds()
        assert client.sockets[0].tool_responses[0][0].response == {"result": "Not handed over: verify the account first."}

    @pytest.mark.asyncio
    async def test_the_callers_audio_during_a_handoff_reaches_the_agent_taking_the_call_once_the_old_socket_closed(self, monkeypatch):
        """ADK keeps the old socket for ``DEFAULT_TRANSFER_AGENT_DELAY`` after a transfer: what the caller says then goes
        to the agent handing over and is lost. Once that socket is closed, the queue holds it for the new agent."""
        for module in ("google.adk.flows.llm_flows.base_llm_flow", "google.adk.live._live_llm_flow"):
            try:
                monkeypatch.setattr(f"{module}.DEFAULT_TRANSFER_AGENT_DELAY", 0.2)
            except (ImportError, AttributeError):
                pass
        client = _GeminiClient(supervisor=[[_calls("t1", "transfer_to_agent", agent_name="billing")]], billing=[[]])
        supervisor, billing, support = self._team()
        call = await _Call(monkeypatch, client, [supervisor, billing, support]).start()
        await call.until(lambda: "agent_changed" in call.kinds())

        call.connection.append_audio(base64.b64encode(b"\x00\x20" * 160).decode())
        await call.until(lambda: client.sockets[0].closed)
        call.connection.append_audio(base64.b64encode(b"\x00\x30" * 160).decode())
        await call.until(lambda: client.of("billing") and client.of("billing")[0].audio)
        await call.close()

        assert len(client.sockets[0].audio) == 1 and len(client.of("billing")[0].audio) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("finished", [True, False], ids=["transcription-finished", "no-end-signal"])
    async def test_words_said_with_a_transfer_reach_the_next_agent_only_once_their_transcription_ends(self, monkeypatch, finished):
        """A known gap of ADK's history: an agent's words are recorded at the end of their transcription or of the turn.
        A turn ending in a transfer never ends on the old socket (Gemini 3.x completes it only once the call is answered),
        so words Gemini sends no transcription end for are not in what the next agent is given."""
        words = _message(output_transcription=genai_types.Transcription(text="Billing will take it.", finished=finished))
        client = _GeminiClient(supervisor=[[words, _calls("t1", "transfer_to_agent", agent_name="billing")]], billing=[[]])
        supervisor, billing, support = self._team()
        call = await _Call(monkeypatch, client, [supervisor, billing, support]).start()

        await call.until(lambda: client.of("billing") and client.of("billing")[0].history)
        await call.close()

        assert ("Billing will take it." in " ".join(client.of("billing")[0].seen())) is finished

    def test_the_team_is_every_agent_reachable_through_transfers(self):
        supervisor, billing, support = self._team()
        with Runtime(InMemorySessionStore()):
            module = GoogleADKModule([supervisor, billing, support])
        assert GoogleADKRealtimeRunner().team(module.get_agent("supervisor")) == ["supervisor", "billing", "support"]


# Recovery: a live run that fails is started again


class TestADKNativeRecovery:
    """ADK resumes a socket itself when the call's RunConfig asks for session resumption; a run that fails anyway,
    or stops answering, is started again for the agent that had the call, with the conversation so far."""

    @pytest.mark.asyncio
    async def test_a_dropped_socket_restarts_the_same_agent_with_the_conversation_and_a_note(self, monkeypatch):
        client = _GeminiClient(
            supervisor=[[_calls("t1", "transfer_to_agent", agent_name="billing")]],
            billing=_Sockets(
                [[_hears("The March one."), _says("Got it."), _done()], ConnectionError("1006 abnormal closure")],
                [[_says("Sorry, I lost you for a moment."), _done()]],
            ),
        )
        supervisor, billing, support = TestADKNativeHandoffs._team()
        call = await _Call(monkeypatch, client, [supervisor, billing, support]).start()

        await call.until(lambda: "reconnected" in call.kinds() and len(client.of("billing")) == 2)
        await call.until(lambda: client.of("billing")[1].text)
        await call.close()

        assert ("done", {"status": "reconnecting"}) in call.events
        reconnected = next(data for kind, data in call.events if kind == "reconnected")
        assert reconnected["agent"] == "billing" and reconnected["seeded"] is True
        renewed = client.of("billing")[1]
        assert "The March one." in " ".join(renewed.seen()) and "Got it." in " ".join(renewed.seen())
        assert "dropped" in renewed.text[-1]
        # The call stayed with billing, and the supervisor's socket was never reopened.
        assert len(client.of("supervisor")) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("answered", ["said", "acted", None], ids=["caller-answered", "caller-acted-on", "caller-waiting"])
    async def test_the_caller_is_asked_to_repeat_only_when_their_words_were_unanswered(self, monkeypatch, answered):
        """Live: a run that stalled after the agent had answered asked the caller to repeat words they never said; and
        one that stalled after a tool had recorded their words asked them to say those again."""

        def price(item: str) -> str:
            """Look up a price."""
            return "ten dollars"

        turns = {
            "said": [[_hears("What does it cost?"), _says("Ten dollars."), _done()]],
            "acted": [[_hears("What does it cost?"), _calls("c1", "price", item="plan")], _answered],
            None: [[_hears("What does it cost?")]],
        }[answered]
        client = _GeminiClient(supervisor=[*turns, ConnectionError("dropped")])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=[price])]).start()

        await call.until(lambda: len(client.sockets) == 2 and client.sockets[1].text)
        await call.close()

        note = client.sockets[1].text[-1]
        assert ("ask them to repeat" in note) is (answered is None) and ("did not speak" in note) is (answered is not None)

    @pytest.mark.asyncio
    async def test_a_tool_that_finished_before_the_drop_is_not_run_again(self, monkeypatch):
        runs = []

        def book(slot: str) -> str:
            """Book a slot."""
            runs.append(slot)
            return "booked"

        client = _GeminiClient(supervisor=[[_calls("c1", "book", slot="9am")], _answered, [_says("Booked."), _done()], ConnectionError("dropped")])
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=[book])]).start()

        await call.until(lambda: len(client.sockets) == 2 and client.sockets[1].history)
        await call.close()

        assert runs == ["9am"]
        seen = " ".join(client.sockets[1].seen())
        assert "Booked." in seen
        # A restarted run is a new invocation: ADK replays the earlier call and its result as quoted context.
        assert "called tool `book`" in seen and "{'result': 'booked'}" in seen

    @pytest.mark.asyncio
    async def test_with_session_resumption_adk_resumes_the_socket_itself(self, monkeypatch):
        from google.adk.agents.run_config import RunConfig
        from websockets.exceptions import ConnectionClosedError

        resumable = genai_types.LiveServerMessage(
            session_resumption_update=genai_types.LiveServerSessionResumptionUpdate(new_handle="h1", resumable=True)
        )
        client = _GeminiClient(
            supervisor=_Sockets([resumable, [_says("Hello."), _done()], ConnectionClosedError(None, None)], [[_says("Still here."), _done()]])
        )
        call = _Call(monkeypatch, client, [_agent("supervisor")])
        call.module.run_options(call.agent.agent, run_config=RunConfig(session_resumption=genai_types.SessionResumptionConfig()))
        await call.start()

        await call.until(lambda: ("agent_said", "supervisor", "Still here.") in call.observed)
        await call.close()

        assert client.sockets[1].config.session_resumption.handle == "h1"
        # The server holds the conversation: nothing is replayed, and Agent Kernel restarted nothing.
        assert client.sockets[1].history == []
        assert "reconnected" not in call.kinds() and ("done", {"status": "reconnecting"}) not in call.events

    @pytest.mark.asyncio
    async def test_a_run_that_stops_answering_is_restarted(self, monkeypatch):
        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.2)
        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_CHECK_SECONDS", 0.05)
        client = _GeminiClient(supervisor=_Sockets([[_hears("Hello?")]], [[_says("Hello, sorry about that."), _done()]]))
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        await call.until(lambda: "reconnected" in call.kinds())
        await call.close()

        assert len(client.sockets) == 2

    @pytest.mark.asyncio
    async def test_a_tool_slower_than_the_stall_wait_is_not_a_stall(self, monkeypatch):
        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.1)
        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_CHECK_SECONDS", 0.02)

        async def slow_lookup(question: str) -> str:
            """A slow lookup."""
            await asyncio.sleep(0.4)
            return "result"

        client = _GeminiClient(
            supervisor=[[_hears("Look it up."), _calls("c1", "slow_lookup", question="q")], _answered, [_says("Found it."), _done()]]
        )
        call = await _Call(monkeypatch, client, [_agent("supervisor", tools=GoogleADKToolBuilder.bind([slow_lookup]))]).start()

        await call.until(lambda: "done" in call.kinds(), timeout=3)
        await call.close()

        assert "reconnected" not in call.kinds() and len(client.sockets) == 1

    @pytest.mark.asyncio
    async def test_a_run_lost_again_right_after_each_restart_is_given_up_on(self, monkeypatch):
        client = _GeminiClient(supervisor=_Sockets(*[[ConnectionError("dropped")] for _ in range(5)]))
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        await call.until(lambda: call.connection.closed, timeout=3)
        await call.close()

        # No restarted run ever said anything, so none was reported back.
        assert "reconnected" not in call.kinds() and "error" in call.kinds()

    @pytest.mark.asyncio
    async def test_a_restart_is_reported_back_only_once_the_new_run_says_something(self, monkeypatch):
        """Review: the line was reported back before the new run had even started, and a restart that then failed had
        already been reported as a success."""
        client = _GeminiClient(supervisor=_Sockets([ConnectionError("dropped")], [[_says("I'm back."), _done()]]))
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()
        await call.until(lambda: client.sockets)
        client.refuse = 1  # the first restart's socket cannot open

        await call.until(lambda: "reconnected" in call.kinds())
        await call.close()

        reconnecting = [index for index, event in enumerate(call.events) if event == ("done", {"status": "reconnecting"})]
        assert len(reconnecting) == 2 and call.kinds().count("reconnected") == 1
        # Reported once the run that opened said something, after the restart that failed.
        assert call.kinds().index("reconnected") > reconnecting[1]
        assert call.kinds().index("reconnected") < call.kinds().index("transcript_delta")

    @pytest.mark.asyncio
    async def test_closing_while_the_run_restarts_ends_it(self, monkeypatch):
        monkeypatch.setattr(GoogleADKRealtimeRunner, "RESTART_DELAYS_SECONDS", (0.5, 0.5, 0.5))
        client = _GeminiClient(supervisor=[ConnectionError("dropped")])
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()
        await call.until(lambda: "done" in call.kinds())

        await call.close()
        await asyncio.sleep(0.6)

        assert "reconnected" not in call.kinds() and len(client.sockets) == 1


# Lifecycle


class TestADKNativeLifecycle:
    @pytest.mark.asyncio
    async def test_disconnect_ends_the_run_and_is_safe_twice_and_before_connect(self, monkeypatch):
        await GoogleADKRealtimeRunner().disconnect()
        client = _GeminiClient(supervisor=[[]])
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()
        await call.until(lambda: client.sockets)
        adapter = call.connection.adapter
        live = adapter._live

        await call.close()
        await adapter.disconnect()

        assert live.done() and adapter._supervisor is None and adapter._runner is None

    @pytest.mark.asyncio
    async def test_a_socket_that_cannot_open_fails_the_call(self, monkeypatch):
        client = _GeminiClient(supervisor=[[]])
        client.refuse = 99
        call = await _Call(monkeypatch, client, [_agent("supervisor")]).start()

        await call.until(lambda: call.connection.closed, timeout=3)
        await call.close()

        assert "error" in call.kinds()
        assert client.sockets == []

    @pytest.mark.asyncio
    async def test_a_tool_scope_on_the_runs_own_task_is_refused(self):
        adapter = GoogleADKRealtimeRunner()
        adapter._live = asyncio.current_task()

        with pytest.raises(RuntimeError, match="live run's own task"):
            await adapter._enter_tool()

    def test_the_pool_runs_no_tool_for_an_adapter_that_runs_its_own(self):
        assert GoogleADKRealtimeRunner.runs_tools is True
        assert realtime_pool.RealtimeConnection.open_tool_scope is not None
