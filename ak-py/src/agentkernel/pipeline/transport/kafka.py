"""Kafka queue transport (spec #495 §6).

Kafka gives per-key ordering and durability but none of SQS's per-message bookkeeping: no
visibility timeout, no delivery count, no publish-time deduplication. This transport rebuilds
those from the pieces Kafka does provide, following the pattern in
``docs/specs/495-onprem-kubernetes/research/kafka.md``: record key = ``session_id`` for
per-session order, manual offset commits after processing, an in-process blocking retry, a
dead-letter topic for permanently failed records, and a :class:`BookkeepingStore` for delivery
counts and dedup claims.

Two consequences worth knowing before choosing this transport:

- **Partitions, not sessions, are the unit of parallelism.** Kafka gives each partition to at
  most one member of a consumer group, and a consumer thread processes its messages one at a
  time, so two sessions whose keys hash to the same partition are handled one after the other.
  That is Kafka's model rather than a choice made here: SQS FIFO, by contrast, lets one queue's
  distinct message groups run concurrently across threads. Concurrency therefore equals the
  number of consumer threads holding partitions, capped by the partition count, which is why
  ``check_consumer_capacity`` warns when a topic has fewer partitions than the configured
  consumers. (The consumer additionally keeps only one record per partition in flight so a retry
  can redeliver before later offsets commit. That costs no throughput, since the loop processes
  a batch sequentially anyway; it only turns one batch into several buffer-served fetches.)
- **No timeout-based redelivery.** An unacked record returns only via nack (in-process retry) or
  when an uncommitted offset is reassigned after a crash, rebalance, or eviction. There is no
  equivalent of a visibility timeout expiring while a worker is alive but stuck.
"""

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition

from ..envelope import QueueMessage, QueueName
from .base import QueueTransport, TransportConsumer
from .bookkeeping import BookkeepingStore, BookkeepingStoreFactory

_log = logging.getLogger("ak.pipeline.transport.kafka")

# Header carrying the envelope's dedup_id (Kafka has no native deduplication).
DEDUP_HEADER = "ak-dedup-id"
# Header added to a record when it is routed to the dead-letter topic.
ERROR_HEADER = "ak-error"

# An agent turn is LLM-bound and can run for many minutes; librdkafka evicts a consumer that
# does not poll within max.poll.interval.ms (default 5 min), which would turn a slow turn into a
# rebalance storm. Raised well past a typical turn and overridable via queues.kafka.client_config.
DEFAULT_MAX_POLL_INTERVAL_MS = 900000

# How long dead_letter waits for the broker to confirm the DLQ copy. Short on purpose: a broken
# dead-letter topic must not stall the consumer, and the delivery callback still logs the outcome
# whenever a later poll services it.
DLQ_CONFIRM_WAIT_SECONDS = 2.0


def _produce_record(producer: Producer, **produce_kwargs: Any) -> None:
    """Produce, giving librdkafka a chance to drain if its local queue is full."""
    try:
        producer.produce(**produce_kwargs)
    except BufferError:
        producer.poll(1.0)
        producer.produce(**produce_kwargs)


