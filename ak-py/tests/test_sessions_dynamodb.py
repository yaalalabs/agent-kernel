"""Store-level tests for DynamoDBSessionStore (mocked shared driver)."""

from unittest.mock import MagicMock

import pytest
from boto3.dynamodb.types import Binary

from agentkernel.core.model import Principal, SessionOwner
from agentkernel.core.session.dynamodb import DynamoDBSessionStore
from agentkernel.core.session.serde import BinarySerde


def _store(monkeypatch) -> DynamoDBSessionStore:
    class FakeCfg:
        class session:
            type = "dynamodb"

            class dynamodb:
                table_name = "ak-sessions"
                ttl = 60

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))
    store = DynamoDBSessionStore()
    store._driver = MagicMock()
    return store


def test_store_wraps_payloads_in_binary(monkeypatch):
    store = _store(monkeypatch)
    session = store.new("s1")
    session.set("greeting", "hello")

    store.store(session)

    item = store._driver.put.call_args.args[0]
    assert item["session_id"] == "s1"
    assert item["key"] == "greeting"
    assert isinstance(item["value"], Binary)
    assert BinarySerde().loads(item["value"].value) == "hello"


def test_load_unwraps_binary_values(monkeypatch):
    store = _store(monkeypatch)
    serde = BinarySerde()
    store._driver.query_sort_keys.return_value = ["greeting"]
    store._driver.get.return_value = {"session_id": "s1", "key": "greeting", "value": Binary(serde.dumps("hello"))}

    loaded = store.load("s1", strict=True)

    assert loaded.get("greeting") == "hello"
    store._driver.get.assert_called_once_with("s1", "greeting")


def test_load_skips_missing_items(monkeypatch):
    """A key listed by the query but whose item vanished (e.g. TTL) is skipped, not an error."""
    store = _store(monkeypatch)
    serde = BinarySerde()
    store._driver.query_sort_keys.return_value = ["gone", "kept"]
    store._driver.get.side_effect = [None, {"session_id": "s1", "key": "kept", "value": Binary(serde.dumps(42))}]

    loaded = store.load("s1", strict=True)

    assert loaded.get("kept") == 42
    keys = [k for k, _ in loaded.get_all(volatile=False)]
    assert "gone" not in keys


def test_the_owner_is_stored_and_the_principal_is_not(monkeypatch):
    """#603: the owner is identity kept with the session; the principal belongs to one run and is never stored."""
    store = _store(monkeypatch)
    items: dict[str, dict] = {}
    store._driver.put.side_effect = lambda item: items.__setitem__(item["key"], item)
    store._driver.query_sort_keys.side_effect = lambda session_id: list(items)
    store._driver.get.side_effect = lambda session_id, key: items.get(key)
    owner = SessionOwner(subject="alice", provider="static", namespace="static")
    session = store.new("s1")
    session._record_owner(owner)
    session._publish_run(Principal(subject="alice", provider="static", namespace="static"), None)

    store.store(session)
    reloaded = store.load("s1", strict=True)

    assert reloaded is not session
    assert reloaded.get_owner() == owner
    assert reloaded.get_principal() is None


def test_load_missing_session_strict_raises(monkeypatch):
    store = _store(monkeypatch)
    store._driver.query_sort_keys.return_value = []
    with pytest.raises(KeyError):
        store.load("missing", strict=True)


def test_clear_delegates_to_driver(monkeypatch):
    store = _store(monkeypatch)
    store.clear()
    store._driver.clear_all.assert_called_once_with()
