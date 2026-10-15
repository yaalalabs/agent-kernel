import asyncio
import base64
import json
import logging
import re
import threading
import time
import types

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.event import TextDelta
from agentkernel.core.model import AgentReplyText, ExecutionMode, StreamChunk
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.tool import ToolContext
from agentkernel.pipeline import realtime_pool
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


class TestRealtimePoolSweep:
    """The pool's loop releases connections nobody will send to again, and reports when it was blocked."""

    @staticmethod
    def _start(monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))
        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        assert pool._loop_ready.wait(timeout=5)
        return pool, thread

    @staticmethod
    def _until(condition, seconds=3.0):
        deadline = time.monotonic() + seconds
        while not condition():
            assert time.monotonic() < deadline, "timed out"
            time.sleep(0.02)

    def test_a_failed_connection_is_released_without_further_input(self, monkeypatch):
        """Before, a failed connection was released only by its session's next input: a caller who had left
        never sent one, and the adapter stayed connected until the process stopped."""
        monkeypatch.setattr(realtime_pool, "_SWEEP_SECONDS", 0.05)
        pool, thread = self._start(monkeypatch)
        agent = _Agent(realtime_runner_cls=TestRealtimePoolShutdown._CountingAdapter)
        conn = pool.get_or_create("s1", agent, Runtime(InMemorySessionStore()), Session("s1"))

        asyncio.run_coroutine_threadsafe(conn.handle_framework_event("error", {"message": "socket closed"}), pool._loop).result(timeout=5)
        self._until(lambda: "s1" not in pool._connections and conn.adapter.disconnects == 1)

        ThreadRunner.shutdown_event.set()
        thread.join(timeout=5)

    def test_the_sweep_closes_the_failed_connection_it_found_not_its_replacement(self):
        """The sweep let go of its lock between finding a failed connection and removing it; a consumer that replaced
        the connection meanwhile had its replacement removed and closed."""
        pool = RealtimeConnectionPool()
        failed = types.SimpleNamespace(closed=True, last_activity_at=time.time())
        replacement = types.SimpleNamespace(closed=False, last_activity_at=time.time())
        pool._connections["s1"] = failed

        class ConsumerReplacesItWhenTheLockIsFree:
            replaced = False

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                if not self.replaced:
                    self.replaced = True
                    pool._connections["s1"] = replacement

        pool._conn_lock = ConsumerReplacesItWhenTheLockIsFree()
        evicted = pool._evict_stale(time.time())

        assert [(session_id, conn) for session_id, conn, _ in evicted] == [("s1", failed)]
        assert pool._connections["s1"] is replacement

    def test_a_blocked_loop_is_reported(self, monkeypatch, caplog):
        monkeypatch.setattr(realtime_pool, "_LOOP_LAG_WARNING_SECONDS", 0.1)
        pool, thread = self._start(monkeypatch)

        with caplog.at_level(logging.WARNING, logger="ak.pipeline.realtime_pool"):
            pool._loop.call_soon_threadsafe(time.sleep, 0.4)
            self._until(lambda: "The realtime loop was blocked" in caplog.text)

        ThreadRunner.shutdown_event.set()
        thread.join(timeout=5)


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


