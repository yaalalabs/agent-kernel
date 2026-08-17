"""SQS queue transport and the SQS wire-format primitives (spec #495 §5).

The wire-format machinery (attribute models, ``send_message`` kwargs assembly, and the
record-attribute flatteners) lives here so the transport is self-contained within the pipeline.
The deployment-side :class:`SQSHandler` delegates to these same primitives, which keeps the
pipeline and the ECS/Lambda queue mode byte-identical on the wire by construction: pipeline
producers and ECS consumers (or vice versa) interoperate during a migration.
"""

import json
import threading
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

import boto3
from pydantic import BaseModel, ConfigDict

from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer

# SQS caps ReceiveMessage long polls at 20 s.
SQS_MAX_WAIT_SECONDS = 20.0


class AttributeDataType(str, Enum):
    """SQS message-attribute data types."""

    STRING = "String"
    NUMBER = "Number"
    BINARY = "Binary"


class CustomAttribute(BaseModel):
    """User-facing SQS attribute definition."""

    name: str
    value: Any
    datatype: AttributeDataType


class SQSQueueInputMessage(BaseModel):
    """Typed FIFO SQS send_message kwargs excluding QueueUrl."""

    MessageBody: str  # a stringified JSON of the message content
    MessageGroupId: Optional[str] = None
    MessageDeduplicationId: Optional[str] = None
    MessageAttributes: Optional[dict] = None

    model_config = ConfigDict(extra="allow")


def serialize_message_body(message_body: Any) -> str:
    """Convert a message payload into the string body required by SQS.

    Strings are passed through unchanged. Pydantic models are converted with exclude_none=True
    before being JSON encoded, and all other values are serialized with json.dumps.

    :param message_body: The message payload to serialize.
    :return: A string representation suitable for the SQS MessageBody field.
    """
    if isinstance(message_body, str):
        return message_body

    if hasattr(message_body, "model_dump"):
        message_body = message_body.model_dump(exclude_none=True)

    return json.dumps(message_body)


def build_message_attribute(custom_attribute: CustomAttribute) -> Dict[str, Any]:
    """
    Build a boto3-compatible SQS message attribute payload.

    Binary attributes are mapped to BinaryValue. All other attribute types are serialized as
    strings, which matches how SQS expects string and number attributes to be sent.

    :param custom_attribute: The custom attribute definition to convert
    :return: A dictionary shaped for the SQS MessageAttributes field
    """
    message_attribute: Dict[str, Any] = {"DataType": custom_attribute.datatype.value}
    if custom_attribute.datatype == AttributeDataType.BINARY:
        message_attribute["BinaryValue"] = custom_attribute.value
    else:
        message_attribute["StringValue"] = str(custom_attribute.value)  # In SQS, numbers also go as string values but with the datatype set to Number
    return message_attribute


def build_message_attributes(message_attributes: Optional[List[CustomAttribute]]) -> Optional[Dict[str, Any]]:
    """
    Convert a list of custom attributes into an SQS attributes map.

    Duplicate attribute names are rejected because SQS requires each message attribute key to be
    unique.

    :param message_attributes: The custom attributes to convert, or None
    :return: A dictionary of message attributes, or None when no attributes are provided
    :raises ValueError: If duplicate attribute names are found
    """
    if message_attributes is None:
        return None

    built_message_attributes: Dict[str, Any] = {}
    for custom_attribute in message_attributes:
        if custom_attribute.name in built_message_attributes:
            raise ValueError(f"Duplicate SQS message attribute name: {custom_attribute.name}")
        built_message_attributes[custom_attribute.name] = build_message_attribute(custom_attribute)
    return built_message_attributes


def build_send_message_kwargs(
    message_body: Any,
    message_group_id: Optional[str] = None,
    message_deduplication_id: Optional[str] = None,
    message_attributes: Optional[List[CustomAttribute]] = None,
    **extra_kwargs: Any,
) -> Dict[str, Any]:
    """
    Assemble the keyword arguments expected by boto3 send_message.

    This helper normalizes the body, optional FIFO identifiers, and message attributes into a
    single dictionary that can be passed directly to boto3.

    :param message_body: The payload to place in the SQS message body
    :param message_group_id: The FIFO message group id, if required
    :param message_deduplication_id: The FIFO deduplication id, if required
    :param message_attributes: Optional custom SQS message attributes
    :param extra_kwargs: Additional send_message keyword arguments to include
    :return: A dictionary of boto3 send_message keyword arguments
    """
    return SQSQueueInputMessage(
        MessageBody=serialize_message_body(message_body),
        MessageGroupId=message_group_id,
        MessageDeduplicationId=message_deduplication_id,
        MessageAttributes=build_message_attributes(message_attributes),
        **extra_kwargs,
    ).model_dump(exclude_none=True)


