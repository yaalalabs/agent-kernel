"""PubSubTransport (spec #886 §1) against a fake Pub/Sub behind the real client interface.

The fake reproduces the Pub/Sub behaviour the transport is built around: ordering keys with at most
one outstanding batch per key, ack deadlines on a controllable clock, redelivery on deadline expiry
or a deadline of 0, the cascade that redelivers every later message of a key (acknowledged ones
included), and topics that drop messages with no subscription. The transport code runs unmodified
over it, as the Kafka and NATS suites run over theirs.
"""

import base64
import itertools
import logging
import sys
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from google.api_core import exceptions as google_exceptions
from google.cloud.pubsub_v1.publisher.exceptions import PublishToPausedOrderingKeyException

from agentkernel.core.config import _QueuesConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport import pubsub as pubsub_module
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.bookkeeping import BookkeepingStoreFactory, InMemoryBookkeepingStore
from agentkernel.pipeline.transport.pubsub import (
    ERROR_ATTRIBUTE,
    SUBSCRIPTION_ACK_DEADLINE_SECONDS,
    PubSubEnvelopeCodec,
    PubSubTransport,
    _LeaseKeeper,
)

PROJECT = "test-project"


def _topic(name: str) -> str:
    return f"projects/{PROJECT}/topics/{name}"


def _sub(name: str) -> str:
    return f"projects/{PROJECT}/subscriptions/{name}"


# -- the fake ----------------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass(eq=False)
class FakeRecord:
    message_id: str
    data: bytes
    attributes: dict[str, str]
    ordering_key: str
    state: str = "available"  # available | outstanding | acked
    ack_id: str | None = None
    deadline: float = 0.0
    deliveries: int = 0


@dataclass
class FakeSubscription:
    name: str
    topic: str
    ordering: bool = True
    ack_deadline: int = SUBSCRIPTION_ACK_DEADLINE_SECONDS
    dead_letter_policy: dict | None = None
    records: list[FakeRecord] = field(default_factory=list)


