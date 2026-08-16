"""
Redis-like implementation of the ThreadStore interface.

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
from typing import List, Optional, Tuple

from ....core.util.driver.redis_like import _RedisLikeDriver
from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore


class _RedisLikeThreadStore(ThreadStore):
    """
    Shared thread store body for the Redis-protocol backends.

    Concrete subclasses (``RedisThreadStore``, ``ValkeyThreadStore``) implement only
    ``__init__``, where they must set all three attributes below — this class reads
    them but never assigns them. Mirrors ``_RedisLikeDriver``, whose subclasses supply
    the driver-specific bits the same way.
    """

    _driver: _RedisLikeDriver
    _prefix: str
    _log: logging.Logger

    def _meta_key(self, session_id: str) -> str:
        return self._driver.key(f"{session_id}:meta")

    def _updated_key(self, session_id: str) -> str:
        return self._driver.key(f"{session_id}:updated_at")

    def _messages_key(self, session_id: str) -> str:
        return self._driver.key(f"{session_id}:messages")

    def _user_index_key(self, user_id: str) -> str:
        return self._driver.key(f"index:user:{user_id}")

    def _group_index_key(self, group_id: str) -> str:
        return self._driver.key(f"index:group:{group_id}")

    def _expire(self, *keys: str) -> None:
        if self._driver.ttl > 0:
            for key in keys:
                self._driver.expire(key)

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata and register it in the user/group indexes.
        Creation is conditional (SET NX): if a concurrent request already created
        the thread, the existing metadata is returned untouched.
        :param thread: The thread to persist.
        :return: The persisted (or already existing) thread.
        """
        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        if not self._driver.set(self._meta_key(thread.session_id), metadata.model_dump_json(), nx=True):
            return self.load_metadata(thread.session_id)
        self._driver.sadd(self._user_index_key(thread.user_id), thread.session_id)
        expire_keys = [self._meta_key(thread.session_id), self._user_index_key(thread.user_id)]
        if thread.group_id:
            self._driver.sadd(self._group_index_key(thread.group_id), thread.session_id)
            expire_keys.append(self._group_index_key(thread.group_id))
        self._expire(*expire_keys)
        return metadata

    def update_name(self, session_id: str, name: str) -> Thread:
        """
        Set a thread's display name and mark it name_locked by rewriting the
        meta key; updated_at (a separate key) is untouched. Concurrent renames
        are last-write-wins, and appends are unaffected since messages live in
        their own key.
        :param session_id: Unique identifier for the thread.
        :param name: The new display name.
        :return: The updated thread metadata.
        :raises KeyError: If the thread does not exist.
        """
        payload = self._driver.get(self._meta_key(session_id))
        if payload is None:
            raise KeyError(f"Thread {session_id} not found")
        thread = Thread.model_validate_json(payload)
        thread.name = name
        thread.name_locked = True
        self._driver.set(self._meta_key(session_id), thread.model_dump_json())
        self._expire(self._meta_key(session_id))
        return self.load_metadata(session_id)

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        payload = self._driver.get(self._meta_key(session_id))
        if payload is None:
            return None
        thread = Thread.model_validate_json(payload)
        updated = self._driver.get(self._updated_key(session_id))
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
        payload = self._driver.get(self._meta_key(session_id))
        if payload is None:
            raise KeyError(f"Thread {session_id} not found")
        self._driver.rpush(self._messages_key(session_id), message.model_dump_json())
        self._driver.set(self._updated_key(session_id), _utc_now().isoformat())
        if self._driver.ttl > 0:
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
        raw = self._driver.lrange(key, offset, offset + limit - 1)
        messages = [ThreadMessage.model_validate_json(item) for item in raw]
        total = self._driver.llen(key)
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
            session_ids = self._driver.smembers(self._user_index_key(user_id))
        elif group_id is not None:
            session_ids = self._driver.smembers(self._group_index_key(group_id))
        else:
            session_ids = {key.rsplit(":meta", 1)[0][len(self._prefix) :] for key in self._driver.scan_keys("*:meta")}

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
        self._driver.clear_prefix()
