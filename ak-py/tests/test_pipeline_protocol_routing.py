"""The ``protocol`` attribute (#780 §2): an A2A or MCP caller waits for one whole reply in the
response store, so tagged messages bypass every mode-specific delivery path."""

import json
from unittest.mock import MagicMock

import pytest

from agentkernel.core.model import ExecutionMode
from agentkernel.integration.adapter.base import OutboundAdapter
from agentkernel.pipeline.agent_runner import AgentRunner, RealtimeAgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import ATTR_INTEGRATION, ATTR_PROTOCOL, QueueMessage, QueueName
from agentkernel.pipeline.realtime_pool import RealtimeConnectionPool
from agentkernel.pipeline.response_handler import ResponseHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.in_memory import InMemoryTransport
from agentkernel.pipeline.ws.base import WebSocketHandlerABC

ALL_MODES = [None, ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC, ExecutionMode.ASYNC, ExecutionMode.STREAM, ExecutionMode.REALTIME]
TAGGED = {"request_id": "r1", ATTR_PROTOCOL: "a2a"}


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()
    yield
    InMemoryTransport.reset()
    InMemoryResponseStore.reset()


def _use_mode(monkeypatch, mode):
    """Stub AKConfig with the mode and the retry counts both pipeline sides read."""

    class _Cfg:
        class execution:
            class queues:
                class input:
                    max_receive_count = 3

                class output:
                    max_receive_count = 3

    _Cfg.execution.mode = mode
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))


def _input_msg(attributes, receive_count=1):
    return QueueMessage(
        body=json.dumps({"prompt": "hi", "session_id": "s1", "agent": "triage"}),
        attributes=dict(attributes),
        group_id="s1",
        dedup_id="d1",
        receive_count=receive_count,
        message_id="m1",
    )


def _output_msg(body, attributes):
    return QueueMessage(body=json.dumps(body), attributes=dict(attributes), group_id="s1", message_id="m1")


def _chat_service(status_code=200, result="ok:hi"):
    chat_service = MagicMock()
    chat_service.process_chat_request.return_value = (status_code, {"result": result, "session_id": "s1"})
    return chat_service


def _fetch_output(transport):
    return transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.5)


class _FakeWSHandler:
    def __init__(self):
        self.broadcasts = []

    def broadcast(self, endpoint_url=None, message=None, user_id=None, connection_ids=None, message_type=None):
        self.broadcasts.append({"message": message, "user_id": user_id, "message_type": message_type})


def _handler():
    store = InMemoryResponseStore()
    ws = _FakeWSHandler()
    return ResponseHandler(transport=InMemoryTransport(), response_store=store, ws_handler=ws), store, ws


class TestAgentRunner:
    def test_the_protocol_and_status_reach_the_output_message(self):
        transport = InMemoryTransport()

        AgentRunner(transport=transport, chat_service=_chat_service()).process(_input_msg(TAGGED))

        [out] = _fetch_output(transport)
        assert out.attributes == {"request_id": "r1", ATTR_PROTOCOL: "a2a", "status_code": "200"}
        assert json.loads(out.body) == {"result": "ok:hi", "session_id": "s1"}

    def test_a_permanent_failure_keeps_the_protocol(self, monkeypatch):
        _use_mode(monkeypatch, None)
        transport = InMemoryTransport()

        AgentRunner(transport=transport, chat_service=MagicMock()).on_permanent_failure(_input_msg(TAGGED, receive_count=4))

        [out] = _fetch_output(transport)
        assert out.attributes[ATTR_PROTOCOL] == "a2a"
        assert out.attributes["status_code"] == "500"
        assert "after 3 retries" in json.loads(out.body)["error"]


class TestStreamAgentRunner:
    def test_a_tagged_message_gets_one_whole_reply_without_a_user_on_a_broker(self, monkeypatch):
        # A broker stream runner demands a USER_ID for WebSocket chunks; a tagged message hands off first.
        monkeypatch.setattr(QueueTransportFactory, "resolve_type", staticmethod(lambda: "nats"))
        transport = InMemoryTransport()
        chat_service = _chat_service()

        StreamAgentRunner(transport=transport, chat_service=chat_service).process(_input_msg(TAGGED))

        [out] = _fetch_output(transport)
        assert json.loads(out.body) == {"result": "ok:hi", "session_id": "s1"}
        assert out.attributes["status_code"] == "200"
        assert out.attributes[ATTR_PROTOCOL] == "a2a"
        chat_service.process_stream_chat_sync.assert_not_called()

    def test_a_tagged_permanent_failure_is_an_error_body_not_a_chunk(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.STREAM)
        transport = InMemoryTransport()

        StreamAgentRunner(transport=transport, chat_service=MagicMock()).on_permanent_failure(_input_msg(TAGGED, receive_count=4))

        [out] = _fetch_output(transport)
        body = json.loads(out.body)
        assert out.attributes["status_code"] == "500"
        assert "done" not in body
        assert "after 3 retries" in body["error"]