def get_message_system_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Return the SQS system attributes from a raw SQS message record.

    Handles both Lambda event records (``attributes`` key, camelCase) and boto3 receive_message
    records (``Attributes`` key, PascalCase).

    :param raw_queue_message_record: Raw SQS record
    :return: A shallow copy of the record's system attributes mapping
    """
    # Lambda uses "attributes", boto3 receive_message uses "Attributes"
    attrs = raw_queue_message_record.get("Attributes") or raw_queue_message_record.get("attributes") or {}
    return dict(attrs)


def get_message_custom_attributes(raw_queue_message_record: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Return the custom SQS message attributes from a raw SQS message record.

    Handles both Lambda event records (``messageAttributes`` key, camelCase) and boto3
    receive_message records (``MessageAttributes`` key, PascalCase).

    :param raw_queue_message_record: Raw SQS record
    :return: A dictionary mapping custom attribute names to their scalar values
    """
    # Lambda uses "messageAttributes", boto3 receive_message uses "MessageAttributes"
    message_attributes = raw_queue_message_record.get("MessageAttributes") or raw_queue_message_record.get("messageAttributes") or {}
    flattened_attributes: Dict[str, Any] = {}
    for attribute_name, attribute in message_attributes.items():
        if isinstance(attribute, Mapping):
            attribute_value = (
                attribute.get("StringValue") or attribute.get("stringValue") or attribute.get("BinaryValue") or attribute.get("binaryValue")
            )
        else:
            attribute_value = attribute
        if attribute_value is not None:
            flattened_attributes[attribute_name] = attribute_value
    return flattened_attributes


class SQSTransportConsumer(TransportConsumer):
    """Consumer over one SQS queue. One boto3 client per instance (single-thread-owned)."""

    # One full-length long poll instead of the ConsumerLoop's default 1 s slices: SQS bills
    # every receive call, so slicing multiplies the empty-poll API cost ~20x. The trade-off is
    # that a graceful drain may wait up to one long-poll interval for the in-progress fetch;
    # default container stop grace periods (30 s on ECS and Kubernetes) accommodate that.
    fetch_wait_slice_seconds = SQS_MAX_WAIT_SECONDS

    def __init__(self, queue_url: str):
        self._queue_url = queue_url
        self._client = boto3.client("sqs")

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=int(min(wait_seconds, SQS_MAX_WAIT_SECONDS)),
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        return [self._to_envelope(record) for record in response.get("Messages", [])]

    def ack(self, message: QueueMessage) -> None:
        self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message.native["ReceiptHandle"])

    # nack: inherited no-op. An unacked message returns via the queue's visibility timeout.

    @staticmethod
    def _to_envelope(record: Mapping[str, Any]) -> QueueMessage:
        system_attributes = get_message_system_attributes(record)
        return QueueMessage(
            body=record.get("Body", ""),
            attributes={name: str(value) for name, value in get_message_custom_attributes(record).items()},
            group_id=system_attributes.get("MessageGroupId"),
            receive_count=int(system_attributes.get("ApproximateReceiveCount", "1")),
            message_id=record.get("MessageId"),
            native=record,
        )


class SQSTransport(QueueTransport):
    """SQS-backed queue transport: the two-process pipeline topology on AWS.

    Queue URLs come from the factory (``execution.queues.input.url`` / ``output.url``), read
    once at construction per the transport config rule (spec §1 rule 4).
    """

    def __init__(self, input_url: str, output_url: str):
        self._queue_urls = {QueueName.INPUT: input_url, QueueName.OUTPUT: output_url}
        self._client = None
        self._client_lock = threading.Lock()

    def _get_client(self):
        """Send-side boto3 client, created lazily under a lock (``send`` may be reached from any
        thread; a built client is safe to share across threads)."""
        with self._client_lock:
            if self._client is None:
                self._client = boto3.client("sqs")
            return self._client

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        send_kwargs = build_send_message_kwargs(
            message_body=message.body,
            message_group_id=message.group_id,
            message_deduplication_id=message.dedup_id,
            message_attributes=self._to_custom_attributes(message.attributes),
        )
        return self._get_client().send_message(QueueUrl=self._queue_urls[queue], **send_kwargs)

    def create_consumer(self, queue: QueueName) -> SQSTransportConsumer:
        return SQSTransportConsumer(self._queue_urls[queue])

    @staticmethod
    def _to_custom_attributes(attributes: Dict[str, str]) -> Optional[List[CustomAttribute]]:
        """Map envelope attributes to SQS custom attributes; None when empty (matches the ECS wire shape)."""
        if not attributes:
            return None
        return [CustomAttribute(name=name, value=value, datatype=AttributeDataType.STRING) for name, value in attributes.items()]
