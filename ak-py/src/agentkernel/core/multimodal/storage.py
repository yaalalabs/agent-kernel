"""
Attachment storage for multimodal memory.

This module provides functions to save and retrieve image/file attachments.
It uses a pluggable StorageDriver pattern, currently defaulting to session-based
Non-Volatile Cache storage, but extensible for other backends.

Storage format:
    Key: "attachment:{id}"
    Value: {
        "id": str,
        "type": "image" | "file",
        "data": str (base64),
        "name": str,
        "mime_type": str,
        "description": str,
        "timestamp": float
    }
"""

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..base import Session
    from ..util.key_value_cache import KeyValueCache

_log = logging.getLogger("ak.core.multimodal.storage")

# Constants
ATTACHMENT_KEY_PREFIX = "attachment:"
ATTACHMENT_INDEX_KEY = "_attachment_index"
DEFAULT_MAX_ATTACHMENTS = 20


@dataclass
class AttachmentData:
    """Full attachment data including the base64 encoded content."""

    id: str
    type: str
    data: str  # Base64 encoded
    name: str
    mime_type: str
    description: str
    timestamp: float


class AttachmentStorageDriver(ABC):
    """Abstract base class for attachment storage drivers."""

    @abstractmethod
    def save(self, attachment: dict, max_attachments: int) -> str:
        """
        Save attachment and return ID.
        :param attachment: Attachment data dictionary
        :param max_attachments: Max attachments policy
        :return: Attachment ID
        """
        pass

    @abstractmethod
    def get(self, attachment_id: str) -> Optional[dict]:
        """
        Retrieve full attachment data by ID.
        :param attachment_id: Attachment ID
        :return: Attachment data dict or None
        """
        pass

    @abstractmethod
    def delete(self, attachment_id: str) -> None:
        """
        Delete attachment by ID.
        :param attachment_id: Attachment ID
        """
        pass


class CacheStorageDriver(AttachmentStorageDriver):
    """Storage driver that uses the Session's non-volatile cache."""

    def __init__(self, cache: "KeyValueCache"):
        self.cache = cache

    def save(self, attachment: dict, max_attachments: int) -> str:
        attachment_id = attachment["id"]

        # Save payload
        self.cache.set(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}", attachment)

        # Update index
        index = self.cache.get(ATTACHMENT_INDEX_KEY) or {"ids": []}
        index["ids"].append(attachment_id)

        # Prune old attachments
        if len(index["ids"]) > max_attachments:
            old_ids = index["ids"][:-max_attachments]
            for old_id in old_ids:
                self.delete(old_id)
            index["ids"] = index["ids"][-max_attachments:]

        self.cache.set(ATTACHMENT_INDEX_KEY, index)
        return attachment_id

    def get(self, attachment_id: str) -> Optional[dict]:
        return self.cache.get(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")

    def delete(self, attachment_id: str) -> None:
        self.cache.delete(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")


def get_storage_driver(session: Optional["Session"] = None, cache: Optional["KeyValueCache"] = None) -> AttachmentStorageDriver:
    """
    Factory to get the configured storage driver.

    :param session: Session object (preferred)
    :param cache: KeyValueCache (alternative if session not available, e.g. in tools)
    """
    if session:
        return CacheStorageDriver(session.get_non_volatile_cache())
    if cache:
        return CacheStorageDriver(cache)

    # Attempt to resolve from context if neither provided?
    # For now, require at least one.
    raise ValueError("Either 'session' or 'cache' is required for storage driver")


def save_attachment(
    session: Optional["Session"],
    data: str,
    attachment_type: str,
    name: str,
    mime_type: str,
    description: str = "",
    max_attachments: int = DEFAULT_MAX_ATTACHMENTS,
    cache: Optional["KeyValueCache"] = None,
) -> str:
    """
    Save an attachment using the configured storage driver.

    :param session: The session to save to
    :param data: Base64 encoded attachment data
    :param attachment_type: "image" or "file"
    :param name: Filename
    :param mime_type: MIME type of the attachment
    :param description: Optional description from LLM
    :param max_attachments: Maximum number of attachments to keep
    :param cache: Optional direct cache to use if session is None
    :return: The generated attachment ID
    """
    driver = get_storage_driver(session=session, cache=cache)
    # Generate ID: if session exists, prefix it (e.g., "sess123_abc12345")
    # This allows tools to recover the session ID just from the attachment ID.
    unique_part = str(uuid.uuid4())[:8]
    if session:
        attachment_id = f"{session.id}_{unique_part}"
    else:
        attachment_id = unique_part
    timestamp = time.time()

    # Save attachment data
    attachment = {
        "id": attachment_id,
        "type": attachment_type,
        "data": data,
        "name": name,
        "mime_type": mime_type,
        "description": description,
        "timestamp": timestamp,
    }

    driver.save(attachment, max_attachments)
    _log.info(f"Saved {attachment_type}: {attachment_id} ({name})")
    return attachment_id


def get_attachment_data(
    session: Optional["Session"],
    attachment_ids: list[str],
    cache: Optional["KeyValueCache"] = None,
) -> list[AttachmentData]:
    """
    Load actual attachment data for specific IDs using the storage driver.

    :param session: The session to read from
    :param attachment_ids: List of attachment IDs to load
    :param cache: Optional direct cache to use if session is None
    :return: List of AttachmentData objects
    """
    if not attachment_ids:
        return []

    # Use 'or' to check if either is present to proceed
    if not session and not cache:
        return []

    driver = get_storage_driver(session=session, cache=cache)
    result = []

    for attachment_id in attachment_ids:
        attachment = driver.get(attachment_id)
        if attachment:
            result.append(
                AttachmentData(
                    id=attachment["id"],
                    type=attachment["type"],
                    data=attachment["data"],
                    name=attachment["name"],
                    mime_type=attachment["mime_type"],
                    description=attachment.get("description", ""),
                    timestamp=attachment["timestamp"],
                )
            )
            _log.debug(f"Loaded attachment: {attachment_id}")
        else:
            _log.warning(f"Attachment not found: {attachment_id}")

    return result
