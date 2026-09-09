"""Store-level tests for RedisAttachmentStore (mocked shared driver)."""

import json
from unittest.mock import MagicMock

from agentkernel.core.multimodal.storage.redis import RedisAttachmentStore

PREFIX = "ak:att:"


def _store() -> tuple[RedisAttachmentStore, MagicMock]:
    store = RedisAttachmentStore(session_id="s1", url="redis://localhost:6379", ttl=60, prefix=PREFIX)
    driver = MagicMock()
    driver.key.side_effect = lambda suffix: f"{PREFIX}{suffix}"
    driver.llen.return_value = 1
    store._driver = driver
    return store, driver


def test_save_refreshes_index_ttl_after_rpush():
    """The index-key TTL refresh moved from the deleted driver's append_index into
    the store — without it, _index keys would outlive their attachments."""
    store, driver = _store()

    store.save({"id": "a1"}, max_attachments=5)

    index_key = f"{PREFIX}s1:_index"
    driver.rpush.assert_called_once_with(index_key, "a1")
    driver.expire.assert_called_once_with(index_key)
    ordered = [name for name, *_ in driver.mock_calls if name in ("rpush", "expire")]
    assert ordered == ["rpush", "expire"]


def test_save_stores_json_under_attachment_key():
    store, driver = _store()
    store.save({"id": "a1", "data": "x"}, max_attachments=5)
    driver.set.assert_called_once_with(f"{PREFIX}s1:a1", json.dumps({"id": "a1", "data": "x"}))


def test_save_prunes_oldest_when_over_limit():
    store, driver = _store()
    driver.llen.side_effect = [3, 2]  # over the limit once, then within it
    driver.lpop.return_value = "old"

    store.save({"id": "a1"}, max_attachments=2)

    driver.lpop.assert_called_once_with(f"{PREFIX}s1:_index")
    driver.delete.assert_called_once_with(f"{PREFIX}s1:old")
    driver.lrem.assert_called_once_with(f"{PREFIX}s1:_index", 0, "old")


def test_get_decodes_json():
    store, driver = _store()
    driver.get.return_value = b'{"id": "a1"}'
    assert store.get("a1") == {"id": "a1"}
    driver.get.assert_called_once_with(f"{PREFIX}s1:a1")


def test_get_missing_returns_none():
    store, driver = _store()
    driver.get.return_value = None
    assert store.get("missing") is None
