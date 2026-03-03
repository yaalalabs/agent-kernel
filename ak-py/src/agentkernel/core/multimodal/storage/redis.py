"""
Redis storage driver for multimodal attachments.

This driver stores attachments in a Redis instance, independently of
the session store. It supports TTL-based expiration and key-prefix isolation.
"""

import json
import logging
from typing import Optional

from .base import (
    AttachmentStorageDriver,
)

_log = logging.getLogger("ak.core.multimodal.storage.redis")


class RedisStorageDriver(AttachmentStorageDriver):
    """
    Redis-backed attachment storage.

    Attachments are stored as JSON-serialised hashes in Redis, keyed by
    ``{prefix}{session_id}:{attachment_id}``.  An additional sorted-set
    ``{prefix}{session_id}:_index`` tracks attachment order for pruning.
    """

    def __init__(self, session_id: str, url: str, ttl: int, prefix: str):
        """
        Initialize the Redis storage driver.
        :param session_id: Session identifier for isolation.
        :param url: Redis connection URL.
        :param ttl: TTL in seconds for attachment keys.
        :param prefix: Key prefix for attachment keys.
        """
        import redis

        self._client = redis.Redis.from_url(url)
        self._session_id = session_id
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, attachment_id: str) -> str:
        return f"{self._prefix}{self._session_id}:{attachment_id}"

    def _index_key(self) -> str:
        return f"{self._prefix}{self._session_id}:_index"

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        # Save payload as JSON
        self._client.set(
            self._key(attachment_id),
            json.dumps(attachment),
            ex=self._ttl if self._ttl > 0 else None,
        )

        # Update index (RPUSH to maintain insertion order)
        self._client.rpush(self._index_key(), attachment_id)
        if self._ttl > 0:
            self._client.expire(self._index_key(), self._ttl)

        # Prune old attachments
        index_len = self._client.llen(self._index_key())
        if index_len > max_attachments:
            prune_count = index_len - max_attachments
            for _ in range(prune_count):
                old_id = self._client.lpop(self._index_key())
                if old_id:
                    self.delete(old_id.decode() if isinstance(old_id, bytes) else old_id)

        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        raw = self._client.get(self._key(attachment_id))
        if raw:
            return json.loads(raw)
        return None

    def delete(self, attachment_id: str) -> None:
        self._client.delete(self._key(attachment_id))
