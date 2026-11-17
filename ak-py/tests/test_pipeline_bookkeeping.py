"""Delivery bookkeeping for transports that lack native receive counts and dedup (spec #495 §6):
attempt counters, retry-safe dedup claims, acknowledged-record memory (#886), and the backend
choice driven by the session and response-store configuration."""

import logging

import pytest

from agentkernel.core.util.driver import valkey as valkey_driver_module
from agentkernel.pipeline.transport.bookkeeping import (
    ACKED_KEY_PREFIX,
    ATTEMPTS_KEY_PREFIX,
    DEDUP_KEY_PREFIX,
    DEFAULT_DEDUP_TTL_SECONDS,
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

    def test_an_acked_record_is_remembered(self):
        """Pub/Sub redelivers acked messages in an ordering-key cascade; this is what lets the
        transport recognise one and acknowledge it again without running it."""
        store = self.make_store()
        assert store.was_acked("sub:m1") is False
        store.mark_acked("sub:m1")
        assert store.was_acked("sub:m1") is True
        assert store.was_acked("sub:m2") is False, "acks are per record"

    def test_acked_memory_is_separate_from_dedup_claims(self):
        store = self.make_store()
        store.mark_acked("d1")
        assert store.claim_dedup("d1", owner="t:0:5") is True, "an acked key must not read as a claimed dedup id"


class TestInMemoryBookkeepingStore(_StoreContract):
    def make_store(self) -> InMemoryBookkeepingStore:
        return InMemoryBookkeepingStore()

    def test_acked_memory_expires_with_the_dedup_window(self):
        store = InMemoryBookkeepingStore(dedup_ttl=0)
        store.mark_acked("sub:m1")
        assert store.was_acked("sub:m1") is False

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

    def test_claim_expiring_between_set_and_get_is_not_read_as_a_duplicate(self):
        """Racing the tail of the dedup window: SET NX fails because the key exists, then the key
        expires before the GET. Reading that None as "another owner holds it" would drop a
        legitimate record, so the claim is retried instead."""
        store = self.make_store()
        real_get = self.client.get

        def get_after_expiry(key):
            self.client.store.pop(key, None)  # the window elapses between the SET and the GET
            return real_get(key)

        self.client.get = get_after_expiry
        self.client.store[f"{DEDUP_KEY_PREFIX}d1"] = "some-other-record"

        assert store.claim_dedup("d1", owner="t:0:5") is True
        assert self.client.store[f"{DEDUP_KEY_PREFIX}d1"] == "t:0:5", "the retry re-claims the id"

    def test_counter_ttl_is_applied_once_on_creation(self):
        """A TTL refreshed on every increment would let a hot counter live forever."""
        store = self.make_store()
        store.incr_attempts("t:0:5")
        assert self.client.expirations == {f"{ATTEMPTS_KEY_PREFIX}t:0:5": 3600}

        self.client.expirations.clear()
        store.incr_attempts("t:0:5")
        assert self.client.expirations == {}

    def test_acked_memory_without_its_own_driver_shares_the_dedup_driver(self):
        """The two-driver construction predates acked memory and must keep working."""
        store = self.make_store()
        store.mark_acked("sub:m1")
        assert f"{DEDUP_KEY_PREFIX}acked:sub:m1" in self.client.store

    def test_acked_memory_uses_its_own_prefix_when_given_a_driver(self):
        from agentkernel.core.util.driver.valkey import ValkeyDriver

        store = RedisLikeBookkeepingStore(
            attempts_driver=ValkeyDriver(url="valkey://localhost:6379", prefix=ATTEMPTS_KEY_PREFIX, ttl=3600, decode_responses=True),
            dedup_driver=ValkeyDriver(url="valkey://localhost:6379", prefix=DEDUP_KEY_PREFIX, ttl=300, decode_responses=True),
            acked_driver=ValkeyDriver(url="valkey://localhost:6379", prefix=ACKED_KEY_PREFIX, ttl=300, decode_responses=True),
        )
        store.mark_acked("sub:m1")
        assert f"{ACKED_KEY_PREFIX}sub:m1" in self.client.store
        assert store.was_acked("sub:m1") is True


class TestFactorySelection:
    SESSION_URL = "valkey://sessions:6379"
    RESPONSE_STORE_URL = "valkey://responses:6379"

    @classmethod
    def _cfg(cls, session_type, block=True, response_store_type=None, response_store_block=True):
        """A config stub carrying a session block and an execution.response_store block.

        Each block's connection URL is distinct, so a test can tell which one the factory used.
        """

        def _block(backend_type, has_block, url):
            class _Connection:
                pass

            _Connection.url = url

            class _Block:
                type = backend_type

            _Block.redis = _Connection if (has_block and backend_type == "redis") else None
            _Block.valkey = _Connection if (has_block and backend_type == "valkey") else None
            return _Block

        class _Cfg:
            session = _block(session_type, block, cls.SESSION_URL)

            class execution:
                response_store = None

        if response_store_type is not None:
            _Cfg.execution.response_store = _block(response_store_type, response_store_block, cls.RESPONSE_STORE_URL)
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

    def test_config_without_an_execution_block_still_resolves(self, monkeypatch):
        """Older stubs and BYO configs may carry only a session block."""

        class _Cfg:
            class session:
                type = "in_memory"
                redis = None
                valkey = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)


