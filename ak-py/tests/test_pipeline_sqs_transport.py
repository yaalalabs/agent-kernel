import itertools
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.core.sqs_handler import SQSHandler
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.testing import QueueTransportContract
from agentkernel.pipeline.transport import sqs as sqs_wire
from agentkernel.pipeline.transport.base import QueueTransportFactory
from agentkernel.pipeline.transport.sqs import SQS_MAX_WAIT_SECONDS, SQSTransport, SQSTransportConsumer

INPUT_URL = "https://sqs.test/input.fifo"
OUTPUT_URL = "https://sqs.test/output.fifo"


def _record(receipt_handle="rh-1"):
    return {
        "MessageId": "mid-1",
        "ReceiptHandle": receipt_handle,
        "Body": '{"result": "ok"}',
        "Attributes": {"MessageGroupId": "s1", "ApproximateReceiveCount": "2"},
        "MessageAttributes": {
            "request_id": {"DataType": "String", "StringValue": "r1"},
            "status_code": {"DataType": "String", "StringValue": "200"},
        },
    }


class TestSendWireFormat:
    """The send side must be byte-identical to the ECS wire format (spec §5): what reaches the
    boto3 client is exactly what SQSHandler.build_send_message_kwargs produces (both run the
    same relocated wire helpers, so this pins the interop guarantee)."""

    @pytest.fixture
    def client(self, monkeypatch):
        mock_client = MagicMock()
        monkeypatch.setattr("agentkernel.pipeline.transport.sqs.boto3.client", lambda service: mock_client)
        return mock_client

    def test_send_kwargs_equal_sqs_handler_build(self, client):
        message = QueueMessage(
            body='{"prompt": "hi", "session_id": "s1"}',
            attributes={"request_id": "r1", "user_id": "u1"},
            group_id="s1",
            dedup_id="d1",
        )
        SQSTransport(input_url=INPUT_URL, output_url=OUTPUT_URL).send(QueueName.INPUT, message)

        expected = SQSHandler.build_send_message_kwargs(
            message_body=message.body,
            message_group_id="s1",
            message_deduplication_id="d1",
            message_attributes=[
                SQSHandler.CustomAttribute(name="request_id", value="r1", datatype=SQSHandler.AttributeDataType.STRING),
                SQSHandler.CustomAttribute(name="user_id", value="u1", datatype=SQSHandler.AttributeDataType.STRING),
            ],
        )
        client.send_message.assert_called_once_with(QueueUrl=INPUT_URL, **expected)

    def test_send_without_optionals_omits_them(self, client):
        SQSTransport(input_url=INPUT_URL, output_url=OUTPUT_URL).send(QueueName.INPUT, QueueMessage(body="{}"))
        assert client.send_message.call_args.kwargs == {"QueueUrl": INPUT_URL, "MessageBody": "{}"}

    def test_send_routes_to_the_output_queue_url(self, client):
        SQSTransport(input_url=INPUT_URL, output_url=OUTPUT_URL).send(QueueName.OUTPUT, QueueMessage(body="{}"))
        assert client.send_message.call_args.kwargs["QueueUrl"] == OUTPUT_URL


class TestSQSHandlerDelegation:
    """SQSHandler's wire-format surface is the relocated pipeline implementation: the nested
    classes must stay the same objects (user imports, isinstance checks, patch targets), and
    the kwargs builders must stay one implementation."""

    def test_nested_classes_alias_the_pipeline_models(self):
        assert SQSHandler.CustomAttribute is sqs_wire.CustomAttribute
        assert SQSHandler.AttributeDataType is sqs_wire.AttributeDataType
        assert SQSHandler.SQSQueueInputMessage is sqs_wire.SQSQueueInputMessage

    def test_build_send_message_kwargs_is_the_shared_implementation(self):
        attributes = [sqs_wire.CustomAttribute(name="request_id", value="r1", datatype=sqs_wire.AttributeDataType.STRING)]
        assert SQSHandler.build_send_message_kwargs(
            message_body={"a": 1}, message_group_id="g1", message_deduplication_id="d1", message_attributes=attributes
        ) == sqs_wire.build_send_message_kwargs(
            message_body={"a": 1}, message_group_id="g1", message_deduplication_id="d1", message_attributes=attributes
        )

    def test_duplicate_attribute_names_still_rejected_through_the_handler(self):
        attributes = [
            SQSHandler.CustomAttribute(name="dup", value="1", datatype=SQSHandler.AttributeDataType.STRING),
            SQSHandler.CustomAttribute(name="dup", value="2", datatype=SQSHandler.AttributeDataType.STRING),
        ]
        with pytest.raises(ValueError, match="Duplicate SQS message attribute name"):
            SQSHandler._build_message_attributes(attributes)