class KafkaTransportConsumer(TransportConsumer):
    """Consumer over one Kafka topic. One instance (and one ``confluent_kafka.Consumer``) per
    consumer thread, as the transport contract requires."""

    def __init__(
        self,
        topic: str,
        dlq_topic: str,
        consumer_config: Dict[str, Any],
        bookkeeping: BookkeepingStore,
        producer: Producer,
        retry_backoff: float,
    ):
        self._topic = topic
        self._dlq_topic = dlq_topic
        self._bookkeeping = bookkeeping
        self._producer = producer
        self._retry_backoff = retry_backoff
        self._consumer = Consumer(consumer_config)
        # Records fetched from the broker but not yet handed to the loop, per partition.
        self._pending: Dict[int, Deque[Any]] = {}
        # Partitions with a record currently in flight (one at a time: see the module docstring).
        self._in_flight: Dict[int, Any] = {}
        # Rebalance callbacks run on this thread inside consume(), so they need no locking. They
        # deliberately do not commit anything: work whose offset has not been committed is meant
        # to be redelivered to the partition's new owner, which is the at-least-once contract.
        self._consumer.subscribe([topic], on_revoke=self._on_partitions_gone, on_lost=self._on_partitions_gone)

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        if not any(self._pending.values()):
            self._buffer(self._consume(batch_size, wait_seconds))
        return self._serve(batch_size)

    def ack(self, message: QueueMessage) -> None:
        record = message.native
        try:
            self._consumer.commit(message=record, asynchronous=False)
        except Exception:
            # The commit can fail because this consumer no longer owns the partition (a rebalance
            # or an eviction during a long turn) or because the broker is briefly unreachable.
            # Processing itself succeeded, so the record is not retried here: the uncommitted
            # offset means it is redelivered later, by whoever owns the partition then.
            _log.exception(
                f"Failed to commit offset for message {message.message_id}: processing succeeded but the offset did not advance, "
                "so the record will be redelivered after a rebalance or restart"
            )
        finally:
            self._bookkeeping.clear_attempts(self._record_key(record))
            self._in_flight.pop(record.partition(), None)

    def nack(self, message: QueueMessage) -> None:
        """Requeue the record for an in-process retry after a backoff.

        The offset is never committed, so the record is still owned by this consumer: putting it
        back at its partition's buffer head redelivers it on the next ``fetch`` without a broker
        round trip, and a crash mid-retry leaves it uncommitted for another group member. The
        backoff is bounded by the loop's own shutdown checks rather than a broker timeout.
        """
        record = message.native
        partition = record.partition()
        self._in_flight.pop(partition, None)
        self._pending.setdefault(partition, deque()).appendleft(record)
        if self._retry_backoff > 0:
            time.sleep(self._retry_backoff)

    def dead_letter(self, message: QueueMessage) -> None:
        """Route a permanently failed record to the dead-letter topic, then commit it.

        The original record is committed either way: the component's permanent-failure hook has
        already surfaced the error to the caller, and leaving a poison record uncommitted would
        replay it forever. That makes the DLQ copy the only remaining evidence, so its delivery is
        confirmed rather than assumed, and a failure is always logged.
        """
        record = message.native
        try:
            headers = list(record.headers() or [])
            headers.append((ERROR_HEADER, f"exceeded max_receive_count after {message.receive_count} deliveries".encode()))
            self._produce_to_dead_letter_topic(message, record, headers)
        except Exception:
            _log.exception(f"Failed to route message {message.message_id} to dead-letter topic {self._dlq_topic}")
        self.ack(message)

    def _produce_to_dead_letter_topic(self, message: QueueMessage, record: Any, headers: List[tuple]) -> None:
        """Produce the DLQ copy and wait briefly for the broker to confirm it.

        The delivery callback owns the logging, so an asynchronous failure (most plausibly a
        missing dead-letter topic, since auto-creation is normally off) is reported instead of
        vanishing. Waiting only ``DLQ_CONFIRM_WAIT_SECONDS`` keeps a broken DLQ from stalling the
        consumer: if the confirm has not arrived by then the callback still fires on a later poll
        of this process-wide producer, and a late log beats no log.
        """
        confirmed = threading.Event()

        def _on_delivery(error, delivered_record) -> None:
            confirmed.set()
            if error is not None:
                _log.error(
                    f"Dead-letter delivery failed for message {message.message_id} to topic {self._dlq_topic}: {error}. "
                    "The original record is already committed, so this copy is lost: check that the dead-letter topic "
                    "exists, since topic auto-creation is normally disabled."
                )
            else:
                _log.warning(f"Routed message {message.message_id} to dead-letter topic {self._dlq_topic}")

        _produce_record(
            self._producer,
            topic=self._dlq_topic,
            value=record.value(),
            key=record.key(),
            headers=headers,
            on_delivery=_on_delivery,
        )

        deadline = time.monotonic() + DLQ_CONFIRM_WAIT_SECONDS
        while not confirmed.is_set() and time.monotonic() < deadline:
            self._producer.poll(0.05)
        if not confirmed.is_set():
            _log.warning(
                f"Dead-letter delivery for message {message.message_id} to topic {self._dlq_topic} was not confirmed "
                f"within {DLQ_CONFIRM_WAIT_SECONDS} s; its outcome will be logged when the producer is next polled"
            )

    def close(self) -> None:
        self._consumer.close()

    # -- internals ---------------------------------------------------------------------------

    def _on_partitions_gone(self, consumer: Consumer, partitions: List[TopicPartition]) -> None:
        """Drop buffered and in-flight work for partitions this consumer no longer owns.

        Bound to both ``on_revoke`` (a cooperative rebalance) and ``on_lost`` (partitions taken
        away, e.g. after an eviction). Without this, records fetched into the local buffer would
        be processed here *and* by the partition's new owner: duplicate work that nothing asked
        for. Neither callback reassigns partitions, so librdkafka's default handling applies.
        """
        for topic_partition in partitions:
            dropped = len(self._pending.pop(topic_partition.partition, ()))
            self._in_flight.pop(topic_partition.partition, None)
            if dropped:
                _log.info(f"Partition {topic_partition.partition} of {self._topic} revoked: dropped {dropped} buffered record(s)")

    def _consume(self, batch_size: int, wait_seconds: float) -> List[Any]:
        """One broker fetch, with Kafka's error records filtered out."""
        records = []
        for record in self._consumer.consume(num_messages=max(batch_size, 1), timeout=wait_seconds):
            error = record.error()
            if error is None:
                records.append(record)
                continue
            if error.code() == KafkaError._PARTITION_EOF:
                continue
            raise KafkaException(error)
        return records

    def _buffer(self, records: List[Any]) -> None:
        for record in records:
            self._pending.setdefault(record.partition(), deque()).append(record)

    def _serve(self, batch_size: int) -> List[QueueMessage]:
        """Hand out up to ``batch_size`` records, at most one per partition, skipping duplicates."""
        batch: List[QueueMessage] = []
        for partition, pending in self._pending.items():
            if len(batch) >= batch_size:
                break
            if partition in self._in_flight:
                continue
            while pending:
                record = pending.popleft()
                message = self._to_envelope(record)
                if self._is_duplicate(record, message):
                    self._consumer.commit(message=record, asynchronous=False)
                    _log.info(f"Dropped duplicate message {message.message_id} (dedup_id={message.dedup_id})")
                    continue
                message.receive_count = self._bookkeeping.incr_attempts(self._record_key(record))
                self._in_flight[partition] = record
                batch.append(message)
                break
        return batch

    def _is_duplicate(self, record: Any, message: QueueMessage) -> bool:
        """Whether another record on this topic already claimed the envelope's dedup_id.

        The claim is scoped to the topic, matching SQS, whose deduplication window is per queue.
        A global namespace would be actively wrong here: a reply carries the same dedup id as the
        request that produced it (``AgentRunner`` forwards it), so the input queue's claim would
        make every reply on the output queue look like a duplicate and get dropped.
        """
        if not message.dedup_id:
            return False
        return not self._bookkeeping.claim_dedup(f"{self._topic}:{message.dedup_id}", owner=self._record_key(record))

    @staticmethod
    def _record_key(record: Any) -> str:
        """Stable identity of one Kafka record: what bookkeeping is keyed by."""
        return f"{record.topic()}:{record.partition()}:{record.offset()}"

    @classmethod
    def _to_envelope(cls, record: Any) -> QueueMessage:
        attributes: Dict[str, str] = {}
        dedup_id: Optional[str] = None
        for name, value in record.headers() or []:
            decoded = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
            if name == DEDUP_HEADER:
                dedup_id = decoded
            else:
                attributes[name] = decoded

        key = record.key()
        return QueueMessage(
            body=record.value().decode() if isinstance(record.value(), (bytes, bytearray)) else (record.value() or ""),
            attributes=attributes,
            group_id=key.decode() if isinstance(key, (bytes, bytearray)) else key,
            dedup_id=dedup_id,
            message_id=cls._record_key(record),
            native=record,
        )


