"""NATS JetStream transport (spec #495 §7) over a fake JetStream.

The fake replaces the client, not the bridge: every call still crosses :class:`_NatsLoop`'s real
event-loop thread via ``run_coroutine_threadsafe``, so the threading path this transport depends on
is exercised rather than mocked away. The fake models the JetStream behaviours the transport leans
on: work-queue delivery with one in-flight message per partition consumer (``max_ack_pending=1``),
``num_delivered`` counting, nak redelivery, term, and stream-scoped dedup on ``Nats-Msg-Id``.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import pytest
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.errors import NotFoundError

from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport import nats as nats_module
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.nats import GROUP_ID_HEADER, MSG_ID_HEADER, NatsTransport, _NatsLoop

URL = "nats://localhost:4222"
INPUT_STREAM = "AGENT_REQUESTS"
OUTPUT_STREAM = "AGENT_REPLIES"
INPUT_PREFIX = "chat.req"
OUTPUT_PREFIX = "chat.out"
PARTITIONS = 4


class FakeSequence:
    def __init__(self, stream: int):
        self.stream = stream


class FakeMetadata:
    def __init__(self, stream: str, sequence: int, num_delivered: int):
        self.stream = stream
        self.sequence = FakeSequence(sequence)
        self.num_delivered = num_delivered


class FakeMsg:
    """A JetStream message with the ack/nak/term surface the transport uses."""

    def __init__(self, stream_state: "FakeStream", record: dict, num_delivered: int):
        self._stream_state = stream_state
        self._record = record
        self.data = record["data"]
        self.headers = dict(record["headers"] or {})
        self.subject = record["subject"]
        self.metadata = FakeMetadata(stream_state.name, record["seq"], num_delivered)

    async def ack(self) -> None:
        self._stream_state.finish(self._record)

    async def nak(self, delay: float = 0) -> None:
        self._record["nak_delay"] = delay
        self._stream_state.release(self._record)

    async def term(self) -> None:
        self._record["terminated"] = True
        self._stream_state.finish(self._record)

    async def in_progress(self) -> None:
        return None


class FakeStream:
    """One work-queue stream: per-partition FIFO, one in-flight message per partition, dedup."""

    def __init__(self, name: str, subjects: List[str], ack_wait: float = 2.0):
        self.name = name
        self.subjects = subjects
        self.ack_wait = ack_wait
        self.records: List[dict] = []
        self.in_flight: Dict[int, dict] = {}  # partition -> record
        self.dedup_ids: set = set()
        self.consumers: Dict[str, Any] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def publish(self, subject: str, data: bytes, headers: Optional[dict]) -> dict:
        with self._lock:
            dedup_id = (headers or {}).get(MSG_ID_HEADER)
            if dedup_id is not None and dedup_id in self.dedup_ids:
                return {"seq": 0, "duplicate": True}
            if dedup_id is not None:
                self.dedup_ids.add(dedup_id)
            self._seq += 1
            record = {
                "seq": self._seq,
                "subject": subject,
                "data": data,
                "headers": headers,
                "partition": int(subject.split(".")[2]),
                "deliveries": 0,
                "done": False,
            }
            self.records.append(record)
            return {"seq": self._seq, "duplicate": False}

    def next_for(self, partition: int) -> Optional[FakeMsg]:
        with self._lock:
            held = self.in_flight.get(partition)
            if held is not None and time.monotonic() >= held["deadline"]:
                self.in_flight.pop(partition)  # ack_wait elapsed: the server redelivers
                held = None
            if held is not None:
                return None  # max_ack_pending=1
            for record in self.records:
                if record["done"] or record["partition"] != partition:
                    continue
                record["deliveries"] += 1
                record["deadline"] = time.monotonic() + self.ack_wait
                self.in_flight[partition] = record
                return FakeMsg(self, record, record["deliveries"])
            return None

    def finish(self, record: dict) -> None:
        with self._lock:
            record["done"] = True
            self.in_flight.pop(record["partition"], None)

    def release(self, record: dict) -> None:
        with self._lock:
            self.in_flight.pop(record["partition"], None)

    def pending(self) -> List[dict]:
        return [record for record in self.records if not record["done"]]


class FakePullSubscription:
    def __init__(self, stream: FakeStream, partition: int):
        self._stream = stream
        self._partition = partition
        self.unsubscribed = False

    async def fetch(self, batch: int = 1, timeout: float = 1.0) -> List[FakeMsg]:
        messages = []
        while len(messages) < batch:
            message = self._stream.next_for(self._partition)
            if message is None:
                break
            messages.append(message)
        if not messages:
            raise NatsTimeoutError
        return messages

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class FakeJetStream:
    def __init__(self, server: "FakeNatsServer"):
        self._server = server

    async def publish(self, subject: str, payload: bytes, headers=None):
        stream = self._server.stream_for_subject(subject)
        if stream is None:
            raise NotFoundError
        result = stream.publish(subject, payload, headers)

        class Ack:
            seq = result["seq"]
            duplicate = result["duplicate"]

        return Ack()

    async def stream_info(self, name: str):
        if name not in self._server.streams:
            raise NotFoundError
        return self._server.streams[name]

    async def add_stream(self, config):
        self._server.streams[config.name] = FakeStream(config.name, list(config.subjects))
        self._server.created_streams.append(config)
        return self._server.streams[config.name]

    async def consumer_info(self, stream: str, durable: str):
        if stream not in self._server.streams or durable not in self._server.streams[stream].consumers:
            raise NotFoundError
        return self._server.streams[stream].consumers[durable]

    async def add_consumer(self, stream: str, config):
        self._server.streams[stream].consumers[config.durable_name] = config
        self._server.created_consumers.append(config)
        return config

    async def pull_subscribe_bind(self, durable: str, stream: str):
        stream_state = self._server.streams[stream]
        if durable not in stream_state.consumers:
            raise NotFoundError
        partition = int(durable.rsplit("p", 1)[1])
        return FakePullSubscription(stream_state, partition)


class FakeClient:
    def __init__(self, server: "FakeNatsServer"):
        self._server = server
        self.is_connected = True

    def jetstream(self):
        return FakeJetStream(self._server)


class FakeNatsServer:
    def __init__(self):
        self.streams: Dict[str, FakeStream] = {}
        self.created_streams: List[Any] = []
        self.created_consumers: List[Any] = []
        self.connect_calls = 0

    def provision(self, name: str, prefix: str, partitions: int = PARTITIONS, ack_wait: float = 2.0) -> None:
        """Pre-create a stream and its partition consumers, as NACK CRs would."""
        stream = FakeStream(name, [f"{prefix}.>"], ack_wait=ack_wait)
        for partition in range(partitions):
            stream.consumers[f"{name}-p{partition}"] = object()
        self.streams[name] = stream

    def stream_for_subject(self, subject: str) -> Optional[FakeStream]:
        for stream in self.streams.values():
            for pattern in stream.subjects:
                if subject.startswith(pattern.rstrip(">").rstrip(".")):
                    return stream
        return None


@pytest.fixture
def server(monkeypatch):
    fake = FakeNatsServer()

    async def _connect(servers=None, **kwargs):
        fake.connect_calls += 1
        return FakeClient(fake)

    monkeypatch.setattr(nats_module.nats, "connect", _connect)
    NatsTransport.reset()
    yield fake
    NatsTransport.reset()


def _transport(server=None, **overrides) -> NatsTransport:
    kwargs = {
        "url": URL,
        "input_stream": INPUT_STREAM,
        "input_subject_prefix": INPUT_PREFIX,
        "output_stream": OUTPUT_STREAM,
        "output_subject_prefix": OUTPUT_PREFIX,
        "partitions": PARTITIONS,
        "retry_backoff": 0.0,
        "request_timeout": 5.0,
    }
    kwargs.update(overrides)
    return NatsTransport(**kwargs)


def _provisioned(server) -> NatsTransport:
    server.provision(INPUT_STREAM, INPUT_PREFIX)
    server.provision(OUTPUT_STREAM, OUTPUT_PREFIX)
    return _transport()


class TestLoopBridge:
    def test_coroutines_run_on_a_shared_daemon_loop(self):
        async def where_am_i():
            return threading.current_thread().name

        assert _NatsLoop.run(where_am_i(), timeout=5) == "nats-event-loop"
        assert _NatsLoop.run(where_am_i(), timeout=5) == "nats-event-loop", "the same loop is reused"

    def test_a_stalled_call_times_out_and_is_cancelled(self):
        started = threading.Event()

        async def never_finishes():
            started.set()
            await asyncio.sleep(30)

        with pytest.raises(TimeoutError):
            _NatsLoop.run(never_finishes(), timeout=0.2)
        assert started.is_set(), "the coroutine did start, so the timeout is the wait and not a scheduling failure"


class TestSend:
    def test_publish_carries_headers_and_partitioned_subject(self, server):
        transport = _provisioned(server)
        result = transport.send(
            QueueName.INPUT,
            QueueMessage(body='{"prompt": "hi"}', attributes={"request_id": "r1"}, group_id="s1", dedup_id="d1"),
        )

        [record] = server.streams[INPUT_STREAM].records
        assert record["data"] == b'{"prompt": "hi"}'
        assert record["headers"]["request_id"] == "r1"
        assert record["headers"][MSG_ID_HEADER] == "d1", "the dedup id becomes the JetStream message id"
        assert record["headers"][GROUP_ID_HEADER] == "s1", "the session id travels as a header, not only a subject token"
        assert record["subject"] == f"{INPUT_PREFIX}.{transport.partition_for('s1')}.s1"
        assert result["MessageId"] == f"{INPUT_STREAM}:1"

    def test_sessions_map_to_stable_partitions(self, server):
        transport = _provisioned(server)
        first = transport.partition_for("session-abc")
        assert first == transport.partition_for("session-abc"), "the same session always lands on one partition"
        assert 0 <= first < PARTITIONS
        assert {transport.partition_for(f"s{i}") for i in range(40)} == set(range(PARTITIONS)), "sessions spread over partitions"

    def test_partition_hash_is_stable_across_processes(self, server):
        """Not Python's hash(): string hashing is salted per interpreter, so two pods would
        disagree about a session's partition and its ordering guarantee would be lost."""
        transport = _provisioned(server)
        # crc32 of "session-abc" is fixed for all time, so this value can be asserted literally.
        import zlib

        assert transport.partition_for("session-abc") == zlib.crc32(b"session-abc") % PARTITIONS

    def test_session_ids_with_dots_stay_a_single_subject_token(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="tenant.a b"))
        [record] = server.streams[INPUT_STREAM].records
        assert record["subject"].count(".") == 3, "prefix has one dot, then partition, then one token"
        assert record["headers"][GROUP_ID_HEADER] == "tenant.a b", "the header keeps the real value"

    def test_output_goes_to_the_reply_stream(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.OUTPUT, QueueMessage(body="reply", group_id="s1"))
        assert len(server.streams[OUTPUT_STREAM].records) == 1
        assert server.streams[INPUT_STREAM].records == []


