import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.core.sqs_handler import SQSHandler


class TestSQSHandler:
    """Test cases for SQSHandler class."""

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
        test_message = {"action": "test", "data": "payload"}
        test_request_id = "req-123"
        test_user_id = "user-456"

        # Execute
        result = SQSHandler.send_message_to_input_queue(
            message_body=test_message,
            request_id=test_request_id,
            user_id=test_user_id,
            message_group_id="group-1",
            message_deduplication_id="dedup-1",
        )

        # Verify
        assert result == {"MessageId": "msg-123", "MD5OfMessageBody": "abc123"}
        mock_sqs_client.send_message.assert_called_once()

        # Check the call arguments
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        assert json.loads(call_args[1]["MessageBody"]) == test_message
        assert call_args[1]["MessageGroupId"] == "group-1"
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
        result = SQSHandler.send_message_to_input_queue(message_body={"test": "data"})

        # Verify
        assert result == {"MessageId": "msg-456"}
        mock_sqs_client.send_message.assert_called_once()

        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        assert json.loads(call_args[1]["MessageBody"]) == {"test": "data"}
        assert "MessageAttributes" not in call_args[1]  # No attributes when request_id and user_id are None

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
            SQSHandler.send_message_to_input_queue(message_body={"test": "data"})

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_with_string_body(self, mock_boto3_client, mock_ak_config):
        """Test sending message with string body to input queue."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-789"}
        mock_boto3_client.return_value = mock_sqs_client

        # Execute with string body
        test_string_body = "plain string message"
        result = SQSHandler.send_message_to_input_queue(message_body=test_string_body, request_id="req-789")

        # Verify
        assert result == {"MessageId": "msg-789"}
        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["MessageBody"] == test_string_body  # String should be passed through unchanged

    @patch("agentkernel.deployment.aws.core.sqs_handler.AKConfig")
    @patch("agentkernel.deployment.aws.core.sqs_handler.boto3.client")
    def test_send_message_to_input_queue_with_pydantic_model(self, mock_boto3_client, mock_ak_config):
        """Test sending message with Pydantic model body to input queue."""
        # Note: @patch decorators stack bottom-to-top but inject parameters top-to-bottom:
        # - Bottom patch (boto3.client) becomes first parameter (mock_boto3_client)
        # - Top patch (AKConfig) becomes second parameter (mock_ak_config)
        # Setup mocks
        mock_config_instance = MagicMock()
        mock_config_instance.execution.queues.input.url = "https://sqs.us-east-1.amazonaws.com/123456789/input-queue"
        mock_ak_config.get.return_value = mock_config_instance

        mock_sqs_client = MagicMock()
        mock_sqs_client.send_message.return_value = {"MessageId": "msg-999"}
        mock_boto3_client.return_value = mock_sqs_client

        # Create a mock Pydantic model that properly implements exclude_none behavior
        mock_model = MagicMock()  # this MagicMock is not linked to any @patch, its just a mock BaseModel

        def mock_model_dump(exclude_none=False):
            if exclude_none:
                return {"field1": "value1", "field3": "value3"}  # None values excluded
            return {"field1": "value1", "field2": None, "field3": "value3"}  # All values included

        mock_model.model_dump = mock_model_dump

        # Execute
        result = SQSHandler.send_message_to_input_queue(message_body=mock_model)

        # Verify
        assert result == {"MessageId": "msg-999"}
        call_args = mock_sqs_client.send_message.call_args
        # Should exclude None values from model_dump with exclude_none=True
        expected_body = {"field1": "value1", "field3": "value3"}
        assert json.loads(call_args[1]["MessageBody"]) == expected_body

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
            request_id=test_request_id,
            user_id=test_user_id,
            message_group_id="output-group",
            message_deduplication_id="output-dedup",
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

        # Execute with only message body
        result = SQSHandler.send_message_to_output_queue(message_body={"output": "test"})

        # Verify
        assert result == {"MessageId": "msg-out-456"}
        mock_sqs_client.send_message.assert_called_once()

        call_args = mock_sqs_client.send_message.call_args
        assert call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123456789/output-queue"
        assert json.loads(call_args[1]["MessageBody"]) == {"output": "test"}
        assert "MessageAttributes" not in call_args[1]  # No attributes when request_id and user_id are None

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
        result = SQSHandler.send_message_to_input_queue(message_body={"test": "extra"}, DelaySeconds=5, VisibilityTimeout=300)

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
        result = SQSHandler.send_message_to_input_queue(message_body={"test": "none"}, request_id=None, user_id=None)

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
