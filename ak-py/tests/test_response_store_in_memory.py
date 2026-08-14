import threading
import time

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.response_store.handler import ResponseDBHandler
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore


class ByoResponseStore(InMemoryResponseStore):
    """Bring-your-own store used by the dotted-path factory tests."""


@pytest.fixture(autouse=True)
def _reset_store():
    InMemoryResponseStore.reset()
    yield
    InMemoryResponseStore.reset()


def _record(request_id="r1", status_code=200, body=None):
    return {"session_id": "s1", "request_id": request_id, "status_code": status_code, "body": body or {"result": "ok"}}


class TestRecords:
    def test_get_message_returns_body(self):
        store = InMemoryResponseStore()
        store.add_message(_record())
        assert store.get_message("r1") == {"result": "ok"}

    def test_get_and_delete_removes_record(self):
        store = InMemoryResponseStore()
        store.add_message(_record())
        assert store.get_message("r1", get_and_delete=True) == {"result": "ok"}
        assert store.get_message("r1") is None

    def test_get_record_exposes_status_code(self):
        store = InMemoryResponseStore()
        store.add_message(_record(status_code=400, body={"error": "bad"}))
        record = store.get_record("r1")
        assert record["status_code"] == 400
        assert record["body"] == {"error": "bad"}

    def test_missing_request_returns_none(self):
        assert InMemoryResponseStore().get_message("nope") is None

    def test_state_is_shared_across_instances(self):
        InMemoryResponseStore().add_message(_record())
        assert InMemoryResponseStore().get_message("r1") == {"result": "ok"}

    def test_delete_message(self):
        store = InMemoryResponseStore()
        store.add_message(_record())
        store.delete_message("r1")
        assert store.get_message("r1") is None

    def test_get_message_with_retry_polls_until_available(self, monkeypatch):
        class _Cfg:
            class execution:
                class response_store:
                    retry_count = 10
                    delay = 0.05

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        store = InMemoryResponseStore()
        threading.Timer(0.1, lambda: store.add_message(_record())).start()
        assert store.get_message_with_retry("r1") == {"result": "ok"}


class TestChunkStream:
    def test_stream_yields_until_done(self):
        store = InMemoryResponseStore()
        store.add_chunk("r1", {"delta": "he"})
        store.add_chunk("r1", {"delta": "llo"})
        store.add_chunk("r1", {"done": True, "session_id": "s1"})
        chunks = list(store.stream("r1", chunk_timeout=1.0))
        assert [chunk.get("delta") for chunk in chunks[:2]] == ["he", "llo"]
        assert chunks[-1]["done"] is True

    def test_stream_timeout_raises(self):
        store = InMemoryResponseStore()
        with pytest.raises(TimeoutError, match="r1"):
            list(store.stream("r1", chunk_timeout=0.05))

    def test_stream_cleans_up_chunk_state(self):
        store = InMemoryResponseStore()
        store.add_chunk("r1", {"done": True})
        list(store.stream("r1", chunk_timeout=1.0))
        assert "r1" not in InMemoryResponseStore._chunks


class TestHandlerSelection:
    def test_handler_selects_in_memory_store(self, monkeypatch):
        class _Cfg:
            class execution:
                class response_store:
                    type = "in_memory"
                    redis = None
                    valkey = None
                    dynamodb = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        assert isinstance(ResponseDBHandler().get_store(), InMemoryResponseStore)

    def test_dotted_path_resolves_byo_store(self, monkeypatch):
        class _Cfg:
            class execution:
                class response_store:
                    type = f"{__name__}.ByoResponseStore"

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        assert isinstance(ResponseDBHandler().get_store(), ByoResponseStore)

    def test_dotted_path_wrong_base_raises(self, monkeypatch):
        class _Cfg:
            class execution:
                class response_store:
                    type = "agentkernel.pipeline.envelope.QueueMessage"

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        with pytest.raises(AKConfigError, match="not a ResponseStore subclass"):
            ResponseDBHandler()

    def test_unknown_short_name_fails_loudly(self, monkeypatch):
        """Unknown short names fail at store-build time (the config field also accepts dotted
        paths, so it no longer pattern-validates)."""

        class _Cfg:
            class execution:
                class response_store:
                    type = "bogus"
                    redis = None
                    valkey = None
                    dynamodb = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        with pytest.raises(ValueError, match="No valid response store"):
            ResponseDBHandler()


class TestCloseStream:
    def test_close_stream_unblocks_a_pending_consumer_and_drops_state(self):
        store = InMemoryResponseStore()
        received = []

        def consume():
            received.extend(store.stream("r1", chunk_timeout=5.0))

        consumer = threading.Thread(target=consume)
        consumer.start()
        time.sleep(0.1)  # let the consumer block on the empty chunk queue

        store.close_stream("r1")
        consumer.join(timeout=2)

        assert not consumer.is_alive(), "close_stream must unblock the pending stream()"
        assert received == []
        assert "r1" not in InMemoryResponseStore._chunks

    def test_close_stream_without_pending_stream_is_a_noop(self):
        InMemoryResponseStore().close_stream("never-streamed")


class TestRetryConfigFallback:
    def test_retry_config_defaults_when_no_response_store_block(self, monkeypatch):
        class _Cfg:
            class execution:
                response_store = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        from agentkernel.pipeline.response_store.base import ResponseStore

        assert ResponseStore._get_retry_config() == (5, 5.0)
