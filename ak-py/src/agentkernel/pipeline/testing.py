"""Reusable conformance suite for :class:`QueueTransport` implementations.

Mirrors ``sandbox/testing.py``'s ``SandboxProviderContract``: subclass
:class:`QueueTransportContract` in a test file, implement ``make_transport()``, and pytest
collects the contract tests against that transport. The contract asserts the queue-semantics
requirements every transport must reproduce (spec #495 §12 / research current-queue-mode.md):
per-group FIFO with one in-flight message per group, bounded-at-least-once redelivery with an
exact ``receive_count``, publish-time deduplication, attribute round-tripping, batch fetch, and
queue isolation.
"""

import time

import pytest

from .envelope import QueueMessage, QueueName
from .transport.base import QueueTransport


class QueueTransportContract:
    """Transport conformance tests. Subclass per transport and implement ``make_transport``.

    Timing knobs (``ack_wait``, ``fetch_wait``) and the ``force_redelivery`` hook may be tuned
    per backend: e.g. a mocked-broker subclass can trigger redelivery without sleeping.
    Declared capabilities let a transport opt out of a guarantee its backend genuinely cannot
    provide; each opt-out must be justified in the subclass, since it narrows what the pipeline
    can promise on that backend.
    """

    ack_wait: float = 0.2
    # Ceiling on a fetch that is expected to return a message. Generous on purpose: an in-process
    # transport returns as soon as the message is there, so a high ceiling costs it nothing, while
    # a real broker's first fetch also has to join a consumer group and can take several seconds.
    # Assertions that a fetch comes back *empty* pass their own short wait instead of this.
    fetch_wait: float = 10.0

    # Whether an unacked message returns for redelivery on a timeout while the consumer is still
    # alive (SQS visibility timeout, NATS ack_wait, the in_memory sweep). Kafka's classic
    # consumer model has no equivalent: redelivery comes from an explicit nack or from an
    # uncommitted offset being reassigned after a crash or rebalance.
    timeout_redelivery: bool = True

    def make_transport(self) -> QueueTransport:
        raise NotImplementedError

    def force_redelivery(self) -> None:
        """Wait until unacked messages become deliverable again. Default: sleep past ack_wait."""
        time.sleep(self.ack_wait + 0.15)

    # -- helpers -------------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _close_created_consumers(self):
        """Close every consumer the test created.

        This is not optional hygiene. A real broker client keeps background threads and consumer
        group membership alive until ``close()``, so a suite that leaks consumers can report every
        test passed and then never exit, which reads as a hung CI job. In-process transports do
        not care, which is precisely why the leak stays invisible until the contract is pointed at
        a broker.
        """
        self._created_consumers = []
        yield
        for consumer in self._created_consumers:
            try:
                consumer.close()
            except Exception:  # a close failure must not mask the test's own result
                pass

    @staticmethod
    def _msg(body="{}", group_id=None, dedup_id=None, attributes=None):
        return QueueMessage(body=body, group_id=group_id, dedup_id=dedup_id, attributes=attributes or {})

    def _consumer(self, transport: QueueTransport, queue=QueueName.INPUT):
        """Create a consumer and register it for closing when the test ends."""
        consumer = transport.create_consumer(queue)
        self._created_consumers.append(consumer)
        return consumer

    def _pair(self, queue=QueueName.INPUT):
        transport = self.make_transport()
        return transport, self._consumer(transport, queue)

    # -- contract ------------------------------------------------------------------------

    def test_roundtrip_preserves_envelope(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body='{"p": 1}', group_id="s1", attributes={"request_id": "r1", "user_id": "u1"}))
        [message] = consumer.fetch(10, self.fetch_wait)
        assert message.body == '{"p": 1}'
        assert message.group_id == "s1"
        assert message.attributes == {"request_id": "r1", "user_id": "u1"}
        assert message.receive_count == 1
        assert message.message_id

    def test_per_group_fifo_one_in_flight(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, self._msg(body="m2", group_id="s1"))

        [first] = consumer.fetch(10, self.fetch_wait)
        assert first.body == "m1"
        assert consumer.fetch(10, 0.05) == []  # m2 blocked behind the in-flight head

        consumer.ack(first)
        [second] = consumer.fetch(10, self.fetch_wait)
        assert second.body == "m2"

    def test_distinct_groups_delivered_in_parallel(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="a", group_id="s1"))
        transport.send(QueueName.INPUT, self._msg(body="b", group_id="s2"))
        batch = consumer.fetch(10, self.fetch_wait)
        assert sorted(message.body for message in batch) == ["a", "b"]

    def test_batch_size_is_respected(self):
        transport, consumer = self._pair()
        for i in range(3):
            transport.send(QueueName.INPUT, self._msg(body=f"m{i}", group_id=f"s{i}"))
        assert len(consumer.fetch(2, self.fetch_wait)) == 2

    def test_ack_removes_message_permanently(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(group_id="s1"))
        [message] = consumer.fetch(10, self.fetch_wait)
        consumer.ack(message)
        self.force_redelivery()
        assert consumer.fetch(10, 0.05) == []

    def test_nack_redelivers_with_incremented_receive_count(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="m1", group_id="s1"))
        [message] = consumer.fetch(10, self.fetch_wait)
        consumer.nack(message)
        # The contract requires redelivery no later than the transport's own mechanism allows:
        # in_memory requeues on nack immediately; SQS nack is a no-op and the visibility timeout
        # (force_redelivery) does the requeue.
        self.force_redelivery()
        [redelivered] = consumer.fetch(10, self.fetch_wait)
        assert redelivered.body == "m1"
        assert redelivered.receive_count == 2

    def test_unacked_message_is_redelivered_after_ack_wait(self):
        if not self.timeout_redelivery:
            pytest.skip("transport has no timeout-based redelivery (see QueueTransportContract.timeout_redelivery)")
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="m1", group_id="s1"))
        [message] = consumer.fetch(10, self.fetch_wait)
        assert message.receive_count == 1
        self.force_redelivery()
        [redelivered] = consumer.fetch(10, self.fetch_wait)
        assert redelivered.body == "m1"
        assert redelivered.receive_count == 2

    def test_dedup_window_drops_duplicate_send(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="m1", group_id="s1", dedup_id="d1"))
        transport.send(QueueName.INPUT, self._msg(body="m1-dup", group_id="s1", dedup_id="d1"))
        [message] = consumer.fetch(10, self.fetch_wait)
        consumer.ack(message)
        assert consumer.fetch(10, 0.05) == []

    def test_fetch_on_empty_queue_returns_empty(self):
        _, consumer = self._pair()
        assert consumer.fetch(10, 0.05) == []

    def test_queues_are_isolated(self):
        transport = self.make_transport()
        transport.send(QueueName.INPUT, self._msg(body="in", group_id="s1"))
        assert self._consumer(transport, QueueName.OUTPUT).fetch(10, 0.05) == []
        [message] = self._consumer(transport, QueueName.INPUT).fetch(10, self.fetch_wait)
        assert message.body == "in"
