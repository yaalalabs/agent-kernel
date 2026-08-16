import json

import pytest

from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueMessage
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()


def _use_mode(monkeypatch, mode, output_max_receive_count=3):
    class _Cfg:
        class execution:
            class queues:
                class output:
                    max_receive_count = output_max_receive_count

    _Cfg.execution.mode = mode
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _handler():
    store = InMemoryResponseStore()
    return ResponseHandler(transport=InMemoryTransport(), response_store=store), store


def _output_msg(body, attributes=None, group_id="s1"):
    return QueueMessage(
        body=json.dumps(body),
        attributes=attributes if attributes is not None else {"request_id": "r1", "status_code": "200"},
        group_id=group_id,
        message_id="m1",
    )


class TestRestDelivery:
    def test_stores_record_with_status_code(self, monkeypatch):
        _use_mode(monkeypatch, None)
        handler, store = _handler()
        handler.process(_output_msg({"error": "bad", "session_id": "s1"}, attributes={"request_id": "r1", "status_code": "400"}))

        record = store.get_record("r1")
        assert record["status_code"] == 400
        assert record["body"] == {"error": "bad", "session_id": "s1"}
        assert record["session_id"] == "s1"

    def test_status_code_defaults_to_200(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        handler, store = _handler()
        handler.process(_output_msg({"result": "ok", "session_id": "s1"}, attributes={"request_id": "r1"}))
        assert store.get_record("r1")["status_code"] == 200

    def test_missing_request_id_raises(self, monkeypatch):
        _use_mode(monkeypatch, None)
        handler, _ = _handler()
        with pytest.raises(ValueError, match="request_id"):
            handler.process(_output_msg({"result": "ok"}, attributes={}))

    def test_permanent_failure_stores_error_record(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        handler, store = _handler()
        handler.on_permanent_failure(_output_msg({"result": "never"}, attributes={"request_id": "r1"}))

        record = store.get_record("r1")
        assert record["status_code"] == 500
        assert record["body"]["error"] == "Failed to process message after 3 retries"
        assert record["body"]["session_id"] == "s1"


class TestStreamDelivery:
    def test_local_chunks_reach_the_store_stream(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, store = _handler()
        handler.process(_output_msg({"delta": "he", "session_id": "s1"}, attributes={"request_id": "r1"}))
        handler.process(_output_msg({"done": True, "session_id": "s1"}, attributes={"request_id": "r1"}))

        chunks = list(store.stream("r1", chunk_timeout=0.5))
        assert chunks == [{"delta": "he", "session_id": "s1"}, {"done": True, "session_id": "s1"}]

    def test_remote_endpoint_is_not_yet_supported(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, _ = _handler()
        message = _output_msg({"delta": "x"}, attributes={"request_id": "r1", "endpoint_url": "http://10.0.0.7:8000"})
        with pytest.raises(AKConfigError, match="WebSocket delivery"):
            handler.process(message)

    def test_permanent_failure_emits_error_chunk(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, store = _handler()
        handler.on_permanent_failure(_output_msg({"delta": "x"}, attributes={"request_id": "r1"}))

        [chunk] = list(store.stream("r1", chunk_timeout=0.5))
        assert chunk["done"] is True
        assert "after 3 retries" in chunk["error"]
        assert chunk["session_id"] == "s1"


class TestAsyncDelivery:
    def test_async_mode_is_not_yet_supported(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _ = _handler()
        with pytest.raises(AKConfigError, match="WebSocket delivery"):
            handler.process(_output_msg({"result": "ok"}))
