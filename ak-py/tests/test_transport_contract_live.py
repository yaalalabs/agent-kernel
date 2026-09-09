"""The transport contract against REAL brokers (spec #495 Testing: integration CI).

The in-repo suites run the :class:`QueueTransportContract` against the in_memory transport and
in-memory broker fakes; this file points the same contract at live servers, which is what
catches the failure modes fakes cannot (consumer-group membership, server-side ack_wait timing,
metadata propagation, real partitioners). Each class is skipped unless its env var points at a
reachable broker, so the normal unit run is unaffected:

    docker compose -f examples/transport/nats/docker-compose.yaml up -d --wait nats
    docker compose -f examples/transport/kafka/docker-compose.yaml up -d --wait kafka
    AK_TEST_NATS_URL=nats://localhost:4222 AK_TEST_KAFKA_BOOTSTRAP=localhost:9092 \
        uv run pytest tests/test_transport_contract_live.py

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