class FakeBroker:
    """Server-side Pub/Sub semantics, shared by every fake client in a test."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.topics: set[str] = set()
        self.subscriptions: dict[str, FakeSubscription] = {}
        self.published: list[tuple[str, FakeRecord]] = []
        self.pull_calls: list[dict] = []
        self.modify_calls: list[tuple[list[str], int]] = []
        self.get_subscription_calls = 0
        self.created_subscriptions: list[dict] = []
        self.fail_publishes: list[Exception] = []
        self.lose_acks = 0
        self._message_ids = itertools.count(1)
        self._ack_ids = itertools.count(1)

    # -- admin -------------------------------------------------------------------------------

    def add_topic(self, topic: str) -> None:
        self.topics.add(topic)

    def add_subscription(self, name: str, topic: str, ordering: bool = True, **kwargs) -> None:
        self.subscriptions[name] = FakeSubscription(name=name, topic=topic, ordering=ordering, **kwargs)

    def provision(self, ordering: bool = True) -> None:
        """The objects Terraform creates: two queues, their dead-letter topics, and a subscription on each."""
        for name in ("in", "out", "in-dlq", "out-dlq"):
            self.add_topic(_topic(name))
            self.add_subscription(_sub(name), _topic(name), ordering=ordering if not name.endswith("dlq") else False)

    # -- data plane --------------------------------------------------------------------------

    def publish(self, topic: str, data: bytes, attributes: dict[str, str], ordering_key: str) -> str:
        if topic not in self.topics:
            raise google_exceptions.NotFound(f"topic {topic}")
        message_id = str(next(self._message_ids))
        record = FakeRecord(message_id=message_id, data=data, attributes=dict(attributes), ordering_key=ordering_key)
        self.published.append((topic, record))
        for subscription in self.subscriptions.values():
            if subscription.topic == topic:
                subscription.records.append(FakeRecord(message_id, data, dict(attributes), ordering_key))
        return message_id

    def pull(self, subscription: FakeSubscription, max_messages: int) -> list[FakeRecord]:
        self._expire(subscription)
        busy = {r.ordering_key for r in subscription.records if r.state == "outstanding" and self._key(subscription, r)}
        delivered: list[FakeRecord] = []
        for record in subscription.records:
            if len(delivered) >= max_messages:
                break
            if record.state != "available" or self._key(subscription, record) in busy:
                continue
            record.state = "outstanding"
            record.ack_id = f"ack-{next(self._ack_ids)}"
            record.deadline = self.clock() + subscription.ack_deadline
            record.deliveries += 1
            delivered.append(record)
        return delivered

    def acknowledge(self, subscription: FakeSubscription, ack_ids: list[str]) -> None:
        if self.lose_acks:
            self.lose_acks -= 1
            return
        for record in self._outstanding(subscription, ack_ids):
            record.state = "acked"

    def modify(self, subscription: FakeSubscription, ack_ids: list[str], seconds: int) -> None:
        self.modify_calls.append((list(ack_ids), seconds))
        for record in self._outstanding(subscription, ack_ids):
            if seconds == 0:
                self._redeliver(subscription, record)
            else:
                record.deadline = self.clock() + seconds

    def records(self, subscription_name: str) -> list[FakeRecord]:
        return self.subscriptions[subscription_name].records

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _key(subscription: FakeSubscription, record: FakeRecord) -> str:
        return record.ordering_key if subscription.ordering else ""

    @staticmethod
    def _outstanding(subscription: FakeSubscription, ack_ids: list[str]) -> list[FakeRecord]:
        wanted = set(ack_ids)
        return [r for r in subscription.records if r.state == "outstanding" and r.ack_id in wanted]

    def _expire(self, subscription: FakeSubscription) -> None:
        for record in list(subscription.records):
            if record.state == "outstanding" and record.deadline <= self.clock():
                self._redeliver(subscription, record)

    def _redeliver(self, subscription: FakeSubscription, record: FakeRecord) -> None:
        """Make a message available again, cascading to every later message of its key."""
        record.state, record.ack_id = "available", None
        key = self._key(subscription, record)
        if not key:
            return
        for later in subscription.records[subscription.records.index(record) + 1 :]:
            if later.ordering_key == key and later.state in ("outstanding", "acked"):
                later.state, later.ack_id = "available", None


class FakeFuture:
    def __init__(self, value: Any = None, error: Exception | None = None):
        self._value, self._error = value, error

    def result(self, timeout: float | None = None) -> Any:
        if self._error is not None:
            raise self._error
        return self._value


class FakePublisherClient:
    broker: FakeBroker | None = None  # set per test by the broker fixture
    instances: list["FakePublisherClient"] = []

    def __init__(self, publisher_options=None, batch_settings=None, **kwargs):
        self.publisher_options = publisher_options
        self.batch_settings = batch_settings
        self.paused: set[tuple[str, str]] = set()
        self.resumed: list[tuple[str, str]] = []
        FakePublisherClient.instances.append(self)

    def publish(self, topic: str, data: bytes, ordering_key: str = "", **attrs: str) -> FakeFuture:
        if ordering_key and (topic, ordering_key) in self.paused:
            raise PublishToPausedOrderingKeyException(ordering_key)
        if self.broker.fail_publishes:
            if ordering_key:
                self.paused.add((topic, ordering_key))
            return FakeFuture(error=self.broker.fail_publishes.pop(0))
        try:
            return FakeFuture(self.broker.publish(topic, data, attrs, ordering_key))
        except google_exceptions.NotFound as e:
            return FakeFuture(error=e)

    def resume_publish(self, topic: str, ordering_key: str) -> None:
        self.paused.discard((topic, ordering_key))
        self.resumed.append((topic, ordering_key))

    def get_topic(self, request: dict, timeout: float | None = None) -> SimpleNamespace:
        if request["topic"] not in self.broker.topics:
            raise google_exceptions.NotFound(request["topic"])
        return SimpleNamespace(name=request["topic"])

    def create_topic(self, request: dict, timeout: float | None = None) -> SimpleNamespace:
        if request["name"] in self.broker.topics:
            raise google_exceptions.AlreadyExists(request["name"])
        self.broker.add_topic(request["name"])
        return SimpleNamespace(name=request["name"])


class FakeSubscriberClient:
    broker: FakeBroker | None = None  # set per test by the broker fixture
    instances: list["FakeSubscriberClient"] = []

    def __init__(self, **kwargs):
        self.closed = False
        FakeSubscriberClient.instances.append(self)

    def __enter__(self) -> "FakeSubscriberClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _subscription(self, name: str) -> FakeSubscription:
        if name not in self.broker.subscriptions:
            raise google_exceptions.NotFound(name)
        return self.broker.subscriptions[name]

    def pull(self, request: dict, timeout: float | None = None, retry: Any = None) -> SimpleNamespace:
        self.broker.pull_calls.append({**request, "timeout": timeout, "retry": retry})
        records = self.broker.pull(self._subscription(request["subscription"]), request["max_messages"])
        if not records:
            raise google_exceptions.DeadlineExceeded("no messages before the deadline")
        return SimpleNamespace(
            received_messages=[
                SimpleNamespace(
                    ack_id=record.ack_id,
                    # Deliberately wrong: the transport must not trust Pub/Sub's approximate count.
                    delivery_attempt=99,
                    message=SimpleNamespace(
                        data=record.data, attributes=dict(record.attributes), message_id=record.message_id, ordering_key=record.ordering_key
                    ),
                )
                for record in records
            ]
        )

    def acknowledge(self, request: dict, timeout: float | None = None) -> None:
        self.broker.acknowledge(self._subscription(request["subscription"]), request["ack_ids"])

    def modify_ack_deadline(self, request: dict, timeout: float | None = None) -> None:
        self.broker.modify(self._subscription(request["subscription"]), request["ack_ids"], request["ack_deadline_seconds"])

    def get_subscription(self, request: dict, timeout: float | None = None) -> SimpleNamespace:
        self.broker.get_subscription_calls += 1
        subscription = self._subscription(request["subscription"])
        return SimpleNamespace(name=subscription.name, enable_message_ordering=subscription.ordering)

    def create_subscription(self, request: dict, timeout: float | None = None) -> SimpleNamespace:
        if request["name"] in self.broker.subscriptions:
            raise google_exceptions.AlreadyExists(request["name"])
        self.broker.created_subscriptions.append(request)
        self.broker.add_subscription(
            request["name"],
            request["topic"],
            ordering=request.get("enable_message_ordering", False),
            ack_deadline=request.get("ack_deadline_seconds", 10),
            dead_letter_policy=request.get("dead_letter_policy"),
        )
        return SimpleNamespace(name=request["name"])

    def close(self) -> None:
        self.closed = True


# -- fixtures and helpers ----------------------------------------------------------------------


@pytest.fixture
def broker(monkeypatch):
    broker = FakeBroker(FakeClock())
    monkeypatch.setattr(FakePublisherClient, "broker", broker)
    monkeypatch.setattr(FakeSubscriberClient, "broker", broker)
    monkeypatch.setattr(FakePublisherClient, "instances", [])
    monkeypatch.setattr(FakeSubscriberClient, "instances", [])
    monkeypatch.setattr(pubsub_module.pubsub_v1, "PublisherClient", FakePublisherClient)
    monkeypatch.setattr(pubsub_module.pubsub_v1, "SubscriberClient", FakeSubscriberClient)
    # Keep the real lease threads idle: lease behaviour is driven through tick() with a fake clock.
    monkeypatch.setattr(pubsub_module, "LEASE_REFRESH_SECONDS", 3600)
    PubSubTransport.reset()
    yield broker
    PubSubTransport.reset()


@pytest.fixture
def provisioned(broker):
    broker.provision()
    return broker


@pytest.fixture
def consumers():
    """Consumers created by a test, closed when it ends so no lease thread outlives it."""
    created = []
    yield created
    for consumer in created:
        consumer.close()


def _transport(**overrides) -> PubSubTransport:
    kwargs = dict(
        project_id=PROJECT,
        input_topic="in",
        input_subscription="in",
        output_topic="out",
        output_subscription="out",
        ack_wait=30.0,
        bookkeeping=InMemoryBookkeepingStore(),
    )
    kwargs.update(overrides)
    return PubSubTransport(**kwargs)


def _consumer(consumers: list, transport: PubSubTransport, queue: QueueName = QueueName.INPUT):
    consumer = transport.create_consumer(queue)
    consumers.append(consumer)
    return consumer


def _msg(body: str = "{}", group_id: str | None = None, dedup_id: str | None = None, attributes: dict | None = None) -> QueueMessage:
    return QueueMessage(body=body, group_id=group_id, dedup_id=dedup_id, attributes=attributes or {})


def _bodies(messages: list[QueueMessage]) -> list[str]:
    return [message.body for message in messages]


# -- tests -------------------------------------------------------------------------------------


class TestEnvelopeCodec:
    def test_round_trip(self):
        message = _msg(body='{"p": 1}', group_id="s1", dedup_id="d1", attributes={"request_id": "r1"})
        data, attributes = PubSubEnvelopeCodec.encode(message)

        decoded = PubSubEnvelopeCodec.decode(data, attributes, "s1", "m1")

        assert (decoded.body, decoded.attributes, decoded.group_id, decoded.dedup_id) == ('{"p": 1}', {"request_id": "r1"}, "s1", "d1")
        assert (decoded.message_id, decoded.receive_count) == ("m1", 1)

    def test_attributes_beyond_pubsub_limits_round_trip_byte_for_byte(self):
        """Pub/Sub allows 100 attributes of up to 1024 bytes; the reply_ context alone may be 8192 bytes."""
        attributes = {f"reply_k{i}": f"v{i}" for i in range(150)}
        attributes["reply_context"] = "é" * 4096  # 8192 bytes of UTF-8
        data, pubsub_attributes = PubSubEnvelopeCodec.encode(_msg(attributes=attributes))

        assert PubSubEnvelopeCodec.decode(data, pubsub_attributes, "", "m1").attributes == attributes

    def test_only_the_version_marker_is_a_pubsub_attribute(self):
        _, attributes = PubSubEnvelopeCodec.encode(_msg(attributes={"request_id": "r1"}))
        assert attributes == {"ak-envelope": "1"}

    def test_the_group_survives_a_delivery_without_an_ordering_key(self):
        """The emulator's push requests carry no ordering key: the data's own copy keeps the session id."""
        data, attributes = PubSubEnvelopeCodec.encode(_msg(group_id="s1"))
        assert PubSubEnvelopeCodec.decode(data, attributes, "", "m1").group_id == "s1"

    def test_an_empty_ordering_key_decodes_to_no_group(self):
        data, attributes = PubSubEnvelopeCodec.encode(_msg())
        assert PubSubEnvelopeCodec.decode(data, attributes, "", "m1").group_id is None

    @pytest.mark.parametrize(
        "data, attributes",
        [
            (b'{"body": "{}", "attributes": {}, "dedup_id": null}', {}),
            (b"not json", {"ak-envelope": "1"}),
            (b'["a list"]', {"ak-envelope": "1"}),
            (b'{"body": 1, "attributes": {}}', {"ak-envelope": "1"}),
            (b'{"body": "{}", "attributes": {"k": 1}}', {"ak-envelope": "1"}),
            (b'{"body": "{}", "attributes": {}, "dedup_id": 5}', {"ak-envelope": "1"}),
            (b'{"body": "{}", "attributes": {}, "group_id": 5}', {"ak-envelope": "1"}),
            (b"\xff", {"ak-envelope": "1"}),
        ],
        ids=["no-marker", "not-json", "not-object", "body-not-str", "attribute-not-str", "dedup-not-str", "group-not-str", "not-utf8"],
    )
    def test_a_foreign_message_raises_value_error(self, data, attributes):
        with pytest.raises(ValueError):
            PubSubEnvelopeCodec.decode(data, attributes, "", "m1")


class TestSend:
    def test_send_maps_the_envelope_onto_the_message(self, provisioned):
        result = _transport().send(QueueName.INPUT, _msg(body='{"p": 1}', group_id="s1", dedup_id="d1", attributes={"user_id": "u1"}))

        [(topic, record)] = provisioned.published
        assert topic == _topic("in")
        assert record.ordering_key == "s1"
        assert record.attributes == {"ak-envelope": "1"}
        assert PubSubEnvelopeCodec.decode(record.data, record.attributes, "s1", "x").attributes == {"user_id": "u1"}
        assert result == {"MessageId": record.message_id}

    def test_a_message_without_a_group_has_no_ordering_key(self, provisioned):
        _transport().send(QueueName.INPUT, _msg())
        assert provisioned.published[0][1].ordering_key == ""

    def test_output_messages_go_to_the_output_topic(self, provisioned):
        _transport().send(QueueName.OUTPUT, _msg(group_id="s1"))
        assert provisioned.published[0][0] == _topic("out")

    def test_a_failed_publish_resumes_its_ordering_key_then_raises(self, provisioned):
        transport = _transport()
        provisioned.fail_publishes.append(google_exceptions.ServiceUnavailable("down"))

        with pytest.raises(google_exceptions.ServiceUnavailable):
            transport.send(QueueName.INPUT, _msg(group_id="s1"))

        publisher = FakePublisherClient.instances[-1]
        assert publisher.resumed == [(_topic("in"), "s1")]
        transport.send(QueueName.INPUT, _msg(group_id="s1"))  # the key is usable again
        assert len(provisioned.published) == 1

    def test_an_unconfirmed_publish_raises_rather_than_dropping_silently(self, provisioned):
        """send() waits for Pub/Sub's confirmation; a timeout surfaces as a failed request."""
        provisioned.fail_publishes.append(TimeoutError("publish not confirmed within request_timeout"))

        with pytest.raises(TimeoutError):
            _transport().send(QueueName.INPUT, _msg(group_id="s1"))
        assert provisioned.published == []

    def test_the_publisher_orders_and_does_not_batch(self, provisioned):
        _transport().send(QueueName.INPUT, _msg())
        publisher = FakePublisherClient.instances[-1]
        assert publisher.publisher_options.enable_message_ordering is True
        assert publisher.batch_settings.max_messages == 1

    def test_the_publisher_is_shared_process_wide(self, provisioned):
        _transport().send(QueueName.INPUT, _msg())
        _transport().send(QueueName.OUTPUT, _msg())
        assert len(FakePublisherClient.instances) == 1


