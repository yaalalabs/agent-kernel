"""The transport contract against REAL brokers (spec #495 Testing: integration CI).

The in-repo suites run the :class:`QueueTransportContract` against the in_memory transport and
in-memory broker fakes; this file points the same contract at live servers, which is what
catches the failure modes fakes cannot (consumer-group membership, server-side ack_wait timing,
metadata propagation, real partitioners). Each class is skipped unless its env var points at a
reachable broker, so the normal unit run is unaffected:

    docker compose -f examples/transport/nats/docker-compose.yaml up -d --wait nats
    docker compose -f examples/transport/kafka/docker-compose.yaml up -d --wait kafka
    docker compose -f examples/transport/pubsub/docker-compose.yaml up -d --wait pubsub
    AK_TEST_NATS_URL=nats://localhost:4222 AK_TEST_KAFKA_BOOTSTRAP=localhost:9092 \
        AK_TEST_PUBSUB_EMULATOR_HOST=localhost:8085 uv run pytest tests/test_transport_contract_live.py

Every test provisions uniquely named streams/topics, so tests are isolated on a shared broker
and repeated runs never see each other's messages; the objects are left behind and die with
the container.
"""

import os
import time
import uuid

import pytest

from agentkernel.pipeline.testing import QueueTransportContract

NATS_URL = os.getenv("AK_TEST_NATS_URL")
KAFKA_BOOTSTRAP = os.getenv("AK_TEST_KAFKA_BOOTSTRAP")
PUBSUB_EMULATOR_HOST = os.getenv("AK_TEST_PUBSUB_EMULATOR_HOST")

# The contract's fixed group ids (s0/s1/s2) must spread over partitions for the parallel-delivery
# and batch assertions, and both partitioners are deterministic, so the counts are chosen from the
# actual mappings: crc32 % 4 puts s1 and s2 on distinct partitions; Kafka's murmur2 needs 8
# (s0 -> 4, s1 -> 5, s2 -> 1), while 4 would collide s1 with s2.
NATS_PARTITIONS = 4
KAFKA_PARTITIONS = 8


@pytest.mark.skipif(not NATS_URL, reason="AK_TEST_NATS_URL not set: the live broker contract runs in integration CI")
class TestNatsTransportContractLive(QueueTransportContract):
    """The shared transport contract against a real JetStream server."""

    # The two timing knobs are coupled: the transport splits fetch_wait across the partitions,
    # holding one pull request open per partition for fetch_wait / partitions seconds, and the
    # server redelivers an in-flight message INTO that still-open pull once ack_wait elapses,
    # duplicating it within a single fetch. So the per-partition window (6/4 = 1.5s) must stay
    # below ack_wait, with slack on both sides for a loaded CI runner.
    ack_wait = 2.0
    fetch_wait = 6.0

    def force_redelivery(self) -> None:
        time.sleep(self.ack_wait + 1.0)

    def make_transport(self):
        from agentkernel.pipeline.transport.nats import NatsTransport

        unique = uuid.uuid4().hex[:8].upper()
        return NatsTransport(
            url=NATS_URL,
            input_stream=f"CT_{unique}_IN",
            input_subject_prefix=f"ct.{unique}.req",
            output_stream=f"CT_{unique}_OUT",
            output_subject_prefix=f"ct.{unique}.out",
            partitions=NATS_PARTITIONS,
            ack_wait=self.ack_wait,
            retry_backoff=0.0,
            duplicate_window=60.0,
            max_age=600.0,
            auto_provision=True,
        )


