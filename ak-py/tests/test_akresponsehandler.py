import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig
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
        ResponseHandler._broadcast_via_websocket(record)


def test_broadcast_stream_chunk_raises_when_user_id_missing():
    record = {
        "body": json.dumps({"delta": "hello", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="user_id is required"):
        ResponseHandler._broadcast_via_websocket(record)


def test_broadcast_stream_chunk_wraps_with_type_and_broadcasts():
    from agentkernel.deployment.aws.serverless.core.router.ws_lambda import LambdaWSHandler

    record = {
        "body": json.dumps({"delta": "hello", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
            "user_id": {"StringValue": "user-1", "DataType": "String"},
        },
    }

    mock_ws_handler = MagicMock()
    with patch.object(ResponseHandler, "_get_base_ws_handler", return_value=mock_ws_handler):
        ResponseHandler._broadcast_via_websocket(record, message_type=LambdaWSHandler.MessageType.STREAM_CHUNK)

    mock_ws_handler.broadcast.assert_called_once()
    call_kwargs = mock_ws_handler.broadcast.call_args
    endpoint_url = call_kwargs.kwargs["endpoint_url"]
    user_id = call_kwargs.kwargs["user_id"]
    message_type = call_kwargs.kwargs["message_type"]
    broadcasted_message = call_kwargs.kwargs["message"]
    assert endpoint_url == "https://example.execute-api.us-east-1.amazonaws.com/prod"
    assert user_id == "user-1"
    assert message_type == LambdaWSHandler.MessageType.STREAM_CHUNK
    assert broadcasted_message["delta"] == "hello"
    assert broadcasted_message["done"] is False


@patch("agentkernel.deployment.aws.serverless.akresponsehandler.AKConfig")
def test_process_message_async_delta_calls_broadcast_stream_chunk(mock_config_cls):
    from agentkernel.core.model import ExecutionMode
    from agentkernel.deployment.aws.serverless.core.router.ws_lambda import LambdaWSHandler

    mock_config = MagicMock()
    mock_config.execution = _ExecutionConfig(mode=ExecutionMode.ASYNC, message_type="delta")
    mock_config_cls.get.return_value = mock_config

    ResponseHandler._config = mock_config

    record = {
        "body": json.dumps({"delta": "token", "done": False, "session_id": "s1"}),
        "messageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
            "user_id": {"StringValue": "user-1", "DataType": "String"},
            "request_id": {"StringValue": "req-1", "DataType": "String"},
        },
    }

    mock_ws_handler = MagicMock()
    with patch.object(ResponseHandler, "_get_base_ws_handler", return_value=mock_ws_handler):
        ResponseHandler.process_message(record)

    mock_ws_handler.broadcast.assert_called_once()
    call_kwargs = mock_ws_handler.broadcast.call_args
    message_type = call_kwargs.kwargs["message_type"]
    broadcasted = call_kwargs.kwargs["message"]
    assert message_type == LambdaWSHandler.MessageType.STREAM_CHUNK
    assert broadcasted["delta"] == "token"


def _sse_record(request_id="req-1"):
    attrs = {"request_id": {"StringValue": request_id, "DataType": "String"}} if request_id else {}
    return {
        "body": json.dumps({"delta": "tok", "done": False, "session_id": "s1"}),
        "attributes": {"MessageGroupId": "s1"},
        "messageAttributes": attrs,
    }


@pytest.fixture
def sse_store():
    from agentkernel.core.model import ExecutionMode

    config = MagicMock()
    config.execution = _ExecutionConfig(mode=ExecutionMode.REST_SYNC, message_type="delta")
    store = MagicMock()
    store.supports_chunk_streaming.return_value = True
    with (
        patch("agentkernel.deployment.aws.serverless.akresponsehandler.AKConfig") as config_cls,
        patch.object(ResponseHandler, "_get_response_store", return_value=store),
    ):
        config_cls.get.return_value = config
        yield store


def test_sse_chunk_is_added_to_the_store_as_a_chunk(sse_store):
    ResponseHandler.process_message(_sse_record())

    sse_store.add_chunk.assert_called_once_with("req-1", {"delta": "tok", "done": False, "session_id": "s1"})
    sse_store.add_message.assert_not_called()


def test_sse_chunk_without_request_id_raises_so_it_is_retried(sse_store):
    with pytest.raises(ValueError, match="request_id is required"):
        ResponseHandler.process_message(_sse_record(request_id=None))


def test_sse_chunk_on_a_store_that_cannot_stream_raises_config_error(sse_store):
    from agentkernel.core.util.factory import AKConfigError

    sse_store.supports_chunk_streaming.return_value = False
    with pytest.raises(AKConfigError, match="chunk-streaming response store"):
        ResponseHandler.process_message(_sse_record())


def test_sse_permanent_failure_writes_one_error_chunk(sse_store):
    ResponseHandler.on_permanent_failure(_sse_record())

    request_id, chunk = sse_store.add_chunk.call_args.args
    assert request_id == "req-1"
    assert chunk["done"] is True
    assert "Failed to process message" in chunk["error"]
    assert chunk["session_id"] == "s1"
    sse_store.add_message.assert_not_called()


def test_sse_permanent_failure_without_request_id_is_dropped_not_raised(sse_store):
    ResponseHandler.on_permanent_failure(_sse_record(request_id=None))

    sse_store.add_chunk.assert_not_called()