class TestRealtimeTurnState:
    """Read-only turn state lets code that talks into a call tell a quiet call from a busy one."""

    class _BlockingAdapter(_Adapter):
        """A tool that runs until the test releases it, or raises when told to."""

        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.fail = False

        async def execute_tool(self, name, arguments, context, call_id):
            await self.release.wait()
            if self.fail:
                raise RuntimeError("tool broke")
            return "done"

    @pytest.fixture(autouse=True)
    def _transport(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))

    @pytest.mark.asyncio
    async def test_a_new_connection_is_quiet(self):
        conn = _connection(loop=asyncio.get_running_loop())

        assert conn.is_responding is False
        assert conn.last_model_output_at is None
        assert conn.last_tool_result_at is None
        assert conn.last_model_generated_at is None
        assert conn.last_agent_change_at is None
        assert conn.last_caller_speech_at is None
        assert conn.last_edge_text_at is None

    @pytest.mark.asyncio
    async def test_queued_output_is_a_response_until_it_reaches_the_edge(self):
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await asyncio.sleep(0.1)
        assert conn.is_responding is False

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("done", {"status": "completed"})
        assert conn.is_responding is True

        await asyncio.sleep(0.2)
        conn._pacing_task.cancel()
        assert conn.is_responding is False
        assert conn.last_model_output_at is not None

    @pytest.mark.asyncio
    async def test_control_events_are_not_model_output(self):
        """An interrupt is the caller's doing, so it must not read as the model answering them."""
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await conn.handle_framework_event("interrupt", {})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.1)
        assert conn.last_model_output_at is None

        await conn.handle_framework_event("transcript_delta", {"delta": "Hi", "message_id": "m1"})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()
        assert conn.last_model_output_at is not None

    @pytest.mark.asyncio
    async def test_a_barge_in_ends_the_response_once_its_kept_events_are_out(self):
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await conn.handle_framework_event("interrupt", {})
        assert conn.is_responding is True

        await conn.connect()
        await asyncio.sleep(0.2)
        conn._pacing_task.cancel()
        assert conn.is_responding is False

    @pytest.mark.asyncio
    async def test_a_pause_mid_answer_is_still_a_response_until_its_done(self):
        """The model's paced audio can run out while it is still answering: only ``done`` ends the response."""
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        await asyncio.sleep(0.2)
        assert conn._audio_queue.qsize() == 0
        assert conn.is_responding is True

        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()
        assert conn.is_responding is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ending", ["interrupt", "speech_started"])
    async def test_the_caller_speaking_ends_an_open_response(self, ending):
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await conn.handle_framework_event("transcript_delta", {"delta": "So the plan", "message_id": "m1"})
        await asyncio.sleep(0.1)
        assert conn.is_responding is True

        await conn.handle_framework_event(ending, {})
        await asyncio.sleep(0.1)
        conn._pacing_task.cancel()
        assert conn.is_responding is False

    @pytest.mark.asyncio
    async def test_a_response_whose_done_never_comes_stops_holding_the_call(self, monkeypatch):
        monkeypatch.setattr(realtime_pool, "_UNFINISHED_RESPONSE_SECONDS", 0.05)
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        await conn.handle_framework_event("transcript_delta", {"delta": "So the plan", "message_id": "m1"})
        await asyncio.sleep(0.15)
        conn._pacing_task.cancel()
        assert conn.is_responding is False

    @pytest.mark.asyncio
    async def test_a_tool_call_is_a_response_until_its_result_is_sent(self):
        conn = _connection(agent=_Agent(realtime_runner_cls=self._BlockingAdapter), loop=asyncio.get_running_loop())

        await conn.handle_framework_event("tool_call", {"call_id": "c1", "name": "lookup", "arguments": "{}"})
        await asyncio.sleep(0.05)
        assert conn.is_responding is True
        assert conn.adapter.tool_results == []

        conn.adapter.release.set()
        await asyncio.sleep(0.05)
        assert conn.adapter.tool_results == [("c1", "done")]
        assert conn.is_responding is False
        # The result is input the model has still to answer, not output: a caller waiting for a quiet
        # moment must not take the gap before the model's reply for silence.
        assert conn.last_tool_result_at is not None
        assert conn.last_model_output_at is None

    @pytest.mark.asyncio
    async def test_a_failing_tool_call_still_ends(self):
        conn = _connection(agent=_Agent(realtime_runner_cls=self._BlockingAdapter), loop=asyncio.get_running_loop())
        conn.adapter.fail = True
        conn.adapter.release.set()

        await conn._execute_tool_and_reply("c1", "lookup", "{}")

        assert conn.adapter.tool_results == [("c1", "Error: tool broke")]
        assert conn.is_responding is False
        assert conn.last_tool_result_at is not None

    @pytest.mark.asyncio
    async def test_the_caller_starting_to_speak_is_timestamped(self):
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        assert conn.last_caller_speech_at is None

        await conn.handle_framework_event("speech_started", {})
        first = conn.last_caller_speech_at
        assert first is not None

        await asyncio.sleep(0.01)
        await conn.handle_framework_event("interrupt", {})
        assert conn.last_caller_speech_at > first

    @pytest.mark.asyncio
    async def test_a_long_answer_keeps_the_caller_heard(self):
        """Live: the caller's turn start was the only timestamp, so a 20 s answer read as silence after 15 s."""
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.handle_framework_event("speech_started", {})
        started = conn.last_caller_speech_at

        await asyncio.sleep(0.01)
        await conn.handle_framework_event("speech_heard", {})

        assert conn.last_caller_speech_at > started
        assert conn.is_caller_speaking is False  # this adapter cannot tell when the caller stops
        assert list(conn._audio_queue._queue) == []

    @pytest.mark.asyncio
    async def test_an_adapter_that_reports_the_end_of_speech_marks_the_caller_speaking_until_then(self):
        class _VADAdapter(_Adapter):
            reports_speech_stopped = True

        conn = _connection(agent=_Agent(realtime_runner_cls=_VADAdapter), loop=asyncio.get_running_loop())

        await conn.handle_framework_event("speech_started", {})
        assert conn.is_caller_speaking is True
        started = conn.last_caller_speech_at

        await asyncio.sleep(0.01)
        await conn.handle_framework_event("speech_stopped", {})
        assert conn.is_caller_speaking is False
        assert conn.last_caller_speech_at > started

        await conn.handle_framework_event("interrupt", {})
        assert conn.is_caller_speaking is True
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        assert conn.is_caller_speaking is False  # the model answering ends it, should a stop never arrive

    @pytest.mark.asyncio
    async def test_what_the_model_generates_is_timestamped_before_it_is_paced_out(self):
        """A handoff's tool call runs while its agent's words are still queued: whether that agent said
        anything is known from when the words were generated, not from when they reached the edge."""
        conn = _connection(loop=asyncio.get_running_loop())

        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "supervisor"})
        changed = conn.last_agent_change_at
        assert changed is not None and conn.last_model_generated_at is None

        await asyncio.sleep(0.01)
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        assert conn.last_model_generated_at > changed  # the new agent has spoken
        assert conn.last_model_output_at is None  # though nothing has been paced out yet

    @pytest.mark.asyncio
    async def test_text_from_the_edge_is_timestamped_and_the_applications_own_is_not(self):
        """Typed chat is the caller's input, which the model owes a reply to; an application's own update is not."""
        conn = _connection(loop=asyncio.get_running_loop())

        conn.send_text("[Team update] J1 finished.")
        await asyncio.sleep(0)
        assert conn.last_edge_text_at is None

        conn.send_text("Here is the link: example.com", from_edge=True)
        await asyncio.sleep(0)
        assert conn.last_edge_text_at is not None
        assert conn.last_caller_speech_at is None  # typed, not spoken
        assert conn.adapter.texts == ["[Team update] J1 finished.", "Here is the link: example.com"]

    def test_turn_state_is_readable_from_another_thread(self):
        loop = asyncio.new_event_loop()
        conn = _connection(loop=loop)
        try:
            loop.run_until_complete(conn.handle_framework_event("audio_delta", {"delta": "QUFB"}))
            seen = {}
            reader = threading.Thread(target=lambda: seen.update(responding=conn.is_responding, speech=conn.last_caller_speech_at))
            reader.start()
            reader.join(timeout=5)
            assert seen == {"responding": True, "speech": None}
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_a_call_whose_socket_is_being_recovered_is_not_ready(self):
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()
        assert conn.is_ready is True

        await conn.handle_framework_event("done", {"status": "reconnecting"})
        assert conn.is_ready is False

        await conn.handle_framework_event("reconnected", {"agent": "general", "seconds": 1, "seeded": False})
        assert conn.is_ready is True
        assert conn.last_reconnect_at is None  # nothing was replayed, so nothing is owed

        await conn.handle_framework_event("done", {"status": "reconnecting"})
        await conn.handle_framework_event("reconnected", {"agent": "general", "seconds": 1, "seeded": True})
        assert conn.last_reconnect_at is not None  # the model owes a reply to the replayed conversation
        conn._pacing_task.cancel()


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

    @pytest.mark.asyncio
    async def test_the_end_of_the_users_speech_is_reported(self):
        """Server VAD signals it, so the pool can tell a long answer from silence."""
        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        adapter = self._adapter()

        await adapter._handle_message(self._event("input_audio_buffer.speech_started"))
        await adapter._handle_message(self._event("input_audio_buffer.speech_stopped"))

        assert adapter.events == ["speech_started", "speech_stopped"]
        assert OpenAIRealtimeRunner.reports_speech_stopped is True


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

    def test_a_statically_disabled_handoff_is_not_part_of_the_team(self):
        """It is never offered to the model, so no participant is opened for it."""
        from agents import Agent as SDKAgent
        from agents import handoff

        from agentkernel.framework.openai.openai import OpenAIRealtimeRunner

        supervisor, billing = self._graph()
        supervisor.handoffs = [billing, handoff(SDKAgent(name="sales"), is_enabled=False)]

        team = OpenAIRealtimeRunner().team(types.SimpleNamespace(name="supervisor", agent=supervisor))

        assert team == ["supervisor", "billing"]

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
    async def test_an_agent_that_cannot_be_activated_keeps_the_call_where_it_was(self):
        """Regression: a failure resolving the new agent escaped the tool task, leaving the call with
        no output and no follow-up response. Now the model is told and the agent stays."""

        def broken(ctx, agent):
            raise RuntimeError("no instructions today")

        supervisor, billing = self._graph()
        billing.instructions = broken
        runner = await self._runner(supervisor)

        await runner._handle_message(self._done(("c1", "transfer_to_billing", "{}")))
        await self._answer(runner)

        assert runner._active is supervisor
        assert self._reported(runner) == [("done", {"status": "completed"})]
        output, follow_up = runner._connection.sent
        assert output["item"]["output"] == "Error: the handoff to billing failed: no instructions today"
        assert follow_up == {"type": "response.create"}
        assert list(runner._handoffs) == ["transfer_to_billing"]

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

    def test_the_calls_run_config_sets_turn_detection_and_transcription_for_every_socket(self):
        from google.adk.agents.run_config import RunConfig
        from google.genai import types as types_genai

        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        detection = types_genai.RealtimeInputConfig(
            automatic_activity_detection=types_genai.AutomaticActivityDetection(
                end_of_speech_sensitivity=types_genai.EndSensitivity.END_SENSITIVITY_HIGH, silence_duration_ms=700
            )
        )
        english = types_genai.AudioTranscriptionConfig(language_codes=["en-US"])
        runner = GoogleADKRealtimeRunner()
        runner._run_config = RunConfig(realtime_input_config=detection, input_audio_transcription=english)

        config = runner._connect_config(self._agent(instruction="x").agent, seeded=True)  # a transfer's socket too

        assert config.realtime_input_config == detection
        assert config.input_audio_transcription.language_codes == ["en-US"]
        assert config.output_audio_transcription is not None  # always on: the runner depends on it

    def test_a_callable_instruction_is_rejected_clearly(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        with pytest.raises(ValueError, match="instruction as a string"):
            GoogleADKRealtimeRunner()._connect_config(self._agent(instruction=lambda ctx: "dynamic").agent)


class _FakeLiveSession:
    """A Gemini Live session replaying scripted turns: each receive() yields one turn's messages, and
    waits once they are spent, as an open socket does. A callable in the script is a wait: the next
    turn comes once it returns True for the session, as a model answers only after its tool calls are.
    A number is a pause in seconds, as a caller listens before answering. An exception is the socket dropping."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.client_content = []
        self.realtime_text = []
        self.realtime_audio = []
        self.tool_responses = []
        self.closed = False
        self._answered = asyncio.Event()

    async def receive(self):
        if self.turns and isinstance(self.turns[0], Exception):
            raise self.turns.pop(0)
        while self.turns and (callable(self.turns[0]) or isinstance(self.turns[0], float)):
            step = self.turns.pop(0)
            if isinstance(step, float):
                await asyncio.sleep(step)
                continue
            while not step(self):
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
        if "audio" in kwargs:
            self.realtime_audio.append(kwargs["audio"].data)

    async def send_tool_response(self, function_responses):
        self.tool_responses.append(function_responses)
        self._answered.set()


class _FakeLiveClient:
    """Stands in for ``genai.Client``: each live connect opens a session with the next script."""

    def __init__(self, *scripts, fail_on=None, fail_from=None):
        self.scripts = list(scripts)
        self.sessions = []
        self.configs = []
        self.fail_on = fail_on
        # Every connect from this one on is refused, as while the network is down.
        self.fail_from = fail_from
        self.attempts = 0
        self.aio = types.SimpleNamespace(live=types.SimpleNamespace(connect=self._connect), aclose=self._aclose)

    def _connect(self, model, config):
        client = self
        session = _FakeLiveSession(self.scripts.pop(0) if self.scripts else [])

        class _ConnectManager:
            async def __aenter__(self):
                client.attempts += 1
                if client.fail_on == len(client.configs) + 1 or (client.fail_from is not None and client.attempts >= client.fail_from):
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


def _seen(turns):
    """What a seeded Gemini socket shows, one line per part: the caller's words as they are, and each agent's
    turn as ADK presents it (``[billing] said: ...``), without ADK's preamble and fence markers."""
    lines = []
    for content in turns:
        for part in content.parts:
            if part.text.startswith("For context:"):
                continue
            lines.append(" ".join(re.sub(r"<<<[A-Z_]+>>>", "", part.text).split()))
    return lines


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

    def test_the_transfer_tool_only_names_the_agents_it_can_reach(self):
        """As ADK 2.x declares it: agent_name is limited to the targets, so the model cannot name another."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        supervisor, _, _ = self._graph()

        [declaration] = GoogleADKRealtimeRunner()._connect_config(supervisor).tools[0].function_declarations

        if declaration.parameters_json_schema:
            enum = declaration.parameters_json_schema["properties"]["agent_name"]["enum"]
        else:
            enum = declaration.parameters.properties["agent_name"].enum
        assert enum == ["billing", "tech_support"]

    def test_an_agent_in_task_mode_gets_no_transfer_instructions(self):
        """As ADK: such an agent is called rather than talked with, so it is not told about transfers."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        _, billing, tech = self._graph()

        assert GoogleADKRealtimeRunner._transfer_instruction(types.SimpleNamespace(mode="task"), [billing, tech]) == ""

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
                # The caller hears billing out before speaking again: words while its audio is
                # still being paced would be a barge-in.
                0.3,
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

        # Every agent turn goes on the user's side, naming who did it, as ADK presents it to a Live socket.
        [(seeded, turn_complete)] = billing.client_content
        assert turn_complete is True
        assert all(content.role == "user" for content in seeded)
        assert _seen(seeded) == [
            "My bill is too high.",
            "[supervisor] called tool `transfer_to_agent` with parameters: {'agent_name': 'billing'}",
            "[supervisor] `transfer_to_agent` tool returned result: {'result': ''}",
        ]
        # Gemini 3.x waits for fresh input after replayed history; the placeholder ADK sends prompts it.
        assert billing.realtime_text == ["."]

        # Back at the supervisor, billing's words are billing's, not the supervisor's own.
        [(reseeded, _)] = last.client_content
        seen = _seen(reseeded)
        assert seen[0] == "My bill is too high."
        assert "[billing] said: Billing here." in seen
        assert "And my internet is down." in seen
        assert seen[-1] == "[billing] `transfer_to_agent` tool returned result: {'result': ''}"

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

        assert _seen(seeded)[-4:] == [
            "[supervisor] called tool `lookup_account` with parameters: {'account_id': 'A-1042'}",
            "[supervisor] called tool `transfer_to_agent` with parameters: {'agent_name': 'billing'}",
            "[supervisor] `lookup_account` tool returned result: {'result': 'A-1042: fibre 500, paid up'}",
            "[supervisor] `transfer_to_agent` tool returned result: {'result': ''}",
        ]
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

        assert _seen(seeded) == [
            "My account is A-1042.",
            "[supervisor] said: Let me check.",
            "[supervisor] called tool `lookup_account` with parameters: {'account_id': 'A-1042'}",
            "[supervisor] `lookup_account` tool returned result: {'result': 'A-1042: fibre 500, paid up'}",
            "[supervisor] said: You are on fibre 500.",
            "Why is my bill higher?",
            "[supervisor] called tool `transfer_to_agent` with parameters: {'agent_name': 'billing'}",
            "[supervisor] `transfer_to_agent` tool returned result: {'result': ''}",
        ]

    @pytest.mark.asyncio
    async def test_only_the_first_transfer_of_a_turn_is_performed(self, monkeypatch):
        message = _live_tool_call("c1", "transfer_to_agent", agent_name="billing")
        message.tool_call.function_calls.append(types.SimpleNamespace(id="c2", name="transfer_to_agent", args={"agent_name": "tech_support"}))
        client = _FakeLiveClient([[message]])

        seeded = await self._seeded_after_first_transfer(monkeypatch, client)

        assert client.configs[1][1].system_instruction.parts[0].text.startswith("Answer billing questions.")
        assert _seen(seeded)[-2:] == [
            "[supervisor] `transfer_to_agent` tool returned result: {'result': ''}",
            "[supervisor] `transfer_to_agent` tool returned result: "
            "{'result': 'Error: only one handoff is performed per turn; this one, to tech_support, was not'}",
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


class TestADKRealtimeRecovery:
    """A socket that drops or stalls is replaced without leaving the agent that had the call; what the caller says
    meanwhile is held for the new socket."""

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "RECONNECT_DELAYS_SECONDS", (0.05, 0.05, 0.05))
        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_CHECK_SECONDS", 0.05)

    @staticmethod
    async def _connect(monkeypatch, client):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr("google.genai.Client", lambda *a, **k: client)
        events = []

        async def callback(event_type, data):
            events.append((event_type, data))

        supervisor, _, _ = TestADKRealtimeTransfers._graph()
        runner = GoogleADKRealtimeRunner()
        await runner.connect(Session("s1"), types.SimpleNamespace(name="supervisor", agent=supervisor), callback)
        return runner, events

    @staticmethod
    async def _until(condition, seconds=3.0):
        for _ in range(int(seconds / 0.02)):
            if condition():
                return
            await asyncio.sleep(0.02)
        raise AssertionError("timed out")

    @staticmethod
    def _spoken_turn():
        return [
            _live_transcript("input_transcription", "My bill is too high."),
            _live_message(output_transcription=types.SimpleNamespace(text="Let me look.")),
            _live_message(turn_complete=True),
        ]

    @pytest.mark.asyncio
    async def test_a_dropped_socket_reconnects_the_same_agent_with_the_conversation_and_a_note(self, monkeypatch):
        client = _FakeLiveClient([self._spoken_turn(), ConnectionError("1006 abnormal closure")], [])
        runner, events = await self._connect(monkeypatch, client)

        await self._until(lambda: ("reconnected", {"agent": "supervisor", "seconds": 0, "seeded": True}) in events)

        assert [kind for kind, _ in events if kind == "error"] == []  # recovered: the pool is never told it failed
        assert len(client.sessions) == 2 and client.sessions[0].closed
        assert client.configs[1][1].system_instruction.parts[0].text.startswith("Route the caller.")  # the same agent
        seeded = _seen(client.sessions[1].client_content[0][0])
        assert seeded[0] == "My bill is too high." and "Let me look." in seeded[1]
        # The caller had finished their turn and said nothing while the line was down: they are not asked to repeat.
        assert "connection dropped" in seeded[-1] and "did not speak meanwhile" in seeded[-1] and "repeat what" not in seeded[-1]
        assert ("done", {"status": "reconnecting"}) in events  # the edge's turn is closed
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_what_the_caller_says_while_reconnecting_reaches_the_new_socket_its_latest_seconds_only(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "RECONNECT_DELAYS_SECONDS", (0.3,))
        monkeypatch.setattr(GoogleADKRealtimeRunner, "HOLD_AUDIO_SECONDS", 0.1)  # 3200 bytes at 16 kHz
        client = _FakeLiveClient([ConnectionError("dropped")], [])
        runner, events = await self._connect(monkeypatch, client)
        await self._until(lambda: runner._connection is None)

        for byte in (b"\x01", b"\x02", b"\x03"):
            await runner.append_audio(base64.b64encode(byte * 1600).decode())  # 50 ms each
        await runner.send_text("[Team update] typed meanwhile")
        await self._until(lambda: len(client.sessions) == 2 and client.sessions[1].realtime_audio)

        assert client.sessions[1].realtime_audio == [b"\x02" * 1600, b"\x03" * 1600]  # the oldest was dropped
        assert _seen([client.sessions[1].client_content[-1][0]]) == ["[Team update] typed meanwhile"]
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_the_caller_is_asked_to_repeat_only_when_they_spoke_while_the_line_was_down(self, monkeypatch):
        """Live: a client asked to repeat said "No, I didn't say anything"."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "RECONNECT_DELAYS_SECONDS", (0.3,))
        client = _FakeLiveClient([ConnectionError("dropped")], [])
        runner, _ = await self._connect(monkeypatch, client)
        await self._until(lambda: runner._connection is None)

        speech = (b"\x00\x40" * 800) + (b"\x00\xc0" * 800)  # loud samples, not the silence an edge also sends
        await runner.append_audio(base64.b64encode(speech).decode())
        await self._until(lambda: len(client.sessions) == 2)

        seeded = _seen(client.sessions[1].client_content[0][0])
        assert "ask them to repeat what they last said" in seeded[-1]
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_socket_that_stops_answering_is_replaced(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.2)
        client = _FakeLiveClient([], [])  # the first socket never says anything again
        runner, events = await self._connect(monkeypatch, client)

        await runner.send_text("Are you there?")  # owed an answer
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert len(client.sessions) == 2
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_text_sent_to_a_silent_socket_does_not_hold_off_its_replacement(self, monkeypatch):
        """Live: an application nudged a silent agent every 15 s; each nudge restarted the 15 s wait, so a socket
        that had stopped answering was replaced only 46 s after it fell silent."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.3)
        client = _FakeLiveClient([], [])  # the first socket never says anything again
        runner, events = await self._connect(monkeypatch, client)

        for _ in range(6):  # a nudge every 0.2 s, more often than the stall wait
            await runner.send_text("[The call has gone quiet; it is your turn]")
            await asyncio.sleep(0.2)
            if any(kind == "reconnected" for kind, _ in events):
                break

        assert any(kind == "reconnected" for kind, _ in events)
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_an_answering_socket_is_not_taken_for_stalled(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.2)
        client = _FakeLiveClient([0.05, self._spoken_turn()])
        runner, events = await self._connect(monkeypatch, client)

        await runner.send_text("Are you there?")
        await asyncio.sleep(0.5)

        assert len(client.sessions) == 1 and not any(kind == "reconnected" for kind, _ in events)
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_socket_lost_again_soon_after_each_reconnect_is_given_up_on(self, monkeypatch, caplog):
        """Live: out of quota, Gemini accepted each reconnect and closed it seconds later; the runner reconnected for
        five minutes, resending the conversation each time, and never gave up."""
        drops = [[ConnectionError("1011 You exceeded your current quota")] for _ in range(10)]
        client = _FakeLiveClient(*drops)
        with caplog.at_level("ERROR", logger="ak.adk.realtime"):
            runner, events = await self._connect(monkeypatch, client)
            await self._until(lambda: any(kind == "error" for kind, _ in events))
            await asyncio.sleep(0.2)

        # The first socket, then one reconnect per quick drop until RECONNECT_ATTEMPTS of them: no more.
        assert len(client.sessions) == 1 + runner.RECONNECT_ATTEMPTS
        [(_, error)] = [event for event in events if event[0] == "error"]
        assert "keeps dropping" in error["message"]
        assert sum(kind == "reconnected" for kind, _ in events) == runner.RECONNECT_ATTEMPTS
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_drop_long_after_a_reconnect_is_a_fresh_one(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "QUICK_DROP_SECONDS", 0.0)  # every drop is "long after"
        drops = [[ConnectionError("dropped")] for _ in range(6)] + [[]]
        client = _FakeLiveClient(*drops)
        runner, events = await self._connect(monkeypatch, client)

        await self._until(lambda: len(client.sessions) == 7)

        assert not any(kind == "error" for kind, _ in events)  # each drop recovered on its own
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_when_every_attempt_fails_the_connection_fails(self, monkeypatch):
        client = _FakeLiveClient([ConnectionError("dropped")], fail_from=2)
        runner, events = await self._connect(monkeypatch, client)

        await self._until(lambda: any(kind == "error" for kind, _ in events))

        assert client.attempts == 1 + runner.RECONNECT_ATTEMPTS
        [(_, error)] = [event for event in events if event[0] == "error"]
        assert "could not reconnect" in error["message"]
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_what_the_caller_says_during_a_transfer_reaches_the_new_agent(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        client = _FakeLiveClient([], [])
        runner, events = await self._connect(monkeypatch, client)
        _, billing, _ = TestADKRealtimeTransfers._graph()
        call = types.SimpleNamespace(id="c1", name="transfer_to_agent", args={"agent_name": "billing"})
        batch = GoogleADKRealtimeRunner._ToolBatch(calls=[call], results={"c1": ""})

        runner._connection = None  # the switch is under way: the old socket no longer takes input
        await runner.append_audio(base64.b64encode(b"\x07" * 320).decode())
        await runner._transfer(batch, billing)

        assert client.sessions[1].realtime_audio == [b"\x07" * 320]
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_the_note_goes_to_the_reconnected_socket_only(self, monkeypatch):
        """Kept in the history, the note was replayed to every later socket as the caller's words."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "QUICK_DROP_SECONDS", 0.0)
        client = _FakeLiveClient([self._spoken_turn(), ConnectionError("dropped")], [ConnectionError("dropped again")], [])
        runner, _ = await self._connect(monkeypatch, client)

        await self._until(lambda: len(client.sessions) == 3)

        third = _seen(client.sessions[2].client_content[0][0])
        assert sum("connection dropped" in line for line in third) == 1
        assert not any("connection dropped" in (part.text or "") for said in runner._history for part in said.content.parts)
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_tool_result_for_a_lost_socket_is_kept_in_the_history(self, monkeypatch):
        client = _FakeLiveClient([[_live_tool_call("c1", "lookup_account", account_id="A-1")], ConnectionError("dropped")], [])
        runner, events = await self._connect(monkeypatch, client)
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        await runner.send_tool_result("c1", "A-1: paid up")

        assert client.sessions[1].tool_responses == []  # the socket that asked is gone
        assert _seen(runner._presented_history())[-2:] == [
            "[supervisor] called tool `lookup_account` with parameters: {'account_id': 'A-1'}",
            "[supervisor] `lookup_account` tool returned result: {'result': 'A-1: paid up'}",
        ]
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_the_callers_own_words_do_not_hide_a_stall(self, monkeypatch):
        """Every message used to end the wait, so a transcription of the caller hid a socket that never answered."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.2)
        client = _FakeLiveClient([0.05, [_live_transcript("input_transcription", "Hello?")]], [])
        runner, events = await self._connect(monkeypatch, client)

        await runner.send_text("Are you there?")
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert len(client.sessions) == 2
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_response_that_stops_part_way_is_a_stall(self, monkeypatch):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "STALL_SECONDS", 0.2)
        audio = _live_message(model_turn=types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b"\x00\x00"))]))
        client = _FakeLiveClient([[audio]], [])  # the answer starts, then nothing, and no turn_complete
        runner, events = await self._connect(monkeypatch, client)

        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert len(client.sessions) == 2
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_handoff_that_finishes_while_the_lost_socket_closes_is_not_performed(self, monkeypatch):
        """A tool that finished while recovery stopped the lost socket's listener still found its call outstanding, so
        the handoff it asked for ran alongside the recovery, both opening sockets."""
        client = _FakeLiveClient([[_live_tool_call("t1", "transfer_to_agent", agent_name="billing")]], [], [])
        runner, events = await self._connect(monkeypatch, client)
        await self._until(lambda: "t1" in runner._batches)
        runner._transfers["t1"] = runner._active.find_agent("billing")  # as running the tool registers it

        stop_listening = runner._stop_listening

        async def tool_finishes_meanwhile():
            await runner.send_tool_result("t1", "Transferring to billing.")
            await stop_listening()

        runner._stop_listening = tool_finishes_meanwhile
        runner._recover_soon("test")
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert not any(kind == "agent_changed" for kind, _ in events)
        assert len(client.sessions) == 2
        assert client.configs[1][1].system_instruction.parts[0].text.startswith("Route the caller.")  # the same agent
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_tool_still_running_when_the_socket_is_lost_is_in_the_new_sockets_seed(self, monkeypatch):
        """The new socket was seeded before the tool finished, so the model did not know the call was made and could
        make it again: a record written twice."""
        client = _FakeLiveClient([[_live_tool_call("c1", "record_story", title="Book online")]], [])
        runner, events = await self._connect(monkeypatch, client)
        await self._until(lambda: "c1" in runner._batches)

        runner._recover_soon("test")
        await asyncio.sleep(0.3)  # the tool is still running
        await runner.send_tool_result("c1", "Recorded story S1.")
        await self._until(lambda: len(client.sessions) == 2)

        assert _seen(client.sessions[1].client_content[0][0])[-3:-1] == [
            "[supervisor] called tool `record_story` with parameters: {'title': 'Book online'}",
            "[supervisor] `record_story` tool returned result: {'result': 'Recorded story S1.'}",
        ]
        assert client.sessions[1].tool_responses == []  # kept in the seed, not answered again
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_tool_that_never_finishes_holds_up_the_reconnect_only_a_moment(self, monkeypatch, caplog):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "LOST_TOOL_WAIT_SECONDS", 0.2)
        client = _FakeLiveClient([[_live_tool_call("c1", "slow_report")]], [])
        runner, events = await self._connect(monkeypatch, client)
        await self._until(lambda: "c1" in runner._batches)

        with caplog.at_level("WARNING", logger="ak.adk.realtime"):
            runner._recover_soon("test")
            await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert "['slow_report'] still run for the lost socket" in caplog.text
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_post_whose_send_fails_reaches_the_next_socket(self, monkeypatch):
        """The pool takes a post out of its outbox before the send: text is kept in the history before it is sent, so
        a socket that fails while it is sent loses nothing; the next socket is seeded with it, and answers it."""
        client = _FakeLiveClient([], [])
        runner, events = await self._connect(monkeypatch, client)

        async def socket_closed(*args, **kwargs):
            raise ConnectionError("1006 abnormal closure")

        client.sessions[0].send_client_content = socket_closed
        with pytest.raises(ConnectionError):
            await runner.send_text("[Team update] J1 finished.")
        runner._recover_soon("socket error: 1006 abnormal closure")  # as the failing socket's listener does
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        turns, turn_complete = client.sessions[1].client_content[0]
        assert "[Team update] J1 finished." in _seen(turns) and turn_complete
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_failed_reconnect_whose_socket_also_fails_to_close_is_retried(self, monkeypatch):
        """The failed attempt's close raising ended the recovery: no next attempt and no error, so the call was left
        with no socket and nothing to replace it."""
        client = _FakeLiveClient([], [])
        runner, events = await self._connect(monkeypatch, client)
        open_socket, close_socket, opens, closes = runner._open_socket, runner._close_socket, [], []

        async def first_attempt_fails(*args, **kwargs):
            opens.append(True)
            if len(opens) == 1:
                raise ConnectionError("seeding failed")
            return await open_socket(*args, **kwargs)

        async def its_close_fails_too():
            closes.append(True)
            if len(closes) == 2:  # the first closes the lost socket, the second the failed attempt's
                raise RuntimeError("close failed")
            await close_socket()

        runner._open_socket, runner._close_socket = first_attempt_fails, its_close_fails_too
        runner._recover_soon("test")
        await self._until(lambda: any(kind == "reconnected" for kind, _ in events))

        assert len(opens) == 2 and not any(kind == "error" for kind, _ in events)
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_audio_held_for_a_new_socket_reaches_it_before_newer_audio(self, monkeypatch):
        """The caller's newer audio went straight to the new socket while the held audio was still being sent: it
        heard old, new, old."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        monkeypatch.setattr(GoogleADKRealtimeRunner, "RECONNECT_DELAYS_SECONDS", (0.3,))
        paused, resume = asyncio.Event(), asyncio.Event()
        send = _FakeLiveSession.send_realtime_input

        async def first_audio_is_slow(session, **kwargs):
            if "audio" in kwargs and not paused.is_set():
                paused.set()
                await resume.wait()
            await send(session, **kwargs)

        monkeypatch.setattr(_FakeLiveSession, "send_realtime_input", first_audio_is_slow)
        client = _FakeLiveClient([ConnectionError("dropped")], [])
        runner, _ = await self._connect(monkeypatch, client)
        await self._until(lambda: runner._connection is None)

        for byte in (b"\x01", b"\x02"):
            await runner.append_audio(base64.b64encode(byte * 320).decode())  # held: no socket
        await self._until(paused.is_set)  # the new socket is being sent the first held chunk
        await runner.append_audio(base64.b64encode(b"\x03" * 320).decode())  # the caller goes on talking
        resume.set()
        await self._until(lambda: len(client.sessions[1].realtime_audio) == 3)

        assert client.sessions[1].realtime_audio == [b"\x01" * 320, b"\x02" * 320, b"\x03" * 320]
        await runner.disconnect()


class TestADKFirstAudioLog:
    """How long the caller waited for an agent to start speaking is logged, measured from the runner's own events."""

    @pytest.mark.asyncio
    async def test_the_wait_after_the_callers_words_and_a_tool_result_is_logged_once_per_turn(self, monkeypatch, caplog):
        audio = _live_message(model_turn=types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b"\x00\x00"))]))
        client = _FakeLiveClient([[_live_transcript("input_transcription", "Book me in.")], 0.1, [audio, audio], [_live_message(turn_complete=True)]])

        with caplog.at_level("INFO", logger="ak.adk.realtime"):
            runner, _ = await TestADKRealtimeRecovery._connect(monkeypatch, client)
            await TestADKRealtimeRecovery._until(lambda: any("started speaking" in r.message for r in caplog.records))
            await asyncio.sleep(0.1)
        await runner.disconnect()

        [line] = [r.message for r in caplog.records if "started speaking" in r.message]
        assert line.startswith("'supervisor' started speaking ") and "s after the caller's last words" in line


