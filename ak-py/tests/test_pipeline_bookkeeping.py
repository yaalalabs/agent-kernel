"""Delivery bookkeeping for transports that lack native receive counts and dedup (spec #495 §6):
attempt counters, retry-safe dedup claims, and the session-config-driven backend choice."""

import logging

import pytest

from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.pipeline.transport.bookkeeping import (
    ATTEMPTS_KEY_PREFIX,
    DEDUP_KEY_PREFIX,
    BookkeepingStoreFactory,
    InMemoryBookkeepingStore,
    RedisLikeBookkeepingStore,
    reset_fallback_warning,
)


@pytest.fixture(autouse=True)
def _reset_warning_latch():
    reset_fallback_warning()
    yield
    reset_fallback_warning()


class FakeValkeyClient:
    """Minimal stand-in for a valkey string client (mirrors test_response_store_valkey)."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def ping(self):
        return True

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def expire(self, name, time):
        self.expirations[name] = time
        return True


class _StoreContract:
    """Assertions every BookkeepingStore implementation must satisfy."""

    def make_store(self) -> "InMemoryBookkeepingStore":
        raise NotImplementedError

    def test_attempts_count_each_delivery(self):
        store = self.make_store()
        assert store.incr_attempts("t:0:5") == 1
        assert store.incr_attempts("t:0:5") == 2
        assert store.incr_attempts("t:0:6") == 1, "counters are per record"

    def test_clear_attempts_resets_the_counter(self):
        store = self.make_store()
        store.incr_attempts("t:0:5")
        store.clear_attempts("t:0:5")
        assert store.incr_attempts("t:0:5") == 1

    def test_first_claim_wins_and_a_second_record_is_a_duplicate(self):
        store = self.make_store()
        assert store.claim_dedup("d1", owner="t:0:5") is True
        assert store.claim_dedup("d1", owner="t:0:9") is False

    def test_the_claim_owner_may_reclaim_so_retries_survive(self):
        """The bug this guards: marking a dedup id as seen on first delivery would make the
        record's own retry look like a duplicate and silently drop it."""
        store = self.make_store()
        assert store.claim_dedup("d1", owner="t:0:5") is True
        assert store.claim_dedup("d1", owner="t:0:5") is True

    def test_distinct_dedup_ids_are_independent(self):
        store = self.make_store()
        assert store.claim_dedup("d1", owner="t:0:5") is True
        assert store.claim_dedup("d2", owner="t:0:6") is True


class TestInMemoryBookkeepingStore(_StoreContract):
    def make_store(self) -> InMemoryBookkeepingStore:
        return InMemoryBookkeepingStore()

    def test_expired_claims_are_pruned(self):
        store = InMemoryBookkeepingStore(dedup_ttl=0)
        assert store.claim_dedup("d1", owner="t:0:5") is True
        assert store.claim_dedup("d1", owner="t:0:9") is True, "the window elapsed, so this is not a duplicate"


class TestRedisLikeBookkeepingStore(_StoreContract):
    @pytest.fixture(autouse=True)
    def _fake_valkey(self, monkeypatch):
        self.client = FakeValkeyClient()
        monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: self.client)

    def make_store(self) -> RedisLikeBookkeepingStore:
        from agentkernel.core.util.driver.valkey import ValkeyDriver

        return RedisLikeBookkeepingStore(
            attempts_driver=ValkeyDriver(url="valkey://localhost:6379", prefix=ATTEMPTS_KEY_PREFIX, ttl=3600, decode_responses=True),
            dedup_driver=ValkeyDriver(url="valkey://localhost:6379", prefix=DEDUP_KEY_PREFIX, ttl=300, decode_responses=True),
        )

    def test_keys_are_prefixed_per_concern(self):
        store = self.make_store()
        store.incr_attempts("t:0:5")
        store.claim_dedup("d1", owner="t:0:5")
        assert f"{ATTEMPTS_KEY_PREFIX}t:0:5" in self.client.store
        assert f"{DEDUP_KEY_PREFIX}d1" in self.client.store

    def test_counter_ttl_is_applied_once_on_creation(self):
        """A TTL refreshed on every increment would let a hot counter live forever."""
        store = self.make_store()
        store.incr_attempts("t:0:5")
        assert self.client.expirations == {f"{ATTEMPTS_KEY_PREFIX}t:0:5": 3600}

        self.client.expirations.clear()
        store.incr_attempts("t:0:5")
        assert self.client.expirations == {}


class TestFactorySelection:
    @staticmethod
    def _cfg(session_type, block=True):
        class _Block:
            url = "valkey://localhost:6379"

        class _Cfg:
            class session:
                type = session_type

        _Cfg.session.redis = _Block if (block and session_type == "redis") else None
        _Cfg.session.valkey = _Block if (block and session_type == "valkey") else None
        return _Cfg

    def test_valkey_session_gives_durable_bookkeeping(self, monkeypatch):
        monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: FakeValkeyClient())
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg("valkey")))
        assert isinstance(BookkeepingStoreFactory.create(), RedisLikeBookkeepingStore)

    def test_redis_session_gives_durable_bookkeeping(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg("redis")))
        assert isinstance(BookkeepingStoreFactory.create(), RedisLikeBookkeepingStore)

    def test_in_memory_session_falls_back_with_one_warning(self, monkeypatch, caplog):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg("in_memory")))

        with caplog.at_level(logging.WARNING, logger="ak.pipeline.transport.bookkeeping"):
            assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)
            assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)

        warnings = [record for record in caplog.records if "process-local" in record.message]
        assert len(warnings) == 1, "the fallback warning is emitted once per process, not per consumer"

    def test_backend_without_a_config_block_falls_back(self, monkeypatch):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: self._cfg("valkey", block=False)))
        assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)
