import json
from unittest.mock import MagicMock, patch

from agentkernel.deployment.aws.serverless.core.router.ws_lambda import LambdaWSHandler, SystemRoutesHandler


def _make_ws_event(user_id="user-1", session_id="s1", request_id="req-1"):
    return {
        "requestContext": {
            "connectionId": "conn-1",
            "domainName": "example.execute-api.us-east-1.amazonaws.com",
            "stage": "prod",
        },
        "body": json.dumps(
            {
                "request_id": request_id,
                "user_id": user_id,
                "body": {
                    "prompt": "Hello",
                    "session_id": session_id,
                },
            }
        ),
    }


def _make_system_routes_handler():
    with (
        patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.AKConfig") as mock_config_cls,
        patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.WebSocketConnectionStore"),
        patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.ChatService"),
    ):
        mock_config = MagicMock()
        mock_config.websocket_api.connection_table.table_name = "connections"
        mock_config.websocket_api.connection_table.ttl = 86400
        mock_config.websocket_api.chat_route = "/chat"
        mock_config.execution.queues.input.url = None
        mock_config_cls.get.return_value = mock_config
        handler = SystemRoutesHandler()
        handler._config = mock_config
    return handler


def test_message_type_includes_stream_chunk():
    assert hasattr(LambdaWSHandler.MessageType, "STREAM_CHUNK")
    assert LambdaWSHandler.MessageType.STREAM_CHUNK.value == "STREAM_CHUNK"


def test_get_chat_handler_by_mode_returns_stream_direct_for_stream_no_queue():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM
    handler._config.execution.queues.input.url = None

    chat_handler = handler._get_chat_handler_by_mode()
    assert chat_handler == handler._handle_stream_direct


def test_get_chat_handler_by_mode_returns_queue_stream_for_stream_with_queue():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM
    handler._config.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123/input"

    chat_handler = handler._get_chat_handler_by_mode()
    assert chat_handler == handler._handle_queue_mode


def test_get_chat_handler_by_mode_returns_direct_chat_for_async_no_queue():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.ASYNC
    handler._config.execution.queues.input.url = None

    chat_handler = handler._get_chat_handler_by_mode()
    assert chat_handler == handler._handle_direct_chat


def test_handle_queue_mode_sends_to_sqs_and_returns_200():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM
    handler._config.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123/input"

    event = _make_ws_event()

    handler.get_user_id = MagicMock(return_value="user-1")

    with (
        patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.AWSWebSocketHandler") as mock_ws_cls,
        patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.SQSHandler") as mock_sqs,
    ):
        mock_ws_cls.construct_endpoint_url.return_value = "https://example.execute-api.us-east-1.amazonaws.com/prod"
        mock_sqs.send_message_to_input_queue.return_value = {"MessageId": "msg-1"}
        mock_sqs.CustomAttribute = MagicMock(side_effect=lambda **kwargs: kwargs)
        mock_sqs.AttributeDataType.STRING = "String"

        status, body = handler._handle_queue_mode(event)

    assert status == 200
    assert body["request_id"] == "req-1"
    mock_sqs.send_message_to_input_queue.assert_called_once()


def test_handle_queue_mode_returns_500_on_error():
    handler = _make_system_routes_handler()

    event = _make_ws_event()
    handler.get_user_id = MagicMock(side_effect=RuntimeError("connection error"))

    status, body = handler._handle_queue_mode(event)

    assert status == 500
    assert body["status"] == "FAILED"


def test_handle_stream_direct_streams_chunks_and_returns_200():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM

    event = _make_ws_event()
    handler.get_user_id = MagicMock(return_value="user-1")
    handler.broadcast = MagicMock()

    def _mock_process_stream_sync(req, sse_format=False):
        yield json.dumps({"delta": "Hello", "done": False, "session_id": "s1"})
        yield json.dumps({"delta": " world", "done": False, "session_id": "s1"})
        yield json.dumps({"done": True, "session_id": "s1"})

    handler._chat_service = MagicMock()
    handler._chat_service.process_stream_chat_sync = _mock_process_stream_sync

    with patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.AWSWebSocketHandler") as mock_ws_cls:
        mock_ws_cls.construct_endpoint_url.return_value = "https://example.execute-api.us-east-1.amazonaws.com/prod"

        status, body = handler._handle_stream_direct(event)

    assert status == 200
    assert handler.broadcast.call_count == 3

    first_call = handler.broadcast.call_args_list[0]
    msg = first_call.kwargs["message"]
    assert first_call.kwargs["message_type"] == handler.MessageType.STREAM_CHUNK
    assert msg["delta"] == "Hello"


def test_handle_stream_direct_broadcasts_error_chunk_on_failure():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM

    event = _make_ws_event()
    handler.get_user_id = MagicMock(return_value="user-1")
    handler.broadcast = MagicMock()

    def _mock_process_stream_sync_error(req, sse_format=False):
        raise ValueError("Agent error")

    handler._chat_service = MagicMock()
    handler._chat_service.process_stream_chat_sync = _mock_process_stream_sync_error

    with patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.AWSWebSocketHandler") as mock_ws_cls:
        mock_ws_cls.construct_endpoint_url.return_value = "https://example.execute-api.us-east-1.amazonaws.com/prod"

        status, body = handler._handle_stream_direct(event)

    assert status == 500
    assert handler.broadcast.call_count >= 1
    last_call = handler.broadcast.call_args_list[-1]
    msg = last_call.kwargs["message"]
    assert last_call.kwargs["message_type"] == handler.MessageType.STREAM_CHUNK
    assert msg.get("error") is not None
    assert msg.get("done") is True


def test_handle_stream_direct_broadcasts_error_chunk_with_session_id_on_failure():
    from agentkernel.core.model import ExecutionMode

    handler = _make_system_routes_handler()
    handler._config.execution.mode = ExecutionMode.STREAM

    event = _make_ws_event(session_id="session-123")
    handler.get_user_id = MagicMock(return_value="user-1")
    handler.broadcast = MagicMock()

    def _mock_process_stream_sync_error(req, sse_format=False):
        raise ValueError("Agent error")

    handler._chat_service = MagicMock()
    handler._chat_service.process_stream_chat_sync = _mock_process_stream_sync_error

    with patch("agentkernel.deployment.aws.serverless.core.router.ws_lambda.AWSWebSocketHandler") as mock_ws_cls:
        mock_ws_cls.construct_endpoint_url.return_value = "https://example.execute-api.us-east-1.amazonaws.com/prod"

        status, body = handler._handle_stream_direct(event)

    assert status == 500
    last_call = handler.broadcast.call_args_list[-1]
    msg = last_call.kwargs["message"]
    assert last_call.kwargs["message_type"] == handler.MessageType.STREAM_CHUNK
    assert msg["session_id"] == "session-123"
