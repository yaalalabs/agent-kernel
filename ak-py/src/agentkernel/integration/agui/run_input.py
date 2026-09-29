"""Map an AG-UI `RunAgentInput` onto Agent Kernel request and session types."""

import logging
import mimetypes
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from ...core.base import Session
from ...core.model import (
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from .state import AGUIState

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
        """Validate the body and keep only the turn's own user message.

        A resume is a turn without a new prompt, so a body carrying `resume` is accepted with no
        user message at all — the same "prompt **or** resume" rule the REST, WebSocket and thread
        surfaces apply.

        **On a resume the messages are history, and no prompt is derived from them.** AG-UI replays
        the whole conversation on every run and has no way to mark a message as new this turn, so any
        rule for picking one out is a guess. The guess fails in exactly the case that matters: a run
        that pauses emits no assistant reply — the pause *is* its outcome — so the conversation still
        ends with the prompt that caused the pause, and re-sending it lands a prompt beside a decision
        that OpenAI and ADK reject outright.

        This is a limit of the protocol, not a rule Agent Kernel is imposing. A client that needs to
        send a prompt together with a decision can do it on the REST surface, where `prompt` and
        `resume` are separate fields and the adapter decides whether its framework can take both.
        """
        from ag_ui.core import RunAgentInput
        from pydantic import ValidationError

        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="RunAgentInput.messages must be a list")

        resuming = bool(body.get("resume"))
        if resuming:
            user_message = None
        else:
            user_message = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"), None)
            if user_message is None:
                raise HTTPException(status_code=400, detail="RunAgentInput.messages carries no user message; there is no turn to run")

        if user_message is not None:
            AGUIRunInput._reject_empty_content(user_message)
            AGUIRunInput._reject_unknown_content_types(user_message)

        filtered = {**body, "messages": [user_message] if user_message is not None else []}
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
            AGUIState.write_state(session, run_input.state)

        if run_input.forwarded_props is not None:
            if isinstance(run_input.forwarded_props, dict):
                AGUIState.write_forwarded_props(session, run_input.forwarded_props)
            else:
                _log.warning(f"Ignoring forwardedProps of type {type(run_input.forwarded_props).__name__}; the read tool returns an object")

        if run_input.context:
            entries = [{"description": entry.description, "value": entry.value} for entry in run_input.context]
            AGUIState.write_context(session, entries)

    @staticmethod
    def to_requests(run_input: "RunAgentInput") -> list[AgentRequest]:
        """Convert the turn's user message, then any decisions, into AK requests.

        The resume request goes last so a prompt the client appended stays first, matching the order
        `RequestBuilder` builds for every other surface.
        """
        requests: list[AgentRequest] = []
        if run_input.messages:
            requests.extend(AGUIRunInput._message_requests(run_input))

        resume = AGUIRunInput.to_resume(run_input)
        if resume is not None:
            requests.append(resume)
        return requests

    @staticmethod
    def to_resume(run_input: "RunAgentInput") -> Optional[AgentResumeRequestAny]:
        """Map `RunAgentInput.resume` onto one resume request, or None when the body carries none.

        **No `run_id` is set, because the protocol has no field for one.** The run is resolved from
        the interruption ids, which is exactly why `AgentResumeRequestAny.run_id` is optional and why
        `PausedInterruption.id` must be unique across a session's records.

        :param run_input: The parsed RunAgentInput.
        :return: The decisions as one AK resume request, or None.
        """
        entries = getattr(run_input, "resume", None)
        if not entries:
            return None
        return AgentResumeRequestAny(decisions=[AGUIRunInput._to_decision(entry) for entry in entries])

    @staticmethod
    def _to_decision(entry: Any) -> ResumeDecision:
        """Map one `ResumeEntry` onto a decision, without flattening its status.

        The protocol carries two statuses where Agent Kernel carries three: `cancelled` passes through
        unchanged, and `resolved` becomes `denied` on an explicit `False` and `approved` otherwise,
        since a human who supplied an answer approved rather than withheld one.

        **A refusal carries no wording over this surface.** AG-UI has no field for one, and Agent
        Kernel does not reserve keys inside `payload` to smuggle it: the SDK states that `payload` is
        "the answer the agent asked for and will act on", so squatting there would both contradict the
        protocol and swallow an answer that happened to use the same key. `denied` still reaches the
        model as a refusal distinct from `cancelled`, which is the distinction that matters. A client
        that needs the human's words uses the REST surface, where `message` is a field of its own.

        :param entry: One ResumeEntry from the protocol.
        :return: The AK decision.
        """
        payload = entry.payload
        if entry.status == "cancelled":
            status = "cancelled"
        elif payload is False:
            status = "denied"
        else:
            status = "approved"

        return ResumeDecision(id=entry.interrupt_id, status=status, payload=None if isinstance(payload, bool) else payload)

    @staticmethod
    def _message_requests(run_input: "RunAgentInput") -> list[AgentRequest]:
        """Convert the turn's user message into AK requests."""
        message = cast("UserMessage", run_input.messages[0])
        content = message.content

        if isinstance(content, str):
            return [AgentRequestText(prompt=content)]

        requests: list[AgentRequest] = []
        for index, part in enumerate(content):
            requests.append(AGUIRunInput._to_request(part, index))
        return requests

    @staticmethod
    def _reject_empty_content(user_message: dict) -> None:
        """Raise 400 if the user message has no content."""
        content = user_message.get("content")
        if (isinstance(content, str) and not content.strip()) or (isinstance(content, list) and not content):
            raise HTTPException(status_code=400, detail="The user message carries no content; there is no turn to run")

    @staticmethod
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

    @staticmethod
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
            return AGUIRunInput._attachment_request(
                value, part.mime_type, part.filename or AGUIRunInput._generated_name(index, part.mime_type, value)
            )

        source = part.source
        name = AGUIRunInput._generated_name(index, source.mime_type, source.value)
        if isinstance(part, ImageInputContent):
            return AgentRequestImage(image_data=source.value, name=name, mime_type=source.mime_type)
        return AgentRequestFile(file_data=source.value, name=name, mime_type=source.mime_type)

    @staticmethod
    def _attachment_request(value: str, mime_type: Optional[str], name: str) -> AgentRequest:
        """Route a binary part to an image or file request by mime type."""
        if mime_type and mime_type.lower().startswith("image/"):
            return AgentRequestImage(image_data=value, name=name, mime_type=mime_type)
        return AgentRequestFile(file_data=value, name=name, mime_type=mime_type)

    @staticmethod
    def _generated_name(index: int, mime_type: Optional[str], value: str) -> str:
        """Invent a filename when AG-UI did not send one."""
        if "://" in value:
            candidate = unquote(urlparse(value).path.rsplit("/", 1)[-1]).strip()
            if candidate:
                return candidate
        extension = mimetypes.guess_extension(mime_type) if mime_type else None
        return f"agui-attachment-{index + 1}{extension or ''}"
