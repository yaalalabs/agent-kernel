"""
Attachment storage and management for multimodal memory.

This module provides functions to save and retrieve image/file attachments
in the session's non-volatile cache. Attachments are stored with metadata
and can be retrieved by ID for the 2-step LLM flow.

Storage format in session.get_non_volatile_cache():
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

    Key: "_attachment_index"
    Value: {"ids": [id1, id2, ...]}
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..base import Session

_log = logging.getLogger("ak.core.multimodal.storage")


# Constants
ATTACHMENT_KEY_PREFIX = "attachment:"
ATTACHMENT_INDEX_KEY = "_attachment_index"
DEFAULT_MAX_ATTACHMENTS = 20
DEFAULT_DESCRIPTION_MAX_LENGTH = 200


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
    Save an attachment to the session's non-volatile cache.

    :param session: The session to save to
    :param data: Base64 encoded attachment data
    :param attachment_type: "image" or "file"
    :param name: Filename
    :param mime_type: MIME type of the attachment
    :param description: Optional description (usually added later from LLM response)
    :param max_attachments: Maximum number of attachments to keep
    :return: The generated attachment ID
    """
    if not session:
        raise ValueError("Session is required to save attachment")

    nv_cache = session.get_non_volatile_cache()
    attachment_id = str(uuid.uuid4())[:8]  # Short ID for easier reference
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

    _log.info(f"Saved {attachment_type} attachment: {attachment_id} ({name})")
    return attachment_id


def get_attachment_list(session: "Session") -> list[AttachmentMetadata]:
    """
    Get list of all attachment metadata (without data) for the session.

    :param session: The session to read from
    :return: List of AttachmentMetadata objects
    """
    if not session:
        return []

    nv_cache = session.get_non_volatile_cache()
    index = nv_cache.get(ATTACHMENT_INDEX_KEY)

    if not index or not index.get("ids"):
        return []

    result = []
    for attachment_id in index["ids"]:
        attachment = nv_cache.get(f"{ATTACHMENT_KEY_PREFIX}{attachment_id}")
        if attachment:
            result.append(
                AttachmentMetadata(
                    id=attachment["id"],
                    type=attachment["type"],
                    name=attachment["name"],
                    mime_type=attachment["mime_type"],
                    description=attachment.get("description", ""),
                    timestamp=attachment["timestamp"],
                )
            )

    return result


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
            _log.debug(f"Loaded attachment data: {attachment_id}")
        else:
            _log.warning(f"Attachment not found: {attachment_id}")

    return result


def format_attachment_list_for_prompt(attachments: list[AttachmentMetadata]) -> str:
    """
    Format attachment list as text for LLM prompt.

    :param attachments: List of attachment metadata
    :return: Formatted string for LLM
    """
    if not attachments:
        return ""

    lines = []
    lines.append("=" * 60)
    lines.append("SYSTEM INSTRUCTION: PREVIOUS ATTACHMENTS AVAILABLE")
    lines.append("=" * 60)
    lines.append("")
    lines.append("The following attachments from previous messages are available:")
    lines.append("")

    for att in attachments:
        desc = att.description if att.description else "No description available"
        lines.append(f"  • [{att.id}] {att.type.upper()}: {att.name}")
        lines.append(f"    Description: {desc}")
        lines.append("")

    lines.append("-" * 60)
    lines.append("IMPORTANT: You MUST respond in ONE of these two formats:")
    lines.append("")
    lines.append("FORMAT 1 - If you need to see attachments to answer:")
    lines.append("  NEED_ATTACHMENTS: <comma-separated IDs>")
    lines.append("  Example: NEED_ATTACHMENTS: abc123, def456")
    lines.append("")
    lines.append("FORMAT 2 - If you can answer without attachments:")
    lines.append("  Just provide your answer directly.")
    lines.append("")
    lines.append("DO NOT say 'I need to see the image' - use FORMAT 1 instead.")
    lines.append("=" * 60)
    lines.append("")

    return "\n".join(lines)


def parse_requested_attachment_ids(response: str, available_ids: list[str]) -> Optional[list[str]]:
    """
    Parse LLM response to extract requested attachment IDs.

    :param response: The LLM response text
    :param available_ids: List of valid attachment IDs
    :return: List of requested IDs, or None if no attachments requested
    """
    # Look for pattern: NEED_ATTACHMENTS: id1, id2, id3
    pattern = r"NEED_ATTACHMENTS:\s*([a-zA-Z0-9,\s]+)"
    match = re.search(pattern, response, re.IGNORECASE)

    if not match:
        return None

    # Extract and validate IDs
    ids_str = match.group(1)
    requested_ids = [id.strip() for id in ids_str.split(",") if id.strip()]

    # Filter to only valid IDs
    valid_ids = [id for id in requested_ids if id in available_ids]

    if not valid_ids:
        _log.warning(f"LLM requested IDs not found in available: {requested_ids}")
        return None

    _log.info(f"LLM requested attachments: {valid_ids}")
    return valid_ids


def extract_description_from_response(response: str, max_length: int = DEFAULT_DESCRIPTION_MAX_LENGTH) -> str:
    """
    Extract a short description from LLM response for saving with attachment.

    :param response: The LLM response text
    :param max_length: Maximum length for description
    :return: Extracted description
    """
    if not response:
        return ""

    # Take first sentence or max_length characters
    description = response.strip()

    # Try to get first sentence
    sentence_end = min(
        (description.find(". ") + 1) if ". " in description else len(description),
        (description.find(".\n") + 1) if ".\n" in description else len(description),
        max_length,
    )

    if sentence_end > 0 and sentence_end < len(description):
        description = description[:sentence_end]
    elif len(description) > max_length:
        description = description[:max_length].rsplit(" ", 1)[0] + "..."

    return description
