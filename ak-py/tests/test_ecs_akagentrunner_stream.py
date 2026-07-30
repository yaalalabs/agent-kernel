import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.containerized.akagentrunner import ECSStreamAgentRunner
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler


def _make_record(
    body: dict,
    message_id: str = "m1",
    message_group_id: str = "session-1",
    request_id: str = "req-1",
    user_id: str = "user-1",
    endpoint_url: str = "https://example.execute-api.us-east-1.amazonaws.com/prod",
):
    return {
        "MessageId": message_id,
        "Body": json.dumps(body),
        "Attributes": {
            "MessageGroupId": message_group_id,
            "MessageDeduplicationId": f"{request_id}-dedup",
        },
        "MessageAttributes": {
            "request_id": {"StringValue": request_id, "DataType": "String"},
            "user_id": {"StringValue": user_id, "DataType": "String"},
            "endpoint_url": {"StringValue": endpoint_url, "DataType": "String"},
        },
    }


def test_get_record_attributes_extracts_all_fields():
    record = _make_record({"prompt": "hello", "session_id": "s1"})
    attrs = ECSStreamAgentRunner._get_record_attributes(record)
    assert attrs["request_id"] == "req-1"
    assert attrs["user_id"] == "user-1"
    assert attrs["endpoint_url"] == "https://example.execute-api.us-east-1.amazonaws.com/prod"
    assert attrs["message_group_id"] == "session-1"


def test_get_record_attributes_raises_when_request_id_missing():
    record = {
        "MessageId": "m1",
        "Body": json.dumps({"prompt": "hello", "session_id": "s1"}),
        "Attributes": {"MessageGroupId": "session-1"},
        "MessageAttributes": {
            "endpoint_url": {"StringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="request_id is required"):
        ECSStreamAgentRunner._get_record_attributes(record)


def test_get_record_attributes_raises_when_endpoint_url_missing():
    record = {
        "MessageId": "m1",
        "Body": json.dumps({"prompt": "hello", "session_id": "s1"}),
        "Attributes": {"MessageGroupId": "session-1"},
        "MessageAttributes": {
            "request_id": {"StringValue": "req-1", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="endpoint_url is required"):
        ECSStreamAgentRunner._get_record_attributes(record)


def test_send_chunk_to_output_queue_calls_sqs_with_correct_attributes():
    record_attributes = {
        "message_group_id": "session-1",
        "message_deduplication_id": "req-1-dedup",
        "request_id": "req-1",
        "user_id": "user-1",
        "endpoint_url": "https://example.execute-api.us-east-1.amazonaws.com/prod",
    }
    chunk_body = {"delta": "hello", "done": False}

    with patch.object(SQSHandler, "send_message_to_output_queue") as mock_send:
        ECSStreamAgentRunner._send_chunk_to_output_queue(
            chunk_body=chunk_body,
            record_attributes=record_attributes,
            chunk_dedup_suffix="0",
        )

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["message_body"] == chunk_body
    assert call_kwargs["attributes"] == {"message_group_id": "session-1", "message_deduplication_id": "req-1-dedup-0"}
    assert call_kwargs["request_id"] == "req-1"
    assert call_kwargs["user_id"] == "user-1"


def test_process_message_streams_chunks_to_output_queue():
    record = _make_record({"prompt": "hello", "session_id": "s1"})

    def _mock_process_stream_sync(req, sse_format=False):
        yield json.dumps({"delta": "Hello", "done": False, "session_id": "s1"})
        yield json.dumps({"delta": " world", "done": False, "session_id": "s1"})
        yield json.dumps({"done": True, "session_id": "s1"})

    mock_chat_service = MagicMock()
    mock_chat_service.process_stream_chat_sync = _mock_process_stream_sync

    with (
        patch.object(ECSStreamAgentRunner, "_get_chat_service", return_value=mock_chat_service),
        patch.object(SQSHandler, "send_message_to_output_queue") as mock_send,
    ):
        ECSStreamAgentRunner.process_message(record)

    assert mock_send.call_count == 3


def test_on_permanent_failure_sends_error_chunk():
    record = _make_record({"prompt": "hello", "session_id": "s1"})

    with patch.object(SQSHandler, "send_message_to_output_queue") as mock_send:
        ECSStreamAgentRunner.on_permanent_failure(record)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    body = call_kwargs["message_body"]
    assert body.get("error") is not None
    assert body.get("done") is True
    assert body.get("session_id") == "session-1"


def test_on_permanent_failure_catches_own_exceptions():
    """on_permanent_failure must never raise — ECSSQSConsumer relies on this to delete the message."""
    bad_record = {"MessageId": "m1", "Body": "not json", "Attributes": {}, "MessageAttributes": {}}
    ECSStreamAgentRunner.on_permanent_failure(bad_record)
