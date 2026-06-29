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

from .base import AttachmentStore


class DynamoDBAttachmentDriver:
    """
    DynamoDBAttachmentDriver provides connection management and helpers for
    raw DynamoDB attachment operations.
    """

    _log = logging.getLogger("ak.multimodal.storage.dynamodb.driver")

    def __init__(self, table_name: str, ttl: int):
        """
        Initialize the DynamoDB attachment driver.
        :param table_name: DynamoDB table name.
        :param ttl: TTL in seconds for attachment items (0 = no TTL).
        """
        self._table_name = table_name
        self._ttl = ttl
        self._table = None

    @property
    def table(self):
        """
        Returns the boto3 DynamoDB Table resource, connecting lazily if needed.
        :return: The DynamoDB Table resource.
        """
        if self._table is None:
            self._connect()
        return self._table

    def _connect(self):
        """
        Establish a connection to DynamoDB and resolve the configured table.

        Retries a few times with a small delay between attempts. Raises the last
        encountered exception if all attempts fail.
        """
        import boto3

        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to DynamoDB resource")
                resource = boto3.resource("dynamodb")
                self._table = resource.Table(self._table_name)
                self._table.load()
                self._log.debug("Connected to DynamoDB table %s", self._table_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning("DynamoDB connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    import time as _time

                    _time.sleep(delay)
        if last_err:
            raise last_err

    def _expiry_time(self) -> int:
        """Calculate expiry time as Unix epoch seconds."""
        return int(time.time()) + self._ttl if self._ttl > 0 else 0

    def put(self, session_id: str, attachment_id: str, data: dict) -> None:
        """
        Store a single attachment item.
        :param session_id: Session identifier (partition key).
        :param attachment_id: Attachment identifier (sort key).
        :param data: Attachment data dict to serialize.
        """
        item = {
            "session_id": session_id,
            "attachment_id": attachment_id,
            "data": json.dumps(data),
        }
        if self._ttl > 0:
            item["expiry_time"] = self._expiry_time()
        self.table.put_item(Item=item)

    def get(self, session_id: str, attachment_id: str) -> Optional[dict]:
        """
        Retrieve a single attachment item.
        :param session_id: Session identifier (partition key).
        :param attachment_id: Attachment identifier (sort key).
        :return: Attachment data dict or None.
        """
        response = self.table.get_item(Key={"session_id": session_id, "attachment_id": attachment_id})
        if "Item" in response:
            return json.loads(response["Item"]["data"])
        return None

    def delete(self, session_id: str, attachment_id: str) -> None:
        """
        Delete a single attachment item.
        :param session_id: Session identifier (partition key).
        :param attachment_id: Attachment identifier (sort key).
        """
        self.table.delete_item(Key={"session_id": session_id, "attachment_id": attachment_id})


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
        self._driver = DynamoDBAttachmentDriver(table_name=table_name, ttl=ttl)

    def save(self, attachment: dict, max_attachments: int) -> str:
        """
        Saves an attachment and prunes old ones if the limit is exceeded.
        :param attachment: Attachment data dictionary.
        :param max_attachments: Maximum number of attachments to keep.
        :return: The attachment ID.
        """
        attachment_id = attachment["id"]

        # Save payload
        self._driver.put(self._session_id, attachment_id, attachment)

        # Update index
        index_ids = self._driver.get(self._session_id, "_index") or []
        index_ids.append(attachment_id)

        # Prune old attachments
        if len(index_ids) > max_attachments:
            old_ids = index_ids[:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            index_ids = index_ids[-max_attachments:]

        # Save updated index
        self._driver.put(self._session_id, "_index", index_ids)

        self._log.debug(f"Saved attachment: {attachment_id}")
        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        """
        Retrieves an attachment by its ID.
        :param attachment_id: Attachment ID.
        :return: Attachment data dict or None if not found.
        """
        return self._driver.get(self._session_id, attachment_id)

    def delete(self, attachment_id: str) -> None:
        """
        Deletes an attachment by its ID.
        :param attachment_id: Attachment ID.
        """
        self._driver.delete(self._session_id, attachment_id)
        index_ids = self._driver.get(self._session_id, "_index") or []
        if attachment_id in index_ids:
            index_ids.remove(attachment_id)
            self._driver.put(self._session_id, "_index", index_ids)
        self._log.debug(f"Deleted attachment: {attachment_id}")
