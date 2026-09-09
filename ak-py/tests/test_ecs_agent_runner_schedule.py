"""Trigger consumption and status forwarding in the ECS agent runner (#629 Phase 2).

Two behaviours: request_id/user_id fall back to the message body (a scheduled trigger cannot
carry SQS message attributes), and the runner no longer discards the status ChatService produced,
so a deferred chat's 202 reaches the REST surface instead of collapsing to 200.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.containerized.akagentrunner import ECSAgentRunner
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler


def _make_record(body: dict, request_id: str | None = "req-1", user_id: str | None = "user-1") -> dict:
    attributes = {}
    if request_id:
        attributes["request_id"] = {"StringValue": request_id, "DataType": "String"}
    if user_id:
        attributes["user_id"] = {"StringValue": user_id, "DataType": "String"}
    return {
        "MessageId": "m1",
        "Body": json.dumps(body),
        "Attributes": {"MessageGroupId": "session-1", "MessageDeduplicationId": "req-1-dedup"},
        "MessageAttributes": attributes,
    }


def _trigger_body(**extras) -> dict:
    return {"prompt": "run the weekly report", "session_id": "s1", "request_id": "sched-run-1", "user_id": "sched-user", **extras}


def _custom_attribute(mock_send, name: str) -> str | None:
    attributes = mock_send.call_args.kwargs["custom_message_attributes"]
    return next((attribute.value for attribute in attributes if attribute.name == name), None)


class TestRequestMetadataBodyFallback:
    def test_body_supplies_request_id_and_user_id_when_attributes_are_absent(self):
        record = _make_record(_trigger_body(), request_id=None, user_id=None)

        attrs = ECSAgentRunner._get_record_attributes(raw_queue_message=record)

        assert attrs["request_id"] == "sched-run-1"
        assert attrs["user_id"] == "sched-user"

    def test_attributes_take_precedence_over_the_body(self):
        record = _make_record(_trigger_body())

        attrs = ECSAgentRunner._get_record_attributes(raw_queue_message=record)

        assert attrs["request_id"] == "req-1"
        assert attrs["user_id"] == "user-1"

    def test_already_validated_body_is_reused_instead_of_reparsed(self):
        """process_message passes the body it validated; the record's own JSON is then irrelevant."""
        record = _make_record({"prompt": "hi", "session_id": "s1"}, request_id=None, user_id=None)
        body = MagicMock(request_id="from-caller", user_id="caller-user")

        attrs = ECSAgentRunner._get_record_attributes(raw_queue_message=record, body=body)

        assert attrs["request_id"] == "from-caller"
        assert attrs["user_id"] == "caller-user"

    def test_missing_in_both_attributes_and_body_raises(self):
        record = _make_record({"prompt": "hi", "session_id": "s1"}, request_id=None, user_id=None)

        with pytest.raises(ValueError, match="request_id is required"):
            ECSAgentRunner._get_record_attributes(raw_queue_message=record)

    def test_unparseable_body_does_not_mask_the_missing_request_id_error(self):
        """on_permanent_failure parses the body itself; a malformed payload must still surface as
        the missing-request_id error rather than a JSON decode error."""
        record = _make_record({"prompt": "hi"}, request_id=None, user_id=None)
        record["Body"] = "not json"

        with pytest.raises(ValueError, match="request_id is required"):
            ECSAgentRunner._get_record_attributes(raw_queue_message=record)


class TestStatusForwarding:
    def test_process_message_forwards_the_chat_service_status(self):
        record = _make_record({"prompt": "hi", "session_id": "s1"})
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (202, {"status": "SCHEDULED", "session_id": "s1"})

        with (
            patch.object(ECSAgentRunner, "_get_chat_service", return_value=chat_service),
            patch.object(SQSHandler, "send_message_to_output_queue") as mock_send,
        ):
            ECSAgentRunner.process_message(record)

        assert _custom_attribute(mock_send, "status_code") == "202"
        assert mock_send.call_args.kwargs["message_body"] == {"status": "SCHEDULED", "session_id": "s1"}

    def test_error_status_is_forwarded_too(self):
        record = _make_record({"prompt": "hi", "session_id": "s1"})
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (500, {"error": "boom", "session_id": "s1"})

        with (
            patch.object(ECSAgentRunner, "_get_chat_service", return_value=chat_service),
            patch.object(SQSHandler, "send_message_to_output_queue") as mock_send,
        ):
            ECSAgentRunner.process_message(record)

        assert _custom_attribute(mock_send, "status_code") == "500"

    def test_permanent_failure_forwards_500(self):
        record = _make_record({"prompt": "hi", "session_id": "s1"})

        with patch.object(SQSHandler, "send_message_to_output_queue") as mock_send:
            ECSAgentRunner.on_permanent_failure(record)

        assert _custom_attribute(mock_send, "status_code") == "500"
        assert "error" in mock_send.call_args.kwargs["message_body"]

    def test_endpoint_url_is_still_forwarded_alongside_the_status(self):
        record = _make_record({"prompt": "hi", "session_id": "s1"})
        record["MessageAttributes"]["endpoint_url"] = {"StringValue": "https://ws.example/prod", "DataType": "String"}
        chat_service = MagicMock()
        chat_service.process_chat_request.return_value = (200, {"result": "ok", "session_id": "s1"})

        with (
            patch.object(ECSAgentRunner, "_get_chat_service", return_value=chat_service),
            patch.object(SQSHandler, "send_message_to_output_queue") as mock_send,
        ):
            ECSAgentRunner.process_message(record)

        assert _custom_attribute(mock_send, "endpoint_url") == "https://ws.example/prod"
        assert _custom_attribute(mock_send, "status_code") == "200"
