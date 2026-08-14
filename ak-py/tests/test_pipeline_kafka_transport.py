"""Kafka transport (spec #495 §6) over a fake in-memory cluster.

The fake reproduces the Kafka behaviors the transport depends on: append-only per-partition
logs, a fetch position that advances independently of committed offsets, manual commits, and
delivery callbacks. Partition assignment gives each distinct record key its own partition, which
is what murmur2 hashing achieves in practice and keeps the semantics assertions deterministic;
``TestHeadOfLineBlocking`` overrides it to force a collision and pin the documented tradeoff.
"""

import logging
from typing import Any, Dict, List, Optional

import pytest
from confluent_kafka import KafkaError, KafkaException

from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport import kafka as kafka_module
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.bookkeeping import InMemoryBookkeepingStore
from agentkernel.pipeline.transport.kafka import DEDUP_HEADER, DEFAULT_MAX_POLL_INTERVAL_MS, ERROR_HEADER, KafkaTransport

INPUT_TOPIC = "agent-input"
OUTPUT_TOPIC = "agent-output"
BOOTSTRAP = "localhost:9092"


class FakeMessage:
    """One record, with the confluent-kafka Message accessor surface."""

    def __init__(self, topic, partition, offset, key, value, headers, error=None):
        self._topic, self._partition, self._offset = topic, partition, offset
        self._key, self._value, self._headers, self._error = key, value, headers, error

    def topic(self):
        return self._topic

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset

    def key(self):
        return self._key

    def value(self):
        return self._value

    def headers(self):
        return self._headers

    def error(self):
        return self._error


class FakeError:
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def __str__(self):
        return f"FakeError({self._code})"


class FakeCluster:
    """Per-partition append-only logs, fetch positions, and committed offsets."""

    def __init__(self):
        self.logs: Dict[str, Dict[int, List[FakeMessage]]] = {}
        self.positions: Dict[tuple, int] = {}  # (consumer id, topic, partition) -> next index
        self.committed: Dict[tuple, int] = {}  # (group, topic, partition) -> next offset
        self.partition_overrides: Dict[Optional[bytes], int] = {}
        self._key_partitions: Dict[tuple, int] = {}
        self.injected: List[FakeMessage] = []  # records handed to the next consume() verbatim

    def partition_for(self, topic: str, key: Optional[bytes]) -> int:
        if key in self.partition_overrides:
            return self.partition_overrides[key]
        if (topic, key) not in self._key_partitions:
            self._key_partitions[(topic, key)] = len(self._key_partitions)
        return self._key_partitions[(topic, key)]

    def append(self, topic: str, key, value, headers) -> FakeMessage:
        partition = self.partition_for(topic, key)
        log = self.logs.setdefault(topic, {}).setdefault(partition, [])
        record = FakeMessage(topic, partition, len(log), key, value, headers)
        log.append(record)
        return record

    def records(self, topic: str) -> List[FakeMessage]:
        return [record for partition in self.logs.get(topic, {}).values() for record in partition]


class FakeProducer:
    def __init__(self, cluster: FakeCluster, config: Dict[str, Any]):
        self.cluster, self.config = cluster, config
        self._callbacks: List[tuple] = []
        self.delivery_error: Optional[FakeError] = None
        self.dropped = False  # when True, produce never fires its callback (unconfirmed delivery)

    def produce(self, topic, value=None, key=None, headers=None, on_delivery=None):
        record = self.cluster.append(topic, key, value, headers)
        if on_delivery is not None and not self.dropped:
            self._callbacks.append((on_delivery, self.delivery_error, record))

    def poll(self, timeout=0):
        pending, self._callbacks = self._callbacks, []
        for callback, error, record in pending:
            callback(error, record)
        return len(pending)

    def flush(self, timeout=None):
        return self.poll(0)


