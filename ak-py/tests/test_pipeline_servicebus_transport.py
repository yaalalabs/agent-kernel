import itertools
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import pytest
from azure.servicebus.exceptions import OperationTimeoutError, SessionLockLostError

from agentkernel.core.config import _QueuesConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport import servicebus as servicebus_module
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.servicebus import ServiceBusTransport

NAMESPACE = "ak-test.servicebus.windows.net"
INPUT_URL = f"https://{NAMESPACE}/agent-input"
OUTPUT_URL = f"https://{NAMESPACE}/agent-output"

# -- a fake behind the azure-servicebus surface the transport uses ------------------------------
#
# Models what the transport relies on: session locks taken by NEXT_AVAILABLE_SESSION, a session
# receiver that (like the real one) hands out the next message before the first is settled,
# duplicate detection on message_id, a 0-based AMQP delivery_count bumped on abandon and on a lapsed
# lock, and a lock that lapses at the renewer's ceiling measured from the session's accept.
# Single-threaded (tests only).


class _FakeReceived:
    def __init__(self, sequence_number, session_id, message_id, body: bytes, properties):
        self.sequence_number = sequence_number
        self.session_id = session_id
        self.message_id = message_id
        self._body = body
        # On receive the SDK decodes AMQP application properties to bytes keys and values.
        self.application_properties = {k.encode(): v.encode() for k, v in (properties or {}).items()} or None
        self.delivery_count = 0

    @property
    def body(self):
        return (part for part in [self._body])


class _FakeSession:
    def __init__(self, session_id, started):
        self.session_id = session_id
        self.started = started
        self.lock_deadline = started  # extended by the fake renewer

    @property
    def locked_until_utc(self):
        return datetime.now(timezone.utc) + timedelta(seconds=self.lock_deadline - time.monotonic())


class _FakeQueue:
    def __init__(self):
        self.pending: dict[str, deque] = {}
        self.holders: dict[str, "FakeReceiver"] = {}
        self.seen_message_ids: set[str] = set()
        self.sequence = itertools.count(1)
        self.accepts = 0

    def expire_locks(self):
        now = time.monotonic()
        for receiver in list(self.holders.values()):
            if receiver.session.lock_deadline <= now:
                receiver.lose_lock()


class FakeBroker:
    def __init__(self):
        self.queues: dict[str, _FakeQueue] = {}
        self.clients: list["FakeServiceBusClient"] = []
        self.renewers: list["FakeAutoLockRenewer"] = []

    def queue(self, name) -> _FakeQueue:
        return self.queues.setdefault(name, _FakeQueue())


class FakeSender:
    def __init__(self, queue: _FakeQueue):
        self._queue = queue

    def send_messages(self, message):
        if message.message_id in self._queue.seen_message_ids:
            return
        self._queue.seen_message_ids.add(message.message_id)
        received = _FakeReceived(
            next(self._queue.sequence), message.session_id, message.message_id, b"".join(message.body), message.application_properties
        )
        self._queue.pending.setdefault(message.session_id, deque()).append(received)