class TestOneKeyAtATime:
    def test_a_keys_batch_is_served_one_message_per_fetch(self, provisioned, consumers):
        transport = _transport()
        for body in ("m1", "m2", "m3"):
            transport.send(QueueName.INPUT, _msg(body=body, group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="a", group_id="s2"))
        consumer = _consumer(consumers, transport)

        first = consumer.fetch(10, 1.0)
        assert _bodies(first) == ["m1", "a"], "one message per key, keys side by side"
        assert consumer.fetch(10, 0.05) == [], "m2 waits behind the in-flight m1"

        consumer.ack(first[0])
        pulls = len(provisioned.pull_calls)
        [second] = consumer.fetch(10, 1.0)
        assert second.body == "m2"
        assert len(provisioned.pull_calls) == pulls, "served from the held batch, not a new pull"

        consumer.ack(second)
        assert _bodies(consumer.fetch(10, 1.0)) == ["m3"]

    def test_keyless_messages_are_served_together(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="x"))
        transport.send(QueueName.INPUT, _msg(body="y"))
        assert sorted(_bodies(_consumer(consumers, transport).fetch(10, 1.0))) == ["x", "y"]

    def test_pull_asks_for_the_batch_size_with_the_wait_as_its_deadline(self, provisioned, consumers):
        _consumer(consumers, _transport()).fetch(7, 0.5)
        assert provisioned.pull_calls[-1] == {"subscription": _sub("in"), "max_messages": 7, "timeout": 0.5, "retry": None}


