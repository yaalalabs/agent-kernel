from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.containerized.core.sqs_consumer import ECSSQSConsumer


def _make_msg(message_id, receive_count=1):
    return {
        "MessageId": message_id,
        "ReceiptHandle": f"rh-{message_id}",
        "Body": "{}",
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


class _SyncConsumer(ECSSQSConsumer):
    process_message = MagicMock()
    on_permanent_failure = MagicMock()
    delete_message = MagicMock()

    @classmethod
    def get_queue_url(cls):
        return "https://sqs.test/sync-queue"


class _AsyncConsumer(ECSSQSConsumer):
    on_permanent_failure = MagicMock()
    delete_message = MagicMock()

    @classmethod
    async def process_message(cls, record):
        pass

    @classmethod
    def get_queue_url(cls):
        return "https://sqs.test/async-queue"


@pytest.fixture(autouse=True)
def reset_mocks():
    _SyncConsumer.process_message.reset_mock()
    _SyncConsumer.on_permanent_failure.reset_mock()
    _SyncConsumer.delete_message.reset_mock()
    _AsyncConsumer.on_permanent_failure.reset_mock()
    _AsyncConsumer.delete_message.reset_mock()
    yield


class TestNumConsumers:
    def test_base_class_default(self):
        assert ECSSQSConsumer.num_consumers == 10


class TestProcessSingle:
    def test_processes_and_deletes_message(self):
        msg = _make_msg("m1")
        _SyncConsumer._process_single(msg)
        _SyncConsumer.process_message.assert_called_once_with(msg)
        _SyncConsumer.delete_message.assert_called_once_with(msg)

    def test_message_exceeds_max_receive_count(self):
        msg = _make_msg("m1", receive_count=_SyncConsumer.max_receive_count + 1)
        _SyncConsumer._process_single(msg)
        _SyncConsumer.on_permanent_failure.assert_called_once_with(msg)
        _SyncConsumer.process_message.assert_not_called()
        _SyncConsumer.delete_message.assert_called_once_with(msg)

    def test_process_message_raises_does_not_delete(self):
        _SyncConsumer.process_message.side_effect = RuntimeError("boom")
        msg = _make_msg("m1")
        _SyncConsumer._process_single(msg)
        _SyncConsumer.delete_message.assert_not_called()
        _SyncConsumer.process_message.side_effect = None

    def test_async_process_message_is_run_and_deleted(self):
        msg = _make_msg("async-msg")
        _AsyncConsumer._process_single(msg)
        _AsyncConsumer.delete_message.assert_called_once_with(msg)


class TestConsumerLoop:
    def test_stops_after_poll_raises_once_processed_batch(self):
        msg = _make_msg("m1")
        poll_results = [[msg], RuntimeError("stop")]

        def fake_poll():
            result = poll_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with (
            patch.object(_SyncConsumer, "poll", side_effect=fake_poll),
            patch(
                "agentkernel.deployment.aws.containerized.core.sqs_consumer.time.sleep",
                side_effect=RuntimeError("stop-loop"),
            ),
        ):
            with pytest.raises(RuntimeError, match="stop-loop"):
                _SyncConsumer._consumer_loop()

        _SyncConsumer.process_message.assert_called_once_with(msg)
        _SyncConsumer.delete_message.assert_called_once_with(msg)


class TestECSOutputConsumerRegression:
    """Verify ECSOutputConsumer's process_message uses the sync dispatch path."""

    def test_process_message_is_sync_not_async(self):
        import inspect

        from agentkernel.deployment.aws.containerized.akoutputconsumer import ECSOutputConsumer

        underlying = getattr(ECSOutputConsumer.process_message, "__func__", ECSOutputConsumer.process_message)
        assert not inspect.iscoroutinefunction(underlying), "ECSOutputConsumer.process_message must be sync for this regression check"
