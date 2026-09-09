import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.model import ExecutionMode
from agentkernel.deployment.aws.containerized.akoutputconsumer import ECSOutputConsumer
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler


def _make_record(
    body: dict,
    message_id: str = "m1",
    message_group_id: str = "session-1",
    request_id: str = "req-1",
    user_id: str = "user-1",
    endpoint_url: str = "https://example.execute-api.us-east-1.amazonaws.com/prod",
):
    attrs = {}
    if request_id:
        attrs["request_id"] = {"StringValue": request_id, "DataType": "String"}
    if user_id:
        attrs["user_id"] = {"StringValue": user_id, "DataType": "String"}
    if endpoint_url:
        attrs["endpoint_url"] = {"StringValue": endpoint_url, "DataType": "String"}
    return {
        "MessageId": message_id,
        "Body": json.dumps(body),
        "Attributes": {"MessageGroupId": message_group_id},
        "MessageAttributes": attrs,
    }


@pytest.fixture(autouse=True)
def _reset_websocket_handler():
    ECSOutputConsumer._websocket_handler = None
    yield
    ECSOutputConsumer._websocket_handler = None


@pytest.fixture
def _stream_mode(monkeypatch):
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", ExecutionMode.STREAM)


@pytest.fixture
def _async_mode(monkeypatch):
    monkeypatch.setattr(ECSOutputConsumer._config.execution, "mode", ExecutionMode.ASYNC)


def test_broadcast_via_websocket_raises_when_endpoint_url_missing():
    record = _make_record({"delta": "hi"}, endpoint_url=None)
    with pytest.raises(ValueError, match="endpoint_url is required"):
        ECSOutputConsumer._broadcast_via_websocket(record, message_type=AWSWebSocketHandler.MessageType.STREAM_CHUNK)


def test_broadcast_via_websocket_raises_when_user_id_missing():
    record = _make_record({"delta": "hi"}, user_id=None)
    with pytest.raises(ValueError, match="user_id is required"):
        ECSOutputConsumer._broadcast_via_websocket(record, message_type=AWSWebSocketHandler.MessageType.STREAM_CHUNK)


def test_broadcast_via_websocket_uses_given_message_type():
    record = _make_record({"delta": "hi", "done": False})
    mock_ws_handler = MagicMock()
    with patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler):
        ECSOutputConsumer._broadcast_via_websocket(record, message_type=AWSWebSocketHandler.MessageType.STREAM_CHUNK)

    mock_ws_handler.broadcast.assert_called_once()
    kwargs = mock_ws_handler.broadcast.call_args.kwargs
    assert kwargs["message_type"] == AWSWebSocketHandler.MessageType.STREAM_CHUNK
    assert kwargs["message"] == {"delta": "hi", "done": False}
    assert kwargs["user_id"] == "user-1"
    assert kwargs["endpoint_url"] == "https://example.execute-api.us-east-1.amazonaws.com/prod"


def test_process_message_stream_mode_broadcasts_stream_chunk(_stream_mode):
    record = _make_record({"delta": "token", "done": False})
    mock_ws_handler = MagicMock()
    mock_store = MagicMock()

    with (
        patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler),
        patch.object(ECSOutputConsumer, "_get_response_store", return_value=mock_store),
    ):
        ECSOutputConsumer.process_message(record)

    mock_ws_handler.broadcast.assert_called_once()
    assert mock_ws_handler.broadcast.call_args.kwargs["message_type"] == AWSWebSocketHandler.MessageType.STREAM_CHUNK
    mock_store.add_message.assert_not_called()


def test_process_message_async_mode_still_broadcasts_chat_response(_async_mode):
    record = _make_record({"result": "ok"})
    mock_ws_handler = MagicMock()

    with patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler):
        ECSOutputConsumer.process_message(record)

    mock_ws_handler.broadcast.assert_called_once()
    assert mock_ws_handler.broadcast.call_args.kwargs["message_type"] == AWSWebSocketHandler.MessageType.CHAT_RESPONSE


def test_on_permanent_failure_async_mode_broadcasts_system_response(_async_mode):
    """Regression: ASYNC permanent-failure errors must stay SYSTEM_RESPONSE, not collapse to CHAT_RESPONSE."""
    record = _make_record({"result": "ok"})
    mock_ws_handler = MagicMock()

    with patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler):
        ECSOutputConsumer.on_permanent_failure(record)

    mock_ws_handler.broadcast.assert_called_once()
    kwargs = mock_ws_handler.broadcast.call_args.kwargs
    assert kwargs["message_type"] == AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE
    assert kwargs["message"]["error"] is not None
    assert kwargs["message"]["session_id"] == "session-1"


def test_on_permanent_failure_stream_mode_broadcasts_error_chunk(_stream_mode):
    record = _make_record({"delta": "token"})
    mock_ws_handler = MagicMock()

    with patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler):
        ECSOutputConsumer.on_permanent_failure(record)

    mock_ws_handler.broadcast.assert_called_once()
    kwargs = mock_ws_handler.broadcast.call_args.kwargs
    assert kwargs["message_type"] == AWSWebSocketHandler.MessageType.STREAM_CHUNK
    assert kwargs["message"]["error"] is not None
    assert kwargs["message"]["done"] is True
    assert kwargs["message"]["session_id"] == "session-1"


def test_on_permanent_failure_stream_mode_warns_when_endpoint_url_missing(_stream_mode, caplog):
    record = _make_record({"delta": "token"}, endpoint_url=None)
    mock_ws_handler = MagicMock()

    with patch.object(ECSOutputConsumer, "_get_websocket_handler", return_value=mock_ws_handler):
        with caplog.at_level("WARNING"):
            ECSOutputConsumer.on_permanent_failure(record)

    mock_ws_handler.broadcast.assert_not_called()
    assert any("endpoint_url or user_id missing" in r.message for r in caplog.records)
