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

from .envelope import QueueMessage, QueueName
from .transport.base import QueueTransport


class QueueTransportContract:
    """Transport conformance tests. Subclass per transport and implement ``make_transport``.

    Timing knobs (``ack_wait``, ``fetch_wait``) and the ``force_redelivery`` hook may be tuned
    per backend: e.g. a mocked-broker subclass can trigger redelivery without sleeping.
    """

    ack_wait: float = 0.2
    fetch_wait: float = 0.5

    def make_transport(self) -> QueueTransport:
        raise NotImplementedError

    def force_redelivery(self) -> None:
        """Wait until unacked messages become deliverable again. Default: sleep past ack_wait."""
        time.sleep(self.ack_wait + 0.15)

    # -- helpers -------------------------------------------------------------------------

    @staticmethod
    def _msg(body="{}", group_id=None, dedup_id=None, attributes=None):
        return QueueMessage(body=body, group_id=group_id, dedup_id=dedup_id, attributes=attributes or {})

    def _pair(self, queue=QueueName.INPUT):
        transport = self.make_transport()
        return transport, transport.create_consumer(queue)

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
        [redelivered] = consumer.fetch(10, self.fetch_wait)
        assert redelivered.body == "m1"
        assert redelivered.receive_count == 2

    def test_unacked_message_is_redelivered_after_ack_wait(self):
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
        assert transport.create_consumer(QueueName.OUTPUT).fetch(10, 0.05) == []
        [message] = transport.create_consumer(QueueName.INPUT).fetch(10, self.fetch_wait)
        assert message.body == "in"
