"""
Attachment storage for multimodal memory.

This module provides functions to save and retrieve image/file attachments.
Currently uses session's non-volatile cache, but designed to be extended
for DynamoDB/Redis backends via config.

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
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..base import Session

_log = logging.getLogger("ak.core.multimodal.storage")


# Constants
ATTACHMENT_KEY_PREFIX = "attachment:"
ATTACHMENT_INDEX_KEY = "_attachment_index"
DEFAULT_MAX_ATTACHMENTS = 20


@dataclass
class AttachmentMetadata:
    """Metadata for an attachment (without the actual data)."""

    id: str
    type: str  # "image" or "file"
    name: str
    mime_type: str
    description: str
    timestamp: float


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


def save_attachment(
    session: "Session",
    data: str,
    attachment_type: str,
    name: str,
    mime_type: str,
    description: str = "",
    max_attachments: int = DEFAULT_MAX_ATTACHMENTS,
) -> str:
    """
    Save an attachment to storage.

    :param session: The session to save to
    :param data: Base64 encoded attachment data
    :param attachment_type: "image" or "file"
    :param name: Filename
    :param mime_type: MIME type of the attachment
    :param description: Optional description from LLM
    :param max_attachments: Maximum number of attachments to keep
    :return: The generated attachment ID
    """
    if not session:
        raise ValueError("Session is required to save attachment")

    nv_cache = session.get_non_volatile_cache()
    attachment_id = str(uuid.uuid4())[:8]  
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
    nv_cache.set(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}", attachment)

    # Update index
    index = nv_cache.get(ATTACHMENT_INDEX_KEY) or {"ids": []}
    index["ids"].append(attachment_id)

    # Keep only recent attachments
    if len(index["ids"]) > max_attachments:
        old_ids = index["ids"][:-max_attachments]
        for old_id in old_ids:
            nv_cache.delete(f"{ATTACHMENT_KEY_PREFIX}{old_id}")
        index["ids"] = index["ids"][-max_attachments:]

    nv_cache.set(ATTACHMENT_INDEX_KEY, index)

    _log.info(f"Saved {attachment_type}: {attachment_id} ({name})")
    return attachment_id


def get_attachment_data(session: "Session", attachment_ids: list[str]) -> list[AttachmentData]:
    """
    Load actual attachment data for specific IDs.

    :param session: The session to read from
    :param attachment_ids: List of attachment IDs to load
    :return: List of AttachmentData objects
    """
    if not session or not attachment_ids:
        return []

    nv_cache = session.get_non_volatile_cache()
    result = []

    for attachment_id in attachment_ids:
        attachment = nv_cache.get(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")
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
