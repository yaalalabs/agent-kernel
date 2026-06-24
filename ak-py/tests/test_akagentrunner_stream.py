import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessStreamAgentRunner


def _make_record(
    body: dict,
    message_group_id: str = "session-1",
    request_id: str = "req-1",
    user_id: str = "user-1",
    endpoint_url: str = "https://example.execute-api.us-east-1.amazonaws.com/prod",
):
    return {
        "body": json.dumps(body),
        "attributes": {
            "MessageGroupId": message_group_id,
            "MessageDeduplicationId": f"{request_id}-dedup",
        },
        "messageAttributes": {
            "request_id": {"stringValue": request_id, "DataType": "String"},
            "user_id": {"stringValue": user_id, "DataType": "String"},
            "endpoint_url": {"stringValue": endpoint_url, "DataType": "String"},
        },
    }


def test_get_record_attributes_extracts_all_fields():
    record = _make_record({"prompt": "hello", "session_id": "s1"})
    attrs = ServerlessStreamAgentRunner._get_record_attributes(record)
    assert attrs["request_id"] == "req-1"
    assert attrs["user_id"] == "user-1"
    assert attrs["endpoint_url"] == "https://example.execute-api.us-east-1.amazonaws.com/prod"
    assert attrs["message_group_id"] == "session-1"


def test_get_record_attributes_raises_when_request_id_missing():
    record = {
        "body": json.dumps({"prompt": "hello", "session_id": "s1"}),
        "attributes": {"MessageGroupId": "session-1"},
        "messageAttributes": {
            "endpoint_url": {"stringValue": "https://example.execute-api.us-east-1.amazonaws.com/prod", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="request_id is required"):
        ServerlessStreamAgentRunner._get_record_attributes(record)


def test_get_record_attributes_raises_when_endpoint_url_missing():
    record = {
        "body": json.dumps({"prompt": "hello", "session_id": "s1"}),
        "attributes": {"MessageGroupId": "session-1"},
        "messageAttributes": {
            "request_id": {"stringValue": "req-1", "DataType": "String"},
        },
    }
    with pytest.raises(ValueError, match="endpoint_url is required"):
        ServerlessStreamAgentRunner._get_record_attributes(record)


def test_parse_body_returns_base_run_request():
    from agentkernel.core.model import BaseRunRequest

    record = _make_record({"prompt": "hello", "session_id": "s1"})
    body = ServerlessStreamAgentRunner._parse_body(record)
    assert isinstance(body, BaseRunRequest)
    assert body.prompt == "hello"
    assert body.session_id == "s1"


def test_send_chunk_to_output_queue_calls_sqs_with_correct_attributes():
    record_attributes = {
        "message_group_id": "session-1",
        "message_deduplication_id": "req-1-dedup",
        "request_id": "req-1",
        "user_id": "user-1",
        "endpoint_url": "https://example.execute-api.us-east-1.amazonaws.com/prod",
    }
    chunk_body = {"delta": "hello", "done": False}

    with patch("agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler") as mock_sqs:
        ServerlessStreamAgentRunner._send_chunk_to_output_queue(
            chunk_body=chunk_body,
            record_attributes=record_attributes,
            chunk_dedup_suffix="0",
        )

    mock_sqs.send_message_to_output_queue.assert_called_once()
    call_kwargs = mock_sqs.send_message_to_output_queue.call_args.kwargs
    assert call_kwargs["message_body"] == chunk_body
    assert call_kwargs["message_group_id"] == "session-1"
    assert call_kwargs["message_deduplication_id"] == "req-1-dedup-0"
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
        patch.object(ServerlessStreamAgentRunner, "_get_chat_service", return_value=mock_chat_service),
        patch("agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler") as mock_sqs,
    ):
        ServerlessStreamAgentRunner.process_message(record)

    assert mock_sqs.send_message_to_output_queue.call_count == 3


def test_on_permanent_failure_sends_error_chunk():
    record = _make_record({"prompt": "hello", "session_id": "s1"})

    with patch("agentkernel.deployment.aws.serverless.akagentrunner.SQSHandler") as mock_sqs:
        ServerlessStreamAgentRunner.max_receive_count = 3
        ServerlessStreamAgentRunner.on_permanent_failure(record)

    mock_sqs.send_message_to_output_queue.assert_called_once()
    call_kwargs = mock_sqs.send_message_to_output_queue.call_args.kwargs
    body = call_kwargs["message_body"]
    assert body.get("error") is not None
    assert body.get("done") is True