class KafkaTransport(QueueTransport):
    """Kafka-backed queue transport: the pipeline's on-prem/self-hosted broker option.

    The producer is process-wide (one per broker configuration) because librdkafka producers own
    background I/O threads and batching state; consumers are per-thread per the contract.
    """

    _producers: Dict[Tuple, Producer] = {}
    _producers_lock = threading.Lock()
    # Topics whose partition capacity has already been reported (once per process per topic).
    _capacity_checked: set = set()
    _capacity_lock = threading.Lock()

    def __init__(
        self,
        bootstrap_servers: str,
        input_topic: str,
        output_topic: str,
        group_id: str,
        dlq_suffix: str = ".dlq",
        retry_backoff: float = 2.0,
        delivery_timeout: float = 30.0,
        metadata_timeout: float = 5.0,
        client_config: Optional[Dict[str, Any]] = None,
        bookkeeping: Optional[BookkeepingStore] = None,
    ):
        self._bootstrap_servers = bootstrap_servers
        self._topics = {QueueName.INPUT: input_topic, QueueName.OUTPUT: output_topic}
        self._group_id = group_id
        self._dlq_suffix = dlq_suffix
        self._retry_backoff = retry_backoff
        self._delivery_timeout = delivery_timeout
        self._metadata_timeout = metadata_timeout
        self._client_config = dict(client_config or {})
        self._bookkeeping = bookkeeping or BookkeepingStoreFactory.create()

    def send(self, queue: QueueName, message: QueueMessage) -> Any:
        """Produce the envelope and wait for the broker's acknowledgement.

        The confirm is synchronous so an unreachable broker surfaces as a failed request rather
        than a silently dropped message (spec error table): the caller is already on a worker
        thread via ``asyncio.to_thread``.
        """
        headers = [(name, str(value).encode()) for name, value in message.attributes.items()]
        if message.dedup_id:
            headers.append((DEDUP_HEADER, message.dedup_id.encode()))

        delivery: Dict[str, Any] = {}

        def _on_delivery(error, record) -> None:
            delivery["error"], delivery["record"] = error, record

        producer = self._get_producer()
        _produce_record(
            producer,
            topic=self._topics[queue],
            value=message.body.encode(),
            key=message.group_id.encode() if message.group_id else None,
            headers=headers,
            on_delivery=_on_delivery,
        )

        deadline = time.monotonic() + self._delivery_timeout
        while not delivery and time.monotonic() < deadline:
            producer.poll(0.05)
        if not delivery:
            raise TimeoutError(f"Kafka delivery not confirmed within {self._delivery_timeout} s for topic {self._topics[queue]}")
        if delivery["error"] is not None:
            raise KafkaException(delivery["error"])

        record = delivery["record"]
        return {"MessageId": f"{record.topic()}:{record.partition()}:{record.offset()}"}

    def check_consumer_capacity(self, queue: QueueName, num_consumers: int) -> None:
        """Warn when a topic has fewer partitions than the consumers configured to read it.

        Kafka assigns each partition to at most one group member, so members beyond the partition
        count sit idle forever: a silent scaling ceiling. Reported once per process per topic;
        any metadata failure is logged at debug and ignored, since a startup check must never
        stop the pipeline from starting.
        """
        topic = self._topics[queue]
        cache_key = (self._bootstrap_servers, topic)
        with self._capacity_lock:
            if cache_key in self._capacity_checked:
                return
            self._capacity_checked.add(cache_key)

        dlq_topic = f"{topic}{self._dlq_suffix}"
        try:
            # No topic filter: one round trip covers the queue and its dead-letter topic, and it
            # cannot nudge a broker with auto-creation enabled into creating either of them.
            metadata = self._get_producer().list_topics(timeout=self._metadata_timeout)
            topic_metadata = metadata.topics.get(topic)
            partitions = 0 if topic_metadata is None or topic_metadata.error is not None else len(topic_metadata.partitions)
            dlq_metadata = metadata.topics.get(dlq_topic)
            dlq_exists = dlq_metadata is not None and dlq_metadata.error is None
        except Exception as e:
            _log.debug(f"Could not read topic metadata for {topic}: {e}")
            return

        if not dlq_exists:
            # Checked here because the alternative is discovering it at the worst moment: the
            # permanently failed record is committed either way, so a missing DLQ silently
            # discards the only copy that would have survived.
            _log.warning(
                f"Dead-letter topic {dlq_topic} does not exist: permanently failed records from {topic} cannot be "
                "preserved. Provision it alongside the queue topics, since topic auto-creation is normally disabled."
            )

        if partitions == 0:
            _log.warning(f"Topic {topic} is unavailable or has no partitions: it must be provisioned before the pipeline can consume it")
        elif partitions < num_consumers:
            _log.warning(
                f"Topic {topic} has {partitions} partition(s) but {num_consumers} consumer(s) are configured for it: "
                f"{num_consumers - partitions} will stay idle, because Kafka assigns each partition to one group member. "
                f"Reduce execution.queues.{queue.value}.no_of_consumers or add partitions (note that adding partitions "
                "re-maps session keys, briefly disturbing per-session ordering)."
            )
        else:
            _log.info(f"Topic {topic}: {partitions} partition(s) for {num_consumers} configured consumer(s) in this replica")

    def create_consumer(self, queue: QueueName) -> KafkaTransportConsumer:
        topic = self._topics[queue]
        return KafkaTransportConsumer(
            topic=topic,
            dlq_topic=f"{topic}{self._dlq_suffix}",
            consumer_config=self._consumer_config(queue),
            bookkeeping=self._bookkeeping,
            producer=self._get_producer(),
            retry_backoff=self._retry_backoff,
        )

    # -- internals ---------------------------------------------------------------------------

    def _consumer_config(self, queue: QueueName) -> Dict[str, Any]:
        """Consumer settings: manual commits, incremental rebalances, agent-turn-sized poll interval."""
        return {
            "bootstrap.servers": self._bootstrap_servers,
            # Input and output are separate topics consumed by separate components: distinct
            # group ids keep their offsets and rebalances independent.
            "group.id": f"{self._group_id}-{queue.value}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "partition.assignment.strategy": "cooperative-sticky",
            "max.poll.interval.ms": DEFAULT_MAX_POLL_INTERVAL_MS,
            **self._client_config,
        }

    def _producer_config(self) -> Dict[str, Any]:
        """Producer settings: idempotence keeps per-partition order across internal retries."""
        return {"bootstrap.servers": self._bootstrap_servers, "enable.idempotence": True, **self._client_config}

    def _get_producer(self) -> Producer:
        config = self._producer_config()
        cache_key = tuple(sorted((name, json.dumps(value, sort_keys=True, default=str)) for name, value in config.items()))
        with self._producers_lock:
            if cache_key not in self._producers:
                self._producers[cache_key] = Producer(config)
            return self._producers[cache_key]

    @classmethod
    def reset(cls) -> None:
        """Drop the process-wide producer cache and capacity-report latch. Test isolation only."""
        with cls._producers_lock:
            cls._producers.clear()
        with cls._capacity_lock:
            cls._capacity_checked.clear()
