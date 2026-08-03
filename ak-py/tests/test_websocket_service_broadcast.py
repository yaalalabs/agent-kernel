from unittest.mock import MagicMock

from agentkernel.deployment.common.websocket_service import WebSocketConnectionStoreABC, WebSocketHandlerABC


class _FakeWebSocketHandler(WebSocketHandlerABC):
    def get_client(self, endpoint_url):
        return None

    def construct_endpoint_url(self, *args, **kwargs):
        return "endpoint"

    def send(self, endpoint_url, connection_id, message):
        self.sent.append(message)


def _make_handler():
    handler = _FakeWebSocketHandler(connection_store=MagicMock(spec=WebSocketConnectionStoreABC))
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

    assert handler.sent == [{"type": WebSocketHandlerABC.MessageType.CHAT_RESPONSE.value, "content": "hello"}]


def test_broadcast_without_message_type_leaves_message_untouched():
    handler = _make_handler()

    handler.broadcast(
        endpoint_url="https://example.execute-api.us-east-1.amazonaws.com/prod",
        message={"content": "hello"},
        connection_ids=["conn-1"],
    )

    assert handler.sent == [{"content": "hello"}]
