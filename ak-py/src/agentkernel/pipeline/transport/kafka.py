"""Kafka queue transport (spec #495 §6).

Kafka gives per-key ordering and durability but none of SQS's per-message bookkeeping: no
visibility timeout, no delivery count, no publish-time deduplication. This transport rebuilds
those from the pieces Kafka does provide, following the pattern in
``docs/specs/495-onprem-kubernetes/research/kafka.md``: record key = ``session_id`` for
per-session order, manual offset commits after processing, an in-process blocking retry, a
dead-letter topic for permanently failed records, and a :class:`BookkeepingStore` for delivery
counts and dedup claims.

Two consequences worth knowing before choosing this transport:

- **One record in flight per partition.** A retry has to be able to redeliver a record before
  any later record from the same partition is processed (offsets commit in order), so the
  consumer hands out at most one record per partition and buffers the rest. Since Kafka hashes
  the key to a partition, sessions that share a partition serialize behind each other: stricter
  than SQS FIFO's per-group blocking. Provision partitions generously (the chart defaults to 32).
- **No timeout-based redelivery.** An unacked record returns only via nack (in-process retry) or
  when an uncommitted offset is reassigned after a crash or rebalance. There is no equivalent of
  a visibility timeout expiring while a worker is alive but stuck.
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
        self._consumer.subscribe([topic])
        # Records fetched from the broker but not yet handed to the loop, per partition.
        self._pending: Dict[int, Deque[Any]] = {}
        # Partitions with a record currently in flight (one at a time: see the module docstring).
        self._in_flight: Dict[int, Any] = {}

    def fetch(self, batch_size: int, wait_seconds: float) -> List[QueueMessage]:
        if not any(self._pending.values()):
            self._buffer(self._consume(batch_size, wait_seconds))
        return self._serve(batch_size)

    def ack(self, message: QueueMessage) -> None:
        record = message.native
        self._consumer.commit(message=record, asynchronous=False)
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
        """Route a permanently failed record to the dead-letter topic, then commit it."""
        record = message.native
        try:
            headers = list(record.headers() or [])
            headers.append((ERROR_HEADER, f"exceeded max_receive_count after {message.receive_count} deliveries".encode()))
            self._producer.produce(topic=self._dlq_topic, value=record.value(), key=record.key(), headers=headers)
            self._producer.poll(0)
            _log.warning(f"Routed message {message.message_id} to dead-letter topic {self._dlq_topic}")
        except Exception:
            # Never block the terminal ack on the DLQ write: the component's permanent-failure
            # hook has already surfaced the error to the caller, and leaving the record
            # uncommitted would replay it forever.
            _log.exception(f"Failed to route message {message.message_id} to dead-letter topic {self._dlq_topic}")
        self.ack(message)

    def close(self) -> None:
        self._consumer.close()

    # -- internals ---------------------------------------------------------------------------

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
        """Whether another record already claimed this envelope's dedup_id."""
        if not message.dedup_id:
            return False
        return not self._bookkeeping.claim_dedup(message.dedup_id, owner=self._record_key(record))

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

    def __init__(
        self,
        bootstrap_servers: str,
        input_topic: str,
        output_topic: str,
        group_id: str,
        dlq_suffix: str = ".dlq",
        retry_backoff: float = 2.0,
        delivery_timeout: float = 30.0,
        client_config: Optional[Dict[str, Any]] = None,
        bookkeeping: Optional[BookkeepingStore] = None,
    ):
        self._bootstrap_servers = bootstrap_servers
        self._topics = {QueueName.INPUT: input_topic, QueueName.OUTPUT: output_topic}
        self._group_id = group_id
        self._dlq_suffix = dlq_suffix
        self._retry_backoff = retry_backoff
        self._delivery_timeout = delivery_timeout
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
        self._produce(
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

    @staticmethod
    def _produce(producer: Producer, **produce_kwargs: Any) -> None:
        """Produce, giving librdkafka a chance to drain if its local queue is full."""
        try:
            producer.produce(**produce_kwargs)
        except BufferError:
            producer.poll(1.0)
            producer.produce(**produce_kwargs)

    @classmethod
    def reset(cls) -> None:
        """Drop the process-wide producer cache. Test isolation only."""
        with cls._producers_lock:
            cls._producers.clear()
