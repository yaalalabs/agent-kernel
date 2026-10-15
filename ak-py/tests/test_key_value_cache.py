"""Tests for the debug logging in ``core/util/key_value_cache.py``.

Every read and write on a KeyValueCache logs its key (and value, where there is one) on the
``ak.core.key_value_cache`` logger at DEBUG, so session cache traffic can be traced.
"""

import logging

import pytest

from agentkernel.core.util.key_value_cache import KeyValueCache

LOGGER = "ak.core.key_value_cache"


@pytest.fixture
def cache_log(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    return caplog


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER]


class TestKeyValueCacheLogging:
    def test_set_logs_key_and_value(self, cache_log):
        KeyValueCache().set("name", "John")

        assert _messages(cache_log) == ["Set key name: John"]

    def test_setitem_logs_through_set(self, cache_log):
        cache = KeyValueCache()
        cache["name"] = "John"

        assert _messages(cache_log) == ["Set key name: John"]

    def test_set_with_empty_key_raises_without_logging(self, cache_log):
        with pytest.raises(ValueError):
            KeyValueCache().set("", "John")

        assert _messages(cache_log) == []

    def test_get_logs_key_and_stored_value(self, cache_log):
        cache = KeyValueCache(data={"name": "John"})

        assert cache.get("name") == "John"
        assert _messages(cache_log) == ["Get key name: John"]

    def test_get_of_missing_key_logs_the_default(self, cache_log):
        assert KeyValueCache().get("missing", "fallback") == "fallback"

        assert _messages(cache_log) == ["Get key missing: fallback"]

    def test_getitem_logs_key_and_value(self, cache_log):
        cache = KeyValueCache(data={"name": "John"})

        assert cache["name"] == "John"
        assert _messages(cache_log) == ["Get key name: John"]

    def test_delete_logs_deleted_key(self, cache_log):
        cache = KeyValueCache(data={"name": "John"})

        assert cache.delete("name") is True
        assert _messages(cache_log) == ["Deleted key name"]

    def test_delete_of_missing_key_logs_skip(self, cache_log):
        assert KeyValueCache().delete("missing") is False

        assert _messages(cache_log) == ["Delete skipped, key missing not found"]

    def test_delitem_logs_deleted_key(self, cache_log):
        cache = KeyValueCache(data={"name": "John"})
        del cache["name"]

        assert _messages(cache_log) == ["Deleted key name"]

    def test_delitem_of_missing_key_raises_without_logging(self, cache_log):
        with pytest.raises(KeyError):
            del KeyValueCache()["missing"]

        assert _messages(cache_log) == []

    def test_update_logs_merged_pairs(self, cache_log):
        KeyValueCache().update({"debug": True, "timeout": 30})

        assert _messages(cache_log) == ["Updated keys: {'debug': True, 'timeout': 30}"]

    def test_clear_logs(self, cache_log):
        KeyValueCache(data={"name": "John"}).clear()

        assert _messages(cache_log) == ["Cleared all keys"]

    def test_logs_are_debug_level(self, cache_log):
        cache = KeyValueCache()
        cache.set("name", "John")
        cache.get("name")
        cache.update({"age": 30})
        cache.delete("name")
        cache.clear()

        records = [record for record in cache_log.records if record.name == LOGGER]
        assert len(records) == 5
        assert all(record.levelno == logging.DEBUG for record in records)

    def test_nothing_logged_above_debug(self, caplog):
        caplog.set_level(logging.INFO, logger=LOGGER)
        cache = KeyValueCache()
        cache.set("name", "John")
        cache.get("name")

        assert _messages(caplog) == []
