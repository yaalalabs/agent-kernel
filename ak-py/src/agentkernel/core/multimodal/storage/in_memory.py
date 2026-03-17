import logging
from typing import ClassVar, Optional

from .base import AttachmentStore


class InMemoryAttachmentStore(AttachmentStore):
    """
    InMemoryAttachmentStore class provides an in-memory implementation of the AttachmentStore interface.

    Storage is shared across all instances via ClassVar so that attachments
    persist for the lifetime of the process, independent of how many times
    a new instance is created per request.
    """

    # Shared across all instances — survives across multiple instantiations per request
    _attachments: ClassVar[dict[str, dict]] = {}  # "session_id:attachment_id" -> attachment
    _index: ClassVar[dict[str, list[str]]] = {}  # session_id -> [attachment_ids]
    _log = logging.getLogger("ak.core.multimodal.storage.inmemory")

    def __init__(self, session_id: str):
        """
        Initializes an InMemoryAttachmentStore instance.
        :param session_id: Session identifier for isolation.
        """
        self._session_id = session_id

    def _key(self, attachment_id: str) -> str:
        return f"{self._session_id}:{attachment_id}"

    def save(self, attachment: dict, max_attachments: int) -> str:
        """
        Saves an attachment and prunes old ones if the limit is exceeded.
        :param attachment: Attachment data dictionary.
        :param max_attachments: Maximum number of attachments to keep.
        :return: The attachment ID.
        """
        attachment_id = attachment["id"]
        self._attachments[self._key(attachment_id)] = attachment

        if self._session_id not in self._index:
            self._index[self._session_id] = []
        self._index[self._session_id].append(attachment_id)

        ids = self._index[self._session_id]
        if len(ids) > max_attachments:
            old_ids = ids[:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            self._index[self._session_id] = ids[-max_attachments:]

        self._log.debug(f"Saved attachment: {attachment_id}")
        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        """
        Retrieves an attachment by its ID.
        :param attachment_id: Attachment ID.
        :return: Attachment data dict or None if not found.
        """
        return self._attachments.get(self._key(attachment_id))

    def delete(self, attachment_id: str) -> None:
        """
        Deletes an attachment by its ID.
        :param attachment_id: Attachment ID.
        """
        self._attachments.pop(self._key(attachment_id), None)
        if self._session_id in self._index and attachment_id in self._index[self._session_id]:
            self._index[self._session_id].remove(attachment_id)
        self._log.debug(f"Deleted attachment: {attachment_id}")

    def clear(self) -> None:
        """
        Clears all stored attachments for this session.
        """
        self._log.debug(f"Clearing all attachments for session {self._session_id}")
        ids = self._index.pop(self._session_id, [])
        for attachment_id in ids:
            self._attachments.pop(self._key(attachment_id), None)
