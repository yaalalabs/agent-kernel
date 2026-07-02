import asyncio
import inspect
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict

import boto3

from .....core.config import AKConfig
from ....common import ThreadRunner


class ECSSQSConsumer(ABC):
    """
    Base class for ECS services that consume SQS queues via manual long-polling.

    Mirrors LambdaSQSConsumer for ECS deployments: extend this class, implement
    process_message and on_permanent_failure, then call run() as the container
    entry-point.

    Unlike Lambda (push-triggered), ECS actively polls SQS. The poll() template
    method represents one SQS receive cycle — analogous to one Lambda invocation
    calling handle(). Override poll() to customise WaitTimeSeconds or
    MessageAttributeNames; override process_message and on_permanent_failure
    for business logic. MaxNumberOfMessages comes from
    execution.queues.batch_size (set via Terraform, never config.yaml).

    Contract for on_permanent_failure implementations: must be internally
    defensive (catch their own exceptions). If on_permanent_failure raises, the
    message is NOT deleted and will re-enter the permanent-failure path on the
    next visibility-timeout cycle.
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

        Required because ECS must fetch messages actively — there is no ESM to
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
    def _process_single(cls, msg: dict) -> None:
        message_id = msg.get("MessageId", "<unknown>")
        receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        cls._log.debug(f"Processing message {message_id} (receive_count={receive_count})")
        try:
            if receive_count > cls.max_receive_count:
                cls._log.warning(f"Message {message_id} exceeded max_receive_count " f"({receive_count} > {cls.max_receive_count})")
                cls.on_permanent_failure(msg)
                cls.delete_message(msg)
                return

            underlying_fn = getattr(cls.process_message, "__func__", cls.process_message)
            if inspect.iscoroutinefunction(underlying_fn):
                asyncio.run(cls.process_message(msg))
            else:
                cls.process_message(msg)

            cls.delete_message(msg)
            cls._log.debug(f"Processed and deleted message {message_id}")

        except Exception:
            cls._log.exception(f"Failed to process message {message_id} — leaving in queue for visibility-timeout retry")
            # Do NOT delete — visibility timeout returns it for retry

    @classmethod
    def _consumer_loop(cls) -> None:
        while True:
            try:
                messages = cls.poll()
            except Exception:
                cls._log.exception("Unexpected error in poll loop — retrying in 5 s")
                time.sleep(5)
                continue

            if messages:
                cls._log.debug(f"Processing batch of {len(messages)} message(s)")
                for msg in messages:
                    cls._process_single(msg)

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
        cls._log.info(f"{cls.__name__} starting — queue: {queue_url}, consumers: {num_consumers}")

        ThreadRunner.run(
            tasks=[
                ThreadRunner.Task(
                    execution_function=cls._consumer_loop,
                    thread_name=f"sqs-consumer-{i}",
                    stop_all_on_failure=True,
                )
                for i in range(num_consumers)
            ],
            max_workers=num_consumers,
        )
