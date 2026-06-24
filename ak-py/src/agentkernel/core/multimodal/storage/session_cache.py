"""
Session non-volatile cache storage driver for multimodal attachments.

This driver stores attachments directly in the session's non-volatile cache.
It is the legacy/simple approach where attachment data lives inside the session object.
"""

import logging
from typing import Optional

from .base import (
    ATTACHMENT_INDEX_KEY,
    ATTACHMENT_KEY_PREFIX,
    AttachmentStore,
)


class SessionNonVolatileCacheAttachmentStore(AttachmentStore):
    """
    Storage driver that uses the Session's non-volatile cache.

    Attachments are stored inside the session object itself. This keeps things
    simple but causes session size to grow with each attachment.
    """

    _log = logging.getLogger("ak.multimodal.storage.session_cache")

    def __init__(self, session_id: str):
        """
        Initialize the driver by resolving the session's non-volatile cache.

        Uses Session.current() to get the active session in the current execution
        context, ensuring writes go to the same Session instance the runtime will
        persist. Falls back to Runtime.load() if no active session context exists.

        :param session_id: The session ID (used as fallback key for load()).
        """
        from ...base import Session

        current = Session.current()
        if current and current.id == session_id:
            session = current
        else:
            from ...runtime import Runtime

            session = Runtime.current().sessions().load(session_id)

        self._cache = session.get_non_volatile_cache()

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        # Save payload
        self._cache.set(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}", attachment)

        # Update index
        index = self._cache.get(ATTACHMENT_INDEX_KEY) or {"ids": []}
        index["ids"].append(attachment_id)

        # Prune old attachments
        if len(index["ids"]) > max_attachments:
            old_ids = index["ids"][:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            index["ids"] = index["ids"][-max_attachments:]

        self._cache.set(ATTACHMENT_INDEX_KEY, index)
        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        return self._cache.get(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")

    def delete(self, attachment_id: str) -> None:
        self._cache.delete(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")
        index = self._cache.get(ATTACHMENT_INDEX_KEY) or {"ids": []}
        ids = index.get("ids", [])
        if attachment_id in ids:
            ids.remove(attachment_id)
            index["ids"] = ids
            self._cache.set(ATTACHMENT_INDEX_KEY, index)
