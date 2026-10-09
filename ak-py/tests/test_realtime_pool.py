import asyncio
import json
import threading
import types

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.event import TextDelta
from agentkernel.core.model import AgentReplyText, ExecutionMode, StreamChunk
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.pipeline.envelope import ATTR_INTEGRATION, ATTR_REALTIME, QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnection, RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset_pipeline_state():
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    RealtimeConnectionPool.reset()
    ThreadRunner.shutdown_event.clear()


class _Runner(Runner):
    def __init__(self):
        super().__init__("test-runner")

    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Adapter(RealtimeRunner):
    """Records every call the pool makes; emits nothing on its own."""

    def __init__(self):
        super().__init__("fake")
        self.connected = 0
        self.audio: list[str] = []
        self.texts: list[str] = []
        self.executed: list[tuple[str, str]] = []
        self.tool_results: list[tuple[str, str]] = []
        self.tool_return = "tool-ok"
        self.callback = None

    async def connect(self, session, agent, callback):
        self.connected += 1
        self.callback = callback

    async def append_audio(self, base64_audio):
        self.audio.append(base64_audio)

    async def send_text(self, text):
        self.texts.append(text)

    async def execute_tool(self, name, arguments, context, call_id):
        self.executed.append((name, arguments, call_id))
        return self.tool_return

    async def send_tool_result(self, call_id, result):
        self.tool_results.append((call_id, result))

    async def disconnect(self):
        pass


class _Agent(Agent):
    def __init__(self, name="general", realtime_runner_cls=_Adapter):
        super().__init__(name, _Runner(), realtime_runner_cls=realtime_runner_cls)

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def attach_tool(self, tool):
        pass

    def override_system_prompt(self, prompt):
        pass


def _connection(session_id="s1", agent=None, loop=None):
    return RealtimeConnection(session_id, agent or _Agent(), Runtime(InMemorySessionStore()), Session(session_id), loop or asyncio.new_event_loop())


def _drain_output(transport):
    """Every output message, in order. The in-memory queue delivers one message per group until it
    is acked, so this drains with acks."""
    consumer = transport.create_consumer(QueueName.OUTPUT)
    drained = []
    while True:
        messages = consumer.fetch(10, 0.2)
        if not messages:
            return drained
        for message in messages:
            drained.append(message)
            consumer.ack(message)


def _kinds(messages):
    return ["done" if json.loads(m.body).get("done") else json.loads(m.body)["event"]["type"] for m in messages]


class TestRealtimeConnection:
    def test_requires_realtime_runner_cls(self):
        with pytest.raises(ValueError, match="no realtime_runner_cls"):
            _connection(agent=_Agent(realtime_runner_cls=None))

    def test_reads_configured_playback_lead(self, monkeypatch):
        """The pacing lead is config-driven so a higher-latency broker can buffer more audio
        (execution.realtime.playback_lead_ms), instead of the old hard-coded 50 ms."""

        class _Cfg:
            class execution:
                class realtime:
                    playback_lead_ms = 250

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        assert _connection()._playback_lead_ms == 250

    @pytest.mark.asyncio
    async def test_emit_stamps_realtime_and_integration(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        conn = _connection(loop=asyncio.get_running_loop())
        conn.update_delivery_context(request_id="r1", user_id="u1", integration="livekit", reply_context={"session_id": "s1"})
        await conn._emit(StreamChunk(event=TextDelta(message_id="m1", content="QUFB"), delta="QUFB"))

        [message] = transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)
        assert message.attributes[ATTR_REALTIME] == "true"
        assert message.attributes[ATTR_INTEGRATION] == "livekit"
        assert message.attributes["request_id"] == "r1"
        assert message.attributes["user_id"] == "u1"
        assert message.attributes["reply_session_id"] == "s1"
        assert message.group_id == "s1"
        body = json.loads(message.body)
        assert body["event"]["type"] == "text_delta"
        assert body["event"]["content"] == "QUFB"
        assert body["delta"] == "QUFB"

    @pytest.mark.asyncio
    async def test_tool_call_delegates_to_adapter(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        conn = _connection(loop=asyncio.get_running_loop())
        conn.adapter.tool_return = "42"
        await conn._execute_tool_and_reply("call-1", "get_weather", '{"location": "Paris"}')

        assert conn.adapter.executed == [("get_weather", '{"location": "Paris"}', "call-1")]
        assert conn.adapter.tool_results == [("call-1", "42")]


class TestRealtimeConnectionPool:
    def test_get_or_create_reuses_one_connection_per_session(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            runtime = Runtime(InMemorySessionStore())
            agent = _Agent()
            first = pool.get_or_create("s1", agent, runtime, Session("s1"))
            second = pool.get_or_create("s1", agent, runtime, Session("s1"))
            other = pool.get_or_create("s2", agent, runtime, Session("s2"))

            assert first is second
            assert other is not first
            assert first.adapter.connected == 1
            assert other.adapter.connected == 1
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(timeout=5)


class TestRealtimePoolShutdown:
    """Shutdown closes every connection once, opens none, and never leaves a caller waiting on a dead loop."""

    class _HangingAdapter(_Adapter):
        """Never finishes connecting, like a socket handshake still in flight at shutdown."""

        entered = threading.Event()

        async def connect(self, session, agent, callback):
            type(self).entered.set()
            await asyncio.Event().wait()

    class _CountingAdapter(_Adapter):
        def __init__(self):
            super().__init__()
            self.disconnects = 0

        async def disconnect(self):
            self.disconnects += 1
            await asyncio.sleep(0)

    def test_no_connection_is_opened_once_shutdown_starts(self):
        pool = RealtimeConnectionPool.initialize()
        pool._loop_ready.set()
        ThreadRunner.shutdown_event.set()

        with pytest.raises(RuntimeError, match="shutting down"):
            pool.get_or_create("s1", _Agent(), Runtime(InMemorySessionStore()), Session("s1"))

    def test_a_connect_in_flight_at_shutdown_fails_fast(self, monkeypatch):
        """A consumer waiting on a connect gets an error when the loop stops, not the 15 s timeout."""
        import concurrent.futures

        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        monkeypatch.setattr("agentkernel.pipeline.realtime_pool._SHUTDOWN_GRACE_SECONDS", 0.1)
        self._HangingAdapter.entered.clear()

        pool = RealtimeConnectionPool.initialize()
        pool_thread = threading.Thread(target=pool.start, daemon=True)
        pool_thread.start()

        outcome = {}

        def connect():
            try:
                pool.get_or_create("s1", _Agent(realtime_runner_cls=self._HangingAdapter), Runtime(InMemorySessionStore()), Session("s1"))
            except BaseException as e:
                outcome["error"] = e

        caller = threading.Thread(target=connect, daemon=True)
        caller.start()
        assert self._HangingAdapter.entered.wait(timeout=5)

        ThreadRunner.shutdown_event.set()
        caller.join(timeout=5)
        pool_thread.join(timeout=5)

        assert not caller.is_alive()
        assert not pool_thread.is_alive()
        assert isinstance(outcome.get("error"), concurrent.futures.CancelledError)

    @pytest.mark.asyncio
    async def test_closing_twice_disconnects_once(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(agent=_Agent(realtime_runner_cls=self._CountingAdapter), loop=asyncio.get_running_loop())

        await asyncio.gather(conn.close(), conn.close())

        assert conn.adapter.disconnects == 1

    def test_the_runner_drops_input_during_shutdown(self, monkeypatch):
        from unittest.mock import MagicMock

        from agentkernel.pipeline.agent_runner import RealtimeAgentRunner
        from agentkernel.pipeline.envelope import QueueMessage

        transport = InMemoryTransport()
        chat_service = MagicMock()
        runner = RealtimeAgentRunner(transport=transport, chat_service=chat_service)
        ThreadRunner.shutdown_event.set()

        body = json.dumps({"prompt": "", "session_id": "s1", "requests": [{"type": "text", "prompt": "hi"}]})
        runner.process(QueueMessage(body=body, attributes={"request_id": "r1", "integration": "livekit"}, group_id="s1", dedup_id="d1"))

        chat_service.prepare_agent_handler.assert_not_called()
        assert RealtimeConnectionPool.get()._connections == {}


class TestRealtimeRunnerReuse:
    def test_audio_chunks_reuse_connection_without_re_resolving(self, monkeypatch):
        from unittest.mock import MagicMock

        from agentkernel.pipeline.agent_runner import RealtimeAgentRunner
        from agentkernel.pipeline.envelope import QueueMessage

        class _Cfg:
            class execution:
                mode = ExecutionMode.REALTIME
                queues = None

                class realtime:
                    playback_lead_ms = 50

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        handler = types.SimpleNamespace(service=types.SimpleNamespace(agent=_Agent(), runtime=Runtime(InMemorySessionStore()), session=Session("s1")))
        chat_service = MagicMock()
        chat_service.prepare_agent_handler.return_value = handler
        chat_service.process_chat_request.return_value = (200, {})

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            runner = RealtimeAgentRunner(transport=transport, chat_service=chat_service)
            body = json.dumps({"prompt": "", "session_id": "s1", "requests": [{"type": "text", "prompt": "hi"}]})
            for i in range(3):
                runner.process(QueueMessage(body=body, attributes={"request_id": f"r{i}", "integration": "livekit"}, group_id="s1", dedup_id=f"d{i}"))

            # Three chunks, one connection: the agent/session is resolved once, not per chunk.
            assert chat_service.prepare_agent_handler.call_count == 1
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(timeout=5)


class TestFrameworkToolExecution:
    """The adapter must hand each framework the context shape it expects, or tools that read
    their context fail (ADK injects a ``ToolContext``; the OpenAI SDK needs its own)."""

    @pytest.mark.asyncio
    async def test_adk_execute_tool_injects_context(self):
        from google.adk.agents import Agent as GoogleAgent
        from google.adk.tools import ToolContext as ADKToolContext

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner, GoogleADKToolBuilder

        def get_weather(location: str, tool_context: ADKToolContext) -> str:
            """Get the weather."""
            return f"{location}:{tool_context.state.get('marker', 'no-state')}"

        adk_agent = GoogleAgent(name="general", model="gemini-2.0-flash", instruction="x", tools=GoogleADKToolBuilder.bind([get_weather]))
        agent = types.SimpleNamespace(agent=adk_agent, name="general")
        session = Session("s1")
        runtime = Runtime(InMemorySessionStore())

        runner = GoogleADKRealtimeRunner()
        runner._agent = agent

        runner._active = agent.agent
        await runner._open_tool_session(session.id)

        result = await runner.execute_tool("get_weather", '{"location": "Paris"}', ToolContext(runtime, agent, session, []), "call-1")
        assert result == "Paris:no-state"

    @pytest.mark.asyncio
    async def test_adk_tool_state_lives_in_the_connection_not_the_ak_session(self):
        """Tool calls on one connection share ``tool_context.state``; nothing is written into the
        Agent Kernel session (the unary runner's ADK session key stays untouched)."""
        from google.adk.agents import Agent as GoogleAgent
        from google.adk.tools import ToolContext as ADKToolContext

        from agentkernel.framework.adk.adk import FRAMEWORK, GoogleADKRealtimeRunner, GoogleADKToolBuilder

        def remember(value: str, tool_context: ADKToolContext) -> str:
            """Remember a value."""
            tool_context.state["remembered"] = value
            return "ok"

        def recall(tool_context: ADKToolContext) -> str:
            """Recall the value."""
            return tool_context.state.get("remembered", "nothing")

        adk_agent = GoogleAgent(name="general", model="gemini-2.0-flash", instruction="x", tools=GoogleADKToolBuilder.bind([remember, recall]))
        agent = types.SimpleNamespace(agent=adk_agent, name="general")
        session = Session("s1")
        runtime = Runtime(InMemorySessionStore())

        runner = GoogleADKRealtimeRunner()
        runner._agent = agent

        runner._active = agent.agent
        await runner._open_tool_session(session.id)

        await runner.execute_tool("remember", '{"value": "blue"}', ToolContext(runtime, agent, session, []), "call-1")
        result = await runner.execute_tool("recall", "{}", ToolContext(runtime, agent, session, []), "call-2")

        assert result == "blue"
        assert session.get(FRAMEWORK) is None

    @pytest.mark.asyncio
    async def test_adk_execute_tool_before_connect_fails_clearly(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        runner = GoogleADKRealtimeRunner()
        runner._agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[types.SimpleNamespace(name="t")]), name="general")

        with pytest.raises(RuntimeError, match="connect"):
            await runner.execute_tool("t", "{}", None, "call-1")

    @pytest.mark.asyncio
    async def test_openai_execute_tool_injects_context(self):
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner, OpenAIToolBuilder

        def get_weather(location: str) -> str:
            """Get the weather."""
            context = ToolContext.get()
            return f"{location}:{context.session.id if context else 'no-context'}"

        [tool] = OpenAIToolBuilder.bind([get_weather])
        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[tool]), name="general")
        session = Session("s1")
        runtime = Runtime(InMemorySessionStore())

        adapter = OpenAIRealtimeRunner()
        adapter._agent = agent
        adapter._tools = {tool.name: tool}

        result = await adapter.execute_tool("get_weather", '{"location": "Paris"}', ToolContext(runtime, agent, session, []), "call-1")
        assert result == "Paris:s1"

    @pytest.mark.asyncio
    async def test_openai_execute_tool_passes_framework_context_as_run_context(self):
        """Parity with the unary path: ``wrapper.context`` is the session's framework_context, not the AK ToolContext."""
        from agents import RunContextWrapper, function_tool

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        @function_tool
        def get_cart(wrapper: RunContextWrapper) -> str:
            """Read the cart."""
            return ",".join(wrapper.context["cart"])

        session = Session("s1")
        session.set_framework_context({"cart": ["apple", "pear"]})
        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[get_cart]), name="general")

        adapter = OpenAIRealtimeRunner()
        adapter._agent = agent
        adapter._tools = {get_cart.name: get_cart}

        result = await adapter.execute_tool("get_cart", "{}", ToolContext(Runtime(InMemorySessionStore()), agent, session, []), "call-1")
        assert result == "apple,pear"


