"""The queue transport contract against the deployed Service Bus namespace.

The weekly integration run exports AK_TEST_SERVICEBUS_NAMESPACE from the deploy's
``servicebus_namespace`` output. Each test gets its own pair of queues, created with the deploying
principal's Data Owner role (deploy/main.tf); they delete themselves after 5 idle minutes, and
destroying the namespace removes any that remain. Locally, after ``az login``:

    AK_TEST_SERVICEBUS_NAMESPACE=<prefix>-queues.servicebus.windows.net uv run pytest servicebus_contract_test.py

This proves what the in-repo fake can only assume: per-session FIFO with one message in flight,
``delivery_count`` growing when a session lock lapses, and MessageId duplicate detection.
"""

import os
import time
import uuid
from datetime import timedelta

import pytest
from agentkernel.pipeline.envelope import QueueName
from agentkernel.pipeline.testing import QueueTransportContract

NAMESPACE = os.getenv("AK_TEST_SERVICEBUS_NAMESPACE")
# Service Bus's minimum lock duration: a lapsed lock frees the session this long after renewal stops.
LOCK_SECONDS = 5


@pytest.mark.skipif(
    not NAMESPACE, reason="AK_TEST_SERVICEBUS_NAMESPACE not set: the live contract runs in the weekly integration test"
)
class TestServiceBusTransportContractLive(QueueTransportContract):
    """The shared transport contract against real Service Bus session queues; only the batching tests are relaxed."""

    # Above the transport's 0.5 s session-reuse wait, as in the fake-backed subclass.
    ack_wait = 1.0
    # The first fetch also opens the AMQP connection and accepts a session.
    fetch_wait = 20.0

    @pytest.fixture(autouse=True)
    def _queues(self):
        # Imported here so collection works on an agentkernel without the Service Bus SDK.
        from azure.identity import DefaultAzureCredential
        from azure.servicebus.management import ServiceBusAdministrationClient

        unique = uuid.uuid4().hex[:12]
        self.queue_names = (f"ct-{unique}-in", f"ct-{unique}-out")
        with ServiceBusAdministrationClient(NAMESPACE, DefaultAzureCredential()) as admin:
            for name in self.queue_names:
                # The same shape the Terraform module creates, with the shortest lock and auto-cleanup.
                admin.create_queue(
                    name,
                    requires_session=True,
                    requires_duplicate_detection=True,
                    duplicate_detection_history_time_window=timedelta(minutes=5),
                    lock_duration=timedelta(seconds=LOCK_SECONDS),
                    max_delivery_count=10,
                    auto_delete_on_idle=timedelta(minutes=5),
                )

    def make_transport(self):
        from agentkernel.pipeline.transport.servicebus import ServiceBusTransport

        input_queue, output_queue = self.queue_names
        return ServiceBusTransport(
            input_url=f"https://{NAMESPACE}/{input_queue}",
            output_url=f"https://{NAMESPACE}/{output_queue}",
            ack_wait=self.ack_wait,
        )

    # Live overrides of the two batching tests. After the first message, a fetch waits only 0.5 s for another
    # session, and the SDK opens a new connection per session receiver within that budget, which a real namespace
    # does not meet. So one fetch returns one new session; other groups arrive on the next fetch, unblocked.
    def _fetch_until(self, consumer, count: int, batch_size: int = 10) -> list[str]:
        bodies: set[str] = set()  # a set: an unacked message may be redelivered once its lock lapses
        deadline = time.monotonic() + self.fetch_wait
        while len(bodies) < count and time.monotonic() < deadline:
            batch = consumer.fetch(batch_size, deadline - time.monotonic())
            assert len(batch) <= batch_size
            bodies |= {message.body for message in batch}  # never acked: delivery proves the group is not blocked
        return sorted(bodies)

    def test_distinct_groups_delivered_in_parallel(self):
        transport, consumer = self._pair()
        transport.send(QueueName.INPUT, self._msg(body="a", group_id="s1"))
        transport.send(QueueName.INPUT, self._msg(body="b", group_id="s2"))
        assert self._fetch_until(consumer, 2) == ["a", "b"]

    def test_batch_size_is_respected(self):
        transport, consumer = self._pair()
        for i in range(3):
            transport.send(QueueName.INPUT, self._msg(body=f"m{i}", group_id=f"s{i}"))
        assert self._fetch_until(consumer, 3, batch_size=2) == ["m0", "m1", "m2"]

    def force_redelivery(self) -> None:
        # Renewal stops after 2 x ack_wait (the transport's ceiling), then the last lock runs out.
        time.sleep(2 * self.ack_wait + LOCK_SECONDS + 2)