class TestFactoryResponseStoreStep:
    """#886: a Redis/Valkey response store gives durable bookkeeping when sessions live elsewhere."""

    _cfg = TestFactorySelection._cfg

    @pytest.fixture(autouse=True)
    def _fake_valkey(self, monkeypatch):
        monkeypatch.setattr(valkey_driver_module.valkey, "from_url", lambda *a, **k: FakeValkeyClient())

    def _use(self, monkeypatch, cfg):
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: cfg))

    @pytest.mark.parametrize("backend", ["redis", "valkey"])
    def test_response_store_gives_durable_bookkeeping_with_firestore_sessions(self, monkeypatch, backend):
        self._use(monkeypatch, self._cfg("firestore", response_store_type=backend))

        store = BookkeepingStoreFactory.create()

        assert isinstance(store, RedisLikeBookkeepingStore)
        assert store._attempts._url == TestFactorySelection.RESPONSE_STORE_URL

    def test_bookkeeping_keys_never_use_the_response_store_prefix(self, monkeypatch):
        self._use(monkeypatch, self._cfg("firestore", response_store_type="valkey"))

        store = BookkeepingStoreFactory.create()

        assert (store._attempts.key(""), store._dedup.key(""), store._acked.key("")) == (ATTEMPTS_KEY_PREFIX, DEDUP_KEY_PREFIX, ACKED_KEY_PREFIX)
        assert store._acked.ttl == DEFAULT_DEDUP_TTL_SECONDS

    def test_session_store_wins_when_both_are_shared(self, monkeypatch):
        """Session first keeps existing Kafka deployments on the store they already use."""
        self._use(monkeypatch, self._cfg("valkey", response_store_type="valkey"))

        store = BookkeepingStoreFactory.create()

        assert store._attempts._url == TestFactorySelection.SESSION_URL

    def test_response_store_type_without_its_block_falls_back(self, monkeypatch):
        self._use(monkeypatch, self._cfg("firestore", response_store_type="valkey", response_store_block=False))
        assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)

    @pytest.mark.parametrize("response_store_type", ["dynamodb", None])
    def test_a_non_shared_response_store_falls_back(self, monkeypatch, response_store_type):
        self._use(monkeypatch, self._cfg("firestore", response_store_type=response_store_type))
        assert isinstance(BookkeepingStoreFactory.create(), InMemoryBookkeepingStore)

    def test_fallback_warning_names_both_options(self, monkeypatch, caplog):
        self._use(monkeypatch, self._cfg("firestore", response_store_type="dynamodb"))

        with caplog.at_level(logging.WARNING, logger="ak.pipeline.transport.bookkeeping"):
            BookkeepingStoreFactory.create()

        [warning] = [record.message for record in caplog.records if "process-local" in record.message]
        assert "session.type 'firestore'" in warning
        assert "execution.response_store.type 'dynamodb'" in warning
