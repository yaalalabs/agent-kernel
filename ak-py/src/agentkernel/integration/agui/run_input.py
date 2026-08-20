"""
Inbound mapping: an AG-UI `RunAgentInput` onto Agent Kernel's own types.

This module is the trust boundary. Everything a client sends arrives here, and three things happen
before any of it reaches an agent:

- **History is discarded.** AK rebuilds conversation history from its session store, so only the
  final `user` message is the turn's input. `design.md`'s "messages is ignored" means the history,
  not the whole list.
- **Unknown shapes are triaged by where they sit.** An unrecognised role or content type in the
  history is ignored; the same thing in the final user message is a 400. Leniency buys forward
  compatibility against a pre-1.0 protocol, but a silent drop of the attachment the user just sent
  would read to them as the agent ignoring it.
- **Client-supplied context never becomes instructions.** `context` and `forwardedProps` are parked
  in the volatile cache for a read-only tool to pull (see `core/client_state.py`), not flattened into
  the prompt.

`tools`, `resume`, system prompts and every non-final message are dropped. No function here writes
`framework_context` — AG-UI state is its own session key.

**The pre-filter exists because leniency is not free.** Three nested discriminated unions —
`Message` on `role`, `InputContent` on `type`, `InputContentSource` on `type` — each reject the whole
request at construction. Keeping only the final user message makes an unknown role or content type in
the history unreachable by construction rather than by walking every part looking for it.
"""

import logging
import mimetypes
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from ...core.base import Session
from ...core.client_state import AGUI_CONTEXT_KEY, AGUI_FORWARDED_PROPS_KEY
from ...core.model import AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText

if TYPE_CHECKING:  # ag_ui ships in the optional `agui` extra, so it is a type-only import here
    from ag_ui.core import InputContent, RunAgentInput, UserMessage

_log = logging.getLogger("ak.integration.agui.run_input")

_KNOWN_CONTENT_TYPES = frozenset({"text", "image", "document", "audio", "video", "binary"})
_KNOWN_SOURCE_TYPES = frozenset({"data", "url"})

# RunAgentInput requires these, but AK either ignores the field or treats it as optional, so an
# absent one is defaulted rather than rejected. Each is (wire name, python name, default).
_OPTIONAL_ON_THE_WIRE: tuple[tuple[str, str, Any], ...] = (
    ("state", "state", None),
    ("tools", "tools", []),
    ("context", "context", []),
    ("forwardedProps", "forwarded_props", None),
)


def parse_run_input(body: dict) -> "RunAgentInput":
    """Validate a raw AG-UI request body and construct its `RunAgentInput`.

    Keeps only the final `user` message, so nothing in the history can fail validation, then
    checks that message's content types by hand — pydantic would reject an unknown one before
    there is any chance to name it in the error.

    :param body: The raw JSON body, as the client sent it (camelCase field names).
    :return: The constructed `ag_ui.core.RunAgentInput`, carrying exactly one message.
    :raises HTTPException: 400 when there is no user message, the message carries no content, or a
                           content type is unrecognised; 422 when the body is malformed in any other way.
    """
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


def _reject_empty_content(user_message: dict) -> None:
    """Reject a user message that carries no content at all.

    An empty list or a blank string maps to zero AK requests, and the agent then runs on nothing
    while the client sees an ordinary `RunStarted` … `RunFinished` — the silent drop this module
    exists to prevent, applied to the whole turn rather than to one attachment.

    Deliberately narrow: parts that are individually empty (a `text` part whose text is "") are a
    content-shape judgement and are left alone. Raised here rather than from `to_requests` so that a
    rejected request has not already had `apply_to_session` write its state onto the session.
    """
    content = user_message.get("content")
    if (isinstance(content, str) and not content.strip()) or (isinstance(content, list) and not content):
        raise HTTPException(status_code=400, detail="The user message carries no content; there is no turn to run")


def _reject_unknown_content_types(user_message: dict) -> None:
    """Reject a content or source type the pinned SDK does not know, naming the value.

    Runs on the raw dict, before construction: the `InputContent` and `InputContentSource` unions
    discriminate on `type`, so an unrecognised value raises a `ValidationError` that says only that
    nothing in the union matched.
    """
    content = user_message.get("content")
    if not isinstance(content, list):
        return  # a plain string, or malformed — pydantic decides

    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type not in _KNOWN_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported content type '{part_type}' in the user message")
        source = part.get("source")
        if isinstance(source, dict) and source.get("type") not in _KNOWN_SOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported content source type '{source.get('type')}' in the user message")


