import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.realtime import RealtimeRunner
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.deployment.aws.containerized.akagentrunner import ECSAgentRunner, ECSRealtimeAgentRunner, ECSStreamAgentRunner
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnectionPool
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


def _make_record(requests, session_id: str = "room_01"):
    return {
        "MessageId": "m1",
        "Body": json.dumps({"prompt": "", "session_id": session_id, "agent": "general", "requests": requests}),
        "Attributes": {"MessageGroupId": session_id, "ApproximateReceiveCount": "1"},
        "MessageAttributes": {
            "request_id": {"StringValue": "req-1", "DataType": "String"},
            "user_id": {"StringValue": "u1", "DataType": "String"},
            "integration": {"StringValue": "livekit", "DataType": "String"},
            # Written by the LiveKit gateway as REPLY_CONTEXT_PREFIX + "session_id".
            "reply_session_id": {"StringValue": session_id, "DataType": "String"},
        },
    }


def _pool_with(conn):
    """A real pool, so the runner exercises the shared ``dispatch`` path, with the socket side mocked."""
    pool = RealtimeConnectionPool()
    pool.get_connection = MagicMock(return_value=conn)
    pool.get_or_create = MagicMock(return_value=conn)
    return pool


def _process(record):
    conn = MagicMock()
    pool = _pool_with(conn)
    with patch.object(RealtimeConnectionPool, "initialize", return_value=pool):
        ECSRealtimeAgentRunner.process_message(record)
    return pool, conn


def test_process_message_extracts_reply_context_from_reply_prefixed_attributes():
    """Regression: the ECS runner must read the reply context with REPLY_CONTEXT_PREFIX ("reply_"),
    not a hard-coded "reply_ctx_", or every realtime chunk fails to resolve its outbound adapter."""
    pool, conn = _process(_make_record([{"type": "text", "prompt": "hi"}]))

    pool.get_connection.assert_called_once_with("room_01")
    ctx = conn.update_delivery_context.call_args.kwargs
    assert ctx["request_id"] == "req-1"
    assert ctx["user_id"] == "u1"
    assert ctx["integration"] == "livekit"
    assert ctx["reply_context"] == {"session_id": "room_01"}


def test_permanent_failure_emits_a_marked_error_chunk_for_the_live_edge(monkeypatch):
    """The generic ECS failure reply drops the realtime marker, so the Response Handler would route it
    to a webhook adapter; the realtime runner must emit a marked error chunk instead."""
    InMemoryTransport.reset()
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *a, **k: transport))
    monkeypatch.setattr(
        ECSRealtimeAgentRunner,
        "_config",
        SimpleNamespace(execution=SimpleNamespace(queues=SimpleNamespace(input=SimpleNamespace(max_receive_count=3)))),
    )

    ECSRealtimeAgentRunner.on_permanent_failure(_make_record([{"type": "text", "prompt": "hi"}]))

    [out] = transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)
    assert out.attributes["realtime"] == "true"
    assert out.attributes["integration"] == "livekit"
    assert out.attributes["reply_session_id"] == "room_01"
    assert out.group_id == "room_01"
    assert json.loads(out.body) == {"error": "Failed to process message after 3 retries", "done": True}


def test_process_message_routes_text_and_audio_requests():
    _, conn = _process(
        _make_record(
            [
                {"type": "text", "prompt": "hello"},
                {"type": "voice", "prompt": "", "audio_data": "AAA=", "name": "general"},
            ]
        )
    )

    conn.send_text.assert_called_once_with("hello")
    conn.append_audio.assert_called_once_with("AAA=")


def test_process_message_reuses_existing_connection_without_loading_agent():
    conn = MagicMock()
    pool = _pool_with(conn)
    chat_service = MagicMock()
    with (
        patch.object(RealtimeConnectionPool, "initialize", return_value=pool),
        patch.object(ECSRealtimeAgentRunner, "_get_chat_service", return_value=chat_service),
    ):
        ECSRealtimeAgentRunner.process_message(_make_record([{"type": "text", "prompt": "hi"}]))

    chat_service.prepare_agent_handler.assert_not_called()


