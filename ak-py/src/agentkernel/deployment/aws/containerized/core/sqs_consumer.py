import asyncio
import inspect
import logging

# Kept so existing patch targets like "….sqs_consumer.time.sleep" still resolve: time is a single
# module object shared with agentkernel.pipeline.consumer, where the poll back-off now lives.
import time  # noqa: F401
from abc import abstractmethod
from typing import Any, Dict, List

import boto3

from .....core.config import AKConfig
from .....pipeline.consumer import ConsumerLoop
from .....pipeline.envelope import QueueMessage
from .....pipeline.transport.base import TransportConsumer
from ....common import QueueConsumer


class _ECSRecordConsumer(TransportConsumer):
    """Adapts an ECSSQSConsumer subclass's classmethod SQS surface to the TransportConsumer interface.

    ``fetch`` delegates to ``cls.poll()`` (raw boto3 records, wrapped into envelopes with
    ``native=record``); ``ack`` delegates to ``cls.delete_message(record)``: so subclass
    overrides keep receiving raw boto3 records, exactly as before #495.
    """

    def __init__(self, consumer_cls: "type[ECSSQSConsumer]"):
        self._consumer_cls = consumer_cls

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        # batch size and wait time are governed by cls.poll() itself (execution.queues.batch_size).
        return [self._consumer_cls._to_envelope(record) for record in self._consumer_cls.poll()]

    def ack(self, message: QueueMessage) -> None:
        self._consumer_cls.delete_message(message.native)


class ECSSQSConsumer(QueueConsumer):
    """
    Base class for ECS services that consume SQS queues via manual long-polling.

    Mirrors LambdaSQSConsumer for ECS deployments: extend this class, implement
    process_message and on_permanent_failure, then call run() as the container
    entry-point.

    Unlike Lambda (push-triggered), ECS actively polls SQS. The poll() template
    method represents one SQS receive cycle: analogous to one Lambda invocation
    calling handle(). Override poll() to customise WaitTimeSeconds or
    MessageAttributeNames; override process_message and on_permanent_failure
    for business logic. MaxNumberOfMessages comes from
    execution.queues.batch_size (set via Terraform, never config.yaml).

    Contract for on_permanent_failure implementations: must be internally
    defensive (catch their own exceptions). If on_permanent_failure raises, the
    message is NOT deleted and will re-enter the permanent-failure path on the
    next visibility-timeout cycle.

    Since #495 the batch/retry/permanent-failure machinery lives in
    agentkernel.pipeline.consumer.ConsumerLoop; this class binds it to the SQS
    classmethod surface, which is unchanged.
    """

    max_receive_count: int = 3  # overridden by classes that inherit this
    num_consumers: int = 10  # overridden by classes that inherit this
    _log = logging.getLogger("ak.ecs.sqsconsumer")
    _client = None

    @classmethod
    @abstractmethod
    def get_queue_url(cls) -> str:
        """
        Return the SQS queue URL to poll.

        Required because ECS must fetch messages actively: there is no ESM to
        configure the queue externally as in Lambda.
        """
        raise NotImplementedError

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            cls._client = boto3.client("sqs")
        return cls._client

    @classmethod
    def poll(cls) -> list:
        """
        Receive one batch of SQS messages and return them.

        Override to customise WaitTimeSeconds or MessageAttributeNames.
        Overriding implementations must return a list of raw boto3
        receive_message records.
        """
        resp = cls._get_client().receive_message(
            QueueUrl=cls.get_queue_url(),
            MaxNumberOfMessages=AKConfig.get().execution.queues.batch_size,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        messages = resp.get("Messages", [])
        return messages

    @classmethod
    @abstractmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process one SQS message.

        :param record: Raw boto3 receive_message record (PascalCase keys:
            Body, MessageId, Attributes, MessageAttributes).
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Called when a message's ApproximateReceiveCount exceeds max_receive_count.
        The message is deleted from the queue immediately after this returns.

        Implementations MUST catch their own exceptions. If this method raises,
        the message is not deleted and will loop back to this path indefinitely.

        :param record: Raw boto3 receive_message record.
        """
        raise NotImplementedError

    @classmethod
    def delete_message(cls, msg: dict) -> None:
        cls._get_client().delete_message(
            QueueUrl=cls.get_queue_url(),
            ReceiptHandle=msg["ReceiptHandle"],
        )

    @classmethod
    def _to_envelope(cls, record: Dict[str, Any]) -> QueueMessage:
        """Wrap a raw boto3 record into the pipeline envelope (native keeps the raw record)."""
        attributes = record.get("Attributes") or {}
        return QueueMessage(
            body=record.get("Body", ""),
            group_id=attributes.get("MessageGroupId"),
            receive_count=int(attributes.get("ApproximateReceiveCount", "1")),
            message_id=record.get("MessageId"),
            native=record,
        )

    @classmethod
    def _dispatch_process_message(cls, message: QueueMessage) -> None:
        """Invoke cls.process_message with the raw record, preserving the original sync/async dispatch."""
        record = message.native
        underlying_fn = getattr(cls.process_message, "__func__", cls.process_message)
        if inspect.iscoroutinefunction(underlying_fn):
            asyncio.run(cls.process_message(record))
        else:
            cls.process_message(record)

    @classmethod
    def _build_consumer_loop(cls) -> ConsumerLoop:
        """Bind a ConsumerLoop to this class's SQS surface; built per call so subclass overrides apply."""
        return ConsumerLoop(
            process=cls._dispatch_process_message,
            on_permanent_failure=lambda message: cls.on_permanent_failure(message.native),
            max_receive_count=cls.max_receive_count,
            num_consumers=cls.num_consumers,
            batch_size=1,  # unused: _ECSRecordConsumer.fetch delegates batching to cls.poll()
            consumer_factory=lambda: _ECSRecordConsumer(cls),
            thread_name_prefix="sqs-consumer",
            logger=cls._log,
        )

    @classmethod
    def _process_single(cls, msg: dict) -> None:
        cls._build_consumer_loop()._process_single(_ECSRecordConsumer(cls), cls._to_envelope(msg))

    @classmethod
    def _consumer_loop(cls) -> None:
        cls._build_consumer_loop()._consumer_loop()

    @classmethod
    def run(cls) -> None:
        """
        Block forever, polling the queue. Call as the container entry-point.

        Starts `num_consumers` long-lived threads, each independently
        polling and processing messages in a loop.
        """
        queue_url = cls.get_queue_url()
        if not queue_url:
            raise ValueError(f"{cls.__name__}: queue URL is required")

        num_consumers = cls.num_consumers
        if num_consumers < 1:
            raise ValueError(f"{cls.__name__}: num_consumers must be >= 1, got {num_consumers}")
        cls._log.info(f"{cls.__name__} starting — queue: {queue_url}, consumers: {num_consumers}")

        cls._build_consumer_loop().run()
