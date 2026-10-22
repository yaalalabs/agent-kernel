from unittest.mock import MagicMock

import pytest

from agentkernel.deployment.common.websocket_service import WebSocketConnectionStoreABC, WebSocketHandlerABC


class _FakeWebSocketHandler(WebSocketHandlerABC):
    def get_client(self, endpoint_url):
        return None

    def construct_endpoint_url(self, *args, **kwargs):
        return "endpoint"

    def send(self, endpoint_url, connection_id, message):
        self.sent.append((connection_id, message))


def _make_handler(connection_store=None):
    handler = _FakeWebSocketHandler(connection_store=connection_store or MagicMock(spec=WebSocketConnectionStoreABC))
    handler.sent = []
    return handler


def test_broadcast_message_type_wins_over_caller_provided_type():
    handler = _make_handler()

    handler.broadcast(
        endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
        message={"type": "SOMETHING_ELSE", "content": "hello"},
        connection_ids=["conn-1"],
        message_type=WebSocketHandlerABC.MessageType.CHAT_RESPONSE,
    )

    assert handler.sent == [("conn-1", {"type": WebSocketHandlerABC.MessageType.CHAT_RESPONSE.value, "content": "hello"})]


def test_broadcast_without_message_type_leaves_message_untouched():
    handler = _make_handler()

    handler.broadcast(
        endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
        message={"content": "hello"},
        connection_ids=["conn-1"],
    )

    assert handler.sent == [("conn-1", {"content": "hello"})]


def test_broadcast_user_id_fans_out_to_all_of_their_connections():
    connection_store = MagicMock(spec=WebSocketConnectionStoreABC)
    connection_store.get_connections.return_value = ["conn-1", "conn-2", "conn-3"]
    handler = _make_handler(connection_store)

    handler.broadcast(
        endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
        message={"content": "hello"},
        user_id="user-1",
    )

    connection_store.get_connections.assert_called_once_with("user-1")
    assert handler.sent == [
        ("conn-1", {"content": "hello"}),
        ("conn-2", {"content": "hello"}),
        ("conn-3", {"content": "hello"}),
    ]


def test_broadcast_connection_ids_sends_to_exactly_those_connections():
    connection_store = MagicMock(spec=WebSocketConnectionStoreABC)
    handler = _make_handler(connection_store)

    handler.broadcast(
        endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
        message={"content": "hello"},
        connection_ids=["conn-5", "conn-6"],
    )

    connection_store.get_connections.assert_not_called()
    assert handler.sent == [
        ("conn-5", {"content": "hello"}),
        ("conn-6", {"content": "hello"}),
    ]


def test_broadcast_raises_without_user_id_or_connection_ids():
    handler = _make_handler()

    with pytest.raises(ValueError, match="Provide either user_id or connection_ids"):
        handler.broadcast(
            endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
            message={"content": "hello"},
        )


class TestAWSPushCarriesALabelledReply:
    """The direct (non-queue) WebSocket routes push ChatService's reply body itself.

    `send` writes it with a plain ``json.dumps``, which is only safe because
    ``ResponseBuilder.build_response`` has already coerced the payload. This test runs the real
    chain rather than handing `send` a raw datetime, because a raw datetime is not something the
    push can actually receive — and a test that invents one would argue for a gate here that the
    design deliberately does not have.
    """

    def _handler(self, api_gateway):
        from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler

        handler = AWSWebSocketHandler(connection_store=MagicMock(spec=WebSocketConnectionStoreABC))
        handler.get_client = lambda endpoint_url: api_gateway
        return handler

    def test_a_bypassed_payload_still_pushes_because_the_body_was_coerced(self):
        import datetime
        import json

        from agentkernel.core.chat_service import ResponseBuilder
        from agentkernel.core.model import AgentReplyAny

        reply = AgentReplyAny(content={"a": 1}, media_type="application/a2ui+json")
        bypassed = reply.model_copy(update={"content": {"version": "v1.0", "at": datetime.datetime(2026, 9, 22, 14, 30)}})
        _status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=bypassed)

        api_gateway = MagicMock()
        self._handler(api_gateway).send(endpoint_url="https://example.com/prod", connection_id="conn-1", message=body)

        pushed = json.loads(api_gateway.post_to_connection.call_args.kwargs["Data"].decode("utf-8"))
        assert pushed == {
            "result": {"version": "v1.0", "at": "2026-09-22T14:30:00"},
            "media_type": "application/a2ui+json",
            "session_id": "s1",
        }

    def test_an_ordinary_body_is_byte_identical_to_json_dumps(self):
        import json

        api_gateway = MagicMock()
        body = {"result": "hello", "session_id": "s1", "type": "CHAT_RESPONSE"}

        self._handler(api_gateway).send(endpoint_url="https://example.com/prod", connection_id="conn-1", message=body)

        assert api_gateway.post_to_connection.call_args.kwargs["Data"] == json.dumps(body).encode("utf-8")
