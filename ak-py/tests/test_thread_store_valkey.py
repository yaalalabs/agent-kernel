"""ValkeyThreadStore: config wiring plus a slice of the inherited store body.

The store body lives in ``_RedisLikeThreadStore`` and is shared verbatim with
``RedisThreadStore``, which ``tests/test_thread_store_redis.py`` covers method by
method. Re-testing all of it here would only be testing Python's inheritance, so
this file focuses on what is genuinely Valkey-specific — the config block it reads
and the driver it builds — plus a representative slice proving the shared body
really does run through a Valkey driver.
"""

from unittest.mock import MagicMock

import pytest

from agentkernel.core.config import AKConfig, _ThreadStoreConfig, _ThreadValkeyConfig
from agentkernel.core.thread.model import Thread, ThreadMessage
from agentkernel.core.thread.store.valkey import ValkeyThreadStore
from agentkernel.core.util.driver.valkey import ValkeyDriver

PREFIX = "ak:thread:"


@pytest.fixture
def set_thread_config():
    """Install a thread config for the duration of one test, restoring the original after."""
    original = AKConfig.get().thread
    yield lambda cfg: setattr(AKConfig.get(), "thread", cfg)
    AKConfig.get().thread = original


@pytest.fixture
def make_store(set_thread_config):
    """Build a ValkeyThreadStore with a mocked Valkey client and the given TTL."""

    def _make(ttl: int = 60) -> ValkeyThreadStore:
        set_thread_config(_ThreadStoreConfig(type="valkey", valkey=_ThreadValkeyConfig(ttl=ttl, prefix=PREFIX)))
        store = ValkeyThreadStore()
        # Inject an established mocked client into the shared driver; the driver's
        # ping health-check passes (MagicMock ping raises nothing).
        store._driver._client = MagicMock()
        return store

    return _make


def _client(store: ValkeyThreadStore) -> MagicMock:
    return store._driver._client


def _expired_keys(store: ValkeyThreadStore) -> set:
    # The shared driver issues EXPIRE with keyword arguments (name=..., time=...).
    return {call.kwargs["name"] for call in _client(store).expire.call_args_list}


class TestValkeyThreadStoreWiring:
    """What ValkeyThreadStore adds over the shared body: its own config block and driver."""

    def test_reads_the_thread_valkey_config_block(self, make_store):
        store = make_store(ttl=120)
        assert store._prefix == PREFIX
        assert store._driver.ttl == 120

    def test_builds_a_valkey_driver_not_a_redis_one(self, make_store):
        store = make_store()
        assert isinstance(store._driver, ValkeyDriver)

    def test_missing_valkey_block_raises_value_error(self, set_thread_config):
        set_thread_config(_ThreadStoreConfig(type="valkey"))  # no valkey sub-block
        with pytest.raises(ValueError):
            ValkeyThreadStore()

    def test_thread_defaults_override_the_session_valkey_defaults(self, set_thread_config):
        # _ThreadValkeyConfig narrows _ValkeyConfig: a 30-day TTL and a thread-scoped
        # key prefix, instead of session's 7-day TTL and "ak:sessions:" prefix.
        set_thread_config(_ThreadStoreConfig(type="valkey", valkey=_ThreadValkeyConfig()))
        store = ValkeyThreadStore()
        assert store._prefix == "ak:thread:"
        assert store._driver.ttl == 2592000


class TestValkeyThreadStoreInheritedBehaviour:
    """A slice of the shared body, exercised through the Valkey driver.

    Deliberately not exhaustive — the full method-by-method coverage lives in
    tests/test_thread_store_redis.py, against the same code.
    """

    def test_create_expires_meta_and_index_keys(self, make_store):
        store = make_store(ttl=60)
        store.create(Thread(session_id="s1", user_id="u1", group_id="g1"))

        assert _expired_keys(store) == {
            f"{PREFIX}s1:meta",
            f"{PREFIX}index:user:u1",
            f"{PREFIX}index:group:g1",
        }

    def test_create_sets_meta_with_nx(self, make_store):
        store = make_store(ttl=0)
        _client(store).set.return_value = True
        store.create(Thread(session_id="s1", user_id="u1"))

        assert _client(store).set.call_args.kwargs.get("nx") is True
        _client(store).sadd.assert_called_once_with(f"{PREFIX}index:user:u1", "s1")

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

    def test_get_messages_pages_and_reports_next_offset(self, make_store):
        store = make_store(ttl=0)
        raw = [ThreadMessage(role="user", content=f"m{i}").model_dump_json() for i in range(3)]
        _client(store).lrange.return_value = raw[:2]
        _client(store).llen.return_value = 3

        page, next_offset = store.get_messages("s1", limit=2)

        assert [message.content for message in page] == ["m0", "m1"]
        assert next_offset == 2

    def test_get_messages_last_page_has_no_next_offset(self, make_store):
        store = make_store(ttl=0)
        _client(store).lrange.return_value = [ThreadMessage(role="user", content="m2").model_dump_json()]
        _client(store).llen.return_value = 3

        page, next_offset = store.get_messages("s1", limit=2, offset=2)

        assert [message.content for message in page] == ["m2"]
        assert next_offset is None
