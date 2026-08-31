import json

import pytest

from agentkernel.core.model import ExecutionMode
from agentkernel.pipeline.envelope import QueueMessage
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.pipeline.ws.base import WebSocketHandlerABC


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


class _FakeWSHandler:
    """Records broadcast calls the way PodPushWebSocketHandler would receive them."""

    def __init__(self):
        self.broadcasts = []

    def broadcast(self, endpoint_url=None, message=None, user_id=None, connection_ids=None, message_type=None):
        self.broadcasts.append({"message": message, "user_id": user_id, "message_type": message_type})


def _handler():
    store = InMemoryResponseStore()
    return ResponseHandler(transport=InMemoryTransport(), response_store=store), store


def _ws_handler():
    store = InMemoryResponseStore()
    ws = _FakeWSHandler()
    return ResponseHandler(transport=InMemoryTransport(), response_store=store, ws_handler=ws), store, ws


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

    def test_ws_entered_chunks_broadcast_over_websocket(self, monkeypatch):
        """The USER_ID attribute (stamped only by the gateway) marks a WS-entered request: its
        chunks are pushed, never routed into the SSE chunk store."""
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, store, ws = _ws_handler()
        handler.process(_output_msg({"delta": "x", "session_id": "s1"}, attributes={"request_id": "r1", "user_id": "u1"}))

        [call] = ws.broadcasts
        assert call["user_id"] == "u1"
        assert call["message"] == {"delta": "x", "session_id": "s1"}
        assert call["message_type"] == WebSocketHandlerABC.MessageType.STREAM_CHUNK
        with pytest.raises(TimeoutError):  # nothing was routed into the SSE chunk store
            next(store.stream("r1", chunk_timeout=0.1))

    def test_permanent_failure_of_a_ws_entered_chunk_broadcasts_the_error(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, _, ws = _ws_handler()
        handler.on_permanent_failure(_output_msg({"delta": "x"}, attributes={"request_id": "r1", "user_id": "u1"}))

        [call] = ws.broadcasts
        assert call["message_type"] == WebSocketHandlerABC.MessageType.STREAM_CHUNK
        assert call["message"]["done"] is True
        assert "after 3 retries" in call["message"]["error"]
        assert call["message"]["session_id"] == "s1"

    def test_permanent_failure_emits_error_chunk(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        handler, store = _handler()
        handler.on_permanent_failure(_output_msg({"delta": "x"}, attributes={"request_id": "r1"}))

        [chunk] = list(store.stream("r1", chunk_timeout=0.5))
        assert chunk["done"] is True
        assert "after 3 retries" in chunk["error"]
        assert chunk["session_id"] == "s1"


class TestAsyncDelivery:
    def test_response_broadcast_as_chat_response(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, ws = _ws_handler()
        handler.process(_output_msg({"result": "ok", "session_id": "s1"}, attributes={"request_id": "r1", "user_id": "u1"}))

        [call] = ws.broadcasts
        assert call["user_id"] == "u1"
        assert call["message"] == {"result": "ok", "session_id": "s1"}
        assert call["message_type"] == WebSocketHandlerABC.MessageType.CHAT_RESPONSE

    def test_missing_user_id_raises_for_retry(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, _ = _ws_handler()
        with pytest.raises(ValueError, match="user_id"):
            handler.process(_output_msg({"result": "ok"}, attributes={"request_id": "r1"}))

    def test_permanent_failure_broadcasts_system_response(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, ws = _ws_handler()
        handler.on_permanent_failure(_output_msg({"result": "never"}, attributes={"request_id": "r1", "user_id": "u1"}))

        [call] = ws.broadcasts
        assert call["message_type"] == WebSocketHandlerABC.MessageType.SYSTEM_RESPONSE
        assert call["message"]["error"] == "Failed to process message after 3 retries"
        assert call["message"]["request_id"] == "r1"
        assert call["message"]["session_id"] == "s1"

    def test_permanent_failure_without_attributes_never_raises(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, ws = _ws_handler()
        handler.on_permanent_failure(_output_msg({"result": "never"}, attributes={"request_id": "r1"}))
        assert ws.broadcasts == []