class TestCascade:
    def test_a_cascade_after_a_lost_ack_runs_nothing_twice(self, provisioned, consumers):
        """m1's ack is lost, m2 is acked, then m1's deadline passes: Pub/Sub redelivers m1 and,
        because they share a key, the already-acknowledged m2. Neither may run again."""
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))
        consumer = _consumer(consumers, transport)

        [m1] = consumer.fetch(10, 1.0)
        provisioned.lose_acks = 1
        consumer.ack(m1)
        [m2] = consumer.fetch(10, 1.0)
        consumer.ack(m2)

        provisioned.clock.advance(61)
        assert consumer.fetch(10, 1.0) == []
        assert [r.state for r in provisioned.records(_sub("in"))] == ["acked", "acked"]
        assert [r.deliveries for r in provisioned.records(_sub("in"))] == [2, 2], "both really were redelivered"


class TestDedup:
    def test_a_second_message_with_the_same_dedup_id_is_dropped(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1", dedup_id="d1"))
        transport.send(QueueName.INPUT, _msg(body="m1-again", group_id="s2", dedup_id="d1"))

        assert _bodies(_consumer(consumers, transport).fetch(10, 1.0)) == ["m1"]
        assert provisioned.records(_sub("in"))[1].state == "acked", "the duplicate is acknowledged, not left to redeliver"

    def test_a_reply_is_not_dropped_because_its_request_claimed_the_same_dedup_id(self, provisioned, consumers):
        """AgentRunner forwards the request's dedup id onto the reply, so claims are per subscription."""
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="request", group_id="s1", dedup_id="d1"))
        [request] = _consumer(consumers, transport).fetch(10, 1.0)

        transport.send(QueueName.OUTPUT, _msg(body="reply", group_id="s1", dedup_id="d1"))
        assert _bodies(_consumer(consumers, transport, QueueName.OUTPUT).fetch(10, 1.0)) == ["reply"]
        assert request.body == "request"


class TestReceiveCount:
    def test_exact_across_nacks(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(group_id="s1"))
        consumer = _consumer(consumers, transport)

        counts = []
        for _ in range(3):
            [message] = consumer.fetch(10, 1.0)
            counts.append(message.receive_count)
            consumer.nack(message)
        assert counts == [1, 2, 3]

    def test_exact_across_a_consumer_restart(self, provisioned, consumers):
        """The durable case: a new consumer (a restarted worker) shares the bookkeeping store."""
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(group_id="s1"))
        first = transport.create_consumer(QueueName.INPUT)
        assert first.fetch(10, 1.0)[0].receive_count == 1
        first.close()

        [again] = _consumer(consumers, transport).fetch(10, 1.0)
        assert again.receive_count == 2

    def test_pubsubs_delivery_attempt_is_ignored(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg())
        assert _consumer(consumers, transport).fetch(10, 1.0)[0].receive_count == 1


class TestNack:
    def test_nack_releases_the_message_and_its_keys_held_messages_only(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="a", group_id="s2"))
        consumer = _consumer(consumers, transport)
        m1, a = consumer.fetch(10, 1.0)
        records = provisioned.records(_sub("in"))
        held_ack_ids = [records[0].ack_id, records[1].ack_id]

        consumer.nack(m1)

        assert provisioned.modify_calls[-1] == (held_ack_ids, 0)
        assert records[2].state == "outstanding", "the other key keeps its lease"
        [redelivered] = consumer.fetch(10, 1.0)
        assert (redelivered.body, redelivered.receive_count) == ("m1", 2)

    def test_a_nack_failure_propagates_after_local_state_is_cleared(self, provisioned, consumers, monkeypatch):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(group_id="s1"))
        consumer = _consumer(consumers, transport)
        [message] = consumer.fetch(10, 1.0)
        monkeypatch.setattr(
            FakeSubscriberClient, "modify_ack_deadline", lambda self, request, timeout=None: (_ for _ in ()).throw(RuntimeError("down"))
        )

        with pytest.raises(RuntimeError):
            consumer.nack(message)
        assert consumer._in_flight == {} and consumer._leases.leased() == set()


