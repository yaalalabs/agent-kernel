import pytest

from agentkernel.core.model import BaseRequest, BaseRunRequest
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler


def test_base_request_from_nested_payload_generates_request_id_and_body():
    payload = {"route": "route-1", "body": {"prompt": "hello", "session_id": "session-1", "agent": "openai"}}

    request = BaseRequest.from_payload(payload)

    assert request.request_id is not None
    assert request.route == "route-1"
    assert request.body is not None
    assert request.body.prompt == "hello"
    assert request.body.session_id == "session-1"
    assert request.body.agent == "openai"


def test_base_request_from_flat_payload_excludes_envelope_fields_from_body():
    payload = {"request_id": "request-1", "route": "route-1", "prompt": "hello", "session_id": "session-1", "agent": "openai"}

    request = BaseRequest.from_payload(payload)

    assert request.request_id == "request-1"
    assert request.route == "route-1"
    assert request.body is not None
    assert request.body.prompt == "hello"
    assert request.body.session_id == "session-1"
    assert request.body.agent == "openai"
    assert "request_id" not in request.body.model_dump()
    assert "route" not in request.body.model_dump()


def test_base_request_from_envelope_only_payload_keeps_body_empty():
    payload = {"request_id": "request-1", "route": "route-1"}

    request = BaseRequest.from_payload(payload)

    assert request.request_id == "request-1"
    assert request.route == "route-1"
    assert request.body is None


def test_base_request_from_route_only_payload_generates_request_id():
    request = BaseRequest.from_payload({"route": "route-1"})

    assert request.request_id is not None
    assert request.route == "route-1"
    assert request.body is None


def test_base_request_from_flat_run_payload_generates_body():
    payload = {"prompt": "hello", "session_id": "session-1", "agent": "openai"}

    request = BaseRequest.from_payload(payload)

    assert request.request_id is not None
    assert request.route is None
    assert request.body is not None
    assert request.body.prompt == "hello"
    assert request.body.session_id == "session-1"
    assert request.body.agent == "openai"


class TestPrincipalIsNotReadFromThePayload:
    """The surface assigns the principal after it parses the payload; a value in the payload is dropped (#603)."""

    FORGED = {"subject": "mallory", "provider": "oidc", "namespace": "https://issuer.example"}

    def test_a_principal_in_the_body_is_dropped(self):
        request = BaseRequest.from_payload(
            {"request_id": "request-1", "body": {"prompt": "hello", "session_id": "session-1", "principal": self.FORGED}}
        )
        assert request.body is not None and request.body.principal is None

    def test_a_principal_on_a_flat_payload_is_dropped(self):
        request = BaseRequest.from_payload({"prompt": "hello", "session_id": "session-1", "principal": self.FORGED})
        assert request.body is not None and request.body.principal is None


class TestUserIdIsNotARequestField:
    """The acting user comes from the credential the surface authenticated, never from the payload (#603)."""

    def test_a_user_id_on_the_envelope_is_refused(self):
        with pytest.raises(ValueError, match="user_id is not a request field"):
            BaseRequest.from_payload({"user_id": "user-1", "body": {"prompt": "hello", "session_id": "session-1"}})

    def test_a_user_id_in_the_body_is_refused(self):
        with pytest.raises(ValueError, match="user_id is not a request field"):
            BaseRequest.from_payload({"request_id": "request-1", "body": {"prompt": "hello", "session_id": "session-1", "user_id": "user-1"}})

    def test_a_user_id_on_a_flat_payload_is_refused(self):
        with pytest.raises(ValueError, match="user_id is not a request field"):
            BaseRequest.from_payload({"prompt": "hello", "session_id": "session-1", "user_id": "user-1"})

    def test_the_envelope_carries_no_user_id(self):
        assert "user_id" not in BaseRequest.from_payload({"route": "route-1"}).model_dump()

    def test_the_chat_request_has_no_user_id_field(self):
        assert "user_id" not in BaseRunRequest.model_fields


def test_sqs_handler_build_send_message_kwargs_serializes_body_and_attributes():
    request_body = BaseRunRequest(prompt="hello", session_id="session-1", agent="openai")
    kwargs = SQSHandler.build_send_message_kwargs(
        message_body=request_body,
        message_group_id="session-1",
        message_deduplication_id="request-1",
        message_attributes=[
            SQSHandler.CustomAttribute(
                name="request_id",
                value="request-1",
                datatype=SQSHandler.AttributeDataType.STRING,
            )
        ],
    )

    assert kwargs["MessageBody"] == '{"prompt": "hello", "agent": "openai", "session_id": "session-1"}'
    assert kwargs["MessageGroupId"] == "session-1"
    assert kwargs["MessageDeduplicationId"] == "request-1"
    assert kwargs["MessageAttributes"]["request_id"]["StringValue"] == "request-1"


def test_sqs_handler_get_message_system_attributes_returns_system_attributes():
    record = {
        "attributes": {
            "MessageGroupId": "session-1",
            "MessageDeduplicationId": "request-1",
        }
    }

    attributes = SQSHandler.get_message_system_attributes(record)

    assert attributes == {"MessageGroupId": "session-1", "MessageDeduplicationId": "request-1"}


def test_sqs_handler_get_message_custom_attributes_flattens_message_attributes():
    record = {
        "messageAttributes": {
            "request_id": {"stringValue": "request-1", "DataType": "String"},
            "user_id": {"StringValue": "user-1", "DataType": "String"},
        }
    }

    attributes = SQSHandler.get_message_custom_attributes(record)

    assert attributes == {"request_id": "request-1", "user_id": "user-1"}


def test_base_request_route_filtered_from_nested_body():
    """Test that route is filtered out when present in nested body dict."""
    payload = {
        "route": "route-1",
        "body": {
            "prompt": "hello",
            "route": "should-be-filtered",
            "session_id": "session-1",
        },
    }

    request = BaseRequest.from_payload(payload)

    assert request.route == "route-1"
    assert request.body is not None
    assert request.body.prompt == "hello"
    assert request.body.session_id == "session-1"
    assert "route" not in request.body.model_dump()