@pytest.mark.skipif(not KAFKA_BOOTSTRAP, reason="AK_TEST_KAFKA_BOOTSTRAP not set: the live broker contract runs in integration CI")
class TestKafkaTransportContractLive(QueueTransportContract):
    """The shared transport contract against a real KRaft broker."""

    # Kafka's classic consumer model has no visibility-timeout equivalent: redelivery comes from
    # an explicit nack or an uncommitted offset being reassigned, never from a timer.
    timeout_redelivery = False
    # The first fetch of a fresh consumer group waits out a real coordinator join.
    fetch_wait = 20.0

    def force_redelivery(self) -> None:
        return None  # nack is the only in-process redelivery path

    def make_transport(self):
        from agentkernel.pipeline.transport.bookkeeping import InMemoryBookkeepingStore
        from agentkernel.pipeline.transport.kafka import KafkaTransport

        unique = uuid.uuid4().hex[:8]
        input_topic, output_topic = f"ct-{unique}-in", f"ct-{unique}-out"
        _create_topics([input_topic, output_topic])
        return KafkaTransport(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            input_topic=input_topic,
            output_topic=output_topic,
            group_id=f"ct-{unique}",
            retry_backoff=0.0,
            bookkeeping=InMemoryBookkeepingStore(),
        )


@pytest.mark.skipif(not PUBSUB_EMULATOR_HOST, reason="AK_TEST_PUBSUB_EMULATOR_HOST not set: the live broker contract runs in integration CI")
class TestPubSubTransportContractLive(QueueTransportContract):
    """The shared transport contract against the Pub/Sub emulator, with no capability opt-outs."""

    # The transport sets each fetched message's first ack deadline to ack_wait (whole seconds, at
    # least 1), below the subscription's own 10 s minimum, so redelivery tests wait seconds, not 10.
    ack_wait = 3.0
    fetch_wait = 10.0

    @pytest.fixture(autouse=True)
    def _emulator(self, monkeypatch):
        """Point the client libraries at the emulator; they read this when a client is built."""
        from agentkernel.pipeline.transport.pubsub import PubSubTransport

        monkeypatch.setenv("PUBSUB_EMULATOR_HOST", PUBSUB_EMULATOR_HOST)
        PubSubTransport.reset()  # the shared publisher must be built against the emulator
        yield
        PubSubTransport.reset()

    def force_redelivery(self) -> None:
        time.sleep(self.ack_wait + 1.0)

    def make_transport(self):
        from agentkernel.pipeline.transport.bookkeeping import InMemoryBookkeepingStore
        from agentkernel.pipeline.transport.pubsub import PubSubTransport

        unique = uuid.uuid4().hex[:8]
        return PubSubTransport(
            project_id="ak-contract",
            input_topic=f"ct-{unique}-in",
            input_subscription=f"ct-{unique}-in",
            output_topic=f"ct-{unique}-out",
            output_subscription=f"ct-{unique}-out",
            ack_wait=self.ack_wait,
            auto_provision=True,
            bookkeeping=InMemoryBookkeepingStore(),
        )

    def test_message_id_is_stable_across_redelivery(self):
        """Bookkeeping is keyed by Pub/Sub's message id, so a redelivery must carry the same one
        (research §9): an exact receive_count of 2 below is only possible if it does."""
        from agentkernel.pipeline.envelope import QueueName

        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="m1", group_id="s1"))
        [first] = consumer.fetch(10, self.fetch_wait)
        consumer.nack(first)
        [again] = consumer.fetch(10, self.fetch_wait)

        assert again.message_id == first.message_id
        assert again.receive_count == 2


def _create_topics(topics, timeout: float = 30.0) -> None:
    """Create the test's topics and wait until their metadata is served.

    Agent Kernel never creates topics (matching production posture, where a typo should fail
    loudly), so the test provisions its own, then polls metadata: a produce racing topic
    creation would otherwise burn part of the delivery timeout on UNKNOWN_TOPIC retries.
    """
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP})
    futures = admin.create_topics([NewTopic(topic, num_partitions=KAFKA_PARTITIONS, replication_factor=1) for topic in topics])
    for future in futures.values():
        future.result(timeout)

    deadline = time.monotonic() + timeout
    pending = set(topics)
    while pending and time.monotonic() < deadline:
        metadata = admin.list_topics(timeout=5.0)
        pending = {topic for topic in pending if topic not in metadata.topics or len(metadata.topics[topic].partitions) < KAFKA_PARTITIONS}
        if pending:
            time.sleep(0.2)
    if pending:
        raise RuntimeError(f"Topics not visible in metadata after {timeout}s: {sorted(pending)}")
