"""The reusable ResponseStoreContract run against every chunk-streaming store.

The redis and valkey runs use a fake client whose ``blpop`` genuinely blocks on a
``threading.Condition``. That matters: the contract's waiting test is the one assertion a
return-immediately fake would pass vacuously, and blocking is the whole mechanism. It still does
not exercise the real BLPOP wire behaviour — ``test_response_store_contract_live.py`` does that
against a real broker.
"""

import threading
import time

import pytest

from agentkernel.core.util.driver import redis as redis_driver_module
from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.pipeline.response_store.in_memory import InMemoryResponseStore
from agentkernel.pipeline.response_store.redis import RedisResponseStore
from agentkernel.pipeline.response_store.testing import ResponseStoreContract
from agentkernel.pipeline.response_store.valkey import ValkeyResponseStore


class FakeRedisLikeClient:
    """In-memory stand-in with the list semantics the chunk path uses, blocking included."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.expires: dict[str, int] = {}
        self._condition = threading.Condition()

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        with self._condition:
            for key in keys:
                self.store.pop(key, None)
                self.lists.pop(key, None)
            self._condition.notify_all()

    def rpush(self, key, value):
        with self._condition:
            self.lists.setdefault(key, []).append(value)
            self._condition.notify_all()

    def blpop(self, keys, timeout=0):
        key = keys[0]
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self.lists.get(key):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return (key, self.lists[key].pop(0))

    def llen(self, key):
        return len(self.lists.get(key, []))

    def expire(self, name, time):  # noqa: A002 — the client's own parameter name
        self.expires[name] = time


class TestInMemoryResponseStoreContract(ResponseStoreContract):
    def make_store(self) -> InMemoryResponseStore:
        store = InMemoryResponseStore()
        InMemoryResponseStore._records.clear()
        InMemoryResponseStore._chunks.clear()
        return store

    def test_in_memory_is_not_shared(self):
        """The one built-in that streams chunks but cannot be read from another process."""
        assert self.make_store().shared is False


class TestRedisResponseStoreContract(ResponseStoreContract):
    @pytest.fixture(autouse=True)
    def _fake_client(self, monkeypatch):
        client = FakeRedisLikeClient()
        monkeypatch.setattr(redis_driver_module.redis, "from_url", lambda *a, **k: client)

    def make_store(self) -> RedisResponseStore:
        return RedisResponseStore(url="redis://localhost:6379", prefix="ak:test:")

    def test_redis_is_shared(self):
        assert self.make_store().shared is True


class TestValkeyResponseStoreContract(ResponseStoreContract):
    @pytest.fixture(autouse=True)
    def _fake_client(self, monkeypatch):
        client = FakeRedisLikeClient()
        monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: client)

    def make_store(self) -> ValkeyResponseStore:
        return ValkeyResponseStore(url="valkey://localhost:6379", prefix="ak:test:")

    def test_valkey_is_shared(self):
        assert self.make_store().shared is True
