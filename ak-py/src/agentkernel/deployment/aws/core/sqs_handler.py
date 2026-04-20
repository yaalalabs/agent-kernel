from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, Mapping, Optional

import boto3
from pydantic import BaseModel, ConfigDict

from ....core.config import AKConfig


class SQSHandler:
    """Shared helper for building and sending SQS messages.

    When used in a Non-Agent Kernel lambda/environment, the following environment variables
    must be exported:
    - AK_EXECUTION__QUEUES__INPUT__URL
    - AK_EXECUTION__QUEUES__OUTPUT__URL
    """

    _sqs_client = None
    _config = None
    _input_queue_url = None
    _output_queue_url = None

    class AttributeDataType(str, Enum):
        STRING = "String"
        NUMBER = "Number"
        BINARY = "Binary"

    class SQSQueueInputMessage(BaseModel):
        """Typed FIFO SQS send_message kwargs excluding QueueUrl."""

        MessageBody: str  # a stringified JSON of the message content
        MessageGroupId: Optional[str] = None
        MessageDeduplicationId: Optional[str] = None
        MessageAttributes: Optional[dict] = None

        model_config = ConfigDict(extra="allow")

    class CustomAttribute(BaseModel):
        """User-facing SQS attribute definition."""

        name: str
        value: Any
        datatype: "SQSHandler.AttributeDataType"

    @classmethod
    def _get_config(cls):
        """Return a cached AKConfig instance.

        :return: A lazily created AKConfig instance.
        """
        if cls._config is None:
            cls._config = AKConfig.get()
        return cls._config

    @classmethod
    def get_input_queue_url(cls):
        """Return the cached input queue URL from config.

        :return: The input queue URL string.
        """
        if cls._input_queue_url is None:
            cls._input_queue_url = cls._get_config().execution.queues.input.url
        return cls._input_queue_url

    @classmethod
    def get_output_queue_url(cls):
        """Return the cached output queue URL from config.

        :return: The output queue URL string.
        """
        if cls._output_queue_url is None:
            cls._output_queue_url = cls._get_config().execution.queues.output.url
        return cls._output_queue_url

    @classmethod
    def get_sqs_client(cls):
        """Return a cached boto3 SQS client.

        :return: A lazily created boto3 SQS client instance.
        """
        if cls._sqs_client is None:
            cls._sqs_client = boto3.client("sqs")
        return cls._sqs_client

    @classmethod
    def _serialize_message_body(cls, message_body: Any) -> str:
        """Convert a message payload into the string body required by SQS.

        Strings are passed through unchanged. Pydantic models are converted with
        exclude_none=True before being JSON encoded, and all other values are
        serialized with json.dumps.

        :param message_body: The message payload to serialize.
        :return: A string representation suitable for the SQS MessageBody field.
        """
        if isinstance(message_body, str):
            return message_body

        if hasattr(message_body, "model_dump"):
            message_body = message_body.model_dump(exclude_none=True)

        return json.dumps(message_body)

    @classmethod
    def _build_message_attribute(cls, custom_attribute: "SQSHandler.CustomAttribute") -> Dict[str, Any]:
        """Build a boto3-compatible SQS message attribute payload.

        Binary attributes are mapped to BinaryValue. All other attribute types are
        serialized as strings, which matches how SQS expects string and number
        attributes to be sent.

        :param custom_attribute: The custom attribute definition to convert.
        :return: A dictionary shaped for the SQS MessageAttributes field.
        """
        message_attribute: Dict[str, Any] = {"DataType": custom_attribute.datatype.value}
        if custom_attribute.datatype == cls.AttributeDataType.BINARY:
            message_attribute["BinaryValue"] = custom_attribute.value
        else:
            message_attribute["StringValue"] = str(
                custom_attribute.value
            )  # In SQS, numbers also go as string values but with the datatype set to Number
        return message_attribute

    @classmethod
    def _build_message_attributes(
        cls,
        message_attributes: list["SQSHandler.CustomAttribute"] | None,
    ) -> Optional[Dict[str, Any]]:
        """Convert a list of custom attributes into an SQS attributes map.

        Duplicate attribute names are rejected because SQS requires each message
        attribute key to be unique.

        :param message_attributes: The custom attributes to convert, or None.
        :return: A dictionary of message attributes, or None when no attributes are provided.
        """
        if message_attributes is None:
            return None

        built_message_attributes: Dict[str, Any] = {}
        for custom_attribute in message_attributes:
            if custom_attribute.name in built_message_attributes:
                raise ValueError(f"Duplicate SQS message attribute name: {custom_attribute.name}")
            built_message_attributes[custom_attribute.name] = cls._build_message_attribute(custom_attribute)
        return built_message_attributes

    @staticmethod
    def get_message_system_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the SQS system attributes from a raw Lambda queue record.

        :param raw_queue_message_record: Raw SQS record from Lambda containing the ``attributes`` block.
        :return: A shallow copy of the record's system ``attributes`` mapping.
        """
        return dict(raw_queue_message_record.get("attributes", {}) or {})

    @staticmethod
    def get_message_custom_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the custom SQS message attributes from a raw Lambda queue record.

        :param raw_queue_message_record: Raw SQS record from Lambda containing ``messageAttributes``.
        :return: A dictionary mapping custom attribute names to their scalar values.
        """
        message_attributes = raw_queue_message_record.get("messageAttributes", {}) or {}
        flattened_attributes: Dict[str, Any] = {}
        for attribute_name, attribute in message_attributes.items():
            if isinstance(attribute, Mapping):
                attribute_value = (
                    attribute.get("stringValue") or attribute.get("StringValue") or attribute.get("binaryValue") or attribute.get("BinaryValue")
                )
            else:
                attribute_value = attribute
            if attribute_value is not None:
                flattened_attributes[attribute_name] = attribute_value
        return flattened_attributes

    @classmethod
    def build_send_message_kwargs(
        cls,
        message_body: Any,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_attributes: list["SQSHandler.CustomAttribute"] | None = None,
        **extra_kwargs: Any,
    ) -> Dict[str, Any]:
        """Assemble the keyword arguments expected by boto3 send_message.

        This helper normalizes the body, optional FIFO identifiers, and message
        attributes into a single dictionary that can be passed directly to boto3.

        :param message_body: The payload to place in the SQS message body.
        :param message_group_id: The FIFO message group id, if required.
        :param message_deduplication_id: The FIFO deduplication id, if required.
        :param message_attributes: Optional custom SQS message attributes.
        :param extra_kwargs: Additional send_message keyword arguments to include.
        :return: A dictionary of boto3 send_message keyword arguments.
        """
        queue_input_message = cls.SQSQueueInputMessage(
            MessageBody=cls._serialize_message_body(message_body),
            MessageGroupId=message_group_id,
            MessageDeduplicationId=message_deduplication_id,
            MessageAttributes=cls._build_message_attributes(message_attributes),
            **extra_kwargs,
        ).model_dump(exclude_none=True)
        return queue_input_message

    @classmethod
    def send_message(
        cls,
        queue_url: str,
        message_body: Any,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_attributes: list["SQSHandler.CustomAttribute"] | None = None,
        **extra_kwargs: Any,
    ):
        """Serialize a payload and send it to SQS.

        The method builds boto3-compatible keyword arguments, injects the target
        queue URL, and delegates the actual send to the cached SQS client.

        :param queue_url: The destination SQS queue URL.
        :param message_body: The payload to send.
        :param message_group_id: The FIFO message group id, if required.
        :param message_deduplication_id: The FIFO deduplication id, if required.
        :param message_attributes: Optional custom SQS message attributes.
        :param extra_kwargs: Additional send_message keyword arguments to include.
        :return: The boto3 send_message response.
        """
        message_kwargs = cls.build_send_message_kwargs(
            message_body=message_body,
            message_group_id=message_group_id,
            message_deduplication_id=message_deduplication_id,
            message_attributes=message_attributes,
            **extra_kwargs,
        )
        return cls.get_sqs_client().send_message(QueueUrl=queue_url, **message_kwargs)

    @classmethod
    def send_prepared_message(cls, queue_url: str, message_kwargs: Mapping[str, Any]):
        """Send a pre-built message payload to SQS.

        Use this when the caller has already prepared a boto3-compatible message
        payload and only needs the queue URL injected at send time.

        :param queue_url: The destination SQS queue URL.
        :param message_kwargs: A mapping of boto3 send_message keyword arguments.
        :return: The boto3 send_message response.
        """
        return cls.get_sqs_client().send_message(QueueUrl=queue_url, **dict(message_kwargs))

    @classmethod
    def send_message_to_input_queue(
        cls,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_body: Optional[Any] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **extra_kwargs: Any,
    ):
        """Send a message to the input queue with standard custom attributes.

        This method handles the common pattern of sending messages to the input queue
        with request_id and user_id as custom message attributes.

        :param message_group_id: The FIFO message group id, if required.
        :param message_deduplication_id: The FIFO deduplication id, if required.
        :param message_body: The payload to send.
        :param request_id: Optional request ID custom attribute.
        :param user_id: Optional user ID custom attribute.
        :param extra_kwargs: Additional send_message keyword arguments to include.
        :return: The boto3 send_message response.
        """
        queue_url = cls.get_input_queue_url()
        if not queue_url:
            raise ValueError("Input queue URL is not configured in AKConfig")

        # Build custom message attributes
        message_attributes = []
        if request_id is not None:
            message_attributes.append(cls.CustomAttribute(name="request_id", value=request_id, datatype=cls.AttributeDataType.STRING))
        if user_id is not None:
            message_attributes.append(cls.CustomAttribute(name="user_id", value=user_id, datatype=cls.AttributeDataType.STRING))

        return cls.send_message(
            queue_url=queue_url,
            message_body=message_body,
            message_group_id=message_group_id,
            message_deduplication_id=message_deduplication_id,
            message_attributes=message_attributes if message_attributes else None,
            **extra_kwargs,
        )

    @classmethod
    def send_message_to_output_queue(
        cls,
        message_group_id: Optional[str] = None,
        message_deduplication_id: Optional[str] = None,
        message_body: Optional[Any] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **extra_kwargs: Any,
    ):
        """Send a message to the output queue with standard custom attributes.

        This method handles the common pattern of sending messages to the output queue
        with request_id and user_id as custom message attributes.

        :param message_group_id: The FIFO message group id, if required.
        :param message_deduplication_id: The FIFO deduplication id, if required.
        :param message_body: The payload to send.
        :param request_id: Optional request ID custom attribute.
        :param user_id: Optional user ID custom attribute.
        :param extra_kwargs: Additional send_message keyword arguments to include.
        :return: The boto3 send_message response.
        """
        queue_url = cls.get_output_queue_url()
        if not queue_url:
            raise ValueError("Output queue URL is not configured in AKConfig")

        # Build custom message attributes
        message_attributes = []
        if request_id is not None:
            message_attributes.append(cls.CustomAttribute(name="request_id", value=request_id, datatype=cls.AttributeDataType.STRING))
        if user_id is not None:
            message_attributes.append(cls.CustomAttribute(name="user_id", value=user_id, datatype=cls.AttributeDataType.STRING))

        return cls.send_message(
            queue_url=queue_url,
            message_body=message_body,
            message_group_id=message_group_id,
            message_deduplication_id=message_deduplication_id,
            message_attributes=message_attributes if message_attributes else None,
            **extra_kwargs,
        )


# Tell Pydantic to resolve the string annotation for CustomAttribute.datatype after the class is fully defined, which allows us to reference AttributeDataType before it's defined in the class body.
SQSHandler.CustomAttribute.model_rebuild()
