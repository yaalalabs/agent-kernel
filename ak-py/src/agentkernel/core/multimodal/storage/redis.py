"""
Redis storage driver for multimodal attachments.

This driver stores attachments in a Redis instance, independently of
the session store. It supports TTL-based expiration and key-prefix isolation.
"""

import json
import logging
import time
from typing import Optional

from .base import AttachmentStore


class RedisAttachmentDriver:
    """
    RedisAttachmentDriver provides connection management and helpers for
    raw Redis attachment operations.
    """

    _log = logging.getLogger("ak.multimodal.storage.redis.driver")
    _redis_client = None

    def __init__(self, url: str, ttl: int, prefix: str):
        """
        Initialize the Redis attachment driver.
        :param url: Redis connection URL.
        :param ttl: TTL in seconds for attachment keys (0 = no TTL).
        :param prefix: Key prefix for attachment keys.
        """
        self._url = url
        self._ttl = ttl
        self._prefix = prefix

    @property
    def client(self):
        """
        Returns the Redis client instance, connecting lazily if needed.
        """
        if self._redis_client is None:
            self._connect()
        else:
            try:
                self._redis_client.ping()
            except Exception:
                self._log.warning("Redis client is not alive, reconnecting")
                self._connect()
        return self._redis_client

    @property
    def ttl(self):
        return self._ttl

    def _connect(self):
        """
        Connects to Redis using the configured URL, with retries.
        """
        import redis

        retries = 3
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug("Connecting to Redis at %s", self._url)
                client = redis.Redis.from_url(self._url, socket_connect_timeout=5)
                client.ping()
                self._redis_client = client
                return
            except Exception as e:
                last_err = e
                self._log.warning("Redis connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(2)
        if last_err:
            raise last_err

    def key(self, session_id: str, attachment_id: str) -> str:
        return f"{self._prefix}{session_id}:{attachment_id}"

    def index_key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}:_index"

    def set(self, session_id: str, attachment_id: str, data: dict) -> None:
        """Store a single attachment as JSON."""
        self.client.set(
            self.key(session_id, attachment_id),
            json.dumps(data),
            ex=self._ttl if self._ttl > 0 else None,
        )

    def get(self, session_id: str, attachment_id: str) -> Optional[dict]:
        """Retrieve a single attachment by ID."""
        raw = self.client.get(self.key(session_id, attachment_id))
        if raw:
            return json.loads(raw)
        return None

    def delete(self, session_id: str, attachment_id: str) -> None:
        """Delete a single attachment."""
        self.client.delete(self.key(session_id, attachment_id))

    def append_index(self, session_id: str, attachment_id: str) -> None:
        """Append an attachment ID to the session index."""
        self.client.rpush(self.index_key(session_id), attachment_id)
        if self._ttl > 0:
            self.client.expire(self.index_key(session_id), self._ttl)

    def pop_oldest(self, session_id: str) -> Optional[str]:
        """Remove and return the oldest attachment ID from the session index."""
        old_id = self.client.lpop(self.index_key(session_id))
        if old_id:
            return old_id.decode() if isinstance(old_id, bytes) else old_id
        return None

    def index_len(self, session_id: str) -> int:
        """Return the number of attachments tracked for this session."""
        return self.client.llen(self.index_key(session_id))

    def list_ids(self, session_id: str) -> list[str]:
        """Return attachment IDs for this session in insertion order."""
        raw_ids = self.client.lrange(self.index_key(session_id), 0, -1)
        return [attachment_id.decode() if isinstance(attachment_id, bytes) else attachment_id for attachment_id in raw_ids]


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
        self._driver = RedisAttachmentDriver(url=url, ttl=ttl, prefix=prefix)

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        self._driver.set(self._session_id, attachment_id, attachment)
        self._driver.append_index(self._session_id, attachment_id)

        # Prune oldest attachments when over the limit
        while self._driver.index_len(self._session_id) > max_attachments:
            old_id = self._driver.pop_oldest(self._session_id)
            if old_id:
                self._driver.delete(self._session_id, old_id)

        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        return self._driver.get(self._session_id, attachment_id)

    def delete(self, attachment_id: str) -> None:
        self._driver.delete(self._session_id, attachment_id)

    def list_ids(self) -> list[str]:
        return self._driver.list_ids(self._session_id)
