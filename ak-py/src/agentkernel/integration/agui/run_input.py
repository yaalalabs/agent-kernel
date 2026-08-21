"""Map an AG-UI `RunAgentInput` onto Agent Kernel request and session types."""

import logging
import mimetypes
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from ...core.base import Session
from .state import AGUI_CONTEXT_KEY, AGUI_FORWARDED_PROPS_KEY, AGUI_STATE_KEY
from ...core.model import AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText

if TYPE_CHECKING:
    from ag_ui.core import InputContent, RunAgentInput, UserMessage

_log = logging.getLogger("ak.integration.agui.run_input")

_KNOWN_CONTENT_TYPES = frozenset({"text", "image", "document", "audio", "video", "binary"})
_KNOWN_SOURCE_TYPES = frozenset({"data", "url"})

_OPTIONAL_ON_THE_WIRE: tuple[tuple[str, str, Any], ...] = (
    ("state", "state", None),
    ("tools", "tools", []),
    ("context", "context", []),
    ("forwardedProps", "forwarded_props", None),
)


class AGUIRunInput:
    """Parse a RunAgentInput, convert the live turn, and land client fields on the session."""

    @staticmethod
    def parse(body: dict) -> "RunAgentInput":
        """Validate the body and keep only the final user message."""
        from ag_ui.core import RunAgentInput
        from pydantic import ValidationError

        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="RunAgentInput.messages must be a list")

        user_message = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"), None)
        if user_message is None:
            raise HTTPException(status_code=400, detail="RunAgentInput.messages carries no user message; there is no turn to run")

        _reject_empty_content(user_message)
        _reject_unknown_content_types(user_message)

        filtered = {**body, "messages": [user_message]}
        for wire_name, python_name, default in _OPTIONAL_ON_THE_WIRE:
            if wire_name not in filtered and python_name not in filtered:
                filtered[wire_name] = default

        try:
            return RunAgentInput.model_validate(filtered)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=f"Malformed RunAgentInput: {e.errors()}")

    @staticmethod
    def set_agui_session_keys(session: Session, run_input: "RunAgentInput") -> None:
        """Write inbound state, forwardedProps, and context onto the session."""
        if run_input.state is not None:
            if not isinstance(run_input.state, dict):
                raise HTTPException(status_code=400, detail=f"RunAgentInput.state must be a JSON object, got {type(run_input.state).__name__}")
            session.get_non_volatile_cache().set(AGUI_STATE_KEY, run_input.state)

        if run_input.forwarded_props is not None:
            if isinstance(run_input.forwarded_props, dict):
                session.get_volatile_cache().set(AGUI_FORWARDED_PROPS_KEY, run_input.forwarded_props)
            else:
                _log.warning(f"Ignoring forwardedProps of type {type(run_input.forwarded_props).__name__}; the read tool returns an object")

        if run_input.context:
            entries = [{"description": entry.description, "value": entry.value} for entry in run_input.context]
            session.get_volatile_cache().set(AGUI_CONTEXT_KEY, entries)

    @staticmethod
    def to_requests(run_input: "RunAgentInput") -> list[AgentRequest]:
        """Convert the final user message into AK requests."""
        message = cast("UserMessage", run_input.messages[0])
        content = message.content

        if isinstance(content, str):
            return [AgentRequestText(prompt=content)]

        requests: list[AgentRequest] = []
        for index, part in enumerate(content):
            requests.append(_to_request(part, index))
        return requests


def _reject_empty_content(user_message: dict) -> None:
    """Raise 400 if the user message has no content."""
    content = user_message.get("content")
    if (isinstance(content, str) and not content.strip()) or (isinstance(content, list) and not content):
        raise HTTPException(status_code=400, detail="The user message carries no content; there is no turn to run")


def _reject_unknown_content_types(user_message: dict) -> None:
    """Raise 400 for content or source types the SDK does not know."""
    content = user_message.get("content")
    if not isinstance(content, list):
        return

    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type not in _KNOWN_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported content type '{part_type}' in the user message")
        source = part.get("source")
        if isinstance(source, dict) and source.get("type") not in _KNOWN_SOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported content source type '{source.get('type')}' in the user message")


def _to_request(part: "InputContent", index: int) -> AgentRequest:
    """Convert one InputContent part into an AK request."""
    from ag_ui.core import AudioInputContent, BinaryInputContent, ImageInputContent, TextInputContent, VideoInputContent

    if isinstance(part, TextInputContent):
        return AgentRequestText(prompt=part.text)

    if isinstance(part, (AudioInputContent, VideoInputContent)):
        raise HTTPException(
            status_code=400,
            detail=f"AG-UI {part.type} content is not supported: Agent Kernel has no {part.type} request type, "
            f"and mapping it onto the generic file type produces misleading model output",
        )

    if isinstance(part, BinaryInputContent):
        value = part.data or part.url
        if value is None:
            raise HTTPException(
                status_code=400,
                detail="AG-UI binary content carrying only an 'id' is not supported: the id references a store Agent Kernel cannot read. Send 'data' or 'url' instead",
            )
        return _attachment_request(value, part.mime_type, part.filename or _generated_name(index, part.mime_type, value))

    source = part.source
    name = _generated_name(index, source.mime_type, source.value)
    if isinstance(part, ImageInputContent):
        return AgentRequestImage(image_data=source.value, name=name, mime_type=source.mime_type)
    return AgentRequestFile(file_data=source.value, name=name, mime_type=source.mime_type)


def _attachment_request(value: str, mime_type: Optional[str], name: str) -> AgentRequest:
    """Route a binary part to an image or file request by mime type."""
    if mime_type and mime_type.lower().startswith("image/"):
        return AgentRequestImage(image_data=value, name=name, mime_type=mime_type)
    return AgentRequestFile(file_data=value, name=name, mime_type=mime_type)


def _generated_name(index: int, mime_type: Optional[str], value: str) -> str:
    """Invent a filename when AG-UI did not send one."""
    if "://" in value:
        candidate = unquote(urlparse(value).path.rsplit("/", 1)[-1]).strip()
        if candidate:
            return candidate
    extension = mimetypes.guess_extension(mime_type) if mime_type else None
    return f"agui-attachment-{index + 1}{extension or ''}"
