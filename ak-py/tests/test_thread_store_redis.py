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
        # Inject an established mocked client into the shared driver; the driver's
        # ping health-check passes (MagicMock ping raises nothing).
        store._driver._client = MagicMock()
        return store

    yield _make
    AKConfig.get().thread = original


def _client(store: RedisThreadStore) -> MagicMock:
    return store._driver._client


def _expired_keys(store: RedisThreadStore) -> set:
    # The shared driver issues EXPIRE with keyword arguments (name=..., time=...).
    return {call.kwargs["name"] for call in _client(store).expire.call_args_list}


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
        _client(store).expire.assert_not_called()

    def test_append_refreshes_thread_and_index_keys(self, make_store):
        store = make_store(ttl=60)
        thread = Thread(session_id="s1", user_id="u1", group_id="g1")
        _client(store).get.return_value = thread.model_dump_json().encode()

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
        _client(store).get.return_value = thread.model_dump_json().encode()

        store.append_message("s1", ThreadMessage(role="user", content="hi"))
        _client(store).expire.assert_not_called()

    def test_append_missing_thread_raises(self, make_store):
        store = make_store(ttl=60)
        _client(store).get.return_value = None
        with pytest.raises(KeyError):
            store.append_message("missing", ThreadMessage(role="user", content="hi"))
        _client(store).rpush.assert_not_called()


class TestRedisThreadStoreUpdateName:
    """update_name must rewrite only the meta key, leaving updated_at alone."""

    def _wire_storage(self, store, payloads: dict):
        """Make the mocked client behave like real key/value storage for GET/SET."""
        _client(store).get.side_effect = lambda key: payloads.get(key)
        _client(store).set.side_effect = lambda key, value, **kwargs: payloads.__setitem__(key, value.encode()) or True

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
        _client(store).set.assert_not_called()


class TestRedisThreadStoreConditionalCreate:
    """create() must be conditional (SET NX) so a lost race never overwrites metadata."""

    def test_create_sets_meta_with_nx(self, make_store):
        store = make_store(ttl=0)
        _client(store).set.return_value = True
        store.create(Thread(session_id="s1", user_id="u1"))

        assert _client(store).set.call_args.kwargs.get("nx") is True
        _client(store).sadd.assert_called_once_with(f"{PREFIX}index:user:u1", "s1")

    def test_create_conflict_returns_existing_without_touching_indexes(self, make_store):
        store = make_store(ttl=60)
        existing = Thread(session_id="s1", user_id="winner")
        _client(store).set.return_value = None  # SET NX lost the race
        payloads = {f"{PREFIX}s1:meta": existing.model_dump_json().encode()}
        _client(store).get.side_effect = lambda key: payloads.get(key)

        result = store.create(Thread(session_id="s1", user_id="loser", group_id="g1"))

        assert result.user_id == "winner"
        _client(store).sadd.assert_not_called()
        _client(store).expire.assert_not_called()