class TestConsume:
    def test_envelope_mapping(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="body", attributes={"request_id": "r1"}, group_id="s1", dedup_id="d1"))

        [message] = transport.create_consumer(QueueName.INPUT).fetch(10, 1.0)

        assert message.body == "body"
        assert message.attributes == {"request_id": "r1"}, "the NATS and group-id headers are lifted out"
        assert message.dedup_id == "d1"
        assert message.group_id == "s1"
        assert message.receive_count == 1, "num_delivered is 1 on the first delivery"
        assert message.message_id == f"{INPUT_STREAM}:1"

    def test_ack_removes_the_message(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="body", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)

        [message] = consumer.fetch(10, 1.0)
        consumer.ack(message)

        assert server.streams[INPUT_STREAM].pending() == []
        assert consumer.fetch(10, 0.2) == []

    def test_nack_redelivers_with_the_configured_delay(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="body", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)

        [message] = consumer.fetch(10, 1.0)
        consumer.nack(message)

        [record] = server.streams[INPUT_STREAM].pending()
        assert record["nak_delay"] == 0.0, "the delay comes from retry_backoff"
        [redelivered] = consumer.fetch(10, 1.0)
        assert redelivered.receive_count == 2, "the server counts the delivery, not the client"

    def test_dead_letter_terminates_delivery(self, server, caplog):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="poison", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)
        [message] = consumer.fetch(10, 1.0)

        with caplog.at_level(logging.WARNING, logger="ak.pipeline.transport.nats"):
            consumer.dead_letter(message)

        [record] = server.streams[INPUT_STREAM].records
        assert record["terminated"] is True, "term() records intent; a bare ack would not"
        assert record["done"] is True
        assert any("Terminated message" in entry.message for entry in caplog.records)

    def test_one_message_in_flight_per_partition(self, server):
        """max_ack_pending=1 is what keeps a session's turns ordered: the server withholds the
        next message on that partition until the current one reaches a terminal state."""
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="first", group_id="s1"))
        transport.send(QueueName.INPUT, QueueMessage(body="second", group_id="s1"))
        consumer = transport.create_consumer(QueueName.INPUT)

        [first] = consumer.fetch(10, 1.0)
        assert first.body == "first"
        assert consumer.fetch(10, 0.2) == [], "the next turn waits for the current one"

        consumer.ack(first)
        [second] = consumer.fetch(10, 1.0)
        assert second.body == "second"

    def test_close_unsubscribes_every_partition(self, server):
        transport = _provisioned(server)
        consumer = transport.create_consumer(QueueName.INPUT)
        subscriptions = list(consumer._subscriptions.values())

        consumer.close()

        assert len(subscriptions) == PARTITIONS
        assert all(subscription.unsubscribed for subscription in subscriptions)