class FakeConsumer:
    def __init__(self, cluster: FakeCluster, config: Dict[str, Any]):
        self.cluster, self.config = cluster, config
        self.group = config["group.id"]
        self.topics: List[str] = []
        self.closed = False
        self._id = id(self)

    def subscribe(self, topics):
        self.topics = list(topics)

    def consume(self, num_messages=1, timeout=None):
        if self.cluster.injected:
            injected, self.cluster.injected = self.cluster.injected, []
            return injected

        batch: List[FakeMessage] = []
        for topic in self.topics:
            for partition, log in self.cluster.logs.get(topic, {}).items():
                position_key = (self._id, topic, partition)
                index = max(self.cluster.positions.get(position_key, 0), self.cluster.committed.get((self.group, topic, partition), 0))
                if index < len(log) and len(batch) < num_messages:
                    batch.append(log[index])
                    self.cluster.positions[position_key] = index + 1
        return batch

    def commit(self, message=None, asynchronous=True):
        self.cluster.committed[(self.group, message.topic(), message.partition())] = message.offset() + 1

    def close(self):
        self.closed = True


@pytest.fixture
def cluster(monkeypatch):
    fake_cluster = FakeCluster()
    monkeypatch.setattr(kafka_module, "Producer", lambda config: FakeProducer(fake_cluster, config))
    monkeypatch.setattr(kafka_module, "Consumer", lambda config: FakeConsumer(fake_cluster, config))
    KafkaTransport.reset()
    yield fake_cluster
    KafkaTransport.reset()


def _transport(**overrides) -> KafkaTransport:
    kwargs = {
        "bootstrap_servers": BOOTSTRAP,
        "input_topic": INPUT_TOPIC,
        "output_topic": OUTPUT_TOPIC,
        "group_id": "agent-kernel",
        "retry_backoff": 0.0,
        "bookkeeping": InMemoryBookkeepingStore(),
    }
    kwargs.update(overrides)
    return KafkaTransport(**kwargs)


def _headers(record) -> Dict[str, str]:
    return {name: value.decode() for name, value in record.headers() or []}


class TestSend:
    def test_send_maps_the_envelope_onto_the_record(self, cluster):
        transport = _transport()
        result = transport.send(
            QueueName.INPUT,
            QueueMessage(body='{"prompt": "hi"}', attributes={"request_id": "r1", "user_id": "u1"}, group_id="s1", dedup_id="d1"),
        )

        [record] = cluster.records(INPUT_TOPIC)
        assert record.value() == b'{"prompt": "hi"}'
        assert record.key() == b"s1", "the session id is the record key: per-session ordering"
        assert _headers(record) == {"request_id": "r1", "user_id": "u1", DEDUP_HEADER: "d1"}
        assert result == {"MessageId": f"{INPUT_TOPIC}:{record.partition()}:{record.offset()}"}

    def test_send_without_group_or_dedup_omits_key_and_header(self, cluster):
        _transport().send(QueueName.OUTPUT, QueueMessage(body="{}"))
        [record] = cluster.records(OUTPUT_TOPIC)
        assert record.key() is None
        assert _headers(record) == {}

    def test_send_routes_to_the_queue_topic(self, cluster):
        transport = _transport()
        transport.send(QueueName.OUTPUT, QueueMessage(body="out", group_id="s1"))
        assert [record.value() for record in cluster.records(OUTPUT_TOPIC)] == [b"out"]
        assert cluster.records(INPUT_TOPIC) == []

    def test_delivery_error_raises(self, cluster):
        transport = _transport()
        transport._get_producer().delivery_error = FakeError(KafkaError._MSG_TIMED_OUT)
        with pytest.raises(KafkaException):
            transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))

    def test_unconfirmed_delivery_raises_rather_than_dropping_silently(self, cluster):
        """An unreachable broker must fail the request, not accept it and lose the message."""
        transport = _transport(delivery_timeout=0.05)
        transport._get_producer().dropped = True
        with pytest.raises(TimeoutError, match="not confirmed"):
            transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))


