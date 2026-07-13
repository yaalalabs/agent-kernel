"""
Redis-backed thread store.

Layout (keys under the configured prefix):
  - Metadata:     {prefix}{session_id}:meta         -> Thread metadata JSON (written once)
  - updated_at:   {prefix}{session_id}:updated_at   -> ISO timestamp (blind SET per append)
  - Messages:     {prefix}{session_id}:messages     -> Redis List, one JSON message per element
  - User index:   {prefix}index:user:{user_id}      -> set of session_ids
  - Group index:  {prefix}index:group:{group_id}    -> set of session_ids

Messages are appended with RPUSH (atomic, append-only) so concurrent appends
never lose a message and no message is ever rewritten.
"""

import datetime
import logging
import time
from typing import List, Optional, Tuple

import redis

from ...config import AKConfig
from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore


class RedisThreadStore(ThreadStore):
    """
    Redis-backed implementation of the ThreadStore interface.
    """

    _redis_client = None

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.redis")
        cfg = AKConfig.get().thread.redis
        if cfg is None:
            raise ValueError("AKConfig.thread.redis must be set to use RedisThreadStore")
        self._url = cfg.url
        self._prefix = cfg.prefix
        self._ttl = int(cfg.ttl)

    @property
    def client(self):
        """
        Returns the Redis client instance, connecting lazily if needed.
        """
        if self._redis_client is None:
            self._connect()
        return self._redis_client

    def _connect(self):
        """
        Connects to Redis using the configured URL, with retries.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._log.debug(f"Connecting to Redis using URL {self._url}")
                self._redis_client = redis.Redis.from_url(self._url)
                self._redis_client.ping()
                return
            except Exception as e:
                last_err = e
                self._log.warning("Redis connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err:
            raise last_err

    def _meta_key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}:meta"

    def _updated_key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}:updated_at"

    def _messages_key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}:messages"

    def _user_index_key(self, user_id: str) -> str:
        return f"{self._prefix}index:user:{user_id}"

    def _group_index_key(self, group_id: str) -> str:
        return f"{self._prefix}index:group:{group_id}"

    def _expire(self, *keys: str) -> None:
        if self._ttl > 0:
            for key in keys:
                self.client.expire(key, self._ttl)

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata and register it in the user/group indexes.
        :param thread: The thread to persist.
        :return: The persisted thread.
        """
        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        self.client.set(self._meta_key(thread.session_id), metadata.model_dump_json())
        self.client.sadd(self._user_index_key(thread.user_id), thread.session_id)
        expire_keys = [self._meta_key(thread.session_id), self._user_index_key(thread.user_id)]
        if thread.group_id:
            self.client.sadd(self._group_index_key(thread.group_id), thread.session_id)
            expire_keys.append(self._group_index_key(thread.group_id))
        self._expire(*expire_keys)
        return metadata

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        payload = self.client.get(self._meta_key(session_id))
        if payload is None:
            return None
        thread = Thread.model_validate_json(payload)
        updated = self.client.get(self._updated_key(session_id))
        if updated is not None:
            thread.updated_at = datetime.datetime.fromisoformat(updated.decode())
        return thread

    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Append a single message via RPUSH and blind-set the updated_at timestamp.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        payload = self.client.get(self._meta_key(session_id))
        if payload is None:
            raise KeyError(f"Thread {session_id} not found")
        self.client.rpush(self._messages_key(session_id), message.model_dump_json())
        self.client.set(self._updated_key(session_id), _utc_now().isoformat())
        if self._ttl > 0:
            # The user/group index sets are shared across a user's threads, so their TTL
            # must be refreshed on every append or active threads would drop out of listings.
            thread = Thread.model_validate_json(payload)
            expire_keys = [
                self._messages_key(session_id),
                self._updated_key(session_id),
                self._meta_key(session_id),
                self._user_index_key(thread.user_id),
            ]
            if thread.group_id:
                expire_keys.append(self._group_index_key(thread.group_id))
            self._expire(*expire_keys)

    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages using LRANGE.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message.
        :return: A tuple of (messages page, next_offset).
        """
        if offset < 0:
            offset = 0
        key = self._messages_key(session_id)
        raw = self.client.lrange(key, offset, offset + limit - 1)
        messages = [ThreadMessage.model_validate_json(item) for item in raw]
        total = self.client.llen(key)
        next_offset = offset + limit if offset + limit < total else None
        return messages, next_offset

    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Thread], Optional[int]]:
        """
        List thread metadata filtered by user_id and/or group_id, most-recently updated first.
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads to return.
        :param offset: Zero-based index of the first thread.
        :return: A tuple of (threads page, next_offset).
        """
        from .base import paginate

        if user_id is not None:
            session_ids = {m.decode() for m in self.client.smembers(self._user_index_key(user_id))}
        elif group_id is not None:
            session_ids = {m.decode() for m in self.client.smembers(self._group_index_key(group_id))}
        else:
            session_ids = {key.decode().rsplit(":meta", 1)[0][len(self._prefix) :] for key in self.client.scan_iter(match=f"{self._prefix}*:meta")}

        threads = []
        for session_id in session_ids:
            thread = self.load_metadata(session_id)
            if thread is None:
                continue
            if user_id is not None and thread.user_id != user_id:
                continue
            if group_id is not None and thread.group_id != group_id:
                continue
            threads.append(thread)
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        return paginate(threads, limit, offset)

    def clear(self) -> None:
        """
        Clears all stored threads, messages, and indexes under the configured prefix.
        """
        self._log.debug(f"Clearing all thread keys with prefix {self._prefix}")
        for key in self.client.scan_iter(match=f"{self._prefix}*"):
            self.client.delete(key)
