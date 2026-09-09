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

    def check_consumer_capacity(self, queue: QueueName, num_consumers: int) -> None:
        """Report, at startup, whether the backend can actually keep ``num_consumers`` busy.

        Backends that bind work to a fixed number of partitions (Kafka, NATS) leave extra
        consumer threads permanently idle, which is invisible without a check like this. Called
        once per component start with the configured consumer count; implementations must never
        raise or block startup on it. Default no-op: transports whose consumers all compete for
        the same queue (in_memory, SQS) have no such ceiling.
        """
        return None


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
    """Resolves a queues config block to a transport (#541 house pattern).

    All four built-ins are available: ``in_memory``, ``sqs``, ``kafka`` and ``nats``. Any other
    value is treated as a dotted path to a :class:`QueueTransport` subclass (bring-your-own),
    which must also implement ``create_consumer``.

    With no explicit ``queues_config`` every method reads ``execution.queues`` exactly as
    before (#503 seam): the sandbox queue broker passes its own ``_QueuesConfig``-shaped
    ``sandbox.broker.queue`` block (input carries execution requests, output carries
    completions), which resolves and validates identically.
    """

    _BUILTIN_TYPES = ("in_memory", "sqs", "kafka", "nats")

    @staticmethod
    def resolve_type(queues_config: Optional[Any] = None) -> str:
        """Resolve the transport type the application declared.

        Only the block's ``type`` decides, which is why the field is mandatory inside a
        declared queues block: queue coordinates are injected per component by a deployment (a
        Lambda that consumes its input queue through an event source mapping is never given the
        input URL, for instance), so inferring the transport from them made one process resolve
        ``sqs`` while its sibling resolved ``in_memory``. A config with no queues block at all
        runs the single-process default. ``queues_config=None`` reads ``execution.queues``
        (#503 seam: the sandbox queue broker passes its own ``sandbox.broker.queue`` block).
        """
        queues = queues_config if queues_config is not None else AKConfig.get().execution.queues
        if queues is None:
            return "in_memory"
        return queues.type

    @classmethod
    def create(cls, queues_config: Optional[Any] = None, config_path: str = "execution.queues") -> QueueTransport:
        """Create the configured transport (send side).

        ``queues_config=None`` reads ``execution.queues`` (the default path, unchanged); an
        explicit block builds a transport over that block's queues instead, with
        ``config_path`` naming that block so configuration errors point at the right section.
        """
        transport_type = cls.resolve_type(queues_config)
        queues = queues_config if queues_config is not None else AKConfig.get().execution.queues
        if transport_type == "in_memory":
            from .in_memory import DEFAULT_ACK_WAIT_SECONDS, DEFAULT_DEDUP_WINDOW_SECONDS, InMemoryTransport

            in_memory_cfg = getattr(queues, "in_memory", None) if queues is not None else None
            return InMemoryTransport(
                ack_wait=in_memory_cfg.ack_wait if in_memory_cfg is not None else DEFAULT_ACK_WAIT_SECONDS,
                dedup_window=in_memory_cfg.dedup_window if in_memory_cfg is not None else DEFAULT_DEDUP_WINDOW_SECONDS,
            )
        if transport_type == "sqs":
            from .sqs import SQSTransport

            input_url = queues.input.url if queues is not None else None
            output_url = queues.output.url if queues is not None else None
            if not input_url or not output_url:
                raise AKConfigError(f"the sqs transport requires both {config_path}.input.url and {config_path}.output.url")
            return SQSTransport(input_url=input_url, output_url=output_url)
        if transport_type == "kafka":
            with require_extra("kafka", f"{config_path}.type: kafka"):
                from .kafka import KafkaTransport

            kafka_config = getattr(queues, "kafka", None) if queues is not None else None
            if kafka_config is None:
                raise AKConfigError(f"the kafka transport requires a {config_path}.kafka configuration block")
            return KafkaTransport(
                bootstrap_servers=kafka_config.bootstrap_servers,
                input_topic=kafka_config.input_topic,
                output_topic=kafka_config.output_topic,
                group_id=kafka_config.group_id,
                dlq_suffix=kafka_config.dlq_suffix,
                retry_backoff=kafka_config.retry_backoff,
                delivery_timeout=kafka_config.delivery_timeout,
                metadata_timeout=kafka_config.metadata_timeout,
                client_config=kafka_config.client_config,
                config_path=config_path,
            )
        if transport_type == "nats":
            with require_extra("nats", f"{config_path}.type: nats"):
                from .nats import NatsTransport

            nats_config = getattr(queues, "nats", None) if queues is not None else None
            if nats_config is None:
                raise AKConfigError(f"the nats transport requires a {config_path}.nats configuration block")
            return NatsTransport(
                url=nats_config.url,
                input_stream=nats_config.input_stream,
                input_subject_prefix=nats_config.input_subject_prefix,
                output_stream=nats_config.output_stream,
                output_subject_prefix=nats_config.output_subject_prefix,
                partitions=nats_config.partitions,
                ack_wait=nats_config.ack_wait,
                retry_backoff=nats_config.retry_backoff,
                duplicate_window=nats_config.duplicate_window,
                max_age=nats_config.max_age,
                request_timeout=nats_config.request_timeout,
                auto_provision=nats_config.auto_provision,
                # The server ceiling sits one delivery above the loop's own limit, so the
                # component's permanent-failure hook runs and the server is only the backstop.
                max_deliver={
                    QueueName.INPUT: queues.input.max_receive_count + 1,
                    QueueName.OUTPUT: queues.output.max_receive_count + 1,
                },
                config_path=config_path,
            )
        if transport_type in cls._BUILTIN_TYPES:
            # Reachable only if a name is added to _BUILTIN_TYPES before its branch above: a clear
            # error for the next transport author beats falling through to the dotted-path resolver.
            raise AKConfigError(f"queue transport '{transport_type}' is listed as a built-in but has no implementation wired up")
        if "." not in transport_type:
            raise AKConfigError(
                f"unknown queue transport '{transport_type}'; expected one of {list(cls._BUILTIN_TYPES)} "
                "or a dotted path to a QueueTransport subclass"
            )
        return resolve_dotted(transport_type, base=QueueTransport)()

    @classmethod
    def create_consumer(cls, queue: QueueName, queues_config: Optional[Any] = None, config_path: str = "execution.queues") -> TransportConsumer:
        """Create a consumer for the given queue on the configured transport.

        ``queues_config`` threads an explicit block through (#503 seam); ``None`` keeps the
        default ``execution.queues`` path and its full validation.
        """
        return cls.create(queues_config=queues_config, config_path=config_path).create_consumer(queue)