class TestADKRealtimeToolCallbacks:
    """A tool call runs between the calling agent's tool callbacks, as on an ADK run, transfers included."""

    MODEL = "gemini-3.1-flash-live-preview"

    @classmethod
    def _graph(cls, supervisor_tools=(), **supervisor_options):
        from google.adk.agents import Agent as GoogleAgent

        billing = GoogleAgent(name="billing", model=cls.MODEL, description="Invoices and charges.", instruction="Answer billing questions.")
        supervisor = GoogleAgent(
            name="supervisor",
            model=cls.MODEL,
            description="Routes callers.",
            instruction="Route the caller.",
            sub_agents=[billing],
            tools=list(supervisor_tools),
            **supervisor_options,
        )
        return supervisor, billing

    @staticmethod
    async def _execute(runner, name, arguments="{}", call_id="c1"):
        return await runner.execute_tool(name, arguments, TestADKRealtimeTransfers._context(), call_id)

    @staticmethod
    def lookup(account_id: str) -> str:
        """Look up a caller's account."""
        return f"{account_id}: paid up"

    @pytest.mark.asyncio
    async def test_a_before_callback_that_answers_stops_a_transfer(self):
        def guard(tool, args, tool_context):
            if tool.name == "transfer_to_agent":
                return {"result": "Too many handoffs; talk to the caller first."}
            return None

        supervisor, _ = self._graph(before_tool_callback=guard)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "transfer_to_agent", '{"agent_name": "billing"}')

        assert "Too many handoffs" in result
        assert runner._transfers == {}

    @pytest.mark.asyncio
    async def test_a_before_callback_returning_none_lets_the_tool_run(self):
        seen = []

        def watch(tool, args, tool_context):
            seen.append((tool.name, args))
            return None

        supervisor, billing = self._graph(before_tool_callback=watch)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        await self._execute(runner, "transfer_to_agent", '{"agent_name": "billing"}')

        assert seen == [("transfer_to_agent", {"agent_name": "billing"})]
        assert runner._transfers["c1"] is billing

    @pytest.mark.asyncio
    async def test_before_callbacks_run_in_order_until_one_answers(self):
        calls = []

        def first(tool, args, tool_context):
            calls.append("first")
            return None

        def second(tool, args, tool_context):
            calls.append("second")
            return {"result": "from second"}

        def third(tool, args, tool_context):
            calls.append("third")
            return {"result": "from third"}

        supervisor, _ = self._graph(supervisor_tools=[self.lookup], before_tool_callback=[first, second, third])
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "lookup", '{"account_id": "A-1"}')

        assert calls == ["first", "second"]
        assert "from second" in result

    @pytest.mark.asyncio
    async def test_a_before_callback_can_ask_for_a_transfer(self):
        def escalate(tool, args, tool_context):
            tool_context.actions.transfer_to_agent = "billing"
            return {"result": "escalated"}

        supervisor, billing = self._graph(supervisor_tools=[self.lookup], before_tool_callback=escalate)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "lookup", '{"account_id": "A-1"}')

        assert "escalated" in result
        assert runner._transfers["c1"] is billing

    @pytest.mark.asyncio
    async def test_an_after_callback_replaces_the_result(self):
        def shout(tool, args, tool_context, tool_response):
            return {"result": tool_response.upper()}

        supervisor, _ = self._graph(supervisor_tools=[self.lookup], after_tool_callback=shout)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "lookup", '{"account_id": "a-1"}')

        assert "A-1: PAID UP" in result

    @pytest.mark.asyncio
    async def test_an_after_callback_returning_none_keeps_the_result(self):
        supervisor, _ = self._graph(supervisor_tools=[self.lookup], after_tool_callback=lambda tool, args, tool_context, tool_response: None)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        assert await self._execute(runner, "lookup", '{"account_id": "A-1"}') == "A-1: paid up"

    @pytest.mark.asyncio
    async def test_an_error_callback_replaces_the_error(self):
        def broken(account_id: str) -> str:
            """Look up a caller's account."""
            raise ValueError("account service down")

        def recover(tool, args, tool_context, error):
            return {"result": f"Could not look it up: {error}"}

        supervisor, _ = self._graph(supervisor_tools=[broken], on_tool_error_callback=recover)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "broken", '{"account_id": "A-1"}')

        assert "Could not look it up: account service down" in result

    @pytest.mark.asyncio
    async def test_without_an_error_callback_the_error_propagates(self):
        def broken(account_id: str) -> str:
            """Look up a caller's account."""
            raise ValueError("account service down")

        supervisor, _ = self._graph(supervisor_tools=[broken], on_tool_error_callback=lambda tool, args, tool_context, error: None)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        with pytest.raises(ValueError, match="account service down"):
            await self._execute(runner, "broken", '{"account_id": "A-1"}')

    @pytest.mark.asyncio
    async def test_async_callbacks_are_awaited(self):
        async def guard(tool, args, tool_context):
            await asyncio.sleep(0)
            return {"result": "refused"}

        async def note(tool, args, tool_context, tool_response):
            await asyncio.sleep(0)
            return None

        supervisor, _ = self._graph(before_tool_callback=guard, after_tool_callback=note)
        runner = await TestADKRealtimeTransfers._runner(supervisor)

        result = await self._execute(runner, "transfer_to_agent", '{"agent_name": "billing"}')

        assert "refused" in result
        assert runner._transfers == {}

    @pytest.mark.asyncio
    async def test_the_callbacks_are_the_calling_agents(self):
        """A call made before a transfer runs as the agent that made it, with that agent's callbacks."""
        callers = []

        supervisor, billing = self._graph(
            before_tool_callback=lambda tool, args, tool_context: callers.append(("supervisor", tool_context.agent_name))
        )
        billing.before_tool_callback = lambda tool, args, tool_context: callers.append(("billing", tool_context.agent_name))
        runner = await TestADKRealtimeTransfers._runner(billing)
        runner._callers["c1"] = supervisor

        await self._execute(runner, "transfer_to_agent", '{"agent_name": "billing"}')

        assert callers == [("supervisor", "supervisor")]


