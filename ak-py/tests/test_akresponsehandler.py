import json

import pytest

from agentkernel.deployment.aws.serverless.akresponsehandler import ResponseHandler


def test_construct_message_for_store_uses_request_id_from_message_attributes():
    record = {
        "body": json.dumps({"request_id": "body-request", "result": "ok"}),
        "attributes": {"MessageGroupId": "session-1"},
        "messageAttributes": {
            "request_id": {"StringValue": "attr-request", "DataType": "String"},
        },
    }

    message = ResponseHandler._construct_message_for_store(record)

    assert message["session_id"] == "session-1"
    assert message["request_id"] == "attr-request"
    assert message["body"] == {"request_id": "body-request", "result": "ok"}


def test_construct_message_for_store_rejects_request_id_in_body_only():
    record = {
        "body": json.dumps({"request_id": "body-request", "result": "ok"}),
        "attributes": {"MessageGroupId": "session-1"},
        "messageAttributes": {},
    }

    with pytest.raises(ValueError, match="request_id is required in SQS message attributes"):
        ResponseHandler._construct_message_for_store(record)
