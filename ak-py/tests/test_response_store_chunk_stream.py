"""
The chunk-streaming half of the response-store contract (spec #524 §10.2).

Run against every store that claims the capability, because the whole point of the capability flag
is that a topology change must not change stream semantics: a run served on ``in_memory`` and the
same run served on ``redis`` have to behave identically. The stores that decline are asserted to
decline, so a future backend cannot half-implement the trio and pass.
"""

import json
import threading
import time

import pytest

from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.pipeline.response_store.dynamodb import DynamoDBResponseStore
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.response_store.redis import RedisResponseStore
from agentkernel.pipeline.response_store.valkey import ValkeyResponseStore


class FakeListClient:
    """A redis-py-shaped client with just the list and key commands the mixin uses.

    ``blpop`` blocks on a condition rather than polling, so the tests exercise the real
    "released the moment a chunk arrives" behaviour instead of a sleep loop.
    """

    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.expires: dict[str, int] = {}
        self.blpop_timeouts: list[int] = []
        self._condition = threading.Condition()

    def ping(self):
        return True

    def rpush(self, key, value):
        with self._condition:
            self.lists.setdefault(key, []).append(value)
            self._condition.notify_all()

    def blpop(self, keys, timeout=0):
        key = keys[0]
        self.blpop_timeouts.append(timeout)
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self.lists.get(key):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return (key, self.lists[key].pop(0))

    def delete(self, *keys):
        with self._condition:
            for key in keys:
                self.lists.pop(key, None)
                self.expires.pop(key, None)

    def expire(self, name, time):  # noqa: A002 - matches redis-py's parameter name
        self.expires[name] = time

    def set(self, key, value, ex=None, nx=False):
        return True

    def get(self, key):
        return None


@pytest.fixture(autouse=True)
def _reset_in_memory():
    InMemoryResponseStore.reset()
    yield
    InMemoryResponseStore.reset()


def _in_memory_store():
    return InMemoryResponseStore(), None


def _redis_store(monkeypatch):
    client = FakeListClient()
    monkeypatch.setattr(redis_driver_module.redis, "from_url", lambda *a, **k: client)
    return RedisResponseStore(url="redis://localhost:6379", prefix="ak:responses:", ttl=120), client


def _valkey_store(monkeypatch):
    client = FakeListClient()
    monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: client)
    return ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:responses:", ttl=120), client


#: Every store that must satisfy the contract, by name.
BUILDERS = {"in_memory": _in_memory_store, "redis": _redis_store, "valkey": _valkey_store}


@pytest.fixture(params=sorted(BUILDERS))
def store(request, monkeypatch):
    """A chunk-streaming store of each supported kind."""
    builder = BUILDERS[request.param]
    built, _ = builder() if builder is _in_memory_store else builder(monkeypatch)
    return built


def _drain(store, request_id, timeout=2.0):
    """Collect a stream to completion on a worker thread, so a hung read fails the test."""
    collected: list = []
    error: list = []

    def run():
        try:
            for chunk in store.stream(request_id, chunk_timeout=timeout):
                collected.append(chunk)
        except BaseException as e:  # noqa: BLE001 - re-raised on the main thread below
            error.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, collected, error


class TestCapability:
    def test_every_streaming_store_declares_the_capability(self, store):
        assert store.supports_chunk_streaming() is True

    def test_dynamodb_declines(self):
        store = DynamoDBResponseStore.__new__(DynamoDBResponseStore)
        assert store.supports_chunk_streaming() is False

    def test_dynamodb_add_chunk_raises_rather_than_silently_dropping(self):
        store = DynamoDBResponseStore.__new__(DynamoDBResponseStore)
        with pytest.raises(NotImplementedError, match="chunk streaming"):
            store.add_chunk("r1", {"delta": "hi"})


