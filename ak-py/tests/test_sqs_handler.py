import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agentkernel.deployment.aws.core.sqs_handler import SQSHandler


class TestSQSHandler:
    """Test cases for SQSHandler class."""

    VALID_INPUT_BODY = {"prompt": "hello", "agent": "test-agent", "session_id": "session-123"}

    def setup_method(self):
        """Reset class variables before each test."""
        SQSHandler._config = None
        SQSHandler._sqs_client = None
        SQSHandler._input_queue_url = None
        SQSHandler._output_queue_url = None

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_success(self, mock_boto3_client, mock_ak_config):
        """Test successful message sending to input queue."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-123", "MD5OfMessageBody": "abc123"}
        mock_boto3_client.return_value = mock_sqs_client

        # Test data
        test_message = {**self.VALID_INPUT_BODY, "data": "payload"}
        test_request_id = "req-123"
        test_user_id = "user-456"

        # Execute
        result = SQSHandler.send_message_to_input_queue(
            message_body=test_message,
            attributes={"message_group_id": "group-1", "message_deduplication_id": "dedup-1"},
            request_id=test_request_id,
            user_id=test_user_id,
        )

        # Verify
        assert result == {"MessageId": "msg-123", "MD5OfMessageBody": "abc123"}
        mock_sqs_client.send_message.assert_called_once()

        # Check the call arguments
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        assert json.loads(call_args[1]["MessageBody"]) == test_message
        assert call_args[1]["MessageGroupId"] == "group-1"  # explicit message_group_id overrides the session_id fallback
        assert call_args[1]["MessageDeduplicationId"] == "dedup-1"

        # Check message attributes
        message_attrs = call_args[1]["MessageAttributes"]
        assert message_attrs["request_id"]["StringValue"] == test_request_id
        assert message_attrs["request_id"]["DataType"] == "String"
        assert message_attrs["user_id"]["StringValue"] == test_user_id
        assert message_attrs["user_id"]["DataType"] == "String"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_minimal_params(self, mock_boto3_client, mock_ak_config):
        """Test sending message to input queue with minimal parameters."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-456"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with only message body
        result = SQSHandler.send_message_to_input_queue(message_body=self.VALID_INPUT_BODY)

        # Verify
        assert result == {"MessageId": "msg-456"}
        mock_sqs_client.send_message.assert_called_once()

        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        assert json.loads(call_args[1]["MessageBody"]) == self.VALID_INPUT_BODY
        assert call_args[1]["MessageGroupId"] == "session-123"  # defaults to the body's session_id
        assert "MessageDeduplicationId" not in call_args[1]
        assert "MessageAttributes" not in call_args[1]  # No attributes when request_id and user_id are None

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_group_id_override(self, mock_boto3_client, mock_ak_config):
        """Test that attributes message_group_id overrides the session_id fallback."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-override"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with an explicit message_group_id different from session_id
        SQSHandler.send_message_to_input_queue(
            message_body=self.VALID_INPUT_BODY,
            attributes={"message_group_id": "custom-group"},
        )

        # Verify
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["MessageGroupId"] == "custom-group"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    def test_send_message_to_input_queue_no_config_url(self, mock_ak_config):
        """Test error when input queue URL is not configured."""
        # Note: @patch decorator patches AKConfig and injects it as mock_ak_config parameter
        # Setup mock with no URL
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = None
        mock_ak_config.get.return_value = mock_config_instance

        # Execute and verify exception
        with pytest.raises(ValueError, match="Input queue URL is not configured in AKConfig"):
            SQSHandler.send_message_to_input_queue(message_body=self.VALID_INPUT_BODY)

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_invalid_body(self, mock_boto3_client, mock_ak_config):
        """Test that input queue bodies missing required fields are rejected."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_boto3_client.return_value = mock_sqs_client

        # Missing session_id
        with pytest.raises(ValidationError):
            SQSHandler.send_message_to_input_queue(message_body={"prompt": "hello"})

        # Missing prompt
        with pytest.raises(ValidationError):
            SQSHandler.send_message_to_input_queue(message_body={"session_id": "session-123"})

        # Plain strings are no longer accepted as input queue bodies
        with pytest.raises(ValidationError):
            SQSHandler.send_message_to_input_queue(message_body="plain string message")

        # Typo'd attribute keys are rejected instead of silently dropping the FIFO ids
        with pytest.raises(ValidationError):
            SQSHandler.send_message_to_input_queue(message_body=self.VALID_INPUT_BODY, attributes={"message_groupid": "group-1"})

        mock_sqs_client.send_message.assert_not_called()

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_without_agent(self, mock_boto3_client, mock_ak_config):
        """Test that agent is optional; the runtime falls back to the first registered agent downstream."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-no-agent"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with a body that has no agent field
        result = SQSHandler.send_message_to_input_queue(message_body={"prompt": "hello", "session_id": "session-123"})

        # Verify: message sent, agent omitted from the serialized body (exclude_none), group id from session_id
        assert result == {"MessageId": "msg-no-agent"}
        call_args = mock_sqs_client.send_message.call_args
        assert json.loads(call_args[1]["MessageBody"]) == {"prompt": "hello", "session_id": "session-123"}
        assert call_args[1]["MessageGroupId"] == "session-123"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_extra_body_fields(self, mock_boto3_client, mock_ak_config):
        """Test that extra message body fields are preserved in the serialized body."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-999"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with a body carrying extra fields, including one that is None
        test_message = {**self.VALID_INPUT_BODY, "files": [{"name": "a.txt"}], "images": None}
        result = SQSHandler.send_message_to_input_queue(message_body=test_message)

        # Verify: extras preserved, None values excluded (matching model_dump(exclude_none=True))
        assert result == {"MessageId": "msg-999"}
        call_args = mock_sqs_client.send_message.call_args
        expected_body = {**self.VALID_INPUT_BODY, "files": [{"name": "a.txt"}]}
        assert json.loads(call_args[1]["MessageBody"]) == expected_body

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_with_model_body(self, mock_boto3_client, mock_ak_config):
        """Test sending a QueueMessageBody instance to the input queue."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-model"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with a validated model instance
        body = SQSHandler.QueueMessageBody(**self.VALID_INPUT_BODY)
        result = SQSHandler.send_message_to_input_queue(message_body=body)

        # Verify
        assert result == {"MessageId": "msg-model"}
        call_args = mock_sqs_client.send_message.call_args
        assert json.loads(call_args[1]["MessageBody"]) == self.VALID_INPUT_BODY
        assert call_args[1]["MessageGroupId"] == "session-123"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_output_queue_success(self, mock_boto3_client, mock_ak_config):
        """Test successful message sending to output queue."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-out-123", "MD5OfMessageBody": "def456"}
        mock_boto3_client.return_value = mock_sqs_client

        # Test data
        test_message = {"result": "success", "data": {"key": "value"}}
        test_request_id = "req-out-123"
        test_user_id = "user-out-456"

        # Execute
        result = SQSHandler.send_message_to_output_queue(
            message_body=test_message,
            attributes={"message_group_id": "output-group", "message_deduplication_id": "output-dedup"},
            request_id=test_request_id,
            user_id=test_user_id,
        )

        # Verify
        assert result == {"MessageId": "msg-out-123", "MD5OfMessageBody": "def456"}
        mock_sqs_client.send_message.assert_called_once()

        # Check the call arguments
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        assert json.loads(call_args[1]["MessageBody"]) == test_message
        assert call_args[1]["MessageGroupId"] == "output-group"
        assert call_args[1]["MessageDeduplicationId"] == "output-dedup"

        # Check message attributes
        message_attrs = call_args[1]["MessageAttributes"]
        assert message_attrs["request_id"]["StringValue"] == test_request_id
        assert message_attrs["request_id"]["DataType"] == "String"
        assert message_attrs["user_id"]["StringValue"] == test_user_id
        assert message_attrs["user_id"]["DataType"] == "String"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_output_queue_minimal_params(self, mock_boto3_client, mock_ak_config):
        """Test sending message to output queue with minimal parameters."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-out-456"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with only message body; output queue bodies stay generic
        result = SQSHandler.send_message_to_output_queue(message_body={"output": "test"})

        # Verify
        assert result == {"MessageId": "msg-out-456"}
        mock_sqs_client.send_message.assert_called_once()

        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        assert json.loads(call_args[1]["MessageBody"]) == {"output": "test"}
        assert "MessageGroupId" not in call_args[1]  # No fallback when the body has no session_id
        assert "MessageAttributes" not in call_args[1]  # No attributes when request_id and user_id are None

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_output_queue_group_id_from_session_id(self, mock_boto3_client, mock_ak_config):
        """Test that the output queue group id falls back to the body's session_id."""
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-out-session"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with a body carrying a session_id and no attributes
        SQSHandler.send_message_to_output_queue(message_body={"output": "test", "session_id": "session-789"})

        # Verify
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["MessageGroupId"] == "session-789"

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    def test_send_message_to_output_queue_no_config_url(self, mock_ak_config):
        """Test error when output queue URL is not configured."""
        # Note: @patch decorator patches AKConfig and injects it as mock_ak_config parameter
        # Setup mock with no URL
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = None
        mock_ak_config.get.return_value = mock_config_instance

        # Execute and verify exception
        with pytest.raises(ValueError, match="Output queue URL is not configured in AKConfig"):
            SQSHandler.send_message_to_output_queue(message_body={"test": "data"})

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_output_queue_with_extra_kwargs(self, mock_boto3_client, mock_ak_config):
        """Test sending message to output queue with extra kwargs."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-out-extra"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with extra kwargs
        result = SQSHandler.send_message_to_output_queue(message_body={"test": "extra"}, DelaySeconds=10, MessageRetentionPeriod=86400)

        # Verify
        assert result == {"MessageId": "msg-out-extra"}
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["DelaySeconds"] == 10
        assert call_args[1]["MessageRetentionPeriod"] == 86400

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_with_extra_kwargs(self, mock_boto3_client, mock_ak_config):
        """Test sending message to input queue with extra kwargs."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-in-extra"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with extra kwargs
        result = SQSHandler.send_message_to_input_queue(message_body=self.VALID_INPUT_BODY, DelaySeconds=5, VisibilityTimeout=300)

        # Verify
        assert result == {"MessageId": "msg-in-extra"}
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["DelaySeconds"] == 5
        assert call_args[1]["VisibilityTimeout"] == 300

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_none_attributes(self, mock_boto3_client, mock_ak_config):
        """Test sending message to input queue with None request_id and user_id."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-none-attrs"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with None attributes
        result = SQSHandler.send_message_to_input_queue(message_body=self.VALID_INPUT_BODY, request_id=None, user_id=None)

        # Verify
        assert result == {"MessageId": "msg-none-attrs"}
        call_args = mock_sqs_client.send_message.call_args
        assert "MessageAttributes" not in call_args[1]  # Should not include MessageAttributes when both are None

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_output_queue_partial_attributes(self, mock_boto3_client, mock_ak_config):
        """Test sending message to output queue with only request_id."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.output.url = "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-partial"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with only request_id
        result = SQSHandler.send_message_to_output_queue(message_body={"test": "partial"}, request_id="req-only", user_id=None)

        # Verify
        assert result == {"MessageId": "msg-partial"}
        call_args = mock_sqs_client.send_message.call_args

        # Should include only request_id attribute
        message_attrs = call_args[1]["MessageAttributes"]
        assert "request_id" in message_attrs
        assert "user_id" not in message_attrs
        assert message_attrs["request_id"]["StringValue"] == "req-only"

    def test_custom_attribute_model(self):
        """Test CustomAttribute model validation."""
        # Test valid attribute
        attr = SQSHandler.CustomAttribute(name="test_attr", value="test_value", datatype=SQSHandler.AttributeDataType.STRING)
        assert attr.name == "test_attr"
        assert attr.value == "test_value"
        assert attr.datatype == SQSHandler.AttributeDataType.STRING

    def test_attribute_data_type_enum(self):
        """Test AttributeDataType enum values."""
        assert SQSHandler.AttributeDataType.STRING == "String"
        assert SQSHandler.AttributeDataType.NUMBER == "Number"
        assert SQSHandler.AttributeDataType.BINARY == "Binary"

    def test_send_message_attributes_model(self):
        """Test SendMessageAttributes model."""
        # Test with all fields
        attrs = SQSHandler.SendMessageAttributes(message_group_id="group-1", message_deduplication_id="dedup-1")
        assert attrs.message_group_id == "group-1"
        assert attrs.message_deduplication_id == "dedup-1"

        # Both fields are optional
        empty_attrs = SQSHandler.SendMessageAttributes()
        assert empty_attrs.message_group_id is None
        assert empty_attrs.message_deduplication_id is None

        # Unknown keys (typos) are rejected instead of being silently ignored
        with pytest.raises(ValidationError):
            SQSHandler.SendMessageAttributes(message_groupid="group-1")

    def test_queue_message_body_model(self):
        """Test QueueMessageBody model."""
        # Required fields plus preserved extras
        body = SQSHandler.QueueMessageBody(prompt="hello", agent="test-agent", session_id="session-1", files=["a.txt"])
        assert body.prompt == "hello"
        assert body.agent == "test-agent"
        assert body.session_id == "session-1"
        assert body.model_dump()["files"] == ["a.txt"]

        # agent is optional and defaults to None
        agentless_body = SQSHandler.QueueMessageBody(prompt="hello", session_id="session-1")
        assert agentless_body.agent is None

        # Missing required fields (session_id here) are rejected
        with pytest.raises(ValidationError):
            SQSHandler.QueueMessageBody(prompt="hello")

        # Both models are inherited from the QueueHandler contract
        from agentkernel.deployment.common.queue_handler import QueueHandler

        assert SQSHandler.QueueMessageBody is QueueHandler.QueueMessageBody
        assert SQSHandler.SendMessageAttributes is QueueHandler.SendMessageAttributes

    def test_sqs_queue_input_message_model(self):
        """Test SQSQueueInputMessage model."""
        # Test with all fields
        message = SQSHandler.SQSQueueInputMessage(
            MessageBody='{"test": "data"}',
            MessageGroupId="group-1",
            MessageDeduplicationId="dedup-1",
            MessageAttributes={"attr1": {"DataType": "String", "StringValue": "value1"}},
        )
        assert message.MessageBody == '{"test": "data"}'
        assert message.MessageGroupId == "group-1"
        assert message.MessageDeduplicationId == "dedup-1"
        assert message.MessageAttributes == {"attr1": {"DataType": "String", "StringValue": "value1"}}

        # Test with minimal fields
        minimal_message = SQSHandler.SQSQueueInputMessage(MessageBody="test body")
        assert minimal_message.MessageBody == "test body"
        assert minimal_message.MessageGroupId is None
        assert minimal_message.MessageDeduplicationId is None
        assert minimal_message.MessageAttributes is None
