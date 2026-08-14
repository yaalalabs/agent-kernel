from abc import ABC, abstractmethod
from typing import Any, List, Optional

from ...core.config import AKConfig
from ...core.util.factory import AKConfigError, require_extra, resolve_dotted
from ..envelope import QueueMessage, QueueName


class QueueTransport(ABC):
    """Send side of a queue transport. Process-wide; ``send`` must be safe to call from any thread."""

    @abstractmethod
    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        """Send a message to the given queue.

        :param queue: Destination queue (input or output).
        :param message: Normalized message envelope.
        :return: The underlying transport's send response.
        """
        raise NotImplementedError

    def create_consumer(self, queue: QueueName) -> "TransportConsumer":
        """Create a consumer for the given queue. One consumer instance per consumer thread.

        Built-in transports and bring-your-own subclasses override this; the base raises so a
        send-only transport fails loudly when used on the receive side.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement create_consumer")


class TransportConsumer(ABC):
    """Receive side of a queue transport. One instance per consumer thread: implementations
    need not be thread-safe across instances, only self-contained."""

    # Cap on how long one ``fetch`` may block before the consumer loop re-checks the shutdown
    # event. None accepts the loop's default slicing (about 1 s), which keeps graceful drains
    # prompt. Transports whose long polls are expensive to slice (SQS bills every receive call)
    # override this with their native long-poll ceiling, accepting a drain that may wait one
    # full poll.
    fetch_wait_slice_seconds: Optional[float] = None

    @abstractmethod
    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        """Fetch up to ``batch_size`` messages, blocking up to ``wait_seconds`` (long poll).

        :return: A list of normalized message envelopes (possibly empty).
        """
        raise NotImplementedError

    @abstractmethod
    def ack(self, message: QueueMessage) -> None:
        """Acknowledge/remove a message after successful processing or a handled permanent failure."""
        raise NotImplementedError

    def nack(self, message: QueueMessage) -> None:
        """Request redelivery of a failed message.

        Default is a no-op: transports whose unacknowledged messages return automatically via a
        timeout (SQS visibility timeout, NATS ack_wait) need nothing here.
        """
        return None

    def dead_letter(self, message: QueueMessage) -> None:
        """Final disposition of a message that exhausted ``max_receive_count`` deliveries.

        Called by :class:`~agentkernel.pipeline.consumer.ConsumerLoop` after the component's
        permanent-failure hook has run, in place of :meth:`ack`. The default simply acks (the
        SQS/in_memory behavior: the message is dropped once the hook has surfaced the error);
        transports override to route the message somewhere first (a Kafka dead-letter topic) or
        to use a different terminal operation (a NATS ``term()``).
        """
        self.ack(message)

    def close(self) -> None:
        """Release consumer-owned resources. Default no-op."""
        return None


class QueueTransportFactory:
    """Resolves ``execution.queues.type`` to a transport (#541 house pattern).

    ``in_memory`` and ``sqs`` are available; the remaining built-ins (``kafka``, ``nats``)
    arrive over later #495 iterations, and selecting one before it lands raises
    :class:`AKConfigError`. Any other value is treated as a dotted path to a
    :class:`QueueTransport` subclass (bring-your-own), which must also implement
    ``create_consumer``.
    """

    _BUILTIN_TYPES = ("in_memory", "sqs", "kafka", "nats")

    @staticmethod
    def resolve_type() -> str:
        """Resolve the effective transport type.

        Explicit ``execution.queues.type`` wins; otherwise a configured input queue URL implies
        ``sqs`` (compatibility with pre-#495 configs), else ``in_memory``.
        """
        queues = AKConfig.get().execution.queues
        # The `type` field lands with the in_memory transport iteration; getattr keeps this
        # resolution correct before and after that config change.
        configured = getattr(queues, "type", None) if queues is not None else None
        if configured:
            return configured
        if queues is not None and queues.input is not None and queues.input.url:
            return "sqs"
        return "in_memory"

    @classmethod
    def create(cls) -> QueueTransport:
        """Create the configured transport (send side)."""
        transport_type = cls.resolve_type()
        if transport_type == "in_memory":
            from .in_memory import DEFAULT_ACK_WAIT_SECONDS, DEFAULT_DEDUP_WINDOW_SECONDS, InMemoryTransport

            queues = AKConfig.get().execution.queues
            in_memory_cfg = getattr(queues, "in_memory", None) if queues is not None else None
            return InMemoryTransport(
                ack_wait=in_memory_cfg.ack_wait if in_memory_cfg is not None else DEFAULT_ACK_WAIT_SECONDS,
                dedup_window=in_memory_cfg.dedup_window if in_memory_cfg is not None else DEFAULT_DEDUP_WINDOW_SECONDS,
            )
        if transport_type == "sqs":
            from .sqs import SQSTransport

            queues = AKConfig.get().execution.queues
            input_url = queues.input.url if queues is not None else None
            output_url = queues.output.url if queues is not None else None
            if not input_url or not output_url:
                raise AKConfigError("the sqs transport requires both execution.queues.input.url and execution.queues.output.url")
            return SQSTransport(input_url=input_url, output_url=output_url)
        if transport_type == "kafka":
            with require_extra("kafka", "execution.queues.type: kafka"):
                from .kafka import KafkaTransport

            queues = AKConfig.get().execution.queues
            kafka_config = getattr(queues, "kafka", None) if queues is not None else None
            if kafka_config is None:
                raise AKConfigError("the kafka transport requires an execution.queues.kafka configuration block")
            return KafkaTransport(
                bootstrap_servers=kafka_config.bootstrap_servers,
                input_topic=kafka_config.input_topic,
                output_topic=kafka_config.output_topic,
                group_id=kafka_config.group_id,
                dlq_suffix=kafka_config.dlq_suffix,
                retry_backoff=kafka_config.retry_backoff,
                delivery_timeout=kafka_config.delivery_timeout,
                client_config=kafka_config.client_config,
            )
        if transport_type in cls._BUILTIN_TYPES:
            raise AKConfigError(f"queue transport '{transport_type}' is not available yet (ships in a later #495 iteration)")
        return resolve_dotted(transport_type, base=QueueTransport)()

    @classmethod
    def create_consumer(cls, queue: QueueName) -> TransportConsumer:
        """Create a consumer for the given queue on the configured transport."""
        return cls.create().create_consumer(queue)