def test_process_message_drops_input_during_shutdown():
    """Input arriving while the model sockets close is dropped: no pool lookup, no new connection."""
    ThreadRunner.shutdown_event.set()
    try:
        pool, conn = _process(_make_record([{"type": "text", "prompt": "hi"}]))
    finally:
        ThreadRunner.shutdown_event.clear()

    pool.get_connection.assert_not_called()
    conn.send_text.assert_not_called()


class _RecordingRealtimeRunner(RealtimeRunner):
    """Model socket double; the ECS consumer and realtime pool remain real."""

    def __init__(self):
        super().__init__("test-realtime")
        self.connect_count = 0
        self.audio: list[str] = []
        self.texts: list[str] = []
        self.disconnected = False

    async def connect(self, session, agent, callback):
        self.connect_count += 1

    async def append_audio(self, base64_audio):
        self.audio.append(base64_audio)

    async def send_text(self, text):
        self.texts.append(text)

    async def execute_tool(self, name, arguments, context, call_id):
        raise NotImplementedError()

    async def send_tool_result(self, call_id, result):
        raise NotImplementedError()

    async def disconnect(self):
        self.disconnected = True


def test_consumer_loop_starts_real_pool_processes_requests_and_closes_connection(monkeypatch):
    """The ECS-built consumer must start the pool task before the first request can connect."""
    RealtimeConnectionPool.reset()
    monkeypatch.setattr(ThreadRunner, "shutdown_event", threading.Event())
    transport = InMemoryTransport()
    monkeypatch.setattr(QueueTransportFactory, "create", staticmethod(lambda *args, **kwargs: transport))
    monkeypatch.setattr(ECSRealtimeAgentRunner, "num_consumers", 1)

    session = Session("room_01")
    agent = SimpleNamespace(name="general", realtime_runner_cls=_RecordingRealtimeRunner)
    service = SimpleNamespace(agent=agent, runtime=Runtime(InMemorySessionStore()), session=session)
    chat_service = MagicMock()
    chat_service.prepare_agent_handler.return_value = SimpleNamespace(service=service)
    monkeypatch.setattr(ECSRealtimeAgentRunner, "_get_chat_service", classmethod(lambda cls: chat_service))

    records = [
        _make_record([{"type": "voice", "audio_data": "AAA=", "name": "general"}]),
        _make_record([{"type": "text", "prompt": "hello"}]),
    ]
    pool = RealtimeConnectionPool.initialize()
    connections = []

    def poll():
        if records:
            return [records.pop(0)]
        ThreadRunner.shutdown_event.wait(0.05)
        return []

    def acknowledge(record):
        connections.append(pool.get_connection("room_01"))
        if len(connections) == 2:
            ThreadRunner.shutdown_event.set()

    monkeypatch.setattr(ECSRealtimeAgentRunner, "poll", classmethod(lambda cls: poll()))
    monkeypatch.setattr(ECSRealtimeAgentRunner, "delete_message", classmethod(lambda cls, record: acknowledge(record)))
    consumer_loop = ECSRealtimeAgentRunner._build_consumer_loop()
    # Exercise ThreadRunner's real startup/drain without exiting the pytest process on shutdown.
    consumer_loop._exit_on_shutdown = False
    consumer_thread = threading.Thread(target=consumer_loop.run, daemon=True)

    try:
        consumer_thread.start()
        consumer_thread.join(timeout=5)
        assert not consumer_thread.is_alive(), "ECS consumer did not process the requests and drain"
        assert len(connections) == 2
        first, second = connections
        assert first is second
        assert first.session is session
        assert first.adapter.connect_count == 1
        assert first.adapter.audio == ["AAA="]
        assert first.adapter.texts == ["hello"]
        assert first.adapter.disconnected
        assert first.closed
        assert pool.get_connection("room_01") is None
        chat_service.prepare_agent_handler.assert_called_once_with("room_01", "general")
    finally:
        ThreadRunner.shutdown_event.set()
        consumer_thread.join(timeout=15)
        RealtimeConnectionPool.reset()


@pytest.mark.parametrize("runner_cls", [ECSAgentRunner, ECSStreamAgentRunner])
def test_non_realtime_consumer_does_not_initialize_pool(runner_cls):
    with patch.object(RealtimeConnectionPool, "initialize") as initialize:
        runner_cls._build_consumer_loop()

    initialize.assert_not_called()