class TestDeduplication:
    def test_repeated_dedup_id_is_dropped_by_the_stream(self, server):
        transport = _provisioned(server)
        transport.send(QueueName.INPUT, QueueMessage(body="m1", group_id="s1", dedup_id="d1"))
        transport.send(QueueName.INPUT, QueueMessage(body="m1-again", group_id="s1", dedup_id="d1"))

        assert len(server.streams[INPUT_STREAM].records) == 1, "the duplicate never enters the stream"

    def test_a_reply_may_reuse_its_request_dedup_id(self, server):
        """JetStream scopes the duplicate window per stream, and requests and replies live on
        different streams, so the reply cannot be mistaken for a repeat of its request. The Kafka
        transport had to scope its own claim by topic to get the same property."""
        transport = _provisioned(server)
        request_id = "req-1"

        transport.send(QueueName.INPUT, QueueMessage(body="request", group_id="s1", dedup_id=request_id))
        transport.send(QueueName.OUTPUT, QueueMessage(body="reply", group_id="s1", dedup_id=request_id))

        assert len(server.streams[INPUT_STREAM].records) == 1
        assert len(server.streams[OUTPUT_STREAM].records) == 1, "the reply survives its request's dedup id"


class TestProvisioning:
    def test_auto_provision_creates_the_stream_and_partition_consumers(self, server):
        transport = _transport(auto_provision=True, max_deliver={QueueName.INPUT: 4})
        transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))

        [stream_config] = server.created_streams
        assert stream_config.name == INPUT_STREAM
        assert stream_config.subjects == [f"{INPUT_PREFIX}.>"]
        assert stream_config.retention == nats_module.RetentionPolicy.WORK_QUEUE
        assert stream_config.duplicate_window == 300.0

        assert len(server.created_consumers) == PARTITIONS
        first = server.created_consumers[0]
        assert first.durable_name == f"{INPUT_STREAM}-p0"
        assert first.filter_subject == f"{INPUT_PREFIX}.0.>", "non-overlapping filters are required on a work-queue stream"
        assert first.max_ack_pending == 1
        assert first.max_deliver == 4, "one above the loop's limit, so the client hook runs before the server cuts off"

    def test_auto_provision_leaves_an_existing_stream_alone(self, server):
        server.provision(INPUT_STREAM, INPUT_PREFIX)
        _transport(auto_provision=True).send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))
        assert server.created_streams == [], "an operator-managed stream is not reconfigured"

    def test_missing_stream_without_auto_provision_fails_loudly(self, server):
        with pytest.raises(AKConfigError, match="does not exist"):
            _transport().send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))

    def test_missing_consumers_without_auto_provision_name_the_gap(self, server):
        # The stream exists but nothing created its partition consumers.
        server.streams[INPUT_STREAM] = FakeStream(INPUT_STREAM, [f"{INPUT_PREFIX}.>"])

        with pytest.raises(AKConfigError, match="partition consumer") as raised:
            _transport().send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))
        assert f"{INPUT_STREAM}-p0" in str(raised.value), "the error names the first missing object"
        assert "auto_provision" in str(raised.value), "and how to have Agent Kernel create it"

    def test_provisioning_failure_is_retried_rather_than_cached(self, server):
        transport = _transport()
        with pytest.raises(AKConfigError):
            transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))

        server.provision(INPUT_STREAM, INPUT_PREFIX)
        transport.send(QueueName.INPUT, QueueMessage(body="{}", group_id="s1"))
        assert len(server.streams[INPUT_STREAM].records) == 1, "the second attempt provisions instead of skipping"

    def test_rejects_a_partition_count_below_one(self, server):
        with pytest.raises(AKConfigError, match="partitions"):
            _transport(partitions=0)