class TestADKRealtimeSpeechStarted:
    """The caller starting a turn while Gemini is silent is reported once, so the pool can timestamp it."""

    @staticmethod
    def _runner():
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        events = []

        async def callback(event_type, data):
            events.append(event_type)

        runner = GoogleADKRealtimeRunner()
        runner._callback = callback
        return runner, events

    @staticmethod
    def _audio():
        return _live_message(model_turn=types.SimpleNamespace(parts=[types.SimpleNamespace(inline_data=types.SimpleNamespace(data=b"\x00\x00"))]))

    @staticmethod
    def _caller(events):
        return [event for event in events if event in ("speech_started", "interrupt")]

    @pytest.mark.asyncio
    async def test_the_callers_words_while_the_model_is_silent_are_reported_once(self):
        runner, events = self._runner()

        await runner._handle_message(_live_transcript("input_transcription", "I need"))
        await runner._handle_message(_live_transcript("input_transcription", " a login page."))

        assert self._caller(events) == ["speech_started"]

    @pytest.mark.asyncio
    async def test_later_words_of_the_same_turn_say_the_caller_is_still_speaking(self):
        runner, events = self._runner()

        await runner._handle_message(_live_transcript("interim_input_transcription", "I need"))
        await runner._handle_message(_live_transcript("interim_input_transcription", "I need a login page"))
        await runner._handle_message(_live_transcript("input_transcription", "I need a login page."))

        assert [e for e in events if e.startswith("speech_")] == ["speech_started", "speech_heard", "speech_heard"]

    @pytest.mark.asyncio
    async def test_words_over_the_model_before_the_barge_in_are_not_speech_heard(self):
        runner, events = self._runner()
        await runner._handle_message(self._audio())

        await runner._handle_message(_live_transcript("interim_input_transcription", "Wait"))

        assert "speech_heard" not in events

    @pytest.mark.asyncio
    async def test_the_callers_words_are_logged_when_the_turn_ends(self, caplog):
        """The edge logs the agent's words; this logs the caller's, so a log reads as both sides of the call."""
        runner, _ = self._runner()

        with caplog.at_level(logging.INFO, logger="ak.adk.realtime"):
            await runner._handle_message(_live_transcript("input_transcription", "I need"))
            await runner._handle_message(_live_transcript("input_transcription", " a login page."))
            await runner._handle_message(_live_message(turn_complete=True))

        assert "Caller said: I need a login page." in caplog.messages

    @pytest.mark.asyncio
    async def test_interim_words_count_too(self):
        runner, events = self._runner()

        await runner._handle_message(_live_transcript("interim_input_transcription", "I ne"))

        assert self._caller(events) == ["speech_started"]

    @pytest.mark.asyncio
    async def test_words_over_the_model_are_a_barge_in_reported_once(self):
        runner, events = self._runner()
        await runner._handle_message(self._audio())

        await runner._handle_message(_live_transcript("interim_input_transcription", "Wait"))
        await runner._handle_message(_live_transcript("input_transcription", "Wait, one more thing."))

        assert self._caller(events) == ["interrupt"]

    @pytest.mark.asyncio
    async def test_the_callers_next_turn_is_reported_after_the_model_answers(self):
        runner, events = self._runner()

        await runner._handle_message(_live_transcript("input_transcription", "Hello team."))
        await runner._handle_message(self._audio())
        await runner._handle_message(_live_message(turn_complete=True))
        await runner._handle_message(_live_transcript("input_transcription", "Can you start?"))

        assert self._caller(events) == ["speech_started", "speech_started"]

    @pytest.mark.asyncio
    async def test_the_pool_timestamps_it(self, monkeypatch):
        """End to end: Gemini's speech_started reaches the connection's turn state, with nothing emitted."""
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
        conn = _connection(agent=_Agent(realtime_runner_cls=GoogleADKRealtimeRunner), loop=asyncio.get_running_loop())
        conn.adapter._callback = conn.handle_framework_event

        await conn.adapter._handle_message(_live_transcript("input_transcription", "Hello team."))

        assert conn.last_caller_speech_at is not None
        assert list(conn._audio_queue._queue) == []


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


