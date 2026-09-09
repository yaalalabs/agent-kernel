"""
DynamoDB storage backend for multimodal attachments.

Attachments are stored in an AWS DynamoDB table, independently of the session
store, with TTL-based expiration.

Expected table schema:
    Partition Key: ``session_id`` (S)
    Sort Key:      ``attachment_id`` (S)
    TTL attribute: ``expiry_time`` (N) — Unix epoch seconds
"""

import json
import logging
from typing import Optional

from ...util.driver.dynamodb import DynamoDBDriver
from .base import AttachmentStore


class DynamoDBAttachmentStore(AttachmentStore):
    """
    DynamoDBAttachmentStore class provides a DynamoDB-backed implementation
    of the AttachmentStore interface.

    Each attachment is stored as an item with ``session_id`` as the partition key
    and ``attachment_id`` as the sort key. An additional index item
    (``attachment_id = "_index"``) tracks the ordered list of attachment IDs
    for pruning.
    """

    _log = logging.getLogger("ak.core.multimodal.storage.dynamodb")

    def __init__(self, session_id: str, table_name: str, ttl: int):
        """
        Initializes a DynamoDBAttachmentStore instance.
        :param session_id: Session identifier for isolation.
        :param table_name: DynamoDB table name.
        :param ttl: TTL in seconds for attachment items.
        """
        self._session_id = session_id
        self._driver = DynamoDBDriver(table_name=table_name, partition_key="session_id", sort_key="attachment_id", ttl=ttl)

    def _put(self, attachment_id: str, data) -> None:
        """Store a single item, JSON-encoding its data attribute."""
        self._driver.put(
            {
                "session_id": self._session_id,
                "attachment_id": attachment_id,
                "data": json.dumps(data),
            }
        )

    def _get(self, attachment_id: str):
        """Retrieve and JSON-decode a single item's data attribute."""
        item = self._driver.get(self._session_id, attachment_id)
        if item:
            return json.loads(item["data"])
        return None

    def save(self, attachment: dict, max_attachments: int) -> str:
        """
        Saves an attachment and prunes old ones if the limit is exceeded.
        :param attachment: Attachment data dictionary.
        :param max_attachments: Maximum number of attachments to keep.
        :return: The attachment ID.
        """
        attachment_id = attachment["id"]

        # Save payload
        self._put(attachment_id, attachment)

        # Update index
        index_ids = self._get("_index") or []
        index_ids.append(attachment_id)

        # Prune old attachments
        if len(index_ids) > max_attachments:
            old_ids = index_ids[:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            index_ids = index_ids[-max_attachments:]

        # Save updated index
        self._put("_index", index_ids)

        self._log.debug(f"Saved attachment: {attachment_id}")
        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        """
        Retrieves an attachment by its ID.
        :param attachment_id: Attachment ID.
        :return: Attachment data dict or None if not found.
        """
        return self._get(attachment_id)

    def delete(self, attachment_id: str) -> None:
        """
        Deletes an attachment by its ID.
        :param attachment_id: Attachment ID.
        """
        self._driver.delete(self._session_id, attachment_id)
        index_ids = self._get("_index") or []
        if attachment_id in index_ids:
            index_ids.remove(attachment_id)
            self._put("_index", index_ids)
        self._log.debug(f"Deleted attachment: {attachment_id}")
