"""
Pydantic models for Conversation Thread Support.

A thread is identified by its session_id — there is no separate thread id.
Attachment bytes are never stored on these models; ThreadAttachment holds only
a reference (attachment_id) into the existing multimodal AttachmentStore.
"""

import datetime
import uuid
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

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
    label over text, would reach a client as a payload it cannot branch on. A blank label counts as
    no label, which is what ``build_response`` and ``ThreadRecorder`` already mean by it.
    ``media_type`` is declared between ``content`` and ``timestamp`` because field order is key
    order in ``model_dump_json``, and both recording paths must produce the same bytes for the
    same reply.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: Union[str, JSONPayload]
    media_type: Optional[str] = None
    timestamp: datetime.datetime = Field(default_factory=_utc_now)
    attachments: List[ThreadAttachment] = Field(default_factory=list)

    @field_validator("media_type", mode="before")
    @classmethod
    def _blank_label_is_no_label(cls, value: Any) -> Any:
        """Normalise a blank label to ``None`` before the pairing validator reads it.

        Every other layer tests the label for truthiness — ``ResponseBuilder.build_response`` and
        ``ThreadRecorder._as_thread_message`` both treat ``""`` as unlabelled — so a blank reaching
        the wire as a present ``media_type`` key would be this model alone disagreeing. Running
        ``mode="before"`` means an object carrying a blank label raises the pairing validator's
        existing "media_type is unset" rather than needing a message of its own.

        :param value: The label as supplied by the caller or a stored row.
        :return: The stripped label, or None when it was blank; any non-string unchanged, so
            pydantic still reports the type error.
        """
        if isinstance(value, str):
            return value.strip() or None
        return value

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
        if self.media_type is None:
            return self.model_dump(mode="json", exclude={"media_type"})
        return self.model_dump(mode="json")


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
