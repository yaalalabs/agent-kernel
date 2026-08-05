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