class FakeReceiver:
    def __init__(self, queue: _FakeQueue, max_wait_time):
        self._queue = queue
        self._max_wait_time = max_wait_time
        self.session: _FakeSession | None = None
        self.unsettled: list[_FakeReceived] = []
        self.lost = False
        self.closed = False

    def receive_messages(self, max_message_count=1, max_wait_time=None):
        self._queue.expire_locks()
        if self.lost:
            raise SessionLockLostError(message="lost")
        if self.session is None:
            self._accept(max_wait_time or self._max_wait_time)
        pending = self._queue.pending.get(self.session.session_id)
        deadline = time.monotonic() + max_wait_time
        while not pending and time.monotonic() < deadline:
            time.sleep(0.01)
        batch = [pending.popleft() for _ in range(min(max_message_count, len(pending)))] if pending else []
        self.unsettled.extend(batch)
        return batch

    def _accept(self, wait):
        deadline = time.monotonic() + wait
        while True:
            self._queue.expire_locks()
            free = [sid for sid, msgs in self._queue.pending.items() if msgs and sid not in self._queue.holders]
            if free:
                self.session = _FakeSession(free[0], time.monotonic())
                self.session.lock_deadline = self.session.started + 60  # the queue's own lock duration
                self._queue.holders[free[0]] = self
                self._queue.accepts += 1
                return
            if time.monotonic() >= deadline:
                raise OperationTimeoutError(message="no session available")
            time.sleep(0.01)

    def _settle(self, message):
        self._queue.expire_locks()
        if self.lost:
            raise SessionLockLostError(message="lost")
        self.unsettled.remove(message)

    def complete_message(self, message):
        self._settle(message)

    def abandon_message(self, message):
        self._settle(message)
        message.delivery_count += 1
        self._queue.pending[self.session.session_id].appendleft(message)

    def dead_letter_message(self, message, reason=None):
        self._settle(message)
        message.dead_letter_reason = reason

    def lose_lock(self):
        """Release the session: unsettled messages return to its head, one delivery older."""
        if self.session is None or self._queue.holders.get(self.session.session_id) is not self:
            return
        del self._queue.holders[self.session.session_id]
        pending = self._queue.pending.setdefault(self.session.session_id, deque())
        for message in reversed(sorted(self.unsettled, key=lambda m: m.sequence_number)):
            message.delivery_count += 1
            pending.appendleft(message)
        self.unsettled = []
        self.lost = True

    def close(self):
        self.lose_lock()
        self.closed = True


class FakeServiceBusClient:
    broker: FakeBroker = None  # set per test by the fixture

    def __init__(self, fully_qualified_namespace=None, credential=None, conn_str=None):
        self.namespace = fully_qualified_namespace
        self.credential = credential
        self.conn_str = conn_str
        self.closed = False
        self.broker.clients.append(self)

    @classmethod
    def from_connection_string(cls, conn_str):
        return cls(conn_str=conn_str)

    def get_queue_sender(self, queue_name):
        return FakeSender(self.broker.queue(queue_name))

    def get_queue_receiver(self, queue_name, session_id=None, max_wait_time=None):
        return FakeReceiver(self.broker.queue(queue_name), max_wait_time)

    def close(self):
        self.closed = True


class FakeAutoLockRenewer:
    """Renews until the ceiling, which the real renewer measures from the session's accept."""

    def __init__(self, max_lock_renewal_duration=300):
        self.registrations: list[float] = []
        self.closed = False
        FakeServiceBusClient.broker.renewers.append(self)

    def register(self, receiver, renewable, max_lock_renewal_duration=None):
        self.registrations.append(max_lock_renewal_duration)
        renewable.lock_deadline = renewable.started + max_lock_renewal_duration

    def close(self):
        self.closed = True


class FakeCredential:
    pass


@pytest.fixture
def broker(monkeypatch):
    fake_broker = FakeBroker()
    monkeypatch.setattr(FakeServiceBusClient, "broker", fake_broker)
    monkeypatch.setattr(servicebus_module, "ServiceBusClient", FakeServiceBusClient)
    monkeypatch.setattr(servicebus_module, "AutoLockRenewer", FakeAutoLockRenewer)
    monkeypatch.setattr(servicebus_module, "DefaultAzureCredential", FakeCredential)
    return fake_broker


def _transport(ack_wait=0.2, **kwargs) -> ServiceBusTransport:
    return ServiceBusTransport(INPUT_URL, OUTPUT_URL, ack_wait=ack_wait, **kwargs)


def _msg(body="{}", group_id="s1", dedup_id=None, attributes=None):
    return QueueMessage(body=body, group_id=group_id, dedup_id=dedup_id, attributes=attributes or {})


