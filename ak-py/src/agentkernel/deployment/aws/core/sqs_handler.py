from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, Mapping, Optional

import boto3
from pydantic import BaseModel, ConfigDict


class SQSHandler:
	"""Shared helper for building and sending SQS messages."""

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

	_sqs_client = None

	@classmethod
	def _get_sqs_client(cls):
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
			message_attribute["StringValue"] = str(custom_attribute.value) # In SQS, numbers also go as string values but with the datatype set to Number
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
		return cls._get_sqs_client().send_message(QueueUrl=queue_url, **message_kwargs)

	@classmethod
	def send_prepared_message(cls, queue_url: str, message_kwargs: Mapping[str, Any]):
		"""Send a pre-built message payload to SQS.

		Use this when the caller has already prepared a boto3-compatible message
		payload and only needs the queue URL injected at send time.

		:param queue_url: The destination SQS queue URL.
		:param message_kwargs: A mapping of boto3 send_message keyword arguments.
		:return: The boto3 send_message response.
		"""
		return cls._get_sqs_client().send_message(QueueUrl=queue_url, **dict(message_kwargs))


# Tell Pydantic to resolve the string annotation for CustomAttribute.datatype after the class is fully defined, which allows us to reference AttributeDataType before it's defined in the class body.
SQSHandler.CustomAttribute.model_rebuild()
