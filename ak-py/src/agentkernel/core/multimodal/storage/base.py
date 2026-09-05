"""
Base classes for multimodal attachment storage.

This module defines the abstract storage interface and the
AttachmentData dataclass used across all storage backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# Constants
ATTACHMENT_KEY_PREFIX = "attachment:"
ATTACHMENT_INDEX_KEY = "_attachment_index"
DEFAULT_MAX_ATTACHMENTS = 20


@dataclass
class AttachmentData:
    """
    Full attachment data: either the base64 content, or the address of a remote attachment.

    `url` is what separates the two. A remote reference (`http://`, `https://`, `s3://`, or a
    `data:` URI that is not base64) is recorded here so a conversation thread has one uniform
    record per attachment, but its bytes are never fetched — that is the framework adapter's job,
    deliberately, so no system pre-hook makes outbound network calls. Such a record carries an
    empty `data`, and any reader wanting bytes must check `url` first rather than trusting `data`
    to hold base64.
    """

    id: str
    type: str
    data: str  # Base64 encoded
    name: str
    mime_type: str
    description: str
    timestamp: float
    url: Optional[str] = None


class AttachmentStore(ABC):
    """Abstract base class for attachment stores."""

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