class TestServiceBusTransportContract(QueueTransportContract):
    """The shared transport contract against Service Bus session semantics, no opt-outs."""

    # Above SESSION_REUSE_WAIT_SECONDS: a batch fetch waits that long for a second session while its
    # first message's lock is renewing, and a shorter ack_wait would let that lock lapse mid-fetch.
    ack_wait = 1.0

    @pytest.fixture(autouse=True)
    def _fake(self, broker):
        self.broker = broker

    def make_transport(self) -> ServiceBusTransport:
        return _transport(ack_wait=self.ack_wait)

    def force_redelivery(self) -> None:
        """Lapse every held session lock now instead of sleeping out the renewal ceiling."""
        for queue in self.broker.queues.values():
            for receiver in list(queue.holders.values()):
                receiver.session.lock_deadline = time.monotonic()


class TestSend:
    def test_maps_the_envelope_onto_the_message(self, broker):
        _transport().send(QueueName.INPUT, _msg(body='{"p": 1}', group_id="s1", dedup_id="d1", attributes={"request_id": "r1"}))
        [sent] = broker.queue("agent-input").pending["s1"]
        assert (sent.session_id, sent.message_id, sent._body) == ("s1", "d1", b'{"p": 1}')
        assert sent.application_properties == {b"request_id": b"r1"}

    def test_ungrouped_undeduplicated_messages_get_fresh_ids(self, broker):
        transport = _transport()
        transport.send(QueueName.OUTPUT, _msg(group_id=None))
        transport.send(QueueName.OUTPUT, _msg(group_id=None))
        sent = [m for messages in broker.queue("agent-output").pending.values() for m in messages]
        assert len({m.session_id for m in sent}) == 2 and len({m.message_id for m in sent}) == 2

    def test_sends_reuse_one_client(self, broker):
        transport = _transport()
        for _ in range(3):
            transport.send(QueueName.INPUT, _msg())
        assert len(broker.clients) == 1


class TestConsume:
    def test_a_held_session_is_reused_after_ack(self, broker):
        transport = _transport(ack_wait=5)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg(body="m1"))
        transport.send(QueueName.INPUT, _msg(body="m2"))
        [first] = consumer.fetch(1, 1.0)
        consumer.ack(first)
        [second] = consumer.fetch(1, 1.0)
        assert second.body == "m2"
        assert broker.queue("agent-input").accepts == 1

    def test_one_renewal_per_accept_and_an_old_session_is_reaccepted(self, broker):
        transport = _transport(ack_wait=0.3)
        consumer = transport.create_consumer(QueueName.INPUT)
        for body in ("m1", "m2", "m3"):
            transport.send(QueueName.INPUT, _msg(body=body))
        consumer.ack(consumer.fetch(1, 1.0)[0])
        consumer.ack(consumer.fetch(1, 1.0)[0])  # reused: no new accept, no new registration
        time.sleep(0.35)  # older than ack_wait: its renewal could no longer cover a full ack_wait
        [third] = consumer.fetch(1, 1.0)
        assert third.body == "m3"
        assert broker.queue("agent-input").accepts == 2
        assert broker.renewers[0].registrations == [0.6, 0.6]

    def test_a_failing_reused_receiver_is_released(self, broker):
        transport = _transport(ack_wait=5)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        consumer.ack(consumer.fetch(1, 1.0)[0])
        receiver = consumer._sessions["s1"].receiver
        receiver.receive_messages = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("link detached"))
        with pytest.raises(ConnectionError):
            consumer.fetch(1, 1.0)
        assert receiver.closed and consumer._sessions == {}

    def test_fetch_returns_promptly_once_it_has_a_message(self, broker):
        transport = _transport(ack_wait=5)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        started = time.monotonic()
        assert len(consumer.fetch(10, 10.0)) == 1
        assert time.monotonic() - started < 2

    def test_a_lapsed_session_is_closed_and_dropped(self, broker):
        transport = _transport(ack_wait=0.1)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        [message] = consumer.fetch(1, 1.0)
        consumer.ack(message)
        receiver = consumer._sessions["s1"].receiver
        time.sleep(0.25)  # past the 2 x ack_wait renewal ceiling
        consumer.fetch(1, 0.05)
        assert receiver.closed and consumer._sessions == {}

    def test_ack_after_a_lost_lock_raises_and_forgets_the_session(self, broker):
        transport = _transport(ack_wait=0.1)
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        [message] = consumer.fetch(1, 1.0)
        time.sleep(0.25)  # past the 2 x ack_wait renewal ceiling
        with pytest.raises(SessionLockLostError):
            consumer.ack(message)
        assert consumer._sessions == {}

    def test_dead_letter_settles_with_a_reason(self, broker):
        transport = _transport()
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        [message] = consumer.fetch(1, 1.0)
        consumer.dead_letter(message)
        assert message.native.dead_letter_reason == "max_receive_count exceeded"

    def test_dead_letter_swallows_a_failure(self, broker):
        transport = _transport()
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        [message] = consumer.fetch(1, 1.0)
        consumer._sessions["s1"].receiver.dead_letter_message = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        consumer.dead_letter(message)
        assert consumer._sessions == {}

    def test_close_releases_receivers_renewer_and_client(self, broker):
        transport = _transport()
        consumer = transport.create_consumer(QueueName.INPUT)
        transport.send(QueueName.INPUT, _msg())
        consumer.fetch(1, 1.0)
        receiver = consumer._sessions["s1"].receiver
        consumer.close()
        assert receiver.closed and broker.renewers[0].closed and broker.clients[0].closed


