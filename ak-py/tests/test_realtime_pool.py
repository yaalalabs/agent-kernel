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
        runner._session = session

        result = await runner.execute_tool("get_weather", '{"location": "Paris"}', ToolContext(runtime, agent, session, []), "call-1")
        assert result == "Paris:no-state"

    @pytest.mark.asyncio
    async def test_openai_execute_tool_injects_context(self):
        from agentkernel.framework.openai.openai import OpenAIRealtimeAdapter, OpenAIToolBuilder

        def get_weather(location: str) -> str:
            """Get the weather."""
            context = ToolContext.get()
            return f"{location}:{context.session.id if context else 'no-context'}"

        [tool] = OpenAIToolBuilder.bind([get_weather])
        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[tool]), name="general")
        session = Session("s1")
        runtime = Runtime(InMemorySessionStore())

        adapter = OpenAIRealtimeAdapter()
        adapter._agent = agent

        result = await adapter.execute_tool("get_weather", '{"location": "Paris"}', ToolContext(runtime, agent, session, []), "call-1")
        assert result == "Paris:s1"

    @pytest.mark.asyncio
    async def test_openai_execute_tool_passes_framework_context_as_run_context(self):
        """Parity with the unary path: ``wrapper.context`` is the session's framework_context, not the AK ToolContext."""
        from agents import RunContextWrapper, function_tool

        from agentkernel.framework.openai.openai import OpenAIRealtimeAdapter

        @function_tool
        def get_cart(wrapper: RunContextWrapper) -> str:
            """Read the cart."""
            return ",".join(wrapper.context["cart"])

        session = Session("s1")
        session.set_framework_context({"cart": ["apple", "pear"]})
        agent = types.SimpleNamespace(agent=types.SimpleNamespace(tools=[get_cart]), name="general")

        adapter = OpenAIRealtimeAdapter()
        adapter._agent = agent

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
        from agentkernel.framework.openai.openai import OpenAIRealtimeAdapter

        adapter = OpenAIRealtimeAdapter()
        adapter._session = None
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