class TestConsumer:
    def _consumer(self, monkeypatch, client, queue_url=INPUT_URL):
        monkeypatch.setattr("agentkernel.pipeline.transport.sqs.boto3.client", lambda service: client)
        return SQSTransportConsumer(queue_url)

    def test_fetch_maps_boto3_record_to_envelope(self, monkeypatch):
        record = _record()
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [record]}

        [message] = self._consumer(monkeypatch, client).fetch(5, 20.0)

        assert message.body == '{"result": "ok"}'
        assert message.attributes == {"request_id": "r1", "status_code": "200"}
        assert message.group_id == "s1"
        assert message.receive_count == 2
        assert message.message_id == "mid-1"
        assert message.native is record

    def test_fetch_passes_long_poll_parameters(self, monkeypatch):
        client = MagicMock()
        client.receive_message.return_value = {}

        assert self._consumer(monkeypatch, client).fetch(5, 20.0) == []

        client.receive_message.assert_called_once_with(
            QueueUrl=INPUT_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )

    def test_wait_time_is_an_integer_capped_at_the_sqs_max(self, monkeypatch):
        client = MagicMock()
        client.receive_message.return_value = {}
        consumer = self._consumer(monkeypatch, client)

        consumer.fetch(1, 30.0)
        assert client.receive_message.call_args.kwargs["WaitTimeSeconds"] == 20

        consumer.fetch(1, 0.5)  # boto3 rejects floats; sub-second waits become a short poll
        assert client.receive_message.call_args.kwargs["WaitTimeSeconds"] == 0

    def test_ack_deletes_by_receipt_handle(self, monkeypatch):
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [_record(receipt_handle="rh-42")]}
        consumer = self._consumer(monkeypatch, client)

        [message] = consumer.fetch(1, 0.0)
        consumer.ack(message)

        client.delete_message.assert_called_once_with(QueueUrl=INPUT_URL, ReceiptHandle="rh-42")

    def test_nack_is_a_noop(self, monkeypatch):
        """Redelivery is the queue's visibility timeout; nack must not touch the message."""
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [_record()]}
        consumer = self._consumer(monkeypatch, client)

        [message] = consumer.fetch(1, 0.0)
        consumer.nack(message)

        client.delete_message.assert_not_called()

    def test_declares_an_unsliced_long_poll(self):
        """SQS bills every receive call, so the consumer lifts the ConsumerLoop's 1 s slicing
        to one full-length long poll (spec §3 rule 5)."""
        assert SQSTransportConsumer.fetch_wait_slice_seconds == SQS_MAX_WAIT_SECONDS == 20.0


class TestFactory:
    @staticmethod
    def _cfg(transport_type="sqs", input_url=INPUT_URL, output_url=OUTPUT_URL):
        class _Cfg:
            class execution:
                class queues:
                    type = transport_type

                    class input:
                        url = input_url

                    class output:
                        url = output_url

        return _Cfg

    def test_type_sqs_creates_transport_with_config_urls(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg()))
        transport = QueueTransportFactory.create()
        assert isinstance(transport, SQSTransport)
        assert transport._queue_urls == {QueueName.INPUT: INPUT_URL, QueueName.OUTPUT: OUTPUT_URL}

    def test_queue_urls_alone_do_not_imply_sqs(self, monkeypatch):
        """Only the declared type selects the transport, however the URLs are configured."""
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg(transport_type="in_memory")))
        assert not isinstance(QueueTransportFactory.create(), SQSTransport)

    def test_missing_output_url_raises(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg(output_url=None)))
        with pytest.raises(AKConfigError, match="output.url"):
            QueueTransportFactory.create()

    def test_missing_input_url_raises(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg(input_url=None)))
        with pytest.raises(AKConfigError, match="input.url"):
            QueueTransportFactory.create()


# -- contract suite over a mocked SQS ----------------------------------------------------------