class TestConsumerCapacity:
    def test_warns_when_partitions_cannot_keep_consumers_busy(self, server, caplog):
        with caplog.at_level(logging.WARNING, logger="ak.pipeline.transport.nats"):
            _transport(partitions=2).check_consumer_capacity(QueueName.INPUT, num_consumers=5)

        [warning] = [record for record in caplog.records if record.levelname == "WARNING"]
        assert "2 partition(s) but 5 consumer(s)" in warning.message
        assert "re-maps sessions" in warning.message

    def test_no_warning_when_partitions_are_sufficient(self, server, caplog):
        with caplog.at_level(logging.INFO, logger="ak.pipeline.transport.nats"):
            _transport(partitions=32).check_consumer_capacity(QueueName.INPUT, num_consumers=5)
        assert [record for record in caplog.records if record.levelname == "WARNING"] == []


class TestFactory:
    @staticmethod
    def _cfg():
        class _Nats:
            url = URL
            input_stream = INPUT_STREAM
            input_subject_prefix = INPUT_PREFIX
            output_stream = OUTPUT_STREAM
            output_subject_prefix = OUTPUT_PREFIX
            partitions = 8
            ack_wait = 300.0
            retry_backoff = 2.0
            duplicate_window = 300.0
            max_age = 86400.0
            request_timeout = 10.0
            auto_provision = True

        class _Cfg:
            class execution:
                class queues:
                    type = "nats"
                    nats = _Nats

                    class input:
                        url = None
                        max_receive_count = 2

                    class output:
                        max_receive_count = 3

        return _Cfg

    def test_type_nats_builds_the_transport_from_config(self, server, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg()))
        transport = QueueTransportFactory.create()

        assert isinstance(transport, NatsTransport)
        assert transport._partitions == 8
        assert transport._auto_provision is True
        assert transport._max_deliver == {
            QueueName.INPUT: 3,
            QueueName.OUTPUT: 4,
        }, "the server ceiling sits one delivery above each queue's max_receive_count"

    def test_missing_nats_block_raises(self, server, monkeypatch):
        cfg = self._cfg()
        cfg.execution.queues.nats = None
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: cfg))
        with pytest.raises(AKConfigError, match="execution.queues.nats"):
            QueueTransportFactory.create()


class TestNatsTransportContract(QueueTransportContract):
    """The shared transport contract against JetStream semantics."""

    ack_wait = 0.3

    @pytest.fixture(autouse=True)
    def _provisioned_server(self, server):
        server.provision(INPUT_STREAM, INPUT_PREFIX, ack_wait=self.ack_wait)
        server.provision(OUTPUT_STREAM, OUTPUT_PREFIX, ack_wait=self.ack_wait)
        self._server = server

    # timeout_redelivery stays True, unlike Kafka: ack_wait is a real visibility timeout, so the
    # contract's unacked-redelivery case genuinely applies here.

    def make_transport(self) -> NatsTransport:
        return _transport()
