import time
from typing import List
from unittest.mock import MagicMock

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.consumer import ConsumerLoop
from agentkernel.pipeline.envelope import QueueMessage, QueueName
from agentkernel.pipeline.thread_runner import ThreadRunner
from agentkernel.pipeline.transport.base import QueueTransport, QueueTransportFactory, TransportConsumer


@pytest.fixture(autouse=True)
def _clear_shutdown_event():
    """shutdown_event is a process-wide singleton — reset between tests (see test_thread_runner.py)."""
    ThreadRunner.shutdown_event.clear()
    yield
    ThreadRunner.shutdown_event.clear()


def _msg(message_id="m1", receive_count=1):
    return QueueMessage(body="{}", message_id=message_id, receive_count=receive_count)


class FakeConsumer(TransportConsumer):
    """Scripted consumer: yields the given batches, then empty batches; records acks/nacks/closes."""

    def __init__(self, batches: List[List[QueueMessage]] = None):
        self.batches = list(batches or [])
        self.acked: List[QueueMessage] = []
        self.nacked: List[QueueMessage] = []
        self.closed = False

    def fetch(self, batch_size, wait_seconds):
        return self.batches.pop(0) if self.batches else []

    def ack(self, message):
        self.acked.append(message)

    def nack(self, message):
        self.nacked.append(message)

    def close(self):
        self.closed = True


def _loop(consumer, process, on_permanent_failure=None, max_receive_count=3, num_consumers=1):
    return ConsumerLoop(
        process=process,
        on_permanent_failure=on_permanent_failure or MagicMock(),
        max_receive_count=max_receive_count,
        num_consumers=num_consumers,
        batch_size=1,
        consumer_factory=lambda: consumer,
        thread_name_prefix="test-consumer",
    )


class TestProcessSingle:
    def test_processes_and_acks(self):
        consumer = FakeConsumer()
        process = MagicMock()
        msg = _msg()
        _loop(consumer, process)._process_single(consumer, msg)
        process.assert_called_once_with(msg)
        assert consumer.acked == [msg]
        assert consumer.nacked == []

    def test_exceeds_max_receive_count_runs_hook_then_acks(self):
        consumer = FakeConsumer()
        process, hook = MagicMock(), MagicMock()
        msg = _msg(receive_count=4)
        _loop(consumer, process, on_permanent_failure=hook)._process_single(consumer, msg)
        hook.assert_called_once_with(msg)
        process.assert_not_called()
        assert consumer.acked == [msg]

    def test_process_raises_nacks_and_does_not_ack(self):
        consumer = FakeConsumer()
        process = MagicMock(side_effect=RuntimeError("boom"))
        msg = _msg()
        _loop(consumer, process)._process_single(consumer, msg)
        assert consumer.acked == []
        assert consumer.nacked == [msg]

    def test_permanent_failure_hook_raises_leaves_message_unacked(self):
        consumer = FakeConsumer()
        hook = MagicMock(side_effect=RuntimeError("hook-boom"))
        msg = _msg(receive_count=4)
        _loop(consumer, MagicMock(), on_permanent_failure=hook)._process_single(consumer, msg)
        assert consumer.acked == []

    def test_async_process_is_run_and_acked(self):
        consumer = FakeConsumer()
        seen = []

        async def process(message):
            seen.append(message)

        msg = _msg()
        _loop(consumer, process)._process_single(consumer, msg)
        assert seen == [msg]
        assert consumer.acked == [msg]

    def test_nack_failure_does_not_propagate(self):
        consumer = FakeConsumer()
        consumer.nack = MagicMock(side_effect=RuntimeError("nack-boom"))
        _loop(consumer, MagicMock(side_effect=RuntimeError("boom")))._process_single(consumer, _msg())
        assert consumer.acked == []