class TestOrderAndTermination:
    def test_chunks_arrive_in_order_and_stop_at_done(self, store):
        store.add_chunk("r1", {"delta": "he"})
        store.add_chunk("r1", {"delta": "llo"})
        store.add_chunk("r1", {"done": True})
        store.add_chunk("r1", {"delta": "never read"})

        chunks = list(store.stream("r1", chunk_timeout=2.0))

        assert chunks == [{"delta": "he"}, {"delta": "llo"}, {"done": True}]

    def test_a_reader_is_released_as_each_chunk_is_written(self, store):
        thread, collected, error = _drain(store, "r1")
        store.add_chunk("r1", {"delta": "a"})
        store.add_chunk("r1", {"delta": "b", "done": True})
        thread.join(timeout=3)

        assert not thread.is_alive(), "stream did not return after its done chunk"
        assert not error, error
        assert collected == [{"delta": "a"}, {"delta": "b", "done": True}]

    def test_typed_events_survive_the_round_trip(self, store):
        # The AG-UI path depends on this: StreamChunk.event is a discriminated union, and the
        # store must not flatten it on the way through.
        event = {"type": "text_delta", "message_id": "m1", "content": "hi"}
        store.add_chunk("r1", {"delta": "hi", "event": event})
        store.add_chunk("r1", {"done": True})

        chunks = list(store.stream("r1", chunk_timeout=2.0))

        assert chunks[0]["event"] == event


class TestCloseAndTimeout:
    def test_close_stream_releases_a_parked_reader(self, store):
        thread, collected, error = _drain(store, "r1")
        time.sleep(0.05)  # let the reader park
        store.close_stream("r1")
        thread.join(timeout=3)

        assert not thread.is_alive(), "close_stream did not release the reader"
        assert not error, error
        assert collected == []

    def test_close_stream_ends_a_stream_mid_run(self, store):
        thread, collected, error = _drain(store, "r1")
        store.add_chunk("r1", {"delta": "a"})
        time.sleep(0.05)
        store.close_stream("r1")
        thread.join(timeout=3)

        assert not thread.is_alive()
        assert collected == [{"delta": "a"}]

    def test_a_silent_stream_times_out(self, store):
        with pytest.raises(TimeoutError, match="r1"):
            list(store.stream("r1", chunk_timeout=1.0))

    def test_the_timeout_message_names_the_request_and_the_budget(self, store):
        with pytest.raises(TimeoutError) as excinfo:
            list(store.stream("rX", chunk_timeout=1.0))
        # RequestHandler._sse_stream surfaces this text to the client, so it must stay
        # request-scoped and free of internals.
        assert "rX" in str(excinfo.value)
        assert "1" in str(excinfo.value)


class TestKeyLifecycle:
    """Redis-only: the in-memory store has no keyspace to assert against."""

    def test_the_chunk_key_is_dropped_when_the_stream_ends(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"done": True})
        list(store.stream("r1", chunk_timeout=1.0))

        assert "ak:responses:r1:chunks" not in client.lists

    def test_the_chunk_key_is_dropped_on_a_timeout_too(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})  # no done chunk follows
        with pytest.raises(TimeoutError):
            list(store.stream("r1", chunk_timeout=1.0))

        assert "ak:responses:r1:chunks" not in client.lists

    def test_add_chunk_applies_the_configured_ttl(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})

        assert client.expires["ak:responses:r1:chunks"] == 120

    def test_delete_message_also_drops_the_chunk_key(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})
        store.delete_message("r1")

        assert "ak:responses:r1:chunks" not in client.lists

    def test_the_chunk_key_is_namespaced_beside_the_record_key(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})

        # Sits under the store's prefix, and cannot collide with the record key "ak:responses:r1".
        assert list(client.lists) == ["ak:responses:r1:chunks"]

    def test_chunks_are_stored_as_json(self, monkeypatch):
        store, client = _redis_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})

        assert json.loads(client.lists["ak:responses:r1:chunks"][0]) == {"delta": "a"}

    def test_valkey_behaves_identically(self, monkeypatch):
        store, client = _valkey_store(monkeypatch)
        store.add_chunk("r1", {"delta": "a"})

        assert client.expires["ak:responses:r1:chunks"] == 120

        store.delete_message("r1")

        # Deleting the key takes its TTL with it, exactly as Redis does.
        assert "ak:responses:r1:chunks" not in client.lists
        assert "ak:responses:r1:chunks" not in client.expires