class _FakeSQSQueue:
    """One in-memory FIFO queue with the SQS semantics the transport relies on: per-group
    ordering with one in-flight message per group, visibility-timeout redelivery with
    ApproximateReceiveCount, and publish-time dedup. Single-threaded (contract tests only)."""

    def __init__(self, visibility_timeout: float):
        self._visibility_timeout = visibility_timeout
        self._groups: Dict[str, deque] = {}
        self._in_flight: Dict[str, Tuple[dict, float, str]] = {}  # group -> (message, deadline, receipt handle)
        self._dedup: Dict[str, float] = {}
        self._synthetic_group_counter = itertools.count()

    def send(self, kwargs: Dict[str, Any]) -> dict:
        now = time.monotonic()
        dedup_id = kwargs.get("MessageDeduplicationId")
        if dedup_id:
            if self._dedup.get(dedup_id, 0) > now:
                return {"MessageId": "deduplicated"}
            self._dedup[dedup_id] = now + 300
        message = {
            "id": str(uuid.uuid4()),
            "body": kwargs["MessageBody"],
            "group": kwargs.get("MessageGroupId"),
            "message_attributes": kwargs.get("MessageAttributes") or {},
            "receive_count": 0,
        }
        group_key = message["group"] or f"__msg-{next(self._synthetic_group_counter)}"
        self._groups.setdefault(group_key, deque()).append(message)
        return {"MessageId": message["id"]}

    def receive(self, max_messages: int, wait_seconds: float) -> List[dict]:
        deadline = time.monotonic() + wait_seconds
        while True:
            now = time.monotonic()
            self._requeue_expired(now)
            batch = []
            for group_key, pending in self._groups.items():
                if len(batch) >= max_messages:
                    break
                if group_key in self._in_flight or not pending:
                    continue
                message = pending.popleft()
                message["receive_count"] += 1
                receipt_handle = str(uuid.uuid4())
                self._in_flight[group_key] = (message, now + self._visibility_timeout, receipt_handle)
                batch.append(self._to_record(message, receipt_handle))
            if batch or now >= deadline:
                return batch
            time.sleep(0.01)

    def delete(self, receipt_handle: str) -> None:
        for group_key, (_, _, receipt) in list(self._in_flight.items()):
            if receipt == receipt_handle:
                del self._in_flight[group_key]
                return

    def _requeue_expired(self, now: float) -> None:
        for group_key in [g for g, (_, dl, _) in self._in_flight.items() if dl <= now]:
            message, _, _ = self._in_flight.pop(group_key)
            self._groups[group_key].appendleft(message)

    @staticmethod
    def _to_record(message: dict, receipt_handle: str) -> dict:
        attributes = {"ApproximateReceiveCount": str(message["receive_count"])}
        if message["group"]:
            attributes["MessageGroupId"] = message["group"]
        return {
            "MessageId": message["id"],
            "ReceiptHandle": receipt_handle,
            "Body": message["body"],
            "Attributes": attributes,
            "MessageAttributes": dict(message["message_attributes"]),
        }


class FakeSQSClient:
    """The boto3-SQS client surface the transport uses, over per-URL fake FIFO queues."""

    def __init__(self, visibility_timeout: float):
        self._visibility_timeout = visibility_timeout
        self._queues: Dict[str, _FakeSQSQueue] = {}

    def _queue(self, url: str) -> _FakeSQSQueue:
        if url not in self._queues:
            self._queues[url] = _FakeSQSQueue(self._visibility_timeout)
        return self._queues[url]

    def send_message(self, QueueUrl: str, **kwargs: Any) -> dict:
        return self._queue(QueueUrl).send(kwargs)

    def receive_message(self, QueueUrl: str, MaxNumberOfMessages: int = 1, WaitTimeSeconds: int = 0, **_: Any) -> dict:
        messages = self._queue(QueueUrl).receive(MaxNumberOfMessages, WaitTimeSeconds)
        return {"Messages": messages} if messages else {}

    def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
        self._queue(QueueUrl).delete(ReceiptHandle)


class TestSQSTransportContract(QueueTransportContract):
    """The transport contract against SQS semantics, boto3 mocked by the in-memory FIFO fake.

    Note: WaitTimeSeconds is int-cast by the transport, so the contract's sub-second fetch waits
    become short polls; the fake's visibility timeout plays the ack_wait role."""

    ack_wait = 0.2  # the fake's visibility timeout

    @pytest.fixture(autouse=True)
    def _fake_sqs(self, monkeypatch):
        # One patch covers both sides: the transport's lazy send client and the per-consumer
        # receive clients are all built via the pipeline module's boto3.client.
        fake_client = FakeSQSClient(visibility_timeout=self.ack_wait)
        monkeypatch.setattr("agentkernel.pipeline.transport.sqs.boto3.client", lambda service: fake_client)

    def make_transport(self) -> SQSTransport:
        return SQSTransport(input_url=INPUT_URL, output_url=OUTPUT_URL)
