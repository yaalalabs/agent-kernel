import asyncio
from threading import current_thread
from unittest.mock import MagicMock, call, patch

import pytest

from agentkernel.deployment.aws.containerized.core.sqs_consumer import ECSSQSConsumer


def _make_msg(message_id, group_id=None, receive_count=1):
    attrs = {"ApproximateReceiveCount": str(receive_count)}
    if group_id:
        attrs["MessageGroupId"] = group_id
    return {
        "MessageId": message_id,
        "ReceiptHandle": f"rh-{message_id}",
        "Body": "{}",
        "Attributes": attrs,
    }


class _SyncConsumer(ECSSQSConsumer):
    process_message = MagicMock()
    on_permanent_failure = MagicMock()

    @classmethod
    def _get_queue_url(cls):
        return "https://sqs.test/sync-queue"


class _AsyncConsumer(ECSSQSConsumer):
    on_permanent_failure = MagicMock()

    @classmethod
    async def process_message(cls, record):
        pass

    @classmethod
    def _get_queue_url(cls):
        return "https://sqs.test/async-queue"


@pytest.fixture(autouse=True)
def reset_mocks():
    _SyncConsumer.process_message.reset_mock()
    _SyncConsumer.on_permanent_failure.reset_mock()
    _AsyncConsumer.on_permanent_failure.reset_mock()
    yield


class TestGetMessageGroupKey:
    def test_returns_message_group_id_when_present(self):
        msg = _make_msg("msg-1", group_id="group-A")
        assert ECSSQSConsumer._get_message_group_key(msg) == "group-A"

    def test_falls_back_to_message_id_when_no_group(self):
        msg = _make_msg("msg-2")
        assert ECSSQSConsumer._get_message_group_key(msg) == "msg-2"

    def test_falls_back_to_unknown_when_no_ids(self):
        assert ECSSQSConsumer._get_message_group_key({}) == "<unknown>"


class TestGetParallelWorkers:
    def test_returns_config_value_when_available(self):
        mock_cfg = MagicMock()
        mock_cfg.execution.queues.parallel_workers = 20
        with patch("agentkernel.core.config.AKConfig.get", return_value=mock_cfg) as mock_get:
            result = ECSSQSConsumer._get_parallel_workers()
        mock_get.assert_called_once()  # verify AKConfig path was actually hit
        assert result == 20  # 20 != default (10), so this can't pass trivially

    def test_returns_default_when_config_unavailable(self):
        with patch(
            "agentkernel.core.config.AKConfig.get",
            side_effect=RuntimeError("config unavailable"),
        ) as mock_get:
            result = ECSSQSConsumer._get_parallel_workers()
        mock_get.assert_called_once()  # verify AKConfig.get was attempted before falling back
        assert result == ECSSQSConsumer._DEFAULT_PARALLEL_WORKERS


class TestProcessBatch:
    def test_empty_batch_returns_without_threads(self):
        client = MagicMock()
        _SyncConsumer._process_batch(client, [])
        _SyncConsumer.process_message.assert_not_called()

    def test_three_messages_three_groups_all_processed(self):
        client = MagicMock()
        msgs = [
            _make_msg("m1", group_id="G1"),
            _make_msg("m2", group_id="G2"),
            _make_msg("m3", group_id="G3"),
        ]
        _SyncConsumer._process_batch(client, msgs)
        assert _SyncConsumer.process_message.call_count == 3
        assert client.delete_message.call_count == 3

    def test_two_messages_same_group_processed_in_order(self):
        call_order = []

        def record_call(msg):
            call_order.append(msg["MessageId"])

        _SyncConsumer.process_message.side_effect = record_call

        client = MagicMock()
        msgs = [
            _make_msg("first", group_id="G1"),
            _make_msg("second", group_id="G1"),
        ]
        _SyncConsumer._process_batch(client, msgs)
        assert call_order == ["first", "second"]
        assert client.delete_message.call_count == 2

    def test_message_exceeds_max_receive_count(self):
        client = MagicMock()
        msg = _make_msg("m1", group_id="G1", receive_count=_SyncConsumer.max_receive_count + 1)
        _SyncConsumer._process_batch(client, [msg])
        _SyncConsumer.on_permanent_failure.assert_called_once_with(msg)
        _SyncConsumer.process_message.assert_not_called()
        client.delete_message.assert_called_once()

    def test_process_message_raises_does_not_delete(self):
        _SyncConsumer.process_message.side_effect = RuntimeError("boom")
        client = MagicMock()
        msg = _make_msg("m1", group_id="G1")
        _SyncConsumer._process_batch(client, [msg])
        client.delete_message.assert_not_called()
        _SyncConsumer.process_message.side_effect = None

    def test_failing_group_does_not_affect_other_groups(self):
        call_order = []

        def side_effect(msg):
            if msg["MessageId"] == "bad":
                raise RuntimeError("intentional failure")
            call_order.append(msg["MessageId"])

        _SyncConsumer.process_message.side_effect = side_effect

        client = MagicMock()
        msgs = [
            _make_msg("bad", group_id="G1"),
            _make_msg("good", group_id="G2"),
        ]
        _SyncConsumer._process_batch(client, msgs)
        assert "good" in call_order
        # bad message was not deleted
        deleted_handles = [c.kwargs["ReceiptHandle"] for c in client.delete_message.call_args_list]
        assert "rh-bad" not in deleted_handles
        assert "rh-good" in deleted_handles
        _SyncConsumer.process_message.side_effect = None


class TestECSOutputConsumerRegression:
    """Verify ECSOutputConsumer's process_message uses the sync dispatch path."""

    def test_process_message_is_sync_not_async(self):
        import inspect

        from agentkernel.deployment.aws.containerized.akoutputconsumer import ECSOutputConsumer

        underlying = getattr(
            ECSOutputConsumer.process_message, "__func__", ECSOutputConsumer.process_message
        )
        assert not inspect.iscoroutinefunction(underlying), (
            "ECSOutputConsumer.process_message must be sync — "
            "changing it to async would require a new event loop per group thread"
        )

    def test_sync_consumer_processes_and_deletes(self):
        # Regression: the sync path (no loop) still calls process_message then delete_message
        client = MagicMock()
        msg = _make_msg("sync-reg", group_id="G1")
        _SyncConsumer._process_batch(client, [msg])
        _SyncConsumer.process_message.assert_called_once_with(msg)
        client.delete_message.assert_called_once()


class TestAsyncAutoDetection:
    def test_async_process_message_uses_event_loop(self):
        loops_created = []
        original_new_event_loop = asyncio.new_event_loop

        def track_loop():
            loop = original_new_event_loop()
            loops_created.append(loop)
            return loop

        client = MagicMock()
        client.delete_message = MagicMock()
        msg = _make_msg("async-msg", group_id="AG1")

        with patch("asyncio.new_event_loop", side_effect=track_loop):
            _AsyncConsumer._process_batch(client, [msg])

        assert len(loops_created) == 1
        client.delete_message.assert_called_once()
