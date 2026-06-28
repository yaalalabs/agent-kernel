import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import boto3


class ECSSQSConsumer(ABC):
    """
    Base class for ECS services that consume SQS queues via manual long-polling.

    Mirrors LambdaSQSConsumer for ECS deployments: extend this class, implement
    process_message and on_permanent_failure, then call run() as the container
    entry-point.

    Unlike Lambda (push-triggered), ECS actively polls SQS. The poll() template
    method represents one SQS receive cycle — analogous to one Lambda invocation
    calling handle(). Override poll() to customise MaxNumberOfMessages,
    WaitTimeSeconds, or MessageAttributeNames; override process_message and
    on_permanent_failure for business logic.

    Contract for on_permanent_failure implementations: must be internally
    defensive (catch their own exceptions). If on_permanent_failure raises, the
    message is NOT deleted and will re-enter the permanent-failure path on the
    next visibility-timeout cycle.
    """

    max_receive_count: int = 3 # overridden by classes that inherit this
    _log = logging.getLogger("ak.ecs.sqsconsumer")

    @classmethod
    @abstractmethod
    def _get_queue_url(cls) -> str:
        """
        Return the SQS queue URL to poll.

        Required because ECS must fetch messages actively — there is no ESM to
        configure the queue externally as in Lambda.
        """
        raise NotImplementedError
    
    @classmethod
    def poll(cls, client) -> list:
        """
        Receive one batch of SQS messages and return them.

        Override to customise MaxNumberOfMessages, WaitTimeSeconds, or
        MessageAttributeNames. Overriding implementations must accept the
        boto3 SQS client as the second argument and return a list of raw
        boto3 receive_message records.
        """
        resp = client.receive_message(
            QueueUrl=cls._get_queue_url(),
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        return resp.get("Messages", [])

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
    def delete_message(cls, client, msg: dict) -> None:
        client.delete_message(
            QueueUrl=cls._get_queue_url(),
            ReceiptHandle=msg["ReceiptHandle"],
        )
    
    @classmethod
    def _process_batch(cls, client, messages: List[Dict[str, Any]]) -> None:
        """
        Dispatch each message in a batch: retry-count check → process_message
        or on_permanent_failure → delete on success.

        On exception: logs and leaves the message in the queue so the
        visibility timeout returns it for a retry — mirroring Lambda's
        batchItemFailures behaviour.
        """
        for msg in messages:
            message_id = msg.get("MessageId", "<unknown>")
            receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
            try:
                if receive_count > cls.max_receive_count:
                    cls._log.warning(
                        f"Message {message_id} exceeded max_receive_count "
                        f"({receive_count} > {cls.max_receive_count})"
                    )
                    cls.on_permanent_failure(msg)
                    cls.delete_message(client, msg)
                    continue

                cls.process_message(msg)
                cls.delete_message(client, msg)

            except Exception:
                cls._log.exception(
                    f"Failed to process message {message_id} — "
                    "leaving in queue for visibility-timeout retry"
                )
                # Do NOT delete — visibility timeout returns it for retry,
                # mirroring how Lambda batchItemFailures re-enqueues a record.

    @classmethod
    def run(cls) -> None:
        """
        Block forever, polling the queue. Call as the container entry-point.

        Analogous to the Lambda runtime invoking handle(event, context) per
        batch: the runtime drives Lambda; run() drives the ECS consumer.
        """
        queue_url = cls._get_queue_url()
        if not queue_url:
            raise ValueError(f"{cls.__name__}: queue URL is required")

        cls._log.info(f"{cls.__name__} starting — queue: {queue_url}")
        client = boto3.client("sqs")
        while True:
            try:
                messages = cls.poll(client)
            except Exception:
                cls._log.exception("Unexpected error in poll loop — retrying in 5 s")
                time.sleep(5)
                continue

            cls._process_batch(client, messages)