class TestRealtimeResampling:
    @pytest.mark.asyncio
    async def test_append_audio_resamples_edge_rate_to_model_rate(self, monkeypatch):
        import base64

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        conn = _connection(loop=asyncio.get_running_loop())
        conn.adapter.input_sample_rate = 16000  # e.g. Gemini's input rate

        # 100 ms of edge-rate (24 kHz) audio; the pool must hand the adapter 16 kHz audio.
        conn.append_audio(base64.b64encode(b"\x00\x00" * 2400).decode())
        for _ in range(50):  # the append is scheduled on the loop; let it run
            if conn.adapter.audio:
                break
            await asyncio.sleep(0.01)

        [converted] = conn.adapter.audio
        assert len(base64.b64decode(converted)) == 1600 * 2  # 100 ms at 16 kHz


class TestRealtimePacing:
    """The connection paces a turn's audio and emits its terminal ``done`` behind it."""

    @pytest.mark.asyncio
    async def test_done_follows_its_audio(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()  # starts the connection's shared pacing loop

        delta = "QUFB"  # 4 bytes -> 2 samples -> a tiny duration, so pacing does not sleep
        for _ in range(3):
            await conn.handle_framework_event("audio_delta", {"delta": delta, "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.2)
        conn._pacing_task.cancel()

        kinds = _kinds(_drain_output(transport))

        # All three audio deltas are emitted, and the terminal event is always the done chunk
        # (it never overtakes its audio).
        assert kinds.count("audio_delta") == 3
        assert kinds[-1] == "done"


class TestRealtimeBargeIn:
    """Barge-in against the pool's paced audio: ``speech_started`` interrupts only while audio is queued."""

    @staticmethod
    def _queued(conn):
        return [item[0] for item in list(conn._audio_queue._queue)]

    @pytest.mark.asyncio
    async def test_speech_started_with_no_queued_audio_is_ignored(self, monkeypatch):
        """The ordinary start of a user's turn must not reach the edge as an interrupt, or it would
        clear playback and drop the transcript of the response that follows."""
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("speech_started", {})

        assert self._queued(conn) == []

    @pytest.mark.asyncio
    async def test_speech_started_over_queued_audio_interrupts_and_keeps_done(self, monkeypatch):
        """The model finished generating but its paced audio is still queued: talking over it is a
        barge-in, and the turn's done still follows so the edge resets its interrupted state."""
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await conn.handle_framework_event("speech_started", {})

        assert self._queued(conn) == ["interrupt", "done"]
        assert conn._queued_audio == 0

    @pytest.mark.asyncio
    async def test_interrupt_keeps_a_queued_done_behind_it(self, monkeypatch):
        """Regression: the drain used to drop a queued done too, leaving the edge's interrupted state
        set into the next turn, which then lost its transcript."""
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("interrupt", {})

        assert self._queued(conn) == ["interrupt", "done"]

    @pytest.mark.asyncio
    async def test_emitted_audio_no_longer_counts_as_queued(self, monkeypatch):
        """Once the pacing loop has emitted a turn's audio, a later speech_started is a new turn."""
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.1)
        await conn.handle_framework_event("speech_started", {})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()

        assert _kinds(_drain_output(transport)) == ["agent_changed", "audio_delta", "done"]


class TestRealtimeAgentChanged:
    """The agent speaking is announced in order with the output it divides, so an edge never credits
    one agent's words to another."""

    @staticmethod
    def _queued(conn):
        return [item[0] for item in list(conn._audio_queue._queue)]

    @pytest.mark.asyncio
    async def test_the_starting_agent_is_announced_before_any_output(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        conn = _connection(agent=_Agent(name="supervisor"), loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()

        messages = _drain_output(transport)
        assert _kinds(messages) == ["agent_changed", "audio_delta", "done"]
        assert json.loads(messages[0].body)["event"] == {"type": "agent_changed", "agent": "supervisor", "agents": ["supervisor"]}

    @pytest.mark.asyncio
    async def test_the_transcript_and_a_handoff_stay_in_order_with_the_audio(self, monkeypatch):
        """Regression: the transcript used to bypass the paced queue, so the new agent's words could
        reach the edge while the previous agent's audio was still queued, ahead of the handoff."""
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m1"})
        await conn.handle_framework_event("transcript_delta", {"delta": "Transferring you.", "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "supervisor"})
        await conn.handle_framework_event("transcript_delta", {"delta": "Billing here.", "message_id": "m2"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m2"})

        assert self._queued(conn) == ["audio_delta", "transcript_delta", "done", "agent_changed", "transcript_delta", "audio_delta"]

    @pytest.mark.asyncio
    async def test_a_handoff_is_emitted_between_the_agents_output(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        conn = _connection(agent=_Agent(name="supervisor"), loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "supervisor"})
        await conn.handle_framework_event("transcript_delta", {"delta": "Billing here.", "message_id": "m2"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m2"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()

        messages = _drain_output(transport)
        assert _kinds(messages) == ["agent_changed", "audio_delta", "done", "agent_changed", "text_delta", "audio_delta", "done"]
        handoff, transcript = json.loads(messages[3].body), json.loads(messages[4].body)
        assert handoff["event"] == {"type": "agent_changed", "agent": "billing", "previous_agent": "supervisor"}
        assert transcript["delta"] == "Billing here."

    @pytest.mark.asyncio
    async def test_an_interrupt_drops_the_unheard_transcript_but_keeps_the_handoff(self, monkeypatch):
        """The user will not hear the dropped audio, so its words are dropped with it; talking over
        an agent does not undo the handoff that made it the speaker."""
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "supervisor"})
        await conn.handle_framework_event("transcript_delta", {"delta": "Your invoice", "message_id": "m2"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m2"})
        await conn.handle_framework_event("interrupt", {})

        assert self._queued(conn) == ["interrupt", "agent_changed"]

    def test_a_new_connection_is_routed_before_it_connects(self, monkeypatch):
        """Its first output (the starting agent) is emitted as soon as it connects, before the caller
        could set a delivery context afterwards, so get_or_create must apply one first."""
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            pool.get_or_create(
                "s1",
                _Agent(),
                Runtime(InMemorySessionStore()),
                Session("s1"),
                request_id="r1",
                integration="livekit",
                reply_context={"session_id": "s1"},
            )
            [message] = _drain_output(transport)
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(timeout=5)

        assert json.loads(message.body)["event"] == {"type": "agent_changed", "agent": "general", "agents": ["general"]}
        assert message.attributes[ATTR_INTEGRATION] == "livekit"
        assert message.attributes["request_id"] == "r1"
        assert message.attributes["reply_session_id"] == "s1"


class TestOpenAIBargeIn:
    """The OpenAI adapter reports ``interrupt`` only while a response is in flight."""

    @staticmethod
    def _adapter():
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        adapter = OpenAIRealtimeRunner()
        adapter.events = []

        async def callback(event_type, data):
            adapter.events.append(event_type)

        adapter._callback = callback
        return adapter

    @staticmethod
    def _event(event_type, **fields):
        return types.SimpleNamespace(type=event_type, **fields)

    @pytest.mark.asyncio
    async def test_speech_started_outside_a_response_is_reported_as_speech_started(self):
        adapter = self._adapter()

        await adapter._handle_message(self._event("input_audio_buffer.speech_started"))

        assert adapter.events == ["speech_started"]

    @pytest.mark.asyncio
    async def test_speech_started_during_a_response_is_an_interrupt(self):
        adapter = self._adapter()

        await adapter._handle_message(self._event("response.created"))
        await adapter._handle_message(self._event("input_audio_buffer.speech_started"))

        assert adapter.events == ["interrupt"]

    @pytest.mark.asyncio
    async def test_speech_started_after_response_done_is_not_an_interrupt(self):
        adapter = self._adapter()

        await adapter._handle_message(self._event("response.created"))
        await adapter._handle_message(self._event("response.done", response=types.SimpleNamespace(status="completed", output=[])))
        await adapter._handle_message(self._event("input_audio_buffer.speech_started"))

        assert adapter.events == ["done", "speech_started"]


class TestOpenAIRealtimeSession:
    """Session setup and the tool round trip follow the Realtime API's documented flow."""

    class _Connection:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

        async def __aiter__(self):
            # An async generator, as the SDK's connection iterates.
            return
            yield

    @classmethod
    def _runner(cls):
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        runner = OpenAIRealtimeRunner()
        runner._connection = cls._Connection()
        runner.events = []

        async def callback(event_type, data):
            runner.events.append((event_type, data))

        runner._callback = callback
        return runner

    @staticmethod
    def _response_done(status, *calls):
        output = [types.SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=args) for call_id, name, args in calls]
        return types.SimpleNamespace(type="response.done", response=types.SimpleNamespace(status=status, output=output))

    @pytest.mark.asyncio
    async def test_function_calls_are_dispatched_from_the_completed_response(self):
        runner = self._runner()

        # The arguments event precedes response.done; acting on it would race the active response.
        await runner._handle_message(types.SimpleNamespace(type="response.function_call_arguments.done", call_id="c1", name="a", arguments="{}"))
        await runner._handle_message(self._response_done("completed", ("c1", "a", '{"x": 1}'), ("c2", "b", "")))

        assert [(kind, data.get("call_id")) for kind, data in runner.events] == [("tool_call", "c1"), ("tool_call", "c2"), ("done", None)]
        assert runner.events[0][1]["arguments"] == '{"x": 1}'
        assert runner.events[1][1]["arguments"] == "{}"

    @pytest.mark.asyncio
    async def test_a_cancelled_response_dispatches_no_function_calls(self):
        runner = self._runner()

        await runner._handle_message(self._response_done("cancelled", ("c1", "a", "{}")))

        assert [kind for kind, _ in runner.events] == ["done"]

    @pytest.mark.asyncio
    async def test_the_follow_up_response_is_requested_once_after_the_last_output(self):
        runner = self._runner()
        await runner._handle_message(self._response_done("completed", ("c1", "a", "{}"), ("c2", "b", "{}")))

        await runner.send_tool_result("c1", "one")
        assert [payload["type"] for payload in runner._connection.sent] == ["conversation.item.create"]

        await runner.send_tool_result("c2", "two")
        assert [payload["type"] for payload in runner._connection.sent] == ["conversation.item.create", "conversation.item.create", "response.create"]

    @staticmethod
    def _patch_socket(monkeypatch):
        connection = TestOpenAIRealtimeSession._Connection()

        class _ConnectManager:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *exc):
                return False

        class _Client:
            realtime = types.SimpleNamespace(connect=lambda model: _ConnectManager())

            async def close(self):
                pass

        monkeypatch.setattr("openai.AsyncOpenAI", lambda *a, **k: _Client())
        return connection

    @staticmethod
    async def _connect(sdk_agent, session=None):
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        runner = OpenAIRealtimeRunner()

        async def callback(event_type, data):
            pass

        await runner.connect(session or Session("s1"), types.SimpleNamespace(name="general", agent=sdk_agent), callback)
        await runner.disconnect()
        return runner

    @pytest.mark.asyncio
    async def test_callable_instructions_are_resolved_with_the_framework_context(self, monkeypatch):
        from agents import Agent as SDKAgent

        connection = self._patch_socket(monkeypatch)
        session = Session("s1")
        session.set_framework_context({"name": "Ada"})
        sdk_agent = SDKAgent(name="general", model="gpt-realtime", instructions=lambda ctx, agent: f"Greet {ctx.context['name']}")

        await self._connect(sdk_agent, session)

        assert connection.sent[0]["session"]["instructions"] == "Greet Ada"

    @pytest.mark.asyncio
    async def test_no_instructions_leaves_the_server_default(self, monkeypatch):
        from agents import Agent as SDKAgent

        connection = self._patch_socket(monkeypatch)

        await self._connect(SDKAgent(name="general", model="gpt-realtime"))

        assert "instructions" not in connection.sent[0]["session"]

    @pytest.mark.asyncio
    async def test_only_function_tools_are_offered_and_others_are_reported(self, monkeypatch, caplog):
        from agents import Agent as SDKAgent
        from agents import WebSearchTool

        from agentkernel.framework.openai.openai import OpenAIToolBuilder

        def get_weather(location: str) -> str:
            """Get the weather."""
            return location

        connection = self._patch_socket(monkeypatch)
        sdk_agent = SDKAgent(name="general", model="gpt-realtime", tools=[*OpenAIToolBuilder.bind([get_weather]), WebSearchTool()])

        with caplog.at_level("WARNING"):
            await self._connect(sdk_agent)

        assert [tool["name"] for tool in connection.sent[0]["session"]["tools"]] == ["get_weather"]
        assert "not a function tool" in caplog.text


class TestOpenAIRealtimeToolGuards:
    """The runner calls tools directly, so tools whose checks it cannot apply are not offered, and only
    offered tools run, within their timeout."""

    @staticmethod
    def _tool(func, **changes):
        import dataclasses

        from agentkernel.framework.openai.openai import OpenAIToolBuilder

        [tool] = OpenAIToolBuilder.bind([func])
        return dataclasses.replace(tool, **changes) if changes else tool

    @staticmethod
    def _offered(*tools):
        from agents import RunContextWrapper

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        sdk_agent = types.SimpleNamespace(tools=list(tools))
        return asyncio.run(OpenAIRealtimeRunner()._offered_tools(sdk_agent, RunContextWrapper(context=None)))

    @staticmethod
    def plain(x: str) -> str:
        """A tool with no extra checks."""
        return x

    def test_tools_needing_approval_or_guardrails_are_not_offered(self, caplog):
        def approve(x: str) -> str:
            """Needs approval."""
            return x

        def guarded(x: str) -> str:
            """Has an input guardrail."""
            return x

        def checked(x: str) -> str:
            """Has an output guardrail."""
            return x

        with caplog.at_level("WARNING"):
            offered = self._offered(
                self._tool(self.plain),
                self._tool(approve, needs_approval=True),
                self._tool(guarded, tool_input_guardrails=[object()]),
                self._tool(checked, tool_output_guardrails=[object()]),
            )

        assert list(offered) == ["plain"]
        assert caplog.text.count("needs approval or has tool guardrails") == 3

    def test_disabled_tools_are_not_offered(self):
        def off(x: str) -> str:
            """Disabled."""
            return x

        def off_by_rule(x: str) -> str:
            """Disabled by a callable."""
            return x

        def on_async(x: str) -> str:
            """Enabled by an async callable."""
            return x

        async def enabled(ctx, agent):
            return True

        offered = self._offered(
            self._tool(off, is_enabled=False),
            self._tool(off_by_rule, is_enabled=lambda ctx, agent: False),
            self._tool(on_async, is_enabled=enabled),
        )

        assert list(offered) == ["on_async"]

    @pytest.mark.asyncio
    async def test_a_tool_that_was_not_offered_does_not_run(self):
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        ran = []

        def secret(x: str) -> str:
            """Never offered."""
            ran.append(x)
            return x

        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[self._tool(secret)]), name="general")
        runner = OpenAIRealtimeRunner()
        runner._agent = agent

        result = await runner.execute_tool("secret", '{"x": "1"}', ToolContext(Runtime(InMemorySessionStore()), agent, Session("s1"), []), "call-1")

        assert result == "Error: Tool secret not found"
        assert ran == []

    @pytest.mark.asyncio
    async def test_the_tool_timeout_is_enforced(self):
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        async def slow() -> str:
            """Takes too long."""
            await asyncio.sleep(1)
            return "late"

        tool = self._tool(slow, timeout_seconds=0.05)
        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[tool]), name="general")
        runner = OpenAIRealtimeRunner()
        runner._agent = agent
        runner._tools = {tool.name: tool}

        result = await runner.execute_tool("slow", "{}", ToolContext(Runtime(InMemorySessionStore()), agent, Session("s1"), []), "call-1")

        assert "timed out" in result


class _ScriptedRealtimeSocket:
    """A realtime socket that replays scripted server events in order.

    A callable in the script is a wait: replay pauses until it returns True over the client events
    sent so far, the way a real model answers only after the runner has. Once the script is spent the
    socket stays open. Iterated through an async generator, as the SDK's connection is."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self._sent = asyncio.Event()

    async def send(self, payload):
        self.sent.append(payload)
        self._sent.set()

    async def __aiter__(self):
        while self.script:
            item = self.script.pop(0)
            if not callable(item):
                yield item
                continue
            while not item(self.sent):
                self._sent.clear()
                await self._sent.wait()
        await asyncio.Event().wait()


class TestOpenAIRealtimeHandoffs:
    """Native handoffs run over the one socket and through the tool path, as the SDK's own realtime
    session runs them: the session moves to the agent the handoff returned when its result is sent,
    and the change is reported in order."""

    @staticmethod
    def _graph(**billing_options):
        from agents import Agent as SDKAgent

        supervisor = SDKAgent(name="supervisor", model="gpt-realtime", instructions="Route the caller.")
        billing = SDKAgent(name="billing", instructions="Answer billing questions.", handoffs=[supervisor], **billing_options)
        supervisor.handoffs = [billing]
        return supervisor, billing

    @staticmethod
    async def _runner(active):
        from agents import RunContextWrapper

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        runner = OpenAIRealtimeRunner()
        runner._connection = TestOpenAIRealtimeSession._Connection()
        runner._model = "gpt-realtime"
        runner._run_context = RunContextWrapper(context=None)
        runner.events = []
        runner.answered = set()

        async def callback(event_type, data):
            runner.events.append((event_type, data))

        runner._callback = callback
        await runner._activate(active)
        return runner

    @staticmethod
    def _context():
        return ToolContext(Runtime(InMemorySessionStore()), _Agent(), Session("s1"), [])

    @classmethod
    async def _answer(cls, runner):
        """Do what the pool does with each reported call: run it, then send its result."""
        for kind, data in list(runner.events):
            if kind != "tool_call" or data["call_id"] in runner.answered:
                continue
            runner.answered.add(data["call_id"])
            try:
                result = await runner.execute_tool(data["name"], data["arguments"], cls._context(), data["call_id"])
            except Exception as e:
                result = f"Error: {e}"
            await runner.send_tool_result(data["call_id"], result)

    @staticmethod
    def _done(*calls, status="completed"):
        return TestOpenAIRealtimeSession._response_done(status, *calls)

    @staticmethod
    def _reported(runner):
        return [event for event in runner.events if event[0] != "tool_call"]

    @pytest.mark.asyncio
    async def test_enabled_handoffs_are_offered_beside_the_tools(self, monkeypatch):
        supervisor, _ = self._graph()
        connection = TestOpenAIRealtimeSession._patch_socket(monkeypatch)

        await TestOpenAIRealtimeSession._connect(supervisor)

        [offered] = connection.sent[0]["session"]["tools"]
        assert offered["name"] == "transfer_to_billing"
        assert offered["description"].startswith("Handoff to the billing agent")

    def test_the_team_is_every_agent_reachable_through_handoffs(self):
        """Followed through handoff() wrappers too, nearest first: the room shows exactly these agents."""
        from agents import Agent as SDKAgent
        from agents import handoff

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        supervisor, billing = self._graph()
        supervisor.handoffs = [billing, handoff(SDKAgent(name="tech_support", handoffs=[supervisor]))]

        team = OpenAIRealtimeRunner().team(types.SimpleNamespace(name="supervisor", agent=supervisor))

        assert team == ["supervisor", "billing", "tech_support"]

    @pytest.mark.asyncio
    async def test_a_handoff_call_is_dispatched_like_a_tool_call(self):
        supervisor, _ = self._graph()
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))

        assert runner.events == [
            ("tool_call", {"call_id": "c1", "name": "transfer_to_billing", "arguments": "{}"}),
            ("done", {"status": "completed"}),
        ]
        assert runner._active is supervisor
        assert runner._connection.sent == []

    @pytest.mark.asyncio
    async def test_a_handoff_points_the_session_at_the_new_agent(self):
        supervisor, billing = self._graph()
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)

        assert runner._active is billing
        assert self._reported(runner) == [("done", {"status": "completed"}), ("agent_changed", {"agent": "billing", "previous_agent": "supervisor"})]
        update, output, follow_up = runner._connection.sent
        assert update["type"] == "session.update"
        assert update["session"]["instructions"] == "Answer billing questions."
        assert [tool["name"] for tool in update["session"]["tools"]] == ["transfer_to_supervisor"]
        assert output["item"] == {"type": "function_call_output", "call_id": "c1", "output": '{"assistant": "billing"}'}
        assert follow_up == {"type": "response.create"}

    @pytest.mark.asyncio
    async def test_the_handoff_callback_runs_once(self):
        from agents import handoff

        calls = []
        supervisor, billing = self._graph()
        supervisor.handoffs = [handoff(billing, on_handoff=lambda ctx: calls.append(ctx))]
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)

        assert len(calls) == 1
        assert runner._active is billing

    @pytest.mark.asyncio
    async def test_an_agent_with_no_instructions_does_not_keep_the_previous_ones(self):
        supervisor, billing = self._graph()
        billing.instructions = None
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)

        assert runner._connection.sent[0]["session"]["instructions"] == ""

    @pytest.mark.asyncio
    async def test_a_tool_called_beside_a_handoff_runs_as_the_agent_that_called_it(self):
        from agents import function_tool
        from agents.tool_context import ToolContext as SDKToolContext

        @function_tool
        def whoami(ctx: SDKToolContext) -> str:
            """Name the agent running this tool."""
            return ctx.agent.name

        supervisor, billing = self._graph()
        supervisor.tools = [whoami]
        runner = await self._runner(supervisor)
        await runner._handle_message(self._done(("c1", "whoami", "{}"), ("c2", "transfer_to_billing", "{}")))

        # The pool may finish the handoff first; billing has no whoami tool.
        await runner.send_tool_result("c2", await runner.execute_tool("transfer_to_billing", "{}", self._context(), "c2"))
        assert runner._active is billing
        # The follow-up response waits for the tool's output too.
        assert {"type": "response.create"} not in runner._connection.sent

        result = await runner.execute_tool("whoami", "{}", self._context(), "c1")
        await runner.send_tool_result("c1", result)

        assert result == "supervisor"
        assert runner._connection.sent[-1] == {"type": "response.create"}

    @pytest.mark.asyncio
    async def test_a_specialist_hands_back_to_the_supervisor(self):
        supervisor, billing = self._graph()
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)
        await runner._handle_message(self._done(("c2", "transfer_to_supervisor", "{}")))
        await self._answer(runner)

        assert runner._active is supervisor
        assert runner.events[-1] == ("agent_changed", {"agent": "supervisor", "previous_agent": "billing"})

    @pytest.mark.asyncio
    async def test_a_failed_handoff_keeps_the_agent(self):
        from agents import handoff

        def refuse(ctx):
            raise RuntimeError("billing is closed")

        supervisor, billing = self._graph()
        supervisor.handoffs = [handoff(billing, on_handoff=refuse)]
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)

        assert runner._active is supervisor
        assert self._reported(runner) == [("done", {"status": "completed"})]
        output, follow_up = runner._connection.sent
        assert output["item"]["output"] == "Error: billing is closed"
        assert follow_up == {"type": "response.create"}

    @pytest.mark.asyncio
    async def test_only_the_first_handoff_of_a_response_is_performed(self):
        from agents import Agent as SDKAgent
        from agents import handoff

        invoked = []
        supervisor, billing = self._graph()
        supervisor.handoffs = [billing, handoff(SDKAgent(name="tech_support"), on_handoff=lambda ctx: invoked.append(ctx))]
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}"), ("c2", "transfer_to_tech_support", "{}")))
        await self._answer(runner)

        assert runner._active is billing
        assert invoked == []
        outputs = {p["item"]["call_id"]: p["item"]["output"] for p in runner._connection.sent if p["type"] == "conversation.item.create"}
        assert outputs["c2"] == "Error: only one handoff is performed per turn; this one, to tech_support, was not"
        assert runner._connection.sent[-1] == {"type": "response.create"}

    @pytest.mark.asyncio
    async def test_a_cancelled_response_performs_no_handoff(self):
        supervisor, _ = self._graph()
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}"), status="cancelled"))

        assert runner._active is supervisor
        assert runner.events == [("done", {"status": "cancelled"})]

    @pytest.mark.asyncio
    async def test_a_disabled_handoff_is_not_offered(self):
        from agents import Agent as SDKAgent
        from agents import handoff

        supervisor, billing = self._graph()
        supervisor.handoffs = [billing, handoff(SDKAgent(name="sales"), is_enabled=False)]

        runner = await self._runner(supervisor)

        assert list(runner._handoffs) == ["transfer_to_billing"]

    @pytest.mark.asyncio
    async def test_a_handoff_that_filters_the_history_fails_before_connecting(self, monkeypatch):
        """Checked across the whole graph, through handoff() wrappers, before any socket opens."""
        from agents import handoff

        supervisor, billing = self._graph()
        supervisor.handoffs = [handoff(billing)]
        billing.handoffs = [handoff(supervisor, input_filter=lambda data: data)]
        connection = TestOpenAIRealtimeSession._patch_socket(monkeypatch)

        with pytest.raises(ValueError, match="filters or nests the history"):
            await TestOpenAIRealtimeSession._connect(supervisor)

        assert connection.sent == []

    @pytest.mark.asyncio
    async def test_a_specialist_declaring_another_model_is_reported_at_connect(self, monkeypatch, caplog):
        supervisor, _ = self._graph(model="gpt-4o")
        TestOpenAIRealtimeSession._patch_socket(monkeypatch)

        with caplog.at_level("WARNING"):
            await TestOpenAIRealtimeSession._connect(supervisor)

        assert "Agent 'billing' declares model gpt-4o" in caplog.text

    @pytest.mark.asyncio
    async def test_a_conversation_moves_to_a_specialist_and_back(self, monkeypatch):
        """End to end through the pool: the specialist's own tool runs once, the handoff's callback runs
        in Agent Kernel's session scope as a tool does, and every speaker change reaches the output in
        order with the speech around it."""
        from agents import handoff

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner, OpenAIToolBuilder

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        looked_up = []
        handed_off_in = []

        def get_invoice(account_id: str) -> str:
            """Look up the caller's latest invoice."""
            looked_up.append(account_id)
            return f"{account_id} owes $42"

        supervisor, billing = self._graph(tools=OpenAIToolBuilder.bind([get_invoice]))
        supervisor.handoffs = [handoff(billing, on_handoff=lambda ctx: handed_off_in.append(Session.current().id))]

        def answered(call_id):
            return lambda sent: any(p.get("item", {}).get("call_id") == call_id for p in sent)

        def event(event_type, **fields):
            return types.SimpleNamespace(type=event_type, **fields)

        socket = _ScriptedRealtimeSocket(
            [
                event("response.created"),
                event("response.output_audio_transcript.delta", delta="Connecting you to billing.", item_id="m1"),
                event("response.output_audio.delta", delta="QUFB", item_id="m1"),
                self._done(("c1", "transfer_to_billing", "{}")),
                answered("c1"),
                event("response.created"),
                event("response.output_audio_transcript.delta", delta="Billing here.", item_id="m2"),
                event("response.output_audio.delta", delta="QUFB", item_id="m2"),
                self._done(("c2", "get_invoice", '{"account_id": "A1"}')),
                answered("c2"),
                event("response.created"),
                self._done(("c3", "transfer_to_supervisor", "{}")),
                answered("c3"),
            ]
        )

        class _ConnectManager:
            async def __aenter__(self):
                return socket

            async def __aexit__(self, *exc):
                return False

        class _Client:
            realtime = types.SimpleNamespace(connect=lambda model: _ConnectManager())

            async def close(self):
                pass

        monkeypatch.setattr("openai.AsyncOpenAI", lambda *a, **k: _Client())

        agent = _Agent(name="supervisor", realtime_runner_cls=OpenAIRealtimeRunner)
        agent.agent = supervisor
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())
        await conn.connect()
        for _ in range(100):
            if not socket.script:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
        await conn.close()

        assert looked_up == ["A1"]
        assert handed_off_in == ["s1"]
        tool_output = next(p for p in socket.sent if p.get("item", {}).get("call_id") == "c2")
        assert tool_output["item"]["output"] == "A1 owes $42"
        assert [p["session"].get("instructions") for p in socket.sent if p["type"] == "session.update"] == [
            "Route the caller.",
            "Answer billing questions.",
            "Route the caller.",
        ]

        bodies = [json.loads(m.body) for m in _drain_output(transport)]
        # The conversation opens by naming its whole team, for the edge to show.
        assert bodies[0]["event"]["agents"] == ["supervisor", "billing"]
        speech = [
            (body["event"]["type"], body["event"].get("agent") or body.get("delta"))
            for body in bodies
            if body.get("event", {}).get("type") in ("agent_changed", "text_delta")
        ]
        assert speech == [
            ("agent_changed", "supervisor"),
            ("text_delta", "Connecting you to billing."),
            ("agent_changed", "billing"),
            ("text_delta", "Billing here."),
            ("agent_changed", "supervisor"),
        ]


class TestADKRealtimeTools:
    """Plain functions work as they do on a normal ADK run; toolsets are skipped; results are wrapped as ADK wraps them."""

    @staticmethod
    def get_weather(location: str) -> str:
        """Get the weather."""
        return f"sunny in {location}"

    def _agent(self, *tools):
        from google.adk.agents import Agent as GoogleAgent

        return types.SimpleNamespace(name="general", agent=GoogleAgent(name="general", model="gemini-live", instruction="x", tools=list(tools)))

    def test_a_plain_function_is_declared(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(self.get_weather).agent)

        assert [d.name for d in config.tools[0].function_declarations] == ["get_weather"]

    @pytest.mark.asyncio
    async def test_a_plain_function_runs(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        agent = self._agent(self.get_weather)
        runner = GoogleADKRealtimeRunner()
        runner._agent = agent
        runner._active = agent.agent
        await runner._open_tool_session("s1")

        result = await runner.execute_tool(
            "get_weather", '{"location": "Paris"}', ToolContext(Runtime(InMemorySessionStore()), agent, Session("s1"), []), "call-1"
        )

        assert result == "sunny in Paris"

    def test_a_toolset_is_skipped_with_a_warning(self, caplog):
        from google.adk.tools.base_toolset import BaseToolset

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        class _Toolset(BaseToolset):
            async def get_tools(self, readonly_context=None):
                return []

            async def close(self):
                pass

        with caplog.at_level("WARNING"):
            config = GoogleADKRealtimeRunner()._connect_config(self._agent(self.get_weather, _Toolset()).agent)

        assert [d.name for d in config.tools[0].function_declarations] == ["get_weather"]
        assert "is a toolset" in caplog.text

    @pytest.mark.asyncio
    async def test_the_tool_result_is_wrapped_as_adk_wraps_it(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        sent = []

        class _Connection:
            async def send_tool_response(self, function_responses):
                sent.append(function_responses)

        async def callback(event_type, data):
            pass

        runner = GoogleADKRealtimeRunner()
        runner._connection = _Connection()
        runner._callback = callback
        await runner._handle_message(_live_tool_call("call-1", "get_weather", location="Paris"))

        await runner.send_tool_result("call-1", "sunny")

        [[response]] = sent
        assert response.name == "get_weather"
        assert response.response == {"result": "sunny"}

    @pytest.mark.asyncio
    async def test_the_results_of_one_tool_call_message_go_back_together(self):
        """As ADK answers a model's parallel calls: once every call has its result, in call order."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        sent = []

        class _Connection:
            async def send_tool_response(self, function_responses):
                sent.append(function_responses)

        async def callback(event_type, data):
            pass

        runner = GoogleADKRealtimeRunner()
        runner._connection = _Connection()
        runner._callback = callback
        message = _live_tool_call("c1", "get_weather", location="Paris")
        message.tool_call.function_calls.append(types.SimpleNamespace(id="c2", name="get_weather", args={"location": "Rome"}))
        await runner._handle_message(message)

        await runner.send_tool_result("c2", "rainy")
        assert sent == []
        await runner.send_tool_result("c1", "sunny")

        [responses] = sent
        assert [(response.id, response.response) for response in responses] == [("c1", {"result": "sunny"}), ("c2", {"result": "rainy"})]


class TestADKConnectConfig:
    """The Live session config carries only what the ADK agent declares."""

    @staticmethod
    def _agent(**kwargs):
        from google.adk.agents import Agent as GoogleAgent

        return types.SimpleNamespace(name="general", agent=GoogleAgent(name="general", model="gemini-live", **kwargs))

    def test_string_instruction_is_the_system_instruction(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(instruction="Be brief.").agent)

        assert config.system_instruction.parts[0].text == "Be brief."

    def test_description_is_not_used_as_an_instruction(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(description="Routes billing questions.").agent)

        assert config.system_instruction is None

    def test_turn_detection_and_thinking_are_left_to_the_live_api(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(instruction="x").agent)

        assert config.realtime_input_config is None
        assert config.thinking_config is None

    def test_a_callable_instruction_is_rejected_clearly(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        with pytest.raises(ValueError, match="instruction as a string"):
            GoogleADKRealtimeRunner()._connect_config(self._agent(instruction=lambda ctx: "dynamic").agent)


class _FakeLiveSession:
    """A Gemini Live session replaying scripted turns: each receive() yields one turn's messages, and
    waits once they are spent, as an open socket does. A callable in the script is a wait: the next
    turn comes once it returns True for the session, as a model answers only after its tool calls are."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.client_content = []
        self.realtime_text = []
        self.tool_responses = []
        self.closed = False
        self._answered = asyncio.Event()

    async def receive(self):
        while self.turns and callable(self.turns[0]):
            ready = self.turns.pop(0)
            while not ready(self):
                self._answered.clear()
                await self._answered.wait()
        if not self.turns:
            await asyncio.Event().wait()
        for message in self.turns.pop(0):
            yield message

    async def send_client_content(self, turns, turn_complete):
        self.client_content.append((turns, turn_complete))

    async def send_realtime_input(self, **kwargs):
        if "text" in kwargs:
            self.realtime_text.append(kwargs["text"])

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(function_responses)
        self._answered.set()


class _FakeLiveClient:
    """Stands in for ``genai.Client``: each live connect opens a session with the next script."""

    def __init__(self, *scripts, fail_on=None):
        self.scripts = list(scripts)
        self.sessions = []
        self.configs = []
        self.fail_on = fail_on
        self.aio = types.SimpleNamespace(live=types.SimpleNamespace(connect=self._connect), aclose=self._aclose)

    def _connect(self, model, config):
        client = self
        session = _FakeLiveSession(self.scripts.pop(0) if self.scripts else [])

        class _ConnectManager:
            async def __aenter__(self):
                if client.fail_on == len(client.configs) + 1:
                    raise ConnectionError("Live connect refused")
                client.sessions.append(session)
                client.configs.append((model, config))
                return session

            async def __aexit__(self, *exc):
                session.closed = True

        return _ConnectManager()

    async def _aclose(self):
        pass


def _live_message(**server_content):
    return types.SimpleNamespace(server_content=types.SimpleNamespace(**server_content), tool_call=None)


def _live_transcript(attribute, text):
    return _live_message(**{attribute: types.SimpleNamespace(text=text)})


def _live_tool_call(call_id, name, **args):
    return types.SimpleNamespace(
        server_content=None, tool_call=types.SimpleNamespace(function_calls=[types.SimpleNamespace(id=call_id, name=name, args=args)])
    )


class TestADKRealtimeTransfers:
    """Native transfers follow ADK's rules: ADK's own transfer_to_agent runs like any tool, and the
    conversation moves to a socket configured for the target, seeded with what was said."""

    MODEL = "gemini-3.1-flash-live-preview"

    @classmethod
    def _graph(cls, supervisor_tools=(), **billing_options):
        from google.adk.agents import Agent as GoogleAgent

        billing = GoogleAgent(
            **{
                "name": "billing",
                "model": cls.MODEL,
                "description": "Invoices and charges.",
                "instruction": "Answer billing questions.",
                **billing_options,
            }
        )
        tech = GoogleAgent(name="tech_support", model=cls.MODEL, description="Connection problems.", instruction="Fix connections.")
        supervisor = GoogleAgent(
            name="supervisor",
            model=cls.MODEL,
            description="Routes callers.",
            instruction="Route the caller.",
            sub_agents=[billing, tech],
            tools=list(supervisor_tools),
        )
        return supervisor, billing, tech

    @staticmethod
    async def _runner(active):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        runner = GoogleADKRealtimeRunner()
        runner._active = active
        await runner._open_tool_session("s1")
        return runner

    @staticmethod
    def _context():
        return ToolContext(Runtime(InMemorySessionStore()), _Agent(), Session("s1"), [])

    @staticmethod
    def _declared(config):
        return [declaration.name for declaration in config.tools[0].function_declarations]

    def test_an_agent_with_sub_agents_gets_adks_transfer_tool_and_instructions(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        supervisor, _, _ = self._graph()

        config = GoogleADKRealtimeRunner()._connect_config(supervisor)

        assert self._declared(config) == ["transfer_to_agent"]
        instruction = config.system_instruction.parts[0].text
        assert instruction.startswith("Route the caller.")
        assert "`billing`, `tech_support`" in instruction

    def test_the_team_is_every_agent_reachable_through_transfers(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        supervisor, _, _ = self._graph()

        team = GoogleADKRealtimeRunner().team(types.SimpleNamespace(name="supervisor", agent=supervisor))

        assert team == ["supervisor", "billing", "tech_support"]

    def test_a_sub_agent_transfers_to_its_parent_and_peers_unless_disallowed(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        supervisor, billing, tech = self._graph()
        assert GoogleADKRealtimeRunner._transfer_targets(billing) == [supervisor, tech]
        assert "transfer to your parent agent supervisor" in GoogleADKRealtimeRunner()._connect_config(billing).system_instruction.parts[0].text

        _, closed_billing, _ = self._graph(disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
        config = GoogleADKRealtimeRunner()._connect_config(closed_billing)
        assert GoogleADKRealtimeRunner._transfer_targets(closed_billing) == []
        assert config.tools is None
        assert config.system_instruction.parts[0].text == "Answer billing questions."

    def test_a_specialist_without_a_model_uses_its_parents(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        _, billing, _ = self._graph()
        billing.model = ""

        assert GoogleADKRealtimeRunner._live_model(billing) == self.MODEL

    def test_each_agent_speaks_with_its_own_voice(self):
        from google.genai import types as genai_types

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        voice = genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name="Kore"))
        )
        supervisor, billing, _ = self._graph(generate_content_config=genai_types.GenerateContentConfig(speech_config=voice))

        assert GoogleADKRealtimeRunner()._connect_config(billing).speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
        assert GoogleADKRealtimeRunner()._connect_config(supervisor).speech_config is None

    def test_a_workflow_agent_cannot_be_transferred_to(self):
        from google.adk.agents import Agent as GoogleAgent
        from google.adk.agents import SequentialAgent

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        step = GoogleAgent(name="step", model=self.MODEL, instruction="x")
        supervisor = GoogleAgent(
            name="supervisor", model=self.MODEL, instruction="x", sub_agents=[SequentialAgent(name="pipeline", sub_agents=[step])]
        )

        with pytest.raises(ValueError, match="LLM agents only"):
            GoogleADKRealtimeRunner()._validate_transfers(supervisor)

    def test_a_specialist_with_an_instruction_provider_fails_at_connect(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        supervisor, _, _ = self._graph(instruction=lambda ctx: "dynamic")

        with pytest.raises(ValueError, match="instruction as a string"):
            GoogleADKRealtimeRunner()._validate_transfers(supervisor)

    @pytest.mark.asyncio
    async def test_adks_transfer_tool_asks_for_a_transfer(self):
        supervisor, billing, _ = self._graph()
        runner = await self._runner(supervisor)

        result = await runner.execute_tool("transfer_to_agent", '{"agent_name": "billing"}', self._context(), "c1")

        assert result == ""
        assert runner._transfers["c1"] is billing

    @pytest.mark.asyncio
    async def test_a_transfer_to_an_unknown_agent_is_refused(self):
        supervisor, _, _ = self._graph()
        runner = await self._runner(supervisor)

        result = await runner.execute_tool("transfer_to_agent", '{"agent_name": "sales"}', self._context(), "c1")

        assert result == "Error: there is no agent named sales to transfer to"
        assert runner._transfers == {}

    @pytest.mark.asyncio
    async def test_any_tool_that_sets_the_transfer_action_transfers(self):
        from google.adk.tools import ToolContext as ADKToolContext

        def escalate(tool_context: ADKToolContext) -> str:
            """Escalate to billing."""
            tool_context.actions.transfer_to_agent = "billing"
            return "escalated"

        supervisor, billing, _ = self._graph()
        supervisor.tools = [escalate]
        runner = await self._runner(supervisor)

        assert await runner.execute_tool("escalate", "{}", self._context(), "c1") == "escalated"
        assert runner._transfers["c1"] is billing

    async def _converse(self, monkeypatch, client, supervisor_tools=()):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        monkeypatch.setattr("google.genai.Client", lambda *a, **k: client)

        supervisor, _, _ = self._graph(supervisor_tools=supervisor_tools)
        agent = _Agent(name="supervisor", realtime_runner_cls=GoogleADKRealtimeRunner)
        agent.agent = supervisor
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())
        await conn.connect()
        return conn, transport

    @pytest.mark.asyncio
    async def test_a_conversation_moves_to_a_specialist_and_back(self, monkeypatch):
        client = _FakeLiveClient(
            [[_live_transcript("input_transcription", "My bill is too high."), _live_tool_call("c1", "transfer_to_agent", agent_name="billing")]],
            [
                [
                    _live_message(
                        output_transcription=types.SimpleNamespace(text="Billing here."),
                        model_turn=types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b"\x00\x00"))]),
                    ),
                    _live_message(turn_complete=True),
                ],
                [
                    _live_transcript("input_transcription", "And my internet is down."),
                    _live_tool_call("c2", "transfer_to_agent", agent_name="supervisor"),
                ],
            ],
        )
        conn, transport = await self._converse(monkeypatch, client)
        for _ in range(100):
            if len(client.sessions) == 3:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
        first, billing, last = client.sessions
        assert first.closed and billing.closed and not last.closed
        await conn.close()

        # Each socket is configured for its agent; the transferred-to ones are seeded and told so.
        instructions = [config.system_instruction.parts[0].text.split("\n")[0] for _, config in client.configs]
        assert instructions == ["Route the caller.", "Answer billing questions.", "Route the caller."]
        assert client.configs[0][1].history_config is None
        assert client.configs[1][1].history_config.initial_history_in_client_content is True

        [(seeded, turn_complete)] = billing.client_content
        assert turn_complete is True
        assert [content.role for content in seeded] == ["user", "model", "user"]
        assert seeded[0].parts[0].text == "My bill is too high."
        assert seeded[1].parts[0].function_call.args == {"agent_name": "billing"}
        assert seeded[2].parts[0].function_response.name == "transfer_to_agent"
        # Gemini 3.x waits for fresh input after replayed history; the placeholder ADK sends prompts it.
        assert billing.realtime_text == ["."]

        [(reseeded, _)] = last.client_content
        assert [part.text for content in reseeded for part in content.parts if part.text] == [
            "My bill is too high.",
            "Billing here.",
            "And my internet is down.",
        ]

        kinds = _kinds(_drain_output(transport))
        assert kinds == ["agent_changed", "done", "agent_changed", "text_delta", "audio_delta", "done", "done", "agent_changed"]

    @pytest.mark.asyncio
    async def _seeded_after_first_transfer(self, monkeypatch, client, **options):
        conn, _ = await self._converse(monkeypatch, client, **options)
        for _ in range(100):
            if len(client.sessions) >= 2 and client.sessions[1].client_content:
                break
            await asyncio.sleep(0.02)
        await conn.close()
        [(seeded, _)] = client.sessions[1].client_content
        return seeded

    @pytest.mark.asyncio
    async def test_a_transfer_keeps_the_other_results_of_its_turn(self, monkeypatch):
        """ADK answers a turn's parallel calls together before it transfers, so the new agent sees them all."""

        def lookup_account(account_id: str) -> str:
            """Look up a caller's account."""
            return f"{account_id}: fibre 500, paid up"

        message = _live_tool_call("c1", "lookup_account", account_id="A-1042")
        message.tool_call.function_calls.append(types.SimpleNamespace(id="c2", name="transfer_to_agent", args={"agent_name": "billing"}))
        client = _FakeLiveClient([[message]])

        seeded = await self._seeded_after_first_transfer(monkeypatch, client, supervisor_tools=[lookup_account])

        calls, responses = seeded[-2], seeded[-1]
        assert [(part.function_call.id, part.function_call.name) for part in calls.parts] == [("c1", "lookup_account"), ("c2", "transfer_to_agent")]
        assert [part.function_response.response for part in responses.parts] == [{"result": "A-1042: fibre 500, paid up"}, {"result": ""}]
        assert len(client.sessions) == 2

    @pytest.mark.asyncio
    async def test_a_later_transfer_replays_the_earlier_tool_calls_too(self, monkeypatch):
        """The history keeps every tool call with its result, as ADK's session does, in the order it
        happened: not only what was said about them."""

        def lookup_account(account_id: str) -> str:
            """Look up a caller's account."""
            return f"{account_id}: fibre 500, paid up"

        client = _FakeLiveClient(
            [
                [
                    _live_transcript("input_transcription", "My account is A-1042."),
                    _live_transcript("output_transcription", "Let me check."),
                    _live_tool_call("c1", "lookup_account", account_id="A-1042"),
                ],
                lambda session: session.tool_responses,
                [_live_transcript("output_transcription", "You are on fibre 500."), _live_message(turn_complete=True)],
                [_live_transcript("input_transcription", "Why is my bill higher?"), _live_tool_call("c2", "transfer_to_agent", agent_name="billing")],
            ]
        )

        seeded = await self._seeded_after_first_transfer(monkeypatch, client, supervisor_tools=[lookup_account])

        def describe(content):
            part = content.parts[0]
            if part.text:
                return part.text
            if part.function_call:
                return f"call {part.function_call.name}"
            return f"result {part.function_response.name}: {part.function_response.response['result']}"

        assert [(content.role, describe(content)) for content in seeded] == [
            ("user", "My account is A-1042."),
            ("model", "Let me check."),
            ("model", "call lookup_account"),
            ("user", "result lookup_account: A-1042: fibre 500, paid up"),
            ("model", "You are on fibre 500."),
            ("user", "Why is my bill higher?"),
            ("model", "call transfer_to_agent"),
            ("user", "result transfer_to_agent: "),
        ]

    @pytest.mark.asyncio
    async def test_only_the_first_transfer_of_a_turn_is_performed(self, monkeypatch):
        message = _live_tool_call("c1", "transfer_to_agent", agent_name="billing")
        message.tool_call.function_calls.append(types.SimpleNamespace(id="c2", name="transfer_to_agent", args={"agent_name": "tech_support"}))
        client = _FakeLiveClient([[message]])

        seeded = await self._seeded_after_first_transfer(monkeypatch, client)

        assert client.configs[1][1].system_instruction.parts[0].text.startswith("Answer billing questions.")
        assert [part.function_response.response["result"] for part in seeded[-1].parts] == [
            "",
            "Error: only one handoff is performed per turn; this one, to tech_support, was not",
        ]

    @pytest.mark.asyncio
    async def test_a_transfer_that_cannot_connect_fails_the_connection(self, monkeypatch, caplog):
        client = _FakeLiveClient([[_live_tool_call("c1", "transfer_to_agent", agent_name="billing")]], fail_on=2)
        with caplog.at_level("ERROR"):
            conn, transport = await self._converse(monkeypatch, client)
            for _ in range(100):
                if conn.closed:
                    break
                await asyncio.sleep(0.02)

        assert conn.closed is True
        assert client.sessions[0].closed
        assert conn.adapter._cm is None
        body = json.loads(_drain_output(transport)[-1].body)
        assert "transfer to 'billing' failed" in body["error"]
        await conn.close()


class TestRealtimeRunnerCleanup:
    """Both framework runners release what they opened the same way."""

    @staticmethod
    def _runners():
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        return [OpenAIRealtimeRunner, GoogleADKRealtimeRunner]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1], ids=["openai", "adk"])
    async def test_disconnect_waits_for_the_listener_to_end(self, index):
        runner = self._runners()[index]()
        listener = asyncio.create_task(asyncio.Event().wait())
        runner._listen_task = listener

        await runner.disconnect()

        assert listener.done()
        assert runner._listen_task is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1], ids=["openai", "adk"])
    async def test_stopping_the_listener_closes_the_sockets_event_stream(self, index):
        """Regression: stopped while handling an event, the listener left the SDK's event generator
        half-run for the loop's finalizer to close from another task, which raced the loop's shutdown
        ("aclose(): asynchronous generator is already running"). The listener must close it itself."""
        closed_by = []

        class _Socket:
            async def _events(self):
                try:
                    yield types.SimpleNamespace(type="unhandled", server_content=None, tool_call=None)
                    await asyncio.Event().wait()
                finally:
                    closed_by.append(asyncio.current_task())

            def __aiter__(self):
                return self._events()

            def receive(self):
                return self._events()

        runner = self._runners()[index]()
        runner._connection = _Socket()
        handling = asyncio.Event()

        async def handle(message):
            handling.set()
            await asyncio.Event().wait()

        runner._handle_message = handle
        listener = asyncio.create_task(runner._listen())
        runner._listen_task = listener
        await asyncio.wait_for(handling.wait(), timeout=1)

        await runner.disconnect()
        for _ in range(3):  # let a finalizer-scheduled close run, were the stream left to one
            await asyncio.sleep(0)

        assert closed_by == [listener]

    @pytest.mark.asyncio
    async def test_a_socket_that_fails_to_open_closes_everything_it_opened(self, monkeypatch):
        from agents import Agent as SDKAgent

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        closed = []

        class _RefusedSocket:
            async def __aenter__(self):
                raise ConnectionError("socket refused")

            async def __aexit__(self, *exc):
                closed.append("socket")

        class _OpenAIClient:
            realtime = types.SimpleNamespace(connect=lambda model: _RefusedSocket())

            async def close(self):
                closed.append("openai client")

        async def _aclose():
            closed.append("genai client")

        genai_client = types.SimpleNamespace(
            aio=types.SimpleNamespace(live=types.SimpleNamespace(connect=lambda model, config: _RefusedSocket()), aclose=_aclose)
        )
        monkeypatch.setattr("openai.AsyncOpenAI", lambda *a, **k: _OpenAIClient())
        monkeypatch.setattr("google.genai.Client", lambda *a, **k: genai_client)

        async def callback(event_type, data):
            pass

        openai_agent = types.SimpleNamespace(name="general", agent=SDKAgent(name="general", model="gpt-realtime"))
        adk_agent = TestADKRealtimeTransfers._graph()[0]
        for runner, agent in (
            (OpenAIRealtimeRunner(), openai_agent),
            (GoogleADKRealtimeRunner(), types.SimpleNamespace(name="supervisor", agent=adk_agent)),
        ):
            with pytest.raises(ConnectionError):
                await runner.connect(Session("s1"), agent, callback)
            assert runner._cm is None

        # Each client is closed; a socket that never opened is not.
        assert closed == ["openai client", "genai client"]


