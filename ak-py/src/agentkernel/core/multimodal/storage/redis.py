"""
Redis storage backend for multimodal attachments.

Attachments are stored in a Redis instance, independently of the session
store, with TTL-based expiration and key-prefix isolation.
"""

import json
from typing import Optional

from ...util.driver.redis import RedisDriver
from .base import AttachmentStore


class RedisAttachmentStore(AttachmentStore):
    """
    Redis-backed attachment storage.

    Attachments are stored as JSON-serialised dicts in Redis, keyed by
    ``{prefix}{session_id}:{attachment_id}``. An additional list
    ``{prefix}{session_id}:_index`` tracks insertion order for pruning.
    """

    def __init__(self, session_id: str, url: str, ttl: int, prefix: str):
        """
        Initialize the Redis attachment store.
        :param session_id: Session identifier for isolation.
        :param url: Redis connection URL.
        :param ttl: TTL in seconds for attachment keys.
        :param prefix: Key prefix for attachment keys.
        """
        self._session_id = session_id
        self._driver = RedisDriver(url=url, prefix=prefix, ttl=ttl)

    def _key(self, attachment_id: str) -> str:
        return self._driver.key(f"{self._session_id}:{attachment_id}")

    def _index_key(self) -> str:
        return self._driver.key(f"{self._session_id}:_index")

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        self._driver.set(self._key(attachment_id), json.dumps(attachment))
        index_key = self._index_key()
        self._driver.rpush(index_key, attachment_id)
        # Refresh the index list's TTL alongside its attachments
        self._driver.expire(index_key)

        # Prune oldest attachments when over the limit
        while self._driver.llen(index_key) > max_attachments:
            old_id = self._driver.lpop(index_key)
            if old_id:
                self.delete(old_id)

        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        raw = self._driver.get(self._key(attachment_id))
        if raw:
            return json.loads(raw)
        return None

    def delete(self, attachment_id: str) -> None:
        self._driver.delete(self._key(attachment_id))
        self._driver.lrem(self._index_key(), 0, attachment_id)
