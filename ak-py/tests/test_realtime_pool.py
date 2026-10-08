import asyncio
import json
import threading
import types

import pytest

from agentkernel import Agent, Runner, Session
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
        # The transcript streams immediately (audio is paced), so it exercises _emit directly.
        await conn.handle_framework_event("transcript_delta", {"delta": "QUFB", "message_id": "m1"})

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
        assert RealtimeConnectionPool.get() is None


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

        # The in-memory queue delivers one message per group until it is acked, so drain with acks.
        consumer = transport.create_consumer(QueueName.OUTPUT)
        kinds = []
        while True:
            messages = consumer.fetch(10, 0.2)
            if not messages:
                break
            for message in messages:
                body = json.loads(message.body)
                kinds.append("done" if body.get("done") else body["event"]["type"])
                consumer.ack(message)

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

        consumer = transport.create_consumer(QueueName.OUTPUT)
        kinds = []
        while True:
            messages = consumer.fetch(10, 0.2)
            if not messages:
                break
            for message in messages:
                body = json.loads(message.body)
                kinds.append("done" if body.get("done") else body["event"]["type"])
                consumer.ack(message)

        assert kinds == ["audio_delta", "done"]


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

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

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

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(self.get_weather))

        assert [d.name for d in config.tools[0].function_declarations] == ["get_weather"]

    @pytest.mark.asyncio
    async def test_a_plain_function_runs(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        agent = self._agent(self.get_weather)
        runner = GoogleADKRealtimeRunner()
        runner._agent = agent
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
            config = GoogleADKRealtimeRunner()._connect_config(self._agent(self.get_weather, _Toolset()))

        assert [d.name for d in config.tools[0].function_declarations] == ["get_weather"]
        assert "is a toolset" in caplog.text

    @pytest.mark.asyncio
    async def test_the_tool_result_is_wrapped_as_adk_wraps_it(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        sent = []

        class _Connection:
            async def send_tool_response(self, function_responses):
                sent.append(function_responses)

        runner = GoogleADKRealtimeRunner()
        runner._connection = _Connection()
        runner._tool_names["call-1"] = "get_weather"

        await runner.send_tool_result("call-1", "sunny")

        assert sent[0].name == "get_weather"
        assert sent[0].response == {"result": "sunny"}


class TestADKConnectConfig:
    """The Live session config carries only what the ADK agent declares."""

    @staticmethod
    def _agent(**kwargs):
        from google.adk.agents import Agent as GoogleAgent

        return types.SimpleNamespace(name="general", agent=GoogleAgent(name="general", model="gemini-live", **kwargs))

    def test_string_instruction_is_the_system_instruction(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(instruction="Be brief."))

        assert config.system_instruction.parts[0].text == "Be brief."

    def test_description_is_not_used_as_an_instruction(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(description="Routes billing questions."))

        assert config.system_instruction is None

    def test_turn_detection_and_thinking_are_left_to_the_live_api(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        config = GoogleADKRealtimeRunner()._connect_config(self._agent(instruction="x"))

        assert config.realtime_input_config is None
        assert config.thinking_config is None

    def test_a_callable_instruction_is_rejected_clearly(self):
        from agentkernel.framework.adk.adk import GoogleADKRealtimeRunner

        with pytest.raises(ValueError, match="instruction as a string"):
            GoogleADKRealtimeRunner()._connect_config(self._agent(instruction=lambda ctx: "dynamic"))


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
        [message] = transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)
        body = json.loads(message.body)
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
