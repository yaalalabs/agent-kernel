import asyncio
import json
import threading
import types

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.base import RealtimeRunner
from agentkernel.core.model import AgentReplyText, ExecutionMode
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

    @pytest.mark.asyncio
    async def test_emit_stamps_realtime_and_integration(self, monkeypatch):
        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        conn = _connection(loop=asyncio.get_running_loop())
        conn.update_delivery_context(request_id="r1", user_id="u1", integration="livekit", reply_context={"session_id": "s1"})
        await conn.handle_framework_event("audio_delta", {"delta": "QUFB"})

        [message] = transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)
        assert message.attributes[ATTR_REALTIME] == "true"
        assert message.attributes[ATTR_INTEGRATION] == "livekit"
        assert message.attributes["request_id"] == "r1"
        assert message.attributes["user_id"] == "u1"
        assert message.attributes["reply_session_id"] == "s1"
        assert message.group_id == "s1"
        body = json.loads(message.body)
        assert body["event"]["type"] == "audio_delta"
        assert body["event"]["content"] == "QUFB"
        assert body["done"] is False

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

        from agentkernel.pipeline.agent_runner import StreamAgentRunner
        from agentkernel.pipeline.envelope import QueueMessage

        class _Cfg:
            class execution:
                mode = ExecutionMode.REALTIME
                queues = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

        transport = InMemoryTransport()
        monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))

        handler = types.SimpleNamespace(service=types.SimpleNamespace(agent=_Agent(), runtime=Runtime(InMemorySessionStore()), session=Session("s1")))
        chat_service = MagicMock()
        chat_service.prepare_agent_handler.return_value = handler

        pool = RealtimeConnectionPool.initialize()
        thread = threading.Thread(target=pool.start, daemon=True)
        thread.start()
        try:
            runner = StreamAgentRunner(transport=transport, chat_service=chat_service)
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


class TestOpenAIPacing:
    """The pacing loop must emit a turn's audio before its terminal ``done`` event."""

    class _Event:
        def __init__(self, type, **fields):
            self.type = type
            for key, value in fields.items():
                setattr(self, key, value)

    class _Connection:
        def __init__(self, events):
            self._events = events

        async def __aiter__(self):
            for event in self._events:
                yield event
                await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_done_follows_its_audio(self):
        from agentkernel.framework.openai.openai import OpenAIRealtimeAdapter

        adapter = OpenAIRealtimeAdapter()
        delta = "QUFB"  # 4 bytes -> 2 samples -> 2/24 ms
        events = [self._Event("response.output_audio.delta", delta=delta) for _ in range(3)]
        events.append(self._Event("response.output_audio_transcript.delta", delta="hi"))
        events.append(self._Event("response.done", response=type("R", (), {"status": "completed"})()))

        adapter._connection = self._Connection(events)
        adapter._audio_queue = asyncio.Queue()
        seen = []

        async def callback(event_type, data):
            seen.append(event_type)

        adapter._callback = callback
        adapter._pacing_task = asyncio.create_task(adapter._pacing_loop())
        adapter._listen_task = asyncio.create_task(adapter._listen())
        await asyncio.sleep(0.1)
        adapter._pacing_task.cancel()
        adapter._listen_task.cancel()

        # All three audio deltas are emitted, the transcript streams as text, and the terminal
        # event is always the done chunk (it never overtakes its audio).
        assert seen.count("audio_delta") == 3
        assert "transcript_delta" in seen
        assert seen[-1] == "done"
