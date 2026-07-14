from unittest.mock import MagicMock

import pytest

from agentkernel.core.config import AKConfig, _ThreadRedisConfig, _ThreadStoreConfig
from agentkernel.core.thread.model import Thread, ThreadMessage
from agentkernel.core.thread.store.redis import RedisThreadStore

PREFIX = "ak:thread:"


@pytest.fixture
def make_store():
    """Build a RedisThreadStore with a mocked Redis client and the given TTL."""
    original = AKConfig.get().thread

    def _make(ttl: int) -> RedisThreadStore:
        AKConfig.get().thread = _ThreadStoreConfig(type="redis", redis=_ThreadRedisConfig(ttl=ttl, prefix=PREFIX))
        store = RedisThreadStore()
        store._redis_client = MagicMock()
        return store

    yield _make
    AKConfig.get().thread = original
    RedisThreadStore._redis_client = None


def _expired_keys(store: RedisThreadStore) -> set:
    return {call.args[0] for call in store.client.expire.call_args_list}


class TestRedisThreadStoreTTL:
    """TTL handling for per-thread keys and the shared user/group index sets."""

    def test_create_expires_meta_and_index_keys(self, make_store):
        store = make_store(ttl=60)
        store.create(Thread(session_id="s1", user_id="u1", group_id="g1"))

        assert _expired_keys(store) == {
            f"{PREFIX}s1:meta",
            f"{PREFIX}index:user:u1",
            f"{PREFIX}index:group:g1",
        }

    def test_create_without_group_skips_group_index(self, make_store):
        store = make_store(ttl=60)
        store.create(Thread(session_id="s1", user_id="u1"))

        assert f"{PREFIX}index:user:u1" in _expired_keys(store)
        assert not any("index:group" in key for key in _expired_keys(store))

    def test_create_with_ttl_disabled_never_expires(self, make_store):
        store = make_store(ttl=0)
        store.create(Thread(session_id="s1", user_id="u1", group_id="g1"))
        store.client.expire.assert_not_called()

    def test_append_refreshes_thread_and_index_keys(self, make_store):
        store = make_store(ttl=60)
        thread = Thread(session_id="s1", user_id="u1", group_id="g1")
        store.client.get.return_value = thread.model_dump_json().encode()

        store.append_message("s1", ThreadMessage(role="user", content="hi"))

        assert _expired_keys(store) == {
            f"{PREFIX}s1:messages",
            f"{PREFIX}s1:updated_at",
            f"{PREFIX}s1:meta",
            f"{PREFIX}index:user:u1",
            f"{PREFIX}index:group:g1",
        }

    def test_append_with_ttl_disabled_never_expires(self, make_store):
        store = make_store(ttl=0)
        thread = Thread(session_id="s1", user_id="u1")
        store.client.get.return_value = thread.model_dump_json().encode()

        store.append_message("s1", ThreadMessage(role="user", content="hi"))
        store.client.expire.assert_not_called()

    def test_append_missing_thread_raises(self, make_store):
        store = make_store(ttl=60)
        store.client.get.return_value = None
        with pytest.raises(KeyError):
            store.append_message("missing", ThreadMessage(role="user", content="hi"))
        store.client.rpush.assert_not_called()


class TestRedisThreadStoreUpdateName:
    """update_name must rewrite only the meta key, leaving updated_at alone."""

    def _wire_storage(self, store, payloads: dict):
        """Make the mocked client behave like real key/value storage for GET/SET."""
        store.client.get.side_effect = lambda key: payloads.get(key)
        store.client.set.side_effect = lambda key, value, **kwargs: payloads.__setitem__(key, value.encode()) or True

    def test_update_name_rewrites_meta_and_refreshes_ttl(self, make_store):
        store = make_store(ttl=60)
        existing = Thread(session_id="s1", user_id="u1", name="old")
        payloads = {f"{PREFIX}s1:meta": existing.model_dump_json().encode()}
        self._wire_storage(store, payloads)

        result = store.update_name("s1", "new name")

        assert result.name == "new name"
        assert result.name_locked is True
        stored = Thread.model_validate_json(payloads[f"{PREFIX}s1:meta"])
        assert stored.name == "new name"
        assert stored.name_locked is True
        assert _expired_keys(store) == {f"{PREFIX}s1:meta"}
        # updated_at lives in its own key and must not be written by a rename
        assert f"{PREFIX}s1:updated_at" not in payloads

    def test_update_name_missing_thread_raises(self, make_store):
        store = make_store(ttl=60)
        self._wire_storage(store, {})
        with pytest.raises(KeyError):
            store.update_name("missing", "new name")
        store.client.set.assert_not_called()


class TestRedisThreadStoreConditionalCreate:
    """create() must be conditional (SET NX) so a lost race never overwrites metadata."""

    def test_create_sets_meta_with_nx(self, make_store):
        store = make_store(ttl=0)
        store.client.set.return_value = True
        store.create(Thread(session_id="s1", user_id="u1"))

        assert store.client.set.call_args.kwargs.get("nx") is True
        store.client.sadd.assert_called_once_with(f"{PREFIX}index:user:u1", "s1")

    def test_create_conflict_returns_existing_without_touching_indexes(self, make_store):
        store = make_store(ttl=60)
        existing = Thread(session_id="s1", user_id="winner")
        store.client.set.return_value = None  # SET NX lost the race
        payloads = {f"{PREFIX}s1:meta": existing.model_dump_json().encode()}
        store.client.get.side_effect = lambda key: payloads.get(key)

        result = store.create(Thread(session_id="s1", user_id="loser", group_id="g1"))

        assert result.user_id == "winner"
        store.client.sadd.assert_not_called()
        store.client.expire.assert_not_called()