class TestRealtimeAgentRunner:
    @pytest.fixture
    def pool(self, monkeypatch):
        pool = MagicMock()
        monkeypatch.setattr(RealtimeConnectionPool, "initialize", classmethod(lambda cls: pool))
        monkeypatch.setattr(RealtimeConnectionPool, "send_permanent_failure", pool.send_permanent_failure)
        return pool

    def test_a_tagged_message_never_reaches_the_connection_pool(self, pool):
        transport = InMemoryTransport()

        RealtimeAgentRunner(transport=transport, chat_service=_chat_service()).process(_input_msg(TAGGED))

        [out] = _fetch_output(transport)
        assert json.loads(out.body)["result"] == "ok:hi"
        assert out.attributes["status_code"] == "200"
        pool.dispatch.assert_not_called()

    def test_a_tagged_permanent_failure_is_an_error_body(self, monkeypatch, pool):
        _use_mode(monkeypatch, ExecutionMode.REALTIME)
        transport = InMemoryTransport()

        RealtimeAgentRunner(transport=transport, chat_service=MagicMock()).on_permanent_failure(_input_msg(TAGGED, receive_count=4))

        [out] = _fetch_output(transport)
        assert out.attributes["status_code"] == "500"
        assert "after 3 retries" in json.loads(out.body)["error"]
        pool.send_permanent_failure.assert_not_called()

    def test_an_untagged_message_still_goes_to_the_pool(self, pool):
        RealtimeAgentRunner(transport=InMemoryTransport(), chat_service=MagicMock()).process(_input_msg({"request_id": "r1", "user_id": "u1"}))

        pool.dispatch.assert_called_once()


class TestResponseHandler:
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_a_tagged_reply_is_stored_in_every_mode(self, monkeypatch, mode):
        _use_mode(monkeypatch, mode)
        handler, store, ws = _handler()

        handler.process(_output_msg({"result": "hi", "session_id": "s1"}, {**TAGGED, "user_id": "u1", "status_code": "200"}))

        assert store.get_record("r1") == {"session_id": "s1", "request_id": "r1", "status_code": 200, "body": {"result": "hi", "session_id": "s1"}}
        assert ws.broadcasts == []

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_a_tagged_permanent_failure_stores_a_500_record_in_every_mode(self, monkeypatch, mode):
        _use_mode(monkeypatch, mode)
        handler, store, ws = _handler()

        handler.on_permanent_failure(_output_msg({"result": "hi"}, {**TAGGED, "user_id": "u1"}))

        record = store.get_record("r1")
        assert record["status_code"] == 500
        assert record["body"] == {"error": "Failed to process message after 3 retries", "request_id": "r1", "session_id": "s1"}
        assert ws.broadcasts == []

    def test_a_tagged_reply_without_a_request_id_raises_for_retry(self, monkeypatch):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, _ = _handler()

        with pytest.raises(ValueError, match="request_id"):
            handler.process(_output_msg({"result": "hi"}, {ATTR_PROTOCOL: "mcp"}))

    def test_a_tagged_permanent_failure_without_a_request_id_never_raises(self, monkeypatch, caplog):
        _use_mode(monkeypatch, ExecutionMode.ASYNC)
        handler, _, ws = _handler()

        handler.on_permanent_failure(_output_msg({"result": "hi"}, {ATTR_PROTOCOL: "mcp"}))

        assert "request_id missing" in caplog.text
        assert ws.broadcasts == []

    @pytest.mark.parametrize(
        "mode, message_type",
        [(ExecutionMode.STREAM, WebSocketHandlerABC.MessageType.STREAM_CHUNK), (ExecutionMode.ASYNC, WebSocketHandlerABC.MessageType.CHAT_RESPONSE)],
    )
    def test_an_untagged_websocket_reply_still_broadcasts(self, monkeypatch, mode, message_type):
        _use_mode(monkeypatch, mode)
        handler, store, ws = _handler()

        handler.process(_output_msg({"delta": "hi"}, {"request_id": "r1", "user_id": "u1"}))

        assert [b["message_type"] for b in ws.broadcasts] == [message_type]
        assert store.get_record("r1") is None


class TestIntegrationWins:
    NAME = "byo_pkg.FakeOutboundAdapter"

    class _Adapter(OutboundAdapter):
        name = "byo_pkg.FakeOutboundAdapter"

        def __init__(self):
            self.delivered = []

        async def deliver(self, reply, reply_context):
            self.delivered.append(str(reply))

        async def deliver_error(self, message, reply_context):
            pass

    @pytest.fixture
    def adapter(self):
        from agentkernel.integration.adapter.factory import IntegrationAdapterFactory

        adapter = self._Adapter()
        IntegrationAdapterFactory.reset()
        IntegrationAdapterFactory._cache[self.NAME] = adapter
        yield adapter
        IntegrationAdapterFactory.reset()

    def test_a_message_carrying_both_attributes_is_integration_traffic(self, monkeypatch, adapter):
        _use_mode(monkeypatch, ExecutionMode.REST_SYNC)
        handler, store, _ = _handler()

        handler.process(_output_msg({"result": "hi", "session_id": "s1"}, {**TAGGED, ATTR_INTEGRATION: self.NAME, "status_code": "200"}))

        assert adapter.delivered == ["hi"]
        assert store.get_record("r1") is None
