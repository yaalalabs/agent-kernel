"""
In-memory storage driver for multimodal attachments.

This driver stores attachments in a module-level dictionary, independent of
the session object. Data is isolated per session_id but does not bloat
the session itself. Data is lost on process restart.
"""

import logging
from typing import ClassVar, Optional

from .base import (
    ATTACHMENT_INDEX_KEY,
    AttachmentStorageDriver,
)

_log = logging.getLogger("ak.core.multimodal.storage.in_memory")


class InMemoryStorageDriver(AttachmentStorageDriver):
    """
    In-memory attachment storage, independent of the session.

    Uses a module-level dict keyed by ``{session_id}:{attachment_id}`` so that
    different sessions are isolated without embedding data in the Session object.
    """

    # Shared across all instances — lives for the lifetime of the process
    _store: ClassVar[dict[str, dict]] = {}
    _index: ClassVar[dict[str, list[str]]] = {}  # session_id -> [attachment_ids]

    def __init__(self, session_id: str):
        """
        Initialize the driver for a specific session.
        :param session_id: Session identifier for isolation.
        """
        self._session_id = session_id

    def _key(self, attachment_id: str) -> str:
        return f"{self._session_id}:{attachment_id}"

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        # Save payload
        self._store[self._key(attachment_id)] = attachment

        # Update index
        if self._session_id not in self._index:
            self._index[self._session_id] = []
        self._index[self._session_id].append(attachment_id)

        # Prune old attachments
        ids = self._index[self._session_id]
        if len(ids) > max_attachments:
            old_ids = ids[:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            self._index[self._session_id] = ids[-max_attachments:]

        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        return self._store.get(self._key(attachment_id))

    def delete(self, attachment_id: str) -> None:
        self._store.pop(self._key(attachment_id), None)
