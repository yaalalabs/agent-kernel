from abc import ABC, abstractmethod
from typing import Any, Dict, List


class RawQueueConsumer(ABC):
    """
    Shared abstract interface for queue-backed consumers that process raw provider records
    (e.g. boto3 dicts), regardless of whether the underlying platform pushes messages to the
    consumer (e.g. Lambda + SQS Event Source Mapping) or requires the consumer to actively
    pull them (e.g. ECS long-polling SQS).

    This is the AWS adapters' internal receive-side base (LambdaSQSConsumer, ECSSQSConsumer):
    its defining trait is that subclass overrides receive provider-native records unchanged.
    The public receive abstraction is ``agentkernel.pipeline.transport.TransportConsumer``
    driven by ``agentkernel.pipeline.consumer.ConsumerLoop``, which speaks ``QueueMessage``
    envelopes; new transports implement that, not this.

    Subclasses implement the four primitives below in whatever way fits their delivery
    model; shared retry/failure semantics (max_receive_count) live on this base class.
    """

    max_receive_count: int = 3  # Fallback value, actual configurable values are defined in the subclasses

    @classmethod
    @abstractmethod
    def poll(cls) -> List[Dict[str, Any]]:
        """
        Retrieve the next batch of messages to process.

        :return: A list of raw queue records to be passed to process_message.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def process_message(cls, record: Dict[str, Any]) -> None:
        """
        Process a single queue message.
        :param record: Single message record, as returned by poll().
        :return: None
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def on_permanent_failure(cls, record: Dict[str, Any]) -> None:
        """
        Called when a message is treated as permanently failed (retry limit reached).
        :param record: The message record that exceeded the retry threshold.
        :return: None
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def delete_message(cls, record: Dict[str, Any]) -> None:
        """
        Acknowledge/remove a message from the queue after it has been handled.
        :param record: The message record to acknowledge.
        :return: None
        """
        raise NotImplementedError