class TestConsumerEnvelope:
    def test_headers_and_identity_map_onto_the_envelope(self, cluster):
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="body", attributes={"request_id": "r1"}, group_id="s1", dedup_id="d1"))

        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.1)

        assert message.body == "body"
        assert message.attributes == {"request_id": "r1"}, "the dedup header is lifted out of the attributes"
        assert message.dedup_id == "d1"
        assert message.group_id == "s1"
        assert message.message_id == f"{INPUT_TOPIC}:{message.native.partition()}:0"
        assert message.receive_count == 1

    def test_ack_commits_the_offset(self, cluster):
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="body", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)

        [message] = consumer.fetch(10, 0.1)
        consumer.ack(message)

        partition = message.native.partition()
        assert cluster.committed[(f"agent-kernel-{QueueName.INPUT.value}", INPUT_TOPIC, partition)] == 1

    def test_nack_requeues_without_committing(self, cluster):
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="body", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)

        [message] = consumer.fetch(10, 0.1)
        consumer.nack(message)

        assert cluster.committed == {}, "an uncommitted offset is what makes a crash mid-retry safe"
        [redelivered] = consumer.fetch(10, 0.1)
        assert redelivered.body == "body"
        assert redelivered.receive_count == 2

    def test_close_closes_the_client(self, cluster):
        consumer = _transport().create_consumer(QueueName.INPUT)
        consumer.close()
        assert consumer._consumer.closed

    def test_partition_eof_records_are_skipped(self, cluster):
        transport = _transport()
        consumer = transport.create_consumer(QueueName.INPUT)
        cluster.injected = [FakeMessage(INPUT_TOPIC, 0, 0, None, None, None, error=FakeError(KafkaError._PARTITION_EOF))]
        assert consumer.fetch(10, 0.1) == []

    def test_other_record_errors_raise(self, cluster):
        transport = _transport()
        consumer = transport.create_consumer(QueueName.INPUT)
        cluster.injected = [FakeMessage(INPUT_TOPIC, 0, 0, None, None, None, error=FakeError(KafkaError.UNKNOWN_TOPIC_OR_PART))]
        with pytest.raises(KafkaException):
            consumer.fetch(10, 0.1)


class TestDeadLetter:
    def test_dead_letter_produces_to_the_dlq_topic_then_commits(self, cluster):
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="poison", attributes={"request_id": "r1"}, group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.1)

        consumer.dead_letter(message)

        [dlq_record] = cluster.records(f"{INPUT_TOPIC}.dlq")
        assert dlq_record.value() == b"poison"
        assert dlq_record.key() == b"s1"
        dlq_headers = _headers(dlq_record)
        assert dlq_headers["request_id"] == "r1", "the original headers travel with the record"
        assert "max_receive_count" in dlq_headers[ERROR_HEADER]
        assert cluster.committed[(f"agent-kernel-{QueueName.INPUT.value}", INPUT_TOPIC, message.native.partition())] == 1

    def test_dlq_write_failure_still_commits(self, cluster, caplog):
        """The permanent-failure hook already answered the caller; leaving the record
        uncommitted would replay it forever."""
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="poison", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.1)

        def _boom(**kwargs):
            raise RuntimeError("dlq unreachable")

        consumer._producer.produce = _boom

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.transport.kafka"):
            consumer.dead_letter(message)

        assert cluster.committed, "the record is committed despite the failed DLQ write"
        assert any("dead-letter" in record.message for record in caplog.records)

    def test_custom_dlq_suffix(self, cluster):
        transport = _transport(dlq_suffix="-failed")
        transport.send(QueueName.INPUT, QueueMessage(body="poison", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)
        consumer.dead_letter(consumer.fetch(10, 0.1)[0])
        assert cluster.records(f"{INPUT_TOPIC}-failed")


class TestHeadOfLineBlocking:
    def test_sessions_sharing_a_partition_serialize(self, cluster):
        """The documented Kafka tradeoff: one record in flight per partition, so two sessions
        hashed to the same partition block each other (stricter than SQS FIFO's per-group lock).
        The alternative would make a retry unable to redeliver before later offsets commit."""
        cluster.partition_overrides = {b"s1": 0, b"s2": 0}
        transport = _transport()
        transport.send(QueueName.INPUT, QueueMessage(body="first", group_id="s1"))
        transport.send(QueueName.INPUT, QueueMessage(body="second", group_id="s2"))

        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.1)
        assert message.body == "first"
        assert consumer.fetch(10, 0.05) == [], "the other session waits behind the in-flight record"

        consumer.ack(message)
        [next_message] = consumer.fetch(10, 0.1)
        assert next_message.body == "second"


