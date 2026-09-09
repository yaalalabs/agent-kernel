"""Trigger consumption in the serverless agent runners (#629 Phase 2).

Same body fallback as the pipeline and ECS runners: a scheduled trigger's request_id/user_id
travel in the message body because EventBridge Scheduler cannot set SQS message attributes.
"""

import json
from unittest.mock import MagicMock

import pytest

from agentkernel.deployment.aws.serverless.akagentrunner import ServerlessAgentRunner, ServerlessStreamAgentRunner

ENDPOINT_URL = "https://example.execute-api.us-east-1.amazonaws.com/prod"


def _make_record(body: dict, request_id: str | None = None, user_id: str | None = None, endpoint_url: str | None = ENDPOINT_URL) -> dict:
    message_attributes = {}
    if request_id:
        message_attributes["request_id"] = {"stringValue": request_id, "DataType": "String"}
    if user_id:
        message_attributes["user_id"] = {"stringValue": user_id, "DataType": "String"}
    if endpoint_url:
        message_attributes["endpoint_url"] = {"stringValue": endpoint_url, "DataType": "String"}
    return {
        "body": json.dumps(body),
        "attributes": {"MessageGroupId": "session-1", "MessageDeduplicationId": "req-1-dedup"},
        "messageAttributes": message_attributes,
    }


def _trigger_body(**extras) -> dict:
    return {"prompt": "run the weekly report", "session_id": "s1", "request_id": "sched-run-1", "user_id": "sched-user", **extras}


@pytest.mark.parametrize("runner", [ServerlessAgentRunner, ServerlessStreamAgentRunner])
class TestRequestMetadataBodyFallback:
    def test_body_supplies_request_id_and_user_id_when_attributes_are_absent(self, runner):
        attrs = runner._get_record_attributes(raw_queue_message=_make_record(_trigger_body()))

        assert attrs["request_id"] == "sched-run-1"
        assert attrs["user_id"] == "sched-user"

    def test_attributes_take_precedence_over_the_body(self, runner):
        record = _make_record(_trigger_body(), request_id="req-1", user_id="user-1")

        attrs = runner._get_record_attributes(raw_queue_message=record)

        assert attrs["request_id"] == "req-1"
        assert attrs["user_id"] == "user-1"

    def test_already_validated_body_is_reused_instead_of_reparsed(self, runner):
        record = _make_record({"prompt": "hi", "session_id": "s1"})
        body = MagicMock(request_id="from-caller", user_id="caller-user")

        attrs = runner._get_record_attributes(raw_queue_message=record, body=body)

        assert attrs["request_id"] == "from-caller"
        assert attrs["user_id"] == "caller-user"

    def test_missing_in_both_attributes_and_body_raises(self, runner):
        record = _make_record({"prompt": "hi", "session_id": "s1"})

        with pytest.raises(ValueError, match="request_id is required"):
            runner._get_record_attributes(raw_queue_message=record)

    def test_unparseable_body_does_not_mask_the_missing_request_id_error(self, runner):
        record = _make_record({"prompt": "hi", "session_id": "s1"})
        record["body"] = "not json"

        with pytest.raises(ValueError, match="request_id is required"):
            runner._get_record_attributes(raw_queue_message=record)