class TestDeadLetter:
    def test_dead_letter_copies_to_the_dead_letter_topic_then_acks(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="poison", group_id="s1"))
        consumer = _consumer(consumers, transport)
        [message] = consumer.fetch(10, 1.0)
        message.receive_count = 4

        consumer.dead_letter(message)

        [(topic, copy)] = [entry for entry in provisioned.published if entry[0] == _topic("in-dlq")]
        assert copy.data == provisioned.records(_sub("in"))[0].data
        assert copy.attributes[ERROR_ATTRIBUTE] == "exceeded max_receive_count after 4 deliveries"
        assert copy.attributes["ak-envelope"] == "1"
        assert copy.ordering_key == ""
        assert provisioned.records(_sub("in"))[0].state == "acked"

    def test_a_failed_copy_is_logged_and_the_original_still_acked(self, provisioned, consumers, caplog):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(group_id="s1"))
        consumer = _consumer(consumers, transport)
        [message] = consumer.fetch(10, 1.0)
        provisioned.topics.discard(_topic("in-dlq"))

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.transport.pubsub"):
            consumer.dead_letter(message)

        assert any("this copy is lost" in record.message for record in caplog.records)
        assert provisioned.records(_sub("in"))[0].state == "acked"


class TestSupersede:
    def test_a_lapsed_in_flight_message_is_served_again(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        consumer = _consumer(consumers, transport)
        consumer.fetch(10, 1.0)

        provisioned.clock.advance(31)  # past ack_wait: the lease lapsed

        [again] = consumer.fetch(10, 1.0)
        assert (again.body, again.receive_count) == ("m1", 2)

    def test_stale_held_messages_are_replaced_not_duplicated(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))
        consumer = _consumer(consumers, transport)
        consumer.fetch(10, 1.0)

        provisioned.clock.advance(31)
        [m1] = consumer.fetch(10, 1.0)
        consumer.ack(m1)
        [m2] = consumer.fetch(10, 1.0)
        consumer.ack(m2)

        assert (m1.body, m2.body, m2.receive_count) == ("m1", "m2", 1)
        assert consumer.fetch(10, 0.05) == [], "no second copy of m2 is left behind"


class TestQuarantine:
    def test_a_foreign_message_is_copied_to_the_dead_letter_topic_and_acked(self, provisioned, consumers, caplog):
        provisioned.publish(_topic("in"), b"not an envelope", {"source": "elsewhere"}, "")

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.transport.pubsub"):
            assert _consumer(consumers, _transport()).fetch(10, 1.0) == []

        [(_, copy)] = [entry for entry in provisioned.published if entry[0] == _topic("in-dlq")]
        assert copy.data == b"not an envelope"
        assert copy.attributes == {"source": "elsewhere", ERROR_ATTRIBUTE: "not an Agent Kernel envelope"}
        assert provisioned.records(_sub("in"))[0].state == "acked"
        assert any("not an Agent Kernel envelope" in record.message for record in caplog.records)


