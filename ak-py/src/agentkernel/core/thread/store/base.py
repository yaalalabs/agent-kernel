"""
Abstract storage interface and builder for Conversation Thread Support.
"""

import logging
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import List, Optional, Self, Tuple

from ...config import AKConfig
from ..model import Thread, ThreadMessage


def paginate(items: list, limit: int, offset: int) -> tuple[list, Optional[int]]:
    """
    Slice an in-order list into an offset/limit page.
    :param items: The full, ordered list of items.
    :param limit: Maximum number of items in the page.
    :param offset: Zero-based index of the first item.
    :return: A tuple of (page, next_offset); next_offset is None on the last page.
    """
    if offset < 0:
        offset = 0
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(items) else None
    return page, next_offset


class ThreadStore(ABC):
    """
    ThreadStore is the base class for thread storage that allows persistence and
    retrieval of conversation threads keyed by session_id.

    Thread metadata and thread messages are stored separately: messages are
    appended as individual, immutable records so that appends are atomic (no
    read-modify-write of the whole thread) and reads can be paginated. Paged
    reads take a zero-based ``offset`` and a ``limit`` and return the page plus
    the ``next_offset`` to pass for the following page (``None`` when the page
    is the last one).
    """

    @abstractmethod
    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata (no messages). Creation must be
        conditional: when a thread already exists for the session id (a
        concurrent first request won the race), implementations must leave the
        stored metadata untouched and return the existing thread instead.
        :param thread: The thread to persist.
        :return: The persisted (or already existing) thread.
        """
        pass

    @abstractmethod
    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata by its session id, with an empty messages list.
        :param session_id: Unique identifier for the thread (same as the session id).
        :return: The thread metadata, or None if it does not exist.
        """
        pass

    @abstractmethod
    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Append a single message to a thread as an immutable record and refresh
        the thread's updated_at timestamp. The write is atomic — it never
        rewrites existing messages — so concurrent appends cannot lose messages.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        pass

    @abstractmethod
    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages in chronological (append) order.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message to return.
        :return: A tuple of (messages page, next_offset). next_offset is the
                 offset to pass for the next page, or None when this is the last page.
        """
        pass

    @abstractmethod
    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Thread], Optional[int]]:
        """
        List thread metadata filtered by user_id and/or group_id, most-recently
        updated first. Returned threads carry metadata only (empty messages).
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads to return.
        :param offset: Zero-based index of the first thread to return.
        :return: A tuple of (threads page, next_offset). next_offset is the
                 offset to pass for the next page, or None when this is the last page.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clears all stored threads.
        """
        pass


class ThreadStoreBuilder:
    """
    Builder class for creating ThreadStore instances based on configuration.
    Mirrors the SessionStoreBuilder pattern.
    """

    _log = logging.getLogger("ak.thread.builder")

    class Types(StrEnum):
        """
        Enumeration of supported thread store types.
        """

        MEMORY = "MEMORY"
        REDIS = "REDIS"
        DYNAMODB = "DYNAMODB"
        COSMOSDB = "COSMOSDB"
        FIRESTORE = "FIRESTORE"

        @classmethod
        def from_str(cls, type_str: str) -> Self:
            """
            Create a Types enum member from a string, falling back to MEMORY.
            :param type_str: The string representation of the thread store type.
            :return: The corresponding Types enum member.
            """
            try:
                return cls[type_str.upper()]
            except KeyError:
                ThreadStoreBuilder._log.warning(f"Invalid thread store type '{type_str}', falling back to MEMORY")
                return ThreadStoreBuilder.Types.MEMORY

    @staticmethod
    def build() -> ThreadStore:
        """
        Build and return a ThreadStore instance based on the configured thread store type.
        :return: A ThreadStore implementation instance.
        :raises ValueError: If thread support is not configured.
        """
        thread_config = AKConfig.get().thread
        if thread_config is None:
            raise ValueError("Thread support is not configured — add a 'thread' block to config.yaml")

        store_type = ThreadStoreBuilder.Types.from_str(thread_config.type)
        ThreadStoreBuilder._log.info(f"Building {store_type} thread store")
        if store_type == ThreadStoreBuilder.Types.REDIS:
            from .redis import RedisThreadStore

            return RedisThreadStore()
        elif store_type == ThreadStoreBuilder.Types.DYNAMODB:
            from .dynamodb import DynamoDBThreadStore

            return DynamoDBThreadStore()
        elif store_type == ThreadStoreBuilder.Types.COSMOSDB:
            from .cosmosdb import CosmosDBThreadStore

            return CosmosDBThreadStore()
        elif store_type == ThreadStoreBuilder.Types.FIRESTORE:
            from .firestore import FirestoreThreadStore

            return FirestoreThreadStore()
        else:
            from .in_memory import InMemoryThreadStore

            return InMemoryThreadStore()
