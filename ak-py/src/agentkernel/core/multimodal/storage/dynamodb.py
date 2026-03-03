"""
DynamoDB storage driver for multimodal attachments.

This driver stores attachments in an AWS DynamoDB table, independently of
the session store. It supports TTL-based expiration.

Expected table schema:
    Partition Key: ``session_id`` (S)
    Sort Key:      ``attachment_id`` (S)
    TTL attribute: ``expiry_time`` (N) — Unix epoch seconds
"""

import json
import logging
import time
from typing import Optional

from .base import (
    AttachmentStorageDriver,
)

_log = logging.getLogger("ak.core.multimodal.storage.dynamodb")


class DynamoDBStorageDriver(AttachmentStorageDriver):
    """
    DynamoDB-backed attachment storage.

    Each attachment is stored as an item with ``session_id`` as the partition key
    and ``attachment_id`` as the sort key. An additional index item
    (``attachment_id = "_index"``) tracks the ordered list of attachment IDs
    for pruning.
    """

    def __init__(self, session_id: str, table_name: str, ttl: int):
        """
        Initialize the DynamoDB storage driver.
        :param session_id: Session identifier for isolation.
        :param table_name: DynamoDB table name.
        :param ttl: TTL in seconds for attachment items.
        """
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)
        self._session_id = session_id
        self._ttl = ttl

    def _expiry_time(self) -> int:
        """Calculate expiry time as Unix epoch seconds."""
        return int(time.time()) + self._ttl if self._ttl > 0 else 0

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        # Save payload
        item = {
            "session_id": self._session_id,
            "attachment_id": attachment_id,
            "data": json.dumps(attachment),
        }
        if self._ttl > 0:
            item["expiry_time"] = self._expiry_time()

        self._table.put_item(Item=item)

        # Update index
        index_response = self._table.get_item(Key={"session_id": self._session_id, "attachment_id": "_index"})
        index_ids = []
        if "Item" in index_response:
            index_ids = json.loads(index_response["Item"].get("data", "[]"))

        index_ids.append(attachment_id)

        # Prune old attachments
        if len(index_ids) > max_attachments:
            old_ids = index_ids[:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            index_ids = index_ids[-max_attachments:]

        # Save updated index
        index_item = {
            "session_id": self._session_id,
            "attachment_id": "_index",
            "data": json.dumps(index_ids),
        }
        if self._ttl > 0:
            index_item["expiry_time"] = self._expiry_time()

        self._table.put_item(Item=index_item)

        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        response = self._table.get_item(Key={"session_id": self._session_id, "attachment_id": attachment_id})
        if "Item" in response:
            return json.loads(response["Item"]["data"])
        return None

    def delete(self, attachment_id: str) -> None:
        self._table.delete_item(Key={"session_id": self._session_id, "attachment_id": attachment_id})