class TestLeases:
    @pytest.mark.parametrize("ack_wait, deadline", [(30.0, 30), (300.0, 60), (0.2, 1)])
    def test_the_first_deadline_is_set_at_fetch(self, provisioned, consumers, ack_wait, deadline):
        transport = _transport(ack_wait=ack_wait)
        transport.send(QueueName.INPUT, _msg())
        _consumer(consumers, transport).fetch(10, 1.0)
        assert provisioned.modify_calls[0] == ([provisioned.records(_sub("in"))[0].ack_id], deadline)

    def test_held_and_in_flight_messages_are_leased_until_settled(self, provisioned, consumers):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))
        consumer = _consumer(consumers, transport)
        [m1] = consumer.fetch(10, 1.0)
        first, second = [r.ack_id for r in provisioned.records(_sub("in"))]

        assert consumer._leases.leased() == {first, second}
        consumer.ack(m1)
        assert consumer._leases.leased() == {second}

    def test_tick_renews_until_ack_wait_then_lets_the_lease_lapse(self, broker):
        clock = FakeClock()
        broker.provision()
        keeper = _LeaseKeeper(FakeSubscriberClient(), _sub("in"), ack_wait=100.0, request_timeout=1.0, clock=clock)
        keeper.add(["a", "b"])

        clock.advance(10)
        keeper.tick()
        assert broker.modify_calls[-1] == (["a", "b"], 60)

        clock.advance(85)  # 5 s of ack_wait left
        keeper.tick()
        assert broker.modify_calls[-1] == (["a", "b"], 5)

        clock.advance(6)
        calls = len(broker.modify_calls)
        keeper.tick()
        assert len(broker.modify_calls) == calls and keeper.leased() == set()

    def test_a_failed_renewal_warns_and_is_retried(self, broker, caplog):
        attempts = []

        class FlakySubscriber:
            def modify_ack_deadline(self, request, timeout=None):
                attempts.append(request["ack_ids"])
                if len(attempts) == 1:
                    raise google_exceptions.ServiceUnavailable("blip")

        keeper = _LeaseKeeper(FlakySubscriber(), _sub("in"), ack_wait=100.0, request_timeout=1.0, clock=FakeClock())
        keeper.add(["a"])
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.transport.pubsub"):
            keeper.tick()
        keeper.tick()

        assert attempts == [["a"], ["a"]]
        assert any("retrying next tick" in record.message for record in caplog.records)

    def test_the_lease_thread_renews_on_its_own(self, broker, monkeypatch):
        monkeypatch.setattr(pubsub_module, "LEASE_REFRESH_SECONDS", 0.01)
        broker.provision()
        renewed = threading.Event()

        class Subscriber:
            def modify_ack_deadline(self, request, timeout=None):
                renewed.set()

        keeper = _LeaseKeeper(Subscriber(), _sub("in"), ack_wait=100.0, request_timeout=1.0)
        keeper.add(["a"])
        keeper.start()
        try:
            assert renewed.wait(5)
        finally:
            keeper.stop()

    def test_close_stops_renewing_releases_messages_and_closes_the_client(self, provisioned):
        transport = _transport()
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        transport.send(QueueName.INPUT, _msg(body="m2", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)
        consumer.fetch(10, 1.0)
        ack_ids = [r.ack_id for r in provisioned.records(_sub("in"))]

        consumer.close()

        assert provisioned.modify_calls[-1] == ([ack_ids[1], ack_ids[0]], 0), "held m2 and in-flight m1, released together"
        assert consumer._leases._stopped.is_set()
        assert FakeSubscriberClient.instances[-1].closed is True


class TestProvisioning:
    def test_a_missing_topic_fails_the_send_with_an_actionable_error(self, broker):
        with pytest.raises(AKConfigError, match=f"Pub/Sub topic '{_topic('in')}' does not exist.*auto_provision"):
            _transport().send(QueueName.INPUT, _msg())

    def test_a_missing_subscription_fails_the_consumer(self, broker):
        broker.add_topic(_topic("in"))
        with pytest.raises(AKConfigError, match=f"subscription '{_sub('in')}' does not exist"):
            _transport().create_consumer(QueueName.INPUT)

    def test_a_missing_dead_letter_topic_fails_the_consumer(self, broker):
        broker.provision()
        broker.topics.discard(_topic("in-dlq"))
        with pytest.raises(AKConfigError, match=_topic("in-dlq")):
            _transport().create_consumer(QueueName.INPUT)

    def test_a_subscription_without_ordering_is_refused(self, broker):
        broker.provision(ordering=False)
        with pytest.raises(AKConfigError, match="message ordering"):
            _transport().create_consumer(QueueName.INPUT)

    def test_verification_runs_once_per_process(self, provisioned, consumers):
        transport = _transport()
        _consumer(consumers, transport)
        _consumer(consumers, transport)
        _consumer(consumers, _transport())
        assert provisioned.get_subscription_calls == 1

    def test_auto_provision_creates_every_object(self, broker, consumers):
        transport = _transport(auto_provision=True, max_delivery_attempts={QueueName.INPUT: 7})
        _consumer(consumers, transport)
        transport.send(QueueName.INPUT, _msg())

        assert {_topic("in"), _topic("in-dlq")} <= broker.topics
        main, dead_letter = broker.created_subscriptions
        assert main == {
            "name": _sub("in"),
            "topic": _topic("in"),
            "enable_message_ordering": True,
            "ack_deadline_seconds": SUBSCRIPTION_ACK_DEADLINE_SECONDS,
            "dead_letter_policy": {"dead_letter_topic": _topic("in-dlq"), "max_delivery_attempts": 7},
        }
        assert dead_letter == {"name": _sub("in-dlq"), "topic": _topic("in-dlq")}

    def test_auto_provision_on_the_send_side_keeps_a_message_sent_before_any_consumer(self, broker, consumers):
        """Pub/Sub drops messages published to a topic with no subscription, so the first send
        provisions the subscription too (found by the live contract on the emulator)."""
        transport = _transport(auto_provision=True)
        transport.send(QueueName.INPUT, _msg(body="early", group_id="s1"))

        assert _bodies(_consumer(consumers, transport).fetch(10, 1.0)) == ["early"]

    def test_auto_provision_accepts_existing_objects(self, provisioned, consumers):
        transport = _transport(auto_provision=True)
        _consumer(consumers, transport)
        transport.send(QueueName.INPUT, _msg())
        assert provisioned.created_subscriptions == []


class TestProject:
    def test_the_configured_project_wins(self, provisioned, monkeypatch):
        monkeypatch.setattr(pubsub_module.google.auth, "default", lambda: pytest.fail("ADC must not be consulted"))
        assert _transport()._topic_path("t") == _topic("t")

    def test_the_adc_project_is_used_and_cached(self, broker, monkeypatch):
        calls = []
        monkeypatch.setattr(pubsub_module.google.auth, "default", lambda: calls.append(1) or (None, "adc-project"))

        assert _transport(project_id=None)._topic_path("t") == "projects/adc-project/topics/t"
        assert _transport(project_id=None)._subscription_path("s") == "projects/adc-project/subscriptions/s"
        assert calls == [1]

    @pytest.mark.parametrize(
        "adc", [lambda: (None, None), lambda: (_ for _ in ()).throw(RuntimeError("no credentials"))], ids=["no-project", "no-adc"]
    )
    def test_no_project_at_all_is_a_config_error(self, broker, monkeypatch, adc):
        monkeypatch.setattr(pubsub_module.google.auth, "default", adc)
        with pytest.raises(AKConfigError, match=r"execution\.queues\.pubsub\.project_id"):
            _transport(project_id=None)._topic_path("t")


class TestFactory:
    @staticmethod
    def _use(monkeypatch, queues: _QueuesConfig):
        config = SimpleNamespace(execution=SimpleNamespace(queues=queues))
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))

    def test_type_pubsub_builds_the_transport_from_config(self, broker, monkeypatch):
        self._use(
            monkeypatch,
            _QueuesConfig(
                type="pubsub",
                pubsub={
                    "project_id": "p",
                    "input_topic": "it",
                    "input_subscription": "is",
                    "dlq_suffix": "-dead",
                    "ack_wait": 42,
                    "auto_provision": True,
                },
                input={"max_receive_count": 10},
                output={"max_receive_count": 2},
            ),
        )

        transport = QueueTransportFactory.create()

        assert isinstance(transport, PubSubTransport)
        assert (transport._project_id, transport._topics[QueueName.INPUT], transport._subscriptions[QueueName.INPUT]) == ("p", "it", "is")
        assert (transport._dlq_suffix, transport._ack_wait, transport._auto_provision) == ("-dead", 42, True)
        assert transport._max_delivery_attempts == {QueueName.INPUT: 11, QueueName.OUTPUT: 5}, "one past the loop's limit, at least 5"

    def test_max_delivery_attempts_is_capped_at_pubsubs_maximum(self, broker, monkeypatch):
        self._use(monkeypatch, _QueuesConfig(type="pubsub", pubsub={}, input={"max_receive_count": 500}))
        assert QueueTransportFactory.create()._max_delivery_attempts[QueueName.INPUT] == 100

    def test_a_missing_pubsub_block_raises(self, broker, monkeypatch):
        self._use(monkeypatch, _QueuesConfig(type="pubsub"))
        with pytest.raises(AKConfigError, match=r"execution\.queues\.pubsub"):
            QueueTransportFactory.create()

    def test_an_explicit_block_names_its_own_path(self, broker):
        """The sandbox broker's seam: errors point at the caller's block."""
        with pytest.raises(AKConfigError, match=r"sandbox\.broker\.queue\.pubsub"):
            QueueTransportFactory.create(queues_config=_QueuesConfig(type="pubsub"), config_path="sandbox.broker.queue")

    def test_a_missing_extra_names_the_pubsub_extra(self, broker, monkeypatch):
        monkeypatch.setitem(sys.modules, "agentkernel.pipeline.transport.pubsub", None)
        with pytest.raises(ImportError, match=r"agentkernel\[pubsub\]"):
            QueueTransportFactory.create(queues_config=_QueuesConfig(type="pubsub", pubsub={}))

    def test_bookkeeping_is_built_on_first_consumer_with_the_pubsub_feature(self, provisioned, consumers, monkeypatch):
        features = []
        monkeypatch.setattr(
            BookkeepingStoreFactory, "create", classmethod(lambda cls, feature="": features.append(feature) or InMemoryBookkeepingStore())
        )
        transport = _transport(bookkeeping=None)

        transport.send(QueueName.INPUT, _msg())
        assert features == [], "the send side needs no bookkeeping"
        _consumer(consumers, transport)
        _consumer(consumers, transport)
        assert features == ["execution.queues.type: pubsub"]


