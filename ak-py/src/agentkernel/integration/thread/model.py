"""
Pydantic models for Conversation Thread Support.

A thread is identified by its session_id — there is no separate thread id.
Attachment bytes are never stored on these models; ThreadAttachment holds only
a reference (attachment_id) into the existing multimodal AttachmentStore.
"""

import datetime
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ...core.util.payload import JSONPayload

HITL_MEDIA_TYPE = "application/json"
"""The label on a pause or a decision message: an object, not text.

Deliberately not a vendor type. `application/a2ui+json` names an external standard; Agent Kernel
owns none for pause/resume, and a `role` of `assistant` carrying `interruptions` or `user` carrying
`decisions` already says which kind a message is. One constant because three writers set it.
"""


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ThreadAttachment(BaseModel):
    """Reference to an attachment stored in the multimodal AttachmentStore."""

    attachment_id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None


class ThreadMessage(BaseModel):
    """A single message within a thread.

    ``content`` is text for an ordinary turn and a payload object for one carrying structured data,
    with ``media_type`` naming the format. The object branch is a ``JSONPayload``, so it runs the
    same normalisation ``AgentReplyAny.content`` runs and a value with no JSON form raises here,
    naming its key path, rather than inside a store's ``model_dump_json``.

    The two fields are one decision, enforced rather than documented: an object with no label, or a
    label over text, would reach a client as a payload it cannot branch on. ``media_type`` is
    declared between ``content`` and ``timestamp`` because field order is key order in
    ``model_dump_json``, and every recording path must produce the same bytes for the same message.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str | JSONPayload
    media_type: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_and_payload_agree(self) -> "ThreadMessage":
        """
        Reject the two shapes a client could not branch on.

        :return: This message, unchanged.
        :raises ValueError: If the label and the content disagree about which one this is.
        """
        if self.media_type and isinstance(self.content, str):
            raise ValueError("media_type is set but content is text; a labelled message carries its payload as an object")
        if not self.media_type and not isinstance(self.content, str):
            raise ValueError("content is an object but media_type is unset; an unlabelled message carries text")
        return self

    def to_wire(self) -> dict:
        """
        Render the message as the thread read routes return it.

        ``media_type`` is omitted rather than sent as ``null`` when unset, matching the live reply:
        ``ResponseBuilder.build_response`` adds the key only for a labelled payload, so a client
        reads history and a live reply with one branch — and a message written before the field
        existed reads back exactly as it did.

        The exclusion names the field rather than using ``exclude_none``, which recurses: that would
        also drop an attachment's unset ``name`` and ``mime_type``, changing a shape this owes
        nothing to.

        :return: The message as a JSON-safe dict.
        """
        return self.model_dump(mode="json", exclude={"media_type"} if self.media_type is None else None)


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
    # True once the name was explicitly supplied (thread_name at creation or a
    # rename) — automatic naming strategies must never overwrite it.
    name_locked: bool = False
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
