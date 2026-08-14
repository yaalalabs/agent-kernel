"""SQS queue transport (spec #495 §5).

The send side delegates to :class:`SQSHandler` so the wire format is byte-identical to the
ECS/Lambda queue mode: pipeline producers and ECS consumers (or vice versa) interoperate during
a migration. This delegation is the one sanctioned pipeline-imports-deployment exception to the
package coupling rules (spec §1): the module is only imported when the ``sqs`` transport is
selected, so in_memory/kafka/nats deployments never touch it.
"""

from typing import Any, Dict, List, Mapping, Optional

import boto3

from ...deployment.aws.core.sqs_handler import SQSHandler
from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer

# SQS caps ReceiveMessage long polls at 20 s.
SQS_MAX_WAIT_SECONDS = 20.0


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
        system_attributes = SQSHandler.get_message_system_attributes(record)
        return QueueMessage(
            body=record.get("Body", ""),
            attributes={name: str(value) for name, value in SQSHandler.get_message_custom_attributes(record).items()},
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

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        return SQSHandler.send_message(
            queue_url=self._queue_urls[queue],
            message_body=message.body,
            message_group_id=message.group_id,
            message_deduplication_id=message.dedup_id,
            message_attributes=self._to_custom_attributes(message.attributes),
        )

    def create_consumer(self, queue: QueueName) -> SQSTransportConsumer:
        return SQSTransportConsumer(self._queue_urls[queue])

    @staticmethod
    def _to_custom_attributes(attributes: Dict[str, str]) -> Optional[List[SQSHandler.CustomAttribute]]:
        """Map envelope attributes to SQS custom attributes; None when empty (matches the ECS wire shape)."""
        if not attributes:
            return None
        return [
            SQSHandler.CustomAttribute(name=name, value=value, datatype=SQSHandler.AttributeDataType.STRING) for name, value in attributes.items()
        ]