class TestAddressing:
    @pytest.mark.parametrize("url", ["https://ns.servicebus.windows.net/", "https://ns.servicebus.windows.net/a/b", "amqp://ns/q", "agent-input"])
    def test_malformed_url_names_the_field(self, broker, url):
        with pytest.raises(AKConfigError, match=r"execution\.queues\.input\.url"):
            ServiceBusTransport(url, OUTPUT_URL, ack_wait=1)

    def test_queues_on_two_namespaces_are_refused(self, broker):
        with pytest.raises(AKConfigError, match="one Service Bus namespace"):
            ServiceBusTransport(INPUT_URL, "https://other.servicebus.windows.net/agent-output", ack_wait=1)

    def test_managed_identity_by_default(self, broker):
        _transport().create_consumer(QueueName.INPUT)
        [client] = broker.clients
        assert client.namespace == NAMESPACE and isinstance(client.credential, FakeCredential)

    def test_connection_string_when_set(self, broker):
        _transport(connection_string="Endpoint=sb://localhost/;UseDevelopmentEmulator=true").create_consumer(QueueName.INPUT)
        [client] = broker.clients
        assert client.conn_str == "Endpoint=sb://localhost/;UseDevelopmentEmulator=true" and client.credential is None


def _block(**servicebus):
    data = {"type": "servicebus", "input": {"url": INPUT_URL}, "output": {"url": OUTPUT_URL}}
    if servicebus:
        data["servicebus"] = servicebus
    return _QueuesConfig.model_validate(data)


class TestFactory:
    def test_builds_from_the_block(self, broker):
        transport = QueueTransportFactory.create(queues_config=_block(ack_wait=42, connection_string="Endpoint=sb://x/"))
        assert isinstance(transport, ServiceBusTransport)
        assert transport._ack_wait == 42 and transport._connection_string == "Endpoint=sb://x/"

    def test_block_defaults_without_a_servicebus_section(self, broker):
        transport = QueueTransportFactory.create(queues_config=_block())
        assert transport._ack_wait == 300.0 and transport._connection_string is None

    def test_both_urls_required(self, broker):
        block = _QueuesConfig.model_validate({"type": "servicebus", "input": {"url": INPUT_URL}})
        with pytest.raises(AKConfigError, match="the servicebus transport requires both"):
            QueueTransportFactory.create(queues_config=block)

    def test_missing_extra_is_named(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.pipeline.transport.servicebus", None)
        with pytest.raises(ImportError, match="execution.queues.type: servicebus requires the 'azure' extra"):
            QueueTransportFactory.create(queues_config=_block())