class TestClientConfiguration:
    def test_consumer_config_is_manual_commit_and_agent_turn_sized(self, cluster):
        consumer = _transport().create_consumer(QueueName.INPUT)
        config = consumer._consumer.config
        assert config["bootstrap.servers"] == BOOTSTRAP
        assert config["enable.auto.commit"] is False, "offsets commit only after processing"
        assert config["partition.assignment.strategy"] == "cooperative-sticky"
        assert config["max.poll.interval.ms"] == DEFAULT_MAX_POLL_INTERVAL_MS, "an LLM-bound turn must not trigger eviction"
        assert config["group.id"] == "agent-kernel-input"

    def test_input_and_output_consumers_use_distinct_groups(self, cluster):
        transport = _transport()
        assert transport.create_consumer(QueueName.INPUT)._consumer.config["group.id"] == "agent-kernel-input"
        assert transport.create_consumer(QueueName.OUTPUT)._consumer.config["group.id"] == "agent-kernel-output"

    def test_client_config_passthrough_reaches_both_clients(self, cluster):
        transport = _transport(client_config={"security.protocol": "SASL_SSL", "sasl.mechanism": "SCRAM-SHA-512"})
        assert transport._get_producer().config["security.protocol"] == "SASL_SSL"
        assert transport.create_consumer(QueueName.INPUT)._consumer.config["sasl.mechanism"] == "SCRAM-SHA-512"

    def test_producer_is_idempotent_and_shared_per_configuration(self, cluster):
        transport = _transport()
        producer = transport._get_producer()
        assert producer.config["enable.idempotence"] is True
        assert transport._get_producer() is producer
        assert _transport()._get_producer() is producer, "one producer per process per broker config"
        assert _transport(bootstrap_servers="other:9092")._get_producer() is not producer


class TestFactory:
    @staticmethod
    def _cfg(with_block=True):
        class _Kafka:
            bootstrap_servers = "broker:9092"
            input_topic = "in"
            output_topic = "out"
            group_id = "gid"
            dlq_suffix = ".dead"
            retry_backoff = 1.5
            delivery_timeout = 12.0
            client_config = {"security.protocol": "SSL"}

        class _Cfg:
            class execution:
                class queues:
                    type = "kafka"
                    kafka = _Kafka if with_block else None

                    class input:
                        url = None

        return _Cfg

    def test_type_kafka_builds_the_transport_from_config(self, cluster, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg()))
        monkeypatch.setattr(
            "agentkernel.pipeline.transport.bookkeeping.BookkeepingStoreFactory.create", classmethod(lambda cls, **kw: InMemoryBookkeepingStore())
        )

        transport = QueueTransportFactory.create()

        assert isinstance(transport, KafkaTransport)
        assert transport._topics == {QueueName.INPUT: "in", QueueName.OUTPUT: "out"}
        assert transport._dlq_suffix == ".dead"
        assert transport._retry_backoff == 1.5
        assert transport._delivery_timeout == 12.0
        assert transport._get_producer().config["security.protocol"] == "SSL"

    def test_missing_kafka_block_raises(self, cluster, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg(with_block=False)))
        with pytest.raises(AKConfigError, match="execution.queues.kafka"):
            QueueTransportFactory.create()


class TestKafkaTransportContract(QueueTransportContract):
    """The shared transport contract against the Kafka semantics rebuild."""

    # Kafka's classic consumer model has no visibility-timeout equivalent: an unacked record
    # returns via nack or via reassignment of its uncommitted offset, never on a timer.
    timeout_redelivery = False

    @pytest.fixture(autouse=True)
    def _fake_cluster(self, cluster):
        self._bookkeeping = InMemoryBookkeepingStore()

    def force_redelivery(self) -> None:
        return None  # nack is the only in-process redelivery path

    def make_transport(self) -> KafkaTransport:
        return _transport(bookkeeping=self._bookkeeping)