def _call_state(**state):
    """The turn state ``RealtimeOutbox`` reads from a connection, quiet and connected unless told otherwise."""
    defaults = dict(
        is_ready=True,
        connected_at=100.0,
        is_responding=False,
        is_caller_speaking=False,
        last_model_output_at=None,
        last_model_generated_at=None,
        last_caller_speech_at=None,
        last_edge_text_at=None,
        last_tool_result_at=None,
        last_reconnect_at=None,
    )
    return types.SimpleNamespace(**{**defaults, **state})


class TestRealtimeOutbox:
    """What an application posts into a call is said only when nobody is talking and nothing is owed a reply."""

    def _outbox(self, *texts, now=100.0, **keys):
        from agentkernel.pipeline.realtime_pool import RealtimeOutbox

        outbox = RealtimeOutbox("s1")
        for text in texts:
            outbox.add(text, keys.get(text), 600.0, now)
        return outbox

    def test_a_post_waits_until_the_call_has_been_quiet_for_a_moment(self):
        conn, outbox = _call_state(), self._outbox("J1 finished.")

        assert outbox.take(conn, now=100.5) is None  # connected half a second ago
        assert outbox.take(conn, now=101.6) == "J1 finished."
        assert outbox.empty

    @pytest.mark.parametrize("busy", [{"is_responding": True}, {"is_caller_speaking": True}, {"is_ready": False}])
    def test_nothing_is_said_into_a_busy_or_unready_call(self, busy):
        conn, outbox = _call_state(**busy), self._outbox("J1 finished.")

        assert outbox.take(conn, now=200.0) is None
        assert outbox.quiet_for(conn, now=200.0) is None

    @pytest.mark.parametrize("given", ["last_caller_speech_at", "last_edge_text_at", "last_tool_result_at", "last_reconnect_at"])
    def test_the_model_answers_what_it_was_given_before_anything_is_said(self, given):
        conn, outbox = _call_state(**{given: 110.0}), self._outbox("J1 finished.")

        assert outbox.take(conn, now=120.0) is None  # unanswered for 10 s: still owed
        conn.last_model_generated_at = conn.last_model_output_at = 121.0
        assert outbox.take(conn, now=122.0) is None  # answered, but only a second ago
        assert outbox.take(conn, now=122.6) == "J1 finished."

    def test_words_still_playing_from_before_a_tool_result_are_no_answer_to_it(self):
        """Audio generated before a handoff or a tool result was taken for the answer to it once it had played out,
        and a post then cut off the answer the model still owed."""
        conn = _call_state(last_model_generated_at=105.0, last_tool_result_at=106.0, last_model_output_at=107.0)
        outbox = self._outbox("J1 finished.")

        assert outbox.take(conn, now=110.0) is None  # quiet for 3 s, but the tool result is not answered yet
        conn.last_model_generated_at = conn.last_model_output_at = 111.0
        assert outbox.take(conn, now=112.6) == "J1 finished."

    def test_an_input_never_answered_stops_holding_the_call(self):
        """Noise or a silent turn must not keep every post waiting for ever."""
        conn, outbox = _call_state(last_caller_speech_at=110.0), self._outbox("J1 finished.")

        assert outbox.take(conn, now=110.0 + outbox.REPLY_TIMEOUT_SECONDS + 0.1) == "J1 finished."

    def test_a_post_is_answered_before_the_next_is_said(self):
        conn, outbox = _call_state(), self._outbox("first", "second")

        assert outbox.take(conn, now=110.0) == "first"
        assert outbox.take(conn, now=112.0) is None  # the model owes a reply to the first
        conn.last_model_generated_at = conn.last_model_output_at = 113.0
        assert outbox.take(conn, now=114.6) == "second"

    def test_a_newer_post_with_the_same_key_replaces_the_waiting_one(self):
        outbox = self._outbox("Build: 2 of 6 tests pass.", "Review started.", **{"Build: 2 of 6 tests pass.": "build"})
        outbox.add("Build: 6 of 6 tests pass.", "build", 600.0, 101.0)

        conn = _call_state()
        said = [outbox.take(conn, now=110.0)]
        conn.last_model_generated_at = conn.last_model_output_at = 111.0
        said.append(outbox.take(conn, now=113.0))
        assert said == ["Build: 6 of 6 tests pass.", "Review started."]

    def test_a_withdrawn_or_expired_post_is_never_said(self):
        outbox = self._outbox("Is a deposit needed?", **{"Is a deposit needed?": "question"})
        outbox.add("Old news.", None, 5.0, 100.0)

        assert outbox.withdraw("question") is True
        assert outbox.withdraw("question") is False
        assert outbox.take(_call_state(), now=106.0) is None  # "Old news." expired at 105
        assert outbox.empty

    def test_a_full_outbox_drops_the_oldest(self):
        from agentkernel.pipeline.realtime_pool import RealtimeOutbox

        outbox = self._outbox(*[f"update {i}" for i in range(RealtimeOutbox.MAX_PENDING + 1)])

        assert outbox.take(_call_state(), now=110.0) == "update 1"

    def test_a_new_connection_owes_no_reply_to_a_post_into_the_old_one(self):
        old, outbox = _call_state(), self._outbox("first", "second")
        assert outbox.take(old, now=110.0) == "first"

        new = _call_state(connected_at=111.0)  # the model socket reconnected
        assert outbox.take(new, now=112.6) == "second"