class TestRealtimeFailureHandling:
    """A dead model socket must be surfaced to the edge and evicted, not written to forever."""

    @pytest.mark.asyncio
    async def test_error_event_marks_closed_and_emits_terminal_error_chunk(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await conn.handle_framework_event("error", {"message": "socket boom"})

        assert conn.closed is True
        # The starting agent may or may not have been announced before the failure; the error is last.
        body = json.loads(_drain_output(transport)[-1].body)
        assert body["error"] == "socket boom"
        assert body["done"] is True

    def test_get_connection_evicts_a_closed_connection(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            runtime = Runtime(InMemorySessionStore())
            agent = _Agent()
            conn = pool.get_or_create("s1", agent, runtime, Session("s1"))
            conn.closed = True

            assert pool.get_connection("s1") is None
            # The next chunk reconnects rather than reusing the dead socket.
            fresh = pool.get_or_create("s1", agent, runtime, Session("s1"))
            assert fresh is not conn
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(timeout=5)


class TestLiveKitGatewayErrorChunk:
    @pytest.mark.asyncio
    async def test_error_chunk_is_surfaced_and_clears_partial_transcript(self):
        from agentkernel.integration.livekit.adapter import LiveKitEdgeGateway

        gateway = object.__new__(LiveKitEdgeGateway)
        gateway._transcript = ["half a sentence"]
        gateway._interrupted = False
        gateway.audio_source = None
        gateway._loop = None
        gateway.room = None

        delivered = []

        async def fake_deliver_error(message, reply_context):
            delivered.append(message)

        gateway.deliver_error = fake_deliver_error

        await gateway.deliver_chunk(StreamChunk(error="model failed", done=True), {})
        assert delivered == ["model failed"]
        assert gateway._transcript == []


class TestRealtimePermanentFailure:
    def test_permanent_failure_reaches_the_live_edge_as_an_error_chunk(self, monkeypatch):
        """End to end: an input that exhausts its retries must be delivered by the registered edge's
        ``deliver_chunk`` error path, not routed to a webhook outbound adapter (which a stateful
        edge has none of), so the room is told instead of left silent."""
        from unittest.mock import MagicMock

        from agentkernel.integration.adapter.registry import StatefulEdgeRegistry
        from agentkernel.pipeline.agent_runner import RealtimeAgentRunner
        from agentkernel.pipeline.envelope import QueueMessage
        from agentkernel.pipeline.response_handler import ResponseHandler

        class _Input:
            max_receive_count = 3

        class _Queues:
            input = _Input()

        class _Cfg:
            class execution:
                mode = ExecutionMode.REALTIME
                queues = _Queues()

                class realtime:
                    playback_lead_ms = 50

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

        class _Edge:
            ERROR_MESSAGE = "sorry"

            def __init__(self):
                self.chunks = []

            async def deliver_chunk(self, chunk, reply_context):
                self.chunks.append((chunk, reply_context))

        edge = _Edge()
        monkeypatch.setattr(StatefulEdgeRegistry, "get", classmethod(lambda cls, session_id: edge if session_id == "s1" else None))

        transport = InMemoryTransport()
        runner = RealtimeAgentRunner(transport=transport, chat_service=MagicMock())
        message = QueueMessage(
            body="{}", attributes={"request_id": "r0", "integration": "livekit", "reply_session_id": "s1"}, group_id="s1", dedup_id="d0"
        )

        runner.on_permanent_failure(message)

        [out] = transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)
        assert out.attributes[ATTR_REALTIME] == "true"
        assert out.attributes[ATTR_INTEGRATION] == "livekit"
        assert out.group_id == "s1"

        ResponseHandler(transport=transport).process(out)

        [(chunk, reply_context)] = edge.chunks
        assert chunk.error == "Failed to process message after 3 retries"
        assert chunk.done is True
        assert reply_context == {"session_id": "s1"}


class TestResponseHandlerRealtimeRouting:
    """Realtime output goes to the live edge registered in this process, never to IntegrationDelivery's
    webhook adapters, which a stateful edge has none of."""

    class _Edge:
        ERROR_MESSAGE = "sorry"

        def __init__(self):
            self.errors = []

        async def deliver_error(self, message, reply_context):
            self.errors.append((message, reply_context))

    @staticmethod
    def _message():
        from agentkernel.pipeline.envelope import QueueMessage

        body = json.dumps(StreamChunk(done=True).model_dump(exclude_none=True))
        attributes = {"request_id": "r1", ATTR_INTEGRATION: "livekit", ATTR_REALTIME: "true", "reply_session_id": "s1"}
        return QueueMessage(body=body, attributes=attributes, group_id="s1", dedup_id="d1")

    def test_a_chunk_for_an_edge_that_is_gone_raises_for_retry(self, monkeypatch):
        from agentkernel.integration.adapter.registry import StatefulEdgeRegistry
        from agentkernel.pipeline.response_handler import ResponseHandler

        monkeypatch.setattr(StatefulEdgeRegistry, "get", classmethod(lambda cls, session_id: None))
        handler = ResponseHandler(transport=InMemoryTransport())
        handler._integration_delivery = None  # the webhook path must not be reached

        with pytest.raises(ValueError, match="No active realtime edge"):
            handler.process(self._message())

    def test_a_permanent_failure_tells_the_live_edge(self, monkeypatch):
        from agentkernel.integration.adapter.registry import StatefulEdgeRegistry
        from agentkernel.pipeline.response_handler import ResponseHandler

        class _Cfg:
            class execution:
                mode = ExecutionMode.REALTIME

                class queues:
                    class output:
                        max_receive_count = 3

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        edge = self._Edge()
        monkeypatch.setattr(StatefulEdgeRegistry, "get", classmethod(lambda cls, session_id: edge if session_id == "s1" else None))
        handler = ResponseHandler(transport=InMemoryTransport())
        handler._integration_delivery = None  # the webhook path must not be reached

        handler.on_permanent_failure(self._message())

        assert edge.errors == [("sorry", {"session_id": "s1"})]


class TestBrokerRealtimeUserGate:
    def test_realtime_chunk_without_user_id_is_not_rejected_on_a_broker(self, monkeypatch):
        """Realtime delivers through the integration adapter, not WebSocket, so the broker
        user_id requirement that guards the STREAM path must not apply to it."""
        from unittest.mock import MagicMock

        from agentkernel.pipeline.agent_runner import RealtimeAgentRunner
        from agentkernel.pipeline.envelope import QueueMessage

        class _Cfg:
            class execution:
                mode = ExecutionMode.REALTIME
                queues = None

                class realtime:
                    playback_lead_ms = 50

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda *a, **k: "kafka"))

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        handler = types.SimpleNamespace(service=types.SimpleNamespace(agent=_Agent(), runtime=Runtime(InMemorySessionStore()), session=Session("s1")))
        chat_service = MagicMock()
        chat_service.prepare_agent_handler.return_value = handler
        chat_service.process_chat_request.return_value = (200, {})

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            runner = RealtimeAgentRunner(transport=transport, chat_service=chat_service)
            body = json.dumps({"prompt": "", "session_id": "s1", "requests": [{"type": "text", "prompt": "hi"}]})
            # No user_id: on a broker transport this used to raise for realtime and drop every chunk.
            runner.process(QueueMessage(body=body, attributes={"request_id": "r0", "integration": "livekit"}, group_id="s1", dedup_id="d0"))
            assert chat_service.prepare_agent_handler.call_count == 1
        finally:
            ThreadRunner.shutdown_event.set()
            thread.join(timeout=5)
