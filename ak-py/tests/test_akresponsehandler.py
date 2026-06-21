import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler


def test_construct_message_for_store_uses_request_id_from_message_attributes():
    record = {
        "body": json.dumps({"session_id": "session-1", "request_id": "body-request", "result": "ok"}),
        "messageAttributes": {
            "request_id": {"StringValue": "attr-request", "DataType": "String"},
        },
    }

    message = ResponseHandler._construct_message_for_store(record)

    assert message["session_id"] == "session-1"
    assert message["request_id"] == "attr-request"
    assert message["body"] == {"session_id": "session-1", "request_id": "body-request", "result": "ok"}


def test_construct_message_for_store_rejects_request_id_in_body_only():
    record = {
        "body": json.dumps({"session_id": "session-1", "request_id": "body-request", "result": "ok"}),
        "messageAttributes": {},
    }

    with pytest.raises(ValueError, match="request_id is required in SQS message attributes"):
        ResponseHandler._construct_message_for_store(record)


def test_broadcast_stream_chunk_raises_when_endpoint_url_missing():
    record = {
        "body": json.dumps({"delta": "hello", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "user_id": {"StringValue": "user-1", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="endpoint_url is required"):
        ResponseHandler._broadcast_stream_chunk_via_websocket(record)


def test_broadcast_stream_chunk_raises_when_user_id_missing():
    record = {
        "body": json.dumps({"delta": "hello", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="user_id is required"):
        ResponseHandler._broadcast_stream_chunk_via_websocket(record)


def test_broadcast_stream_chunk_wraps_with_type_and_broadcasts():
    record = {
        "body": json.dumps({"delta": "hello", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
            "user_id": {"StringValue": "user-1", "DataType": "String"},
        },
    }

    mock_ws_handler = MagicMock()
    with patch.object(ResponseHandler, "_get_websocket_handler", return_value=mock_ws_handler):
        ResponseHandler._broadcast_stream_chunk_via_websocket(record)

    mock_ws_handler.broadcast.assert_called_once()
    call_kwargs = mock_ws_handler.broadcast.call_args
    broadcasted_message = call_kwargs.kwargs["message"]
    assert broadcasted_message["type"] == "STREAM_CHUNK"
    assert broadcasted_message["delta"] == "hello"
    assert broadcasted_message["done"] is False


@patch("agentkernel.deployment.aws.serverless.akresponsehandler.AKConfig")
def test_process_message_stream_mode_calls_broadcast_stream_chunk(mock_config_cls):
    mock_config = MagicMock()
    mock_config.execution.mode.value = "stream"
    mock_config_cls.get.return_value = mock_config

    from agentkernel.core.model import ExecutionMode

    ResponseHandler._config = MagicMock()
    ResponseHandler._config.execution.mode = ExecutionMode.STREAM

    record = {
        "body": json.dumps({"delta": "token", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
            "user_id": {"StringValue": "user-1", "DataType": "String"},
            "request_id": {"StringValue": "req-1", "DataType": "String"},
        },
    }

    mock_ws_handler = MagicMock()
    with patch.object(ResponseHandler, "_get_websocket_handler", return_value=mock_ws_handler):
        ResponseHandler.process_message(record)

    mock_ws_handler.broadcast.assert_called_once()
    broadcasted = mock_ws_handler.broadcast.call_args.kwargs["message"]
    assert broadcasted["type"] == "STREAM_CHUNK"
    assert broadcasted["delta"] == "token"