class TestRealtimeCall:
    """Application code talks into a live call through ``RealtimeCall``, never through the connection's internals."""

    @pytest.fixture(autouse=True)
    def _transport(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))

    @staticmethod
    def _pool():
        pool = RealtimeConnectionPool()
        RealtimeConnectionPool._instance = pool
        return pool

    @staticmethod
    def _connect(pool, session_id="s1", connected_ago=5.0):
        conn = _connection(session_id, loop=asyncio.get_running_loop())
        conn._connected_at = time.time() - connected_ago
        pool._connections[session_id] = conn
        return conn

    @pytest.mark.asyncio
    async def test_a_post_waits_for_the_call_and_is_said_once_it_is_quiet(self):
        from agentkernel.pipeline import RealtimeCall

        pool, call = self._pool(), RealtimeCall("s1")
        assert call.post_when_idle("[Team update] J1 finished.", key="build") is False  # no call yet

        conn = self._connect(pool)
        assert call.connected is True
        pool._deliver_posts(time.time())
        await asyncio.sleep(0)

        assert conn.adapter.texts == ["[Team update] J1 finished."]
        assert conn.last_edge_text_at is None  # the application's words, not the caller's

    @pytest.mark.asyncio
    async def test_a_withdrawn_post_is_never_said(self):
        from agentkernel.pipeline import RealtimeCall

        pool, call = self._pool(), RealtimeCall("s1")
        conn = self._connect(pool)
        call.post_when_idle("Is a deposit needed?", key="question")

        assert call.withdraw("question") is True
        pool._deliver_posts(time.time())
        await asyncio.sleep(0)
        assert conn.adapter.texts == []

    @pytest.mark.asyncio
    async def test_what_the_call_is_doing(self):
        from agentkernel.pipeline import RealtimeCall

        pool, call = self._pool(), RealtimeCall("s1")
        assert (call.connected, call.quiet_for(), call.agent_has_spoken) == (False, None, None)

        conn = self._connect(pool, connected_ago=3.0)
        assert call.quiet_for() == pytest.approx(3.0, abs=0.5)
        assert call.agent_has_spoken is False

        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "general"})
        assert call.agent_has_spoken is False  # the new agent has not said a word
        await asyncio.sleep(0.01)
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})
        assert call.agent_has_spoken is True
        assert call.quiet_for() is None  # its words are still waiting to be played

    @pytest.mark.asyncio
    async def test_an_outbox_with_no_call_and_nothing_waiting_is_forgotten(self):
        pool = self._pool()
        pool.post_when_idle("s1", "Old news.", expires_after=0.0)

        pool._deliver_posts(time.time() + 1)

        assert pool._outboxes == {}

    def test_without_a_pool_nothing_is_reached(self, caplog):
        from agentkernel.pipeline import RealtimeCall

        call = RealtimeCall("s1")
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.realtime_pool"):
            assert call.post_when_idle("J1 finished.") is False
        assert "No realtime pool in this process" in caplog.text
        assert (call.connected, call.quiet_for(), call.withdraw("k")) == (False, None, False)

    def test_close_ends_the_sessions_connection_and_drops_its_posts(self, monkeypatch):
        from agentkernel.pipeline import RealtimeCall

        closed = []

        class Conn:
            closed = False
            is_ready = False

            async def close(self):
                closed.append(True)

        pool = RealtimeConnectionPool()
        loop = asyncio.new_event_loop()
        pool._loop = loop
        conn = Conn()
        pool._connections["s1"] = conn
        pool.post_when_idle("s1", "an update")
        monkeypatch.setattr(RealtimeConnectionPool, "_instance", pool)
        try:
            assert RealtimeCall("s1").close() is True
            loop.run_until_complete(asyncio.sleep(0.01))
        finally:
            loop.close()

        assert closed == [True] and conn.closed
        assert "s1" not in pool._connections and "s1" not in pool._outboxes
        assert RealtimeCall("s1").close() is False

    def test_close_without_a_pool_is_a_no_op(self, monkeypatch):
        from agentkernel.pipeline import RealtimeCall

        monkeypatch.setattr(RealtimeConnectionPool, "_instance", None)
        assert RealtimeCall("s1").close() is False

    @pytest.mark.asyncio
    async def test_nothing_is_posted_while_the_socket_is_being_recovered(self):
        """Text handed to a recovering adapter waits for its next socket, then cuts off the recovered agent."""
        from agentkernel.pipeline import RealtimeCall

        pool, call = self._pool(), RealtimeCall("s1")
        conn = self._connect(pool)
        call.post_when_idle("[Team update] J1 finished.")

        await conn.handle_framework_event("done", {"status": "reconnecting"})
        conn._audio_queue.get_nowait()  # the turn's done, which the pacing loop would have sent on
        pool._deliver_posts(time.time())
        await asyncio.sleep(0)
        assert conn.adapter.texts == [] and call.connected is False

        await conn.handle_framework_event("reconnected", {"agent": "general", "seconds": 1, "seeded": False})
        pool._deliver_posts(time.time())
        await asyncio.sleep(0)
        assert conn.adapter.texts == ["[Team update] J1 finished."]