class FailingBookkeeping(InMemoryBookkeepingStore):
    """Bookkeeping whose named operations raise, as when its Redis is unreachable."""

    def __init__(self, *failing: str, times: int = 1_000):
        super().__init__()
        self._failing = {name: times for name in failing}

    def _maybe_fail(self, name: str) -> None:
        if self._failing.get(name, 0) > 0:
            self._failing[name] -= 1
            raise ConnectionError(f"{name}: bookkeeping store unreachable")

    def incr_attempts(self, key):
        self._maybe_fail("incr_attempts")
        return super().incr_attempts(key)

    def clear_attempts(self, key):
        self._maybe_fail("clear_attempts")
        super().clear_attempts(key)

    def mark_acked(self, key):
        self._maybe_fail("mark_acked")
        super().mark_acked(key)


class TestFailures:
    def test_ack_never_raises(self, provisioned, consumers, monkeypatch, caplog):
        """Processing already succeeded: a failing ack must not turn into a nack and a second run."""
        transport = _transport(bookkeeping=FailingBookkeeping("mark_acked", "clear_attempts"))
        transport.send(QueueName.INPUT, _msg(group_id="s1"))
        consumer = _consumer(consumers, transport)
        [message] = consumer.fetch(10, 1.0)
        monkeypatch.setattr(FakeSubscriberClient, "acknowledge", lambda self, request, timeout=None: (_ for _ in ()).throw(RuntimeError("down")))

        with caplog.at_level(logging.ERROR, logger="ak.pipeline.transport.pubsub"):
            consumer.ack(message)

        assert consumer._in_flight == {} and consumer._leases.leased() == set()
        assert len([record for record in caplog.records if record.levelname == "ERROR"]) == 3

    def test_unreachable_bookkeeping_keeps_the_message_for_the_next_fetch(self, provisioned, consumers):
        transport = _transport(bookkeeping=FailingBookkeeping("incr_attempts", times=1))
        transport.send(QueueName.INPUT, _msg(body="m1", group_id="s1"))
        consumer = _consumer(consumers, transport)

        with pytest.raises(ConnectionError):
            consumer.fetch(10, 1.0)
        pulls = len(provisioned.pull_calls)
        [message] = consumer.fetch(10, 1.0)

        assert (message.body, message.receive_count) == ("m1", 1)
        assert len(provisioned.pull_calls) == pulls, "served from what was held, not pulled again"


def _push_body(message: QueueMessage, message_id: str = "m1", subscription: str | None = None, **extra) -> dict:
    """A push request body exactly as Pub/Sub sends it: base64 data, the envelope marker, the ordering key."""
    data, attributes = PubSubEnvelopeCodec.encode(message)
    return {
        "subscription": subscription or _sub("in"),
        "message": {
            "data": base64.b64encode(data).decode(),
            "attributes": attributes,
            "messageId": message_id,
            "orderingKey": message.group_id or "",
            "publishTime": "2026-11-09T00:00:00Z",
        },
        **extra,
    }


