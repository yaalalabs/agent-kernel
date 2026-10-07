"""Map an AG-UI `RunAgentInput` onto Agent Kernel request and session types."""

import logging
import mimetypes
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
from pydantic import BaseModel

from ...core.base import Session
from ...core.model import AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText, BaseRunRequest
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
        """Validate the body and keep only the final user message."""
        from ag_ui.core import RunAgentInput
        from pydantic import ValidationError

        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="RunAgentInput.messages must be a list")

        user_message = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "user"), None)
        if user_message is None:
            raise HTTPException(status_code=400, detail="RunAgentInput.messages carries no user message; there is no turn to run")

        AGUIRunInput._reject_empty_content(user_message)
        AGUIRunInput._reject_unknown_content_types(user_message)

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
        """Write inbound state, forwardedProps, and context onto the session.

        The direct path's one-liner: validate at the edge, then apply to the session that is
        about to run. The queue path calls the two halves separately, because
        a queue hop sits between them.
        """
        AGUIRunEnvelope.apply(session, AGUIRunEnvelope.build(run_input))

    @staticmethod
    def to_requests(run_input: "RunAgentInput") -> list[AgentRequest]:
        """Convert the final user message into AK requests."""
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


class AGUIRunEnvelope(BaseModel):
    """The client's per-run AG-UI values, carried on the queue body rather than the session.

    The session cannot carry them. ``forwardedProps`` and ``context`` live in the **volatile**
    cache by design (see :class:`~agentkernel.integration.agui.state.AGUIState`) because Runtime
    clears it after every run, and every session store persists only ``get_all(volatile=False)`` —
    so a session hop drops two of the three silently. ``state`` fares no better under a configured
    ``session.cache``, where the runner's ``load`` returns its own process-local copy. So all three
    travel on the body, and the runner is the only process that touches a session (spec #710 §5).

    Split in two deliberately: ``build`` runs at the edge, where an HTTP status still exists and a
    bad value can be a 400; ``apply`` runs wherever the agent does. The direct handler calls both
    back to back, so the two execution models cannot drift on which cache a field belongs in.
    """

    # These three fields only, not the queue body: the client's message text rides on `requests`
    # unmeasured, so a large enough turn still exceeds the smallest transport (SQS, 256 KB). That
    # gap is pipeline-wide — no producer measures its body — and belongs at RequestProducer.enqueue.
    # This bounds the part AG-UI adds, which a client can grow turn after turn because `state`
    # round-trips back on every run.
    BUDGET_BYTES: ClassVar[int] = 65536

    state: Optional[dict] = None
    forwarded_props: Optional[dict] = None
    context: Optional[list[dict]] = None

    @staticmethod
    def build(run_input: "RunAgentInput") -> "AGUIRunEnvelope":
        """Validate the inbound values and collect them for the queue hop.

        :param run_input: The parsed RunAgentInput.
        :return: The envelope to put on the body.
        :raises HTTPException: 400 when `state` is not an object.
        """
        state = None
        if run_input.state is not None:
            if not isinstance(run_input.state, dict):
                raise HTTPException(status_code=400, detail=f"RunAgentInput.state must be a JSON object, got {type(run_input.state).__name__}")
            state = run_input.state

        forwarded_props = None
        if run_input.forwarded_props is not None:
            if isinstance(run_input.forwarded_props, dict):
                forwarded_props = run_input.forwarded_props
            else:
                _log.warning(f"Ignoring forwardedProps of type {type(run_input.forwarded_props).__name__}; the read tool returns an object")

        context = None
        if run_input.context:
            context = [{"description": entry.description, "value": entry.value} for entry in run_input.context]

        return AGUIRunEnvelope(state=state, forwarded_props=forwarded_props, context=context)

    def reject_if_oversized(self) -> None:
        """Fail at the edge rather than as a transport-specific send error after enqueue.

        Called by the handler that enqueues the envelope, not by ``build``: the direct handler
        builds one too and puts it on nothing, so charging it a transport budget there would
        reject a request that works today.

        :raises HTTPException: 400 when the three fields together exceed ``BUDGET_BYTES``.
        """
        size = len(self.model_dump_json(exclude_none=True).encode())
        if size > self.BUDGET_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"AG-UI state, forwardedProps and context total {size} bytes, over the {self.BUDGET_BYTES}-byte budget for one run",
            )

    @staticmethod
    def apply(session: Session, envelope: Optional["AGUIRunEnvelope"]) -> None:
        """Write the envelope onto a session, in the caches AG-UI chose for each field.

        Goes through the AGUIState accessors rather than touching a cache directly: they are the
        single place that knows a field's lifetime, and `forwardedProps`/`context` must never
        become non-volatile or they would leak into the next turn.

        :param session: The session the run is about to use.
        :param envelope: The values from the body, or None when the client sent none.
        """
        if envelope is None:
            return
        if envelope.state is not None:
            AGUIState.write_state(session, envelope.state)
        if envelope.forwarded_props is not None:
            AGUIState.write_forwarded_props(session, envelope.forwarded_props)
        if envelope.context:
            AGUIState.write_context(session, envelope.context)


class AGUIRunRequest(BaseRunRequest):
    """A chat request carrying the AG-UI envelope across the queue.

    `agui` is a typed field rather than an extra for the reason BaseRunRequest already gives for
    `requests` and the scheduling fields: an extra would reach the agent as AgentRequestAny
    context. It lives here rather than on BaseRunRequest so core grows no field for an optional
    extra; RequestProducer takes a BaseRunRequest, so a subclass needs no producer change.
    """

    # AG-UI maps the client's user message straight onto `requests`, so there is no prompt string
    # to carry. Defaulted here rather than relaxed on BaseChatRequest, which every other surface
    # still requires one from; the runner reads `requests`, never this.
    prompt: str = ""

    agui: Optional[AGUIRunEnvelope] = None