class TestRealtimeHooks:
    """An agent's realtime hooks see the call: who connected, what each side said, who has the call."""

    class _Recorder:
        def __init__(self, fail=False):
            self.events = []
            self.fail = fail

        async def on_event(self, session, agent, event):
            if self.fail:
                raise RuntimeError("hook broke")
            self.events.append((event.type, event.agent, event.text, event.interrupted))

        def name(self):
            return "recorder"

    @pytest.fixture(autouse=True)
    def _transport(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: InMemoryTransport()))

    @pytest.mark.asyncio
    async def test_the_hooks_follow_a_call_from_connect_to_close(self):
        agent = _Agent(name="general")
        recorder = self._Recorder()
        agent.realtime_hooks.append(recorder)
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())

        await conn.connect()
        await asyncio.sleep(0.05)
        await conn.handle_framework_event("caller_transcript", {"text": " I need a login page. "})
        await conn.handle_framework_event("transcript_delta", {"delta": "Sure, ", "message_id": "m1"})
        await conn.handle_framework_event("transcript_delta", {"delta": "a login page.", "message_id": "m1"})
        await conn.handle_framework_event("done", {"status": "completed"})
        await asyncio.sleep(0.05)
        await conn.handle_framework_event("agent_changed", {"agent": "billing", "previous_agent": "general"})
        await conn.handle_framework_event("transcript_delta", {"delta": "Billing here, your invoice", "message_id": "m2"})
        await asyncio.sleep(0.05)
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB", "message_id": "m2"})
        await conn.handle_framework_event("interrupt", {})
        await asyncio.sleep(0.05)
        conn.send_text("example.com/login", from_edge=True)
        conn.send_text("[Team update] J1 finished.")  # the application's own: not reported
        await asyncio.sleep(0.05)
        await conn.close()

        assert recorder.events == [
            ("connected", "general", "", False),
            ("agent_changed", "general", "", False),
            ("caller_said", None, "I need a login page.", False),
            ("agent_said", "general", "Sure, a login page.", False),
            ("agent_changed", "billing", "", False),
            ("agent_said", "billing", "Billing here, your invoice", True),
            ("edge_text", None, "example.com/login", False),
            ("disconnected", "billing", "", False),
        ]

    @pytest.mark.asyncio
    async def test_a_failing_hook_is_logged_and_the_next_still_runs(self, caplog):
        agent = _Agent()
        recorder = self._Recorder()
        agent.realtime_hooks.extend([self._Recorder(fail=True), recorder])
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.realtime_pool"):
            await conn.connect()
            await conn.close()

        assert [event[0] for event in recorder.events] == ["connected", "disconnected"]
        assert "Realtime hook _Recorder failed on connected" in caplog.text

    @pytest.mark.asyncio
    async def test_a_failed_socket_is_reported_disconnected_once(self):
        agent = _Agent()
        recorder = self._Recorder()
        agent.realtime_hooks.append(recorder)
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("error", {"message": "socket closed"})
        await conn.close()

        assert [event[0] for event in recorder.events].count("disconnected") == 1

    @pytest.mark.asyncio
    async def test_text_from_the_edge_on_another_thread_reaches_the_hooks(self):
        agent = _Agent()
        recorder = self._Recorder()
        agent.realtime_hooks.append(recorder)
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())
        await conn.connect()

        typed = threading.Thread(target=lambda: conn.send_text("example.com", from_edge=True))
        typed.start()
        while typed.is_alive():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        await conn.close()

        assert ("edge_text", None, "example.com", False) in recorder.events

    @pytest.mark.asyncio
    async def test_an_agent_without_realtime_hooks_queues_nothing(self):
        conn = _connection(loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("caller_transcript", {"text": "Hello"})

        assert conn._hook_events is None and conn._hook_task is None
        await conn.close()

    @pytest.mark.asyncio
    async def test_a_reconnect_reaches_the_hooks(self):
        agent = _Agent()
        recorder = self._Recorder()
        agent.realtime_hooks.append(recorder)
        conn = _connection(agent=agent, loop=asyncio.get_running_loop())
        await conn.connect()

        await conn.handle_framework_event("reconnected", {"agent": "billing", "seconds": 2, "seeded": True})
        await conn.close()

        assert ("reconnected", "billing", "", False) in recorder.events


class TestADKCallerTranscript:
    """The Gemini adapter reports the caller's words in a turn, for the agent's realtime hooks."""

    @staticmethod
    def _runner():
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        events = []

        async def callback(event_type, data):
            events.append((event_type, data))

        runner = GoogleADKRealtimeRunner()
        runner._callback = callback
        return runner, events

    @pytest.mark.asyncio
    async def test_the_callers_words_are_reported_when_the_turn_ends(self):
        runner, events = self._runner()

        await runner._handle_message(_live_transcript("input_transcription", "I need"))
        await runner._handle_message(_live_transcript("input_transcription", " a login page."))
        await runner._handle_message(_live_message(turn_complete=True))

        reported = [(t, d) for t, d in events if t in ("caller_transcript", "done")]
        assert reported == [("caller_transcript", {"text": "I need a login page."}), ("done", {"status": "completed"})]

    @pytest.mark.asyncio
    async def test_the_callers_words_are_reported_before_text_is_sent_in(self):
        runner, events = self._runner()

        class _Socket:
            async def send_client_content(self, **kwargs):
                pass

        runner._connection = _Socket()
        await runner._handle_message(_live_transcript("input_transcription", "Book me in for Friday."))
        await runner.send_text("[Team update] J1 finished.")

        assert ("caller_transcript", {"text": "Book me in for Friday."}) in events

    @pytest.mark.asyncio
    async def test_a_turn_without_the_callers_words_reports_none(self):
        runner, events = self._runner()

        await runner._handle_message(_live_message(turn_complete=True))

        assert [t for t, _ in events] == ["done"]