class TestConsumerLoopBody:
    def test_fetch_raises_sleeps_and_retries(self, monkeypatch):
        consumer = FakeConsumer(batches=[[_msg()]])
        first_fetch = consumer.fetch
        fetches = [first_fetch, RuntimeError("fetch-boom")]

        def scripted_fetch(batch_size, wait_seconds):
            step = fetches.pop(0)
            if isinstance(step, Exception):
                raise step
            return step(batch_size, wait_seconds)

        consumer.fetch = scripted_fetch
        process = MagicMock()
        monkeypatch.setattr("agentkernel.pipeline.consumer.time.sleep", MagicMock(side_effect=RuntimeError("stop-loop")))

        with pytest.raises(RuntimeError, match="stop-loop"):
            _loop(consumer, process)._consumer_loop()

        process.assert_called_once()
        assert len(consumer.acked) == 1
        assert consumer.closed  # finally-close even on loop exit via exception

    def test_shutdown_event_stops_loop_and_closes_consumer(self):
        consumer = FakeConsumer()
        ThreadRunner.shutdown_event.set()
        _loop(consumer, MagicMock())._consumer_loop()
        assert consumer.closed
        assert consumer.acked == []


class TestRun:
    def test_run_validates_num_consumers(self):
        with pytest.raises(ValueError, match="num_consumers"):
            _loop(FakeConsumer(), MagicMock(), num_consumers=0).run()

    def test_run_builds_one_graceful_task_per_consumer(self, monkeypatch):
        captured = {}

        def fake_run(tasks, max_workers=None):
            captured["tasks"], captured["max_workers"] = tasks, max_workers
            return {}

        monkeypatch.setattr(ThreadRunner, "run", staticmethod(fake_run))
        _loop(FakeConsumer(), MagicMock(), num_consumers=3).run()

        assert captured["max_workers"] == 3
        assert [t.thread_name for t in captured["tasks"]] == ["test-consumer-0", "test-consumer-1", "test-consumer-2"]
        assert all(t.stop_all_on_failure and t.graceful for t in captured["tasks"])


class TestEnvelope:
    def test_native_is_excluded_from_serialization(self):
        msg = QueueMessage(body="x", native=object(), attributes={"request_id": "r1"})
        dumped = msg.model_dump()
        assert "native" not in dumped
        assert dumped["attributes"] == {"request_id": "r1"}


class TestTransportFactory:
    class _FakeCfgNoTypeNoUrl:
        class execution:
            class queues:
                class input:
                    url = None

    class _FakeCfgNoTypeWithUrl:
        class execution:
            class queues:
                class input:
                    url = "https://sqs.test/input"

    def test_resolve_type_defaults_to_in_memory(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._FakeCfgNoTypeNoUrl))
        assert QueueTransportFactory.resolve_type() == "in_memory"

    def test_resolve_type_url_implies_sqs(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._FakeCfgNoTypeWithUrl))
        assert QueueTransportFactory.resolve_type() == "sqs"

    def test_default_type_creates_in_memory_transport(self, monkeypatch):
        from agentkernel.pipeline.transport.in_memory import InMemoryTransport

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._FakeCfgNoTypeNoUrl))
        assert isinstance(QueueTransportFactory.create(), InMemoryTransport)

    def test_builtin_not_yet_available_raises(self, monkeypatch):
        class _Cfg:
            class execution:
                class queues:
                    type = "kafka"

                    class input:
                        url = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        with pytest.raises(AKConfigError, match="not available yet"):
            QueueTransportFactory.create()

    def test_dotted_path_resolves_byo_transport(self, monkeypatch):
        class _Cfg:
            class execution:
                class queues:
                    type = f"{__name__}.ByoTransport"

                    class input:
                        url = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        transport = QueueTransportFactory.create()
        assert isinstance(transport, ByoTransport)
        assert isinstance(QueueTransportFactory.create_consumer(QueueName.INPUT), FakeConsumer)

    def test_dotted_path_wrong_base_raises(self, monkeypatch):
        class _Cfg:
            class execution:
                class queues:
                    type = "agentkernel.pipeline.envelope.QueueMessage"

                    class input:
                        url = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        with pytest.raises(AKConfigError, match="not a QueueTransport subclass"):
            QueueTransportFactory.create()


class ByoTransport(QueueTransport):
    """Bring-your-own transport used by the dotted-path factory test."""

    def send(self, queue, message):
        return None

    def create_consumer(self, queue):
        return FakeConsumer()
