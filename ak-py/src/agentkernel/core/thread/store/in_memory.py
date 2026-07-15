"""
In-memory thread store for local development and testing.
"""

import logging
from typing import ClassVar, List, Optional, Tuple

from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore, paginate


class InMemoryThreadStore(ThreadStore):
    """
    InMemoryThreadStore provides an in-memory implementation of the ThreadStore interface.

    Storage is shared across all instances via ClassVar so that threads persist
    for the lifetime of the process. Thread metadata and messages are kept in
    separate maps so that appending a message never rewrites existing messages.
    """

    _threads: ClassVar[dict[str, Thread]] = {}  # session_id -> Thread metadata (messages always [])
    _messages: ClassVar[dict[str, List[ThreadMessage]]] = {}  # session_id -> ordered messages
    _log = logging.getLogger("ak.thread.store.inmemory")

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata. If a thread already exists for the
        session id (e.g. a concurrent first request won the race), the existing
        thread is returned untouched.
        :param thread: The thread to persist.
        :return: The persisted (or already existing) thread.
        """
        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        stored = self._threads.setdefault(thread.session_id, metadata)
        self._messages.setdefault(thread.session_id, [])
        return stored.model_copy(update={"messages": []})

    def update_name(self, session_id: str, name: str) -> Thread:
        """
        Set a thread's display name and mark it name_locked; updated_at is untouched.
        :param session_id: Unique identifier for the thread.
        :param name: The new display name.
        :return: The updated thread metadata.
        :raises KeyError: If the thread does not exist.
        """
        thread = self._threads.get(session_id)
        if thread is None:
            raise KeyError(f"Thread {session_id} not found")
        thread.name = name
        thread.name_locked = True
        return thread.model_copy(update={"messages": []})

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        thread = self._threads.get(session_id)
        return thread.model_copy(update={"messages": []}) if thread is not None else None

    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Append a single message to a thread.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        thread = self._threads.get(session_id)
        if thread is None:
            raise KeyError(f"Thread {session_id} not found")
        self._messages.setdefault(session_id, []).append(message)
        thread.updated_at = _utc_now()

    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages in append order.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message.
        :return: A tuple of (messages page, next_offset).
        """
        return paginate(self._messages.get(session_id, []), limit, offset)

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
        matches = [
            thread.model_copy(update={"messages": []})
            for thread in self._threads.values()
            if (user_id is None or thread.user_id == user_id) and (group_id is None or thread.group_id == group_id)
        ]
        matches.sort(key=lambda t: t.updated_at, reverse=True)
        return paginate(matches, limit, offset)

    def clear(self) -> None:
        """
        Clears all stored threads and messages.
        """
        self._log.debug("Clearing all stored threads")
        self._threads.clear()
        self._messages.clear()
