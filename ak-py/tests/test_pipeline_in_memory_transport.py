import threading
import time
from unittest.mock import MagicMock

import pytest

from agentkernel.pipeline.consumer import ConsumerLoop
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.in_memory import InMemoryTransport


@pytest.fixture(autouse=True)
def _reset_state():
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()
    yield
    InMemoryTransport.reset()
    ThreadRunner.shutdown_event.clear()


def _msg(body="{}", group_id=None, dedup_id=None):
    return QueueMessage(body=body, group_id=group_id, dedup_id=dedup_id)


class TestProcessWideSharing:
    def test_queues_are_shared_across_transport_instances(self):
        InMemoryTransport(ack_wait=0.2).send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        consumer = InMemoryTransport(ack_wait=0.2).create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 0.5)
        assert message.body == "m1"

    def test_sender_object_is_not_shared_with_consumer(self):
        transport = InMemoryTransport(ack_wait=0.2)
        original = _msg(body="m1", group_id="s1")
        transport.send(QueueName.INPUT, original)
        original.body = "mutated-after-send"
        [message] = transport.create_consumer(QueueName.INPUT).fetch(10, 0.5)
        assert message.body == "m1"


class TestGroupSemantics:
    def test_groupless_messages_are_not_serialized_behind_each_other(self):
        transport = InMemoryTransport(ack_wait=0.2)
        transport.send(QueueName.INPUT, _msg(body="a"))
        transport.send(QueueName.INPUT, _msg(body="b"))
        batch = transport.create_consumer(QueueName.INPUT).fetch(10, 0.5)
        assert sorted(message.body for message in batch) == ["a", "b"]

    def test_group_order_preserved_across_nack(self):
        transport = InMemoryTransport(ack_wait=5.0)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))

        [first] = consumer.fetch(10, 0.5)
        consumer.nack(first)
        # The nacked head must come back before m2.
        [redelivered] = consumer.fetch(10, 0.5)
        assert (redelivered.body, redelivered.receive_count) == ("m1", 2)


class TestBlockingFetch:
    def test_fetch_wakes_on_send(self):
        transport = InMemoryTransport(ack_wait=0.2)
        consumer = transport.create_consumer(QueueName.INPUT)
        threading.Timer(0.1, lambda: transport.send(QueueName.INPUT, _msg(body="late", group_id="s1"))).start()

        started = time.monotonic()
        batch = consumer.fetch(10, 2.0)
        elapsed = time.monotonic() - started

        assert [message.body for message in batch] == ["late"]
        assert elapsed < 1.5, "fetch should wake on send, not sleep the full wait"


class TestDedupWindow:
    def test_duplicate_delivered_again_after_window_expires(self):
        transport = InMemoryTransport(ack_wait=0.2, dedup_window=0.1)
        consumer = transport.create_consumer(QueueName.INPUT)

        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1", dedup_id="d1"))
        [message] = consumer.fetch(10, 0.5)
        consumer.ack(message)

        time.sleep(0.15)
        transport.send(QueueName.INPUT, _msg(body="m1-again", group_id="s1", dedup_id="d1"))
        [redelivered] = consumer.fetch(10, 0.5)
        assert redelivered.body == "m1-again"

    def test_dropped_duplicate_returns_none(self):
        transport = InMemoryTransport(ack_wait=0.2, dedup_window=5.0)
        assert transport.send(QueueName.INPUT, _msg(dedup_id="d1")) is not None
        assert transport.send(QueueName.INPUT, _msg(dedup_id="d1")) is None


class TestConsumerLoopIntegration:
    def test_consumer_loop_drains_in_memory_queue(self):
        """Bridge iteration 2 + 3: the generic loop drains the in_memory transport end to end."""
        transport = InMemoryTransport(ack_wait=5.0)
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s2"))

        processed = []

        def process(message):
            processed.append(message.body)
            if len(processed) == 2:
                ThreadRunner.shutdown_event.set()

        loop = ConsumerLoop(
            process=process,
            on_permanent_failure=MagicMock(),
            max_receive_count=3,
            num_consumers=1,
            batch_size=10,
            consumer_factory=lambda: transport.create_consumer(QueueName.INPUT),
            thread_name_prefix="test",
            wait_seconds=0.1,
        )
        loop._consumer_loop()

        assert sorted(processed) == ["m1", "m2"]
        # Both messages acked: nothing left even after a redelivery window.
        assert transport.create_consumer(QueueName.INPUT).fetch(10, 0.05) == []


class TestStaleHandles:
    """A handle that expired via ack_wait must become inert once the message is redelivered
    (SQS FIFO parity: stale receipt handles are rejected)."""

    def test_stale_ack_after_redelivery_does_not_release_group(self):
        # ack_wait must comfortably outlive the assertions below so the redelivery itself
        # stays in flight; only the FIRST delivery is meant to expire (via the sleep).
        transport = InMemoryTransport(ack_wait=0.3)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))

        [stale] = consumer.fetch(10, 0.5)  # worker A's delivery
        time.sleep(0.35)  # ack_wait expires while A is still "processing"
        [redelivered] = consumer.fetch(10, 0.5)  # worker B picks up the redelivery
        assert redelivered.receive_count == 2
        assert redelivered is not stale

        consumer.ack(stale)  # A finishes late: its handle must be a no-op
        assert consumer.fetch(10, 0.05) == [], "m2 must stay blocked behind B's in-flight redelivery"

        consumer.ack(redelivered)  # only the live handle releases the group
        [next_message] = consumer.fetch(10, 0.5)
        assert next_message.body == "m2"

    def test_stale_nack_does_not_duplicate_in_flight_message(self):
        transport = InMemoryTransport(ack_wait=0.3)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))

        [stale] = consumer.fetch(10, 0.5)
        time.sleep(0.35)
        [redelivered] = consumer.fetch(10, 0.5)
        assert redelivered.receive_count == 2

        consumer.nack(stale)  # late nack from the expired delivery: must be a no-op
        assert consumer.fetch(10, 0.05) == [], "the message must not be duplicated while in flight"
        assert redelivered.receive_count == 2, "the live delivery's receive_count must be untouched"
