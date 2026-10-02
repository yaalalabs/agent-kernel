import json
from unittest.mock import MagicMock, patch

from agentkernel.deployment.aws.containerized.akagentrunner import ECSRealtimeAgentRunner
from agentkernel.pipeline.realtime_pool import RealtimeConnectionPool


def _make_record(requests, session_id: str = "room_01"):
    return {
        "MessageId": "m1",
        "Body": json.dumps({"prompt": "", "session_id": session_id, "agent": "general", "requests": requests}),
        "Attributes": {"MessageGroupId": session_id, "ApproximateReceiveCount": "1"},
        "MessageAttributes": {
            "request_id": {"StringValue": "req-1", "DataType": "String"},
            "user_id": {"StringValue": "u1", "DataType": "String"},
            "integration": {"StringValue": "livekit", "DataType": "String"},
            # Written by the LiveKit gateway as REPLY_CONTEXT_PREFIX + "session_id".
            "reply_session_id": {"StringValue": session_id, "DataType": "String"},
        },
    }


def _process(record):
    conn = MagicMock()
    pool = MagicMock()
    pool.get_connection.return_value = conn
    with patch.object(RealtimeConnectionPool, "initialize", return_value=pool):
        ECSRealtimeAgentRunner.process_message(record)
    return pool, conn


def test_process_message_extracts_reply_context_from_reply_prefixed_attributes():
    """Regression: the ECS runner must read the reply context with REPLY_CONTEXT_PREFIX ("reply_"),
    not a hard-coded "reply_ctx_", or every realtime chunk fails to resolve its outbound adapter."""
    pool, conn = _process(_make_record([{"type": "text", "prompt": "hi"}]))

    pool.get_connection.assert_called_once_with("room_01")
    ctx = conn.update_delivery_context.call_args.kwargs
    assert ctx["request_id"] == "req-1"
    assert ctx["user_id"] == "u1"
    assert ctx["integration"] == "livekit"
    assert ctx["reply_context"] == {"session_id": "room_01"}


def test_process_message_routes_text_and_audio_requests():
    _, conn = _process(
        _make_record(
            [
                {"type": "text", "prompt": "hello"},
                {"type": "voice", "prompt": "", "audio_data": "AAA=", "name": "general"},
            ]
        )
    )

    conn.send_text.assert_called_once_with("hello")
    conn.append_audio.assert_called_once_with("AAA=")


def test_process_message_reuses_existing_connection_without_loading_agent():
    conn = MagicMock()
    pool = MagicMock()
    pool.get_connection.return_value = conn
    chat_service = MagicMock()
    with (
        patch.object(RealtimeConnectionPool, "initialize", return_value=pool),
        patch.object(ECSRealtimeAgentRunner, "_get_chat_service", return_value=chat_service),
    ):
        ECSRealtimeAgentRunner.process_message(_make_record([{"type": "text", "prompt": "hi"}]))

    chat_service.prepare_agent_handler.assert_not_called()