def apply_to_session(session: Session, run_input: "RunAgentInput") -> None:
    """Land the inbound `state`, `forwardedProps` and `context` on the session.

    `state` takes a durable session key because it must survive the run; the other two go in the
    volatile cache, which `Runtime` clears afterwards — AG-UI re-sends both on every request, so a
    previous copy is never wanted.

    :param session: The session the run will execute in.
    :param run_input: The parsed `RunAgentInput`.
    :raises HTTPException: 400 when `state` is present but is not a JSON object.
    """
    if run_input.state is not None:
        if not isinstance(run_input.state, dict):
            raise HTTPException(status_code=400, detail=f"RunAgentInput.state must be a JSON object, got {type(run_input.state).__name__}")
        session.set_agui_state(run_input.state)

    if run_input.forwarded_props is not None:
        if isinstance(run_input.forwarded_props, dict):
            session.get_volatile_cache().set(AGUI_FORWARDED_PROPS_KEY, run_input.forwarded_props)
        else:
            _log.warning(f"Ignoring forwardedProps of type {type(run_input.forwarded_props).__name__}; the read tool returns an object")

    if run_input.context:
        entries = [{"description": entry.description, "value": entry.value} for entry in run_input.context]
        session.get_volatile_cache().set(AGUI_CONTEXT_KEY, entries)


def to_requests(run_input: "RunAgentInput") -> list[AgentRequest]:
    """Convert the final user message into the AK request list for one turn.

    :param run_input: The parsed `RunAgentInput`, carrying exactly the final user message.
    :return: The requests to run the agent with, in the order the client sent their parts.
    :raises HTTPException: 400 for content AK has no request type for (audio, video) or for a
                           `binary` part that references a store AK does not have.
    """
    # parse_run_input is the guarantee: it keeps exactly the final user message and nothing else.
    message = cast("UserMessage", run_input.messages[0])
    content = message.content

    if isinstance(content, str):
        return [AgentRequestText(prompt=content)]

    requests: list[AgentRequest] = []
    for index, part in enumerate(content):
        requests.append(_to_request(part, index))
    return requests


def _to_request(part: "InputContent", index: int) -> AgentRequest:
    """Convert one `InputContent` part into its AK request type.

    Dispatches on the classes rather than on the `type` discriminator so the union narrows: each
    member carries a different payload field, and reading one off the un-narrowed union is exactly
    the mistake a rename upstream would turn into an AttributeError at request time.
    """
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
        # Deprecated in the SDK, still accepted: `data` and `url` are both real payloads, but `id`
        # references a store AK has no access to.
        value = part.data or part.url
        if value is None:
            raise HTTPException(
                status_code=400,
                detail="AG-UI binary content carrying only an 'id' is not supported: the id references a store Agent Kernel cannot read. Send 'data' or 'url' instead",
            )
        return _attachment_request(value, part.mime_type, part.filename or _generated_name(index, part.mime_type, value))

    # Image and document are what remain, and both carry a source.
    source = part.source
    name = _generated_name(index, source.mime_type, source.value)
    if isinstance(part, ImageInputContent):
        return AgentRequestImage(image_data=source.value, name=name, mime_type=source.mime_type)
    return AgentRequestFile(file_data=source.value, name=name, mime_type=source.mime_type)


def _attachment_request(value: str, mime_type: Optional[str], name: str) -> AgentRequest:
    """Route a `binary` part to the image or file request type by its declared mime type."""
    if mime_type and mime_type.lower().startswith("image/"):
        return AgentRequestImage(image_data=value, name=name, mime_type=mime_type)
    return AgentRequestFile(file_data=value, name=name, mime_type=mime_type)


def _generated_name(index: int, mime_type: Optional[str], value: str) -> str:
    """Name an attachment AG-UI did not name.

    `ImageInputContent` and `DocumentInputContent` carry no filename, but `AgentRequestImage` and
    `AgentRequestFile` require one — it is what the multimodal pre-hook shows the model and what an
    attachment is stored under. A URL's own last path segment is the most useful name available;
    everything else gets a positional name with an extension guessed from the mime type.
    """
    if "://" in value:
        candidate = unquote(urlparse(value).path.rsplit("/", 1)[-1]).strip()
        if candidate:
            return candidate
    extension = mimetypes.guess_extension(mime_type) if mime_type else None
    return f"agui-attachment-{index + 1}{extension or ''}"
