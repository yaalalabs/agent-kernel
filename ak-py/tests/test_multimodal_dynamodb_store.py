"""Store-level tests for DynamoDBAttachmentStore (mocked shared driver)."""

import json
from unittest.mock import MagicMock

import pytest

from agentkernel.core.multimodal.storage.dynamodb import DynamoDBAttachmentStore


def _store() -> tuple[DynamoDBAttachmentStore, MagicMock]:
    store = DynamoDBAttachmentStore(session_id="s1", table_name="ak-attachments", ttl=60)
    driver = MagicMock()
    driver.get.return_value = None  # no index yet
    store._driver = driver
    return store, driver


def _attachment(data_bytes: int) -> dict:
    return {"id": "a1", "name": "report.pdf", "type": "file", "mime_type": "application/pdf", "data": "x" * data_bytes}


def test_an_attachment_under_the_item_limit_is_written():
    store, driver = _store()
    attachment = _attachment(300 * 1024)

    store.save(attachment, max_attachments=5)

    item = driver.put.call_args_list[0].args[0]
    assert item == {"session_id": "s1", "attachment_id": "a1", "data": json.dumps(attachment)}


def test_an_attachment_over_the_item_limit_is_refused_before_any_write():
    store, driver = _store()

    with pytest.raises(ValueError) as raised:
        store.save(_attachment(400 * 1024), max_attachments=5)

    message = str(raised.value)
    assert "report.pdf" in message
    assert "400 KB" in message
    assert "redis" in message
    driver.put.assert_not_called()  # neither the attachment nor the index item


def test_the_limit_counts_the_keys_and_overhead_not_only_the_data():
    store, driver = _store()
    # The JSON payload alone fits; the keys and attribute-name overhead push the item over.
    attachment = _attachment(0)
    payload_bytes = len(json.dumps(attachment).encode())
    attachment["data"] = "x" * (DynamoDBAttachmentStore.MAX_ITEM_BYTES - payload_bytes - 8)

    with pytest.raises(ValueError):
        store.save(attachment, max_attachments=5)
    driver.put.assert_not_called()
