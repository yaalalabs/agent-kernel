"""
Pydantic models for Conversation Thread Support.

A thread is identified by its session_id — there is no separate thread id.
Attachment bytes are never stored on these models; ThreadAttachment holds only
a reference (attachment_id) into the existing multimodal AttachmentStore.
"""

import datetime
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ThreadAttachment(BaseModel):
    """Reference to an attachment stored in the multimodal AttachmentStore."""

    attachment_id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None


class ThreadMessage(BaseModel):
    """A single message within a thread."""

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)


class Thread(BaseModel):
    """A named, persistent conversation context keyed by session_id.

    Messages are stored and retrieved separately (paginated) rather than being
    embedded here, so this model carries thread metadata. ``messages`` holds a
    page of messages only when one has been explicitly attached for a response.
    """

    session_id: str
    user_id: str
    group_id: Optional[str] = None
    name: str = ""
    created_at: datetime.datetime = Field(default_factory=_utc_now)
    updated_at: datetime.datetime = Field(default_factory=_utc_now)
    messages: List[ThreadMessage] = Field(default_factory=list)


class MessagePage(BaseModel):
    """A page of thread messages with an opaque cursor to the next page."""

    messages: List[ThreadMessage] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class ThreadPage(BaseModel):
    """A page of thread metadata with an opaque cursor to the next page."""

    threads: List[Thread] = Field(default_factory=list)
    next_cursor: Optional[str] = None
