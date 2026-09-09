import json
import signal
from unittest.mock import MagicMock

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()


class _FakeCfg:
    class execution:
        class queues:
            class input:
                max_receive_count = 3


def _input_msg(dedup_id="d1", attributes=None, receive_count=1):
    return QueueMessage(
        body=json.dumps({"prompt": "hi", "session_id": "s1", "agent": None}),
        attributes=attributes if attributes is not None else {"request_id": "r1", "user_id": "u1"},
        group_id="s1",
        dedup_id=dedup_id,
        receive_count=receive_count,
        message_id="m1",
    )


def _fetch_output(transport, n=10):
    return transport.create_consumer(QueueName.OUTPUT).fetch(n, 0.5)


class TestAgentRunner:
    def test_process_forwards_response_with_status(self):
        transport = InMemoryTransport()
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (200, {"result": "ok:hi", "session_id": "s1"})

        AgentRunner(transport=transport, chat_service=chat_service).process(_input_msg())

        [out] = _fetch_output(transport)
        assert json.loads(out.body) == {"result": "ok:hi", "session_id": "s1"}
        assert out.attributes["request_id"] == "r1"
        assert out.attributes["user_id"] == "u1"
        assert out.attributes["status_code"] == "200"
        assert out.group_id == "s1"
        assert out.dedup_id == "d1"

    def test_error_status_is_forwarded(self):
        transport = InMemoryTransport()
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (500, {"error": "boom", "session_id": "s1"})

        AgentRunner(transport=transport, chat_service=chat_service).process(_input_msg())

        [out] = _fetch_output(transport)
        assert out.attributes["status_code"] == "500"
        assert json.loads(out.body)["error"] == "boom"

    def test_missing_request_id_raises(self):
        runner = AgentRunner(transport=InMemoryTransport(), chat_service=MagicMock())
        with pytest.raises(ValueError, match="request_id"):
            runner.process(_input_msg(attributes={}))

    def test_permanent_failure_sends_error_body(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _FakeCfg))
        transport = InMemoryTransport()

        AgentRunner(transport=transport, chat_service=MagicMock()).on_permanent_failure(_input_msg())

        [out] = _fetch_output(transport)
        assert json.loads(out.body) == {"error": "Failed to process message after 3 retries"}
        assert out.attributes["status_code"] == "500"

    def test_run_rejects_in_memory_transport(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        with pytest.raises(AKConfigError, match="IOHandler"):
            AgentRunner.run()


class TestRunSignalHandlers:
    @pytest.fixture(autouse=True)
    def _restore_signal_state(self):
        previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        yield
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        ThreadRunner.shutdown_exit_code = 1

    def test_run_installs_graceful_drain_handlers(self, monkeypatch):
        """A standalone runner container is PID 1: run() must install the SIGTERM/SIGINT drain
        handlers itself (IOHandler is not there to do it in the two-process topology)."""

        class _Cfg:
            class execution:
                mode = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "sqs"))
        monkeypatch.setattr(QueueTransportFactory, "create", classmethod(lambda cls: MagicMock()))
        started = []
        monkeypatch.setattr(AgentRunner, "start", lambda self, exit_on_shutdown=True: started.append(exit_on_shutdown))

        AgentRunner.run()

        assert started == [True], "a standalone main keeps the drain-then-exit default"
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        assert signal.getsignal(signal.SIGINT) is handler

        handler(signal.SIGTERM, None)
        assert ThreadRunner.shutdown_event.is_set()
        assert ThreadRunner.shutdown_exit_code == 0


class TestStreamAgentRunner:
    def test_fans_out_chunks_with_dedup_suffix(self, monkeypatch):
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "in_memory"))
        transport = InMemoryTransport()
        chat_service = MagicMock()
        chat_service.process_stream_chat_sync.return_value = iter(
            [json.dumps({"delta": "he", "session_id": "s1"}), json.dumps({"done": True, "session_id": "s1"})]
        )

        StreamAgentRunner(transport=transport, chat_service=chat_service).process(_input_msg())

        # Chunks of one session share a group: fetch them one ack at a time (FIFO per group).
        consumer = transport.create_consumer(QueueName.OUTPUT)
        [first] = consumer.fetch(10, 0.5)
        consumer.ack(first)
        [second] = consumer.fetch(10, 0.5)
        assert json.loads(first.body) == {"delta": "he", "session_id": "s1"}
        assert json.loads(second.body) == {"done": True, "session_id": "s1"}
        assert first.dedup_id == "d1-1-0"
        assert second.dedup_id == "d1-1-1"
        assert "status_code" not in first.attributes

    def test_user_id_required_on_broker_transport(self, monkeypatch):
        """Broker STREAM chunks are WebSocket-delivered, so the WS-entered marker (the
        authenticated USER_ID attribute) must be present."""
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "kafka"))
        runner = StreamAgentRunner(transport=InMemoryTransport(), chat_service=MagicMock())
        with pytest.raises(ValueError, match="user_id"):
            runner.process(_input_msg(attributes={"request_id": "r1"}))

    def test_permanent_failure_sends_error_chunk(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _FakeCfg))
        transport = InMemoryTransport()

        StreamAgentRunner(transport=transport, chat_service=MagicMock()).on_permanent_failure(_input_msg(receive_count=4))

        [out] = _fetch_output(transport)
        chunk = json.loads(out.body)
        assert chunk["done"] is True
        assert "after 3 retries" in chunk["error"]
        assert chunk["session_id"] == "s1"
        assert out.dedup_id == "d1-4-error"
