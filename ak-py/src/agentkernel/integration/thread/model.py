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


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class ThreadAttachment(BaseModel):
    """Reference to an attachment stored in the multimodal AttachmentStore."""

    attachment_id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None


class ThreadMessage(BaseModel):
    """A single message within a thread.

    ``content`` is text for every reply the agent did not label. When ``media_type`` is set it is
    the payload object instead — the same shape #706 gives ``result`` on the REST surface, so a
    client renders replayed history with the code it already renders a live reply with. The object
    branch is a ``JSONPayload``, so it runs the same normalisation ``AgentReplyAny.content`` runs
    and a value with no JSON form raises here rather than inside a store's ``model_dump_json``.

    The two fields are one decision, enforced rather than documented: an object with no label, or a
    label over text, would reach a client as a payload it cannot branch on. ``media_type`` is
    declared between ``content`` and ``timestamp`` because field order is key order in
    ``model_dump_json``, and both recording paths must produce the same bytes for the same reply.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str | JSONPayload
    media_type: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_and_payload_agree(self) -> "ThreadMessage":
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
        reads history and a live reply with one branch.

        The exclusion names the field rather than using ``exclude_none``, which recurses — it would
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