class TestPushReceiver:
    """The push path (spec #886 §1.9): the same bookkeeping and failure path as the pull consumer."""

    @pytest.fixture
    def runs(self):
        return {"processed": [], "failed_permanently": [], "fail": False}

    def _receiver(self, runs, max_receive_count: int = 2, **transport_overrides):
        def process(message):
            runs["processed"].append(message)
            if runs["fail"]:
                raise RuntimeError("agent failed")

        return _transport(**transport_overrides).create_push_receiver(
            QueueName.INPUT, process=process, on_permanent_failure=runs["failed_permanently"].append, max_receive_count=max_receive_count
        )

    def test_a_delivery_runs_once_and_is_acknowledged(self, provisioned, runs):
        receiver = self._receiver(runs)
        body = _push_body(_msg(body='{"p": 1}', group_id="s1", attributes={"request_id": "r1"}))

        assert receiver.handle(body) == 204
        [message] = runs["processed"]
        assert (message.body, message.group_id, message.attributes, message.receive_count) == ('{"p": 1}', "s1", {"request_id": "r1"}, 1)
        assert message.message_id == "m1"

        assert receiver.handle(body) == 204, "a redelivery of an acknowledged message (ack deadline passed mid-run, or a cascade)"
        assert len(runs["processed"]) == 1, "it does not run again"

    def test_a_failed_run_is_nacked_and_counted_exactly(self, provisioned, runs):
        receiver = self._receiver(runs, max_receive_count=5)
        runs["fail"] = True
        body = _push_body(_msg(group_id="s1"), deliveryAttempt=9)

        assert [receiver.handle(body) for _ in range(3)] == [500, 500, 500]
        assert [message.receive_count for message in runs["processed"]] == [1, 2, 3], "Pub/Sub's deliveryAttempt is not trusted"

    def test_permanent_failure_runs_the_hook_copies_to_the_dead_letter_topic_and_acks(self, provisioned, runs):
        receiver = self._receiver(runs, max_receive_count=2)
        runs["fail"] = True
        body = _push_body(_msg(body="poison", group_id="s1"))

        assert [receiver.handle(body) for _ in range(3)] == [500, 500, 204]

        assert len(runs["processed"]) == 2, "the third delivery does not run the agent"
        [failed] = runs["failed_permanently"]
        assert failed.receive_count == 3
        [(_, copy)] = [entry for entry in provisioned.published if entry[0] == _topic("in-dlq")]
        assert copy.attributes[ERROR_ATTRIBUTE] == "exceeded max_receive_count after 3 deliveries"
        assert PubSubEnvelopeCodec.decode(copy.data, copy.attributes, "", "x").body == "poison"

    def test_a_raising_permanent_failure_hook_is_nacked(self, provisioned, runs):
        def broken_hook(message):
            raise RuntimeError("could not answer the caller")

        receiver = _transport().create_push_receiver(QueueName.INPUT, process=lambda m: None, on_permanent_failure=broken_hook, max_receive_count=0)
        assert receiver.handle(_push_body(_msg())) == 500, "the ConsumerLoop contract: a raising hook leaves the message for redelivery"

    def test_a_duplicate_dedup_id_is_acknowledged_without_running(self, provisioned, runs):
        receiver = self._receiver(runs)
        assert receiver.handle(_push_body(_msg(body="first", group_id="s1", dedup_id="d1"), message_id="m1")) == 204
        assert receiver.handle(_push_body(_msg(body="again", group_id="s2", dedup_id="d1"), message_id="m2")) == 204
        assert [message.body for message in runs["processed"]] == ["first"]

    def test_a_foreign_message_is_copied_to_the_dead_letter_topic_and_acknowledged(self, provisioned, runs):
        receiver = self._receiver(runs)
        body = {
            "subscription": _sub("in"),
            "message": {"data": base64.b64encode(b"not an envelope").decode(), "attributes": {"k": "v"}, "messageId": "m9"},
        }

        assert receiver.handle(body) == 204
        assert runs["processed"] == []
        [(_, copy)] = [entry for entry in provisioned.published if entry[0] == _topic("in-dlq")]
        assert (copy.data, copy.attributes) == (b"not an envelope", {"k": "v", ERROR_ATTRIBUTE: "not an Agent Kernel envelope"})

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"subscription": _sub("in")},
            {"message": {"messageId": "m1", "data": ""}},
            {"subscription": _sub("in"), "message": {"data": ""}},
            {"subscription": _sub("in"), "message": {"messageId": "m1", "data": "%%% not base64"}},
            {"subscription": _sub("in"), "message": {"messageId": "m1", "data": "", "attributes": ["not", "a", "map"]}},
        ],
        ids=["empty", "no-message", "no-subscription", "no-message-id", "bad-base64", "bad-attributes"],
    )
    def test_a_request_that_is_not_a_push_delivery_is_rejected(self, provisioned, runs, body):
        assert self._receiver(runs).handle(body) == 400
        assert runs["processed"] == []

    def test_an_unreachable_bookkeeping_store_propagates_for_a_nack(self, provisioned, runs):
        receiver = self._receiver(runs, bookkeeping=FailingBookkeeping("incr_attempts"))
        with pytest.raises(ConnectionError):
            receiver.handle(_push_body(_msg()))
        assert runs["processed"] == []

    def test_bookkeeping_is_keyed_by_the_delivering_subscription(self, provisioned, runs):
        """A reply carries its request's dedup id, so the claims must not cross subscriptions."""
        receiver = self._receiver(runs)
        receiver.handle(_push_body(_msg(body="request", dedup_id="d1"), message_id="m1", subscription=_sub("in")))
        receiver.handle(_push_body(_msg(body="reply", dedup_id="d1"), message_id="m2", subscription=_sub("out")))
        assert [message.body for message in runs["processed"]] == ["request", "reply"]


class TestPubSubTransportContract(QueueTransportContract):
    """The shared transport contract, with no capability opt-outs."""

    @pytest.fixture(autouse=True)
    def _fake_pubsub(self, provisioned):
        self._broker = provisioned
        self._bookkeeping = InMemoryBookkeepingStore()

    def force_redelivery(self) -> None:
        # Past every deadline the transport or the subscription could have set.
        self._broker.clock.advance(601)

    def make_transport(self) -> PubSubTransport:
        return _transport(ack_wait=self.ack_wait, bookkeeping=self._bookkeeping)
