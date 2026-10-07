import json
import uuid
from enum import Enum
from typing import Annotated, Any, Callable, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .event import PausedInterruption, StreamEvent


class AgentRequestText(BaseModel):
    """
    AgentRequestText encapsulates a text request to an agent.

    prompt: str  : This is the user input text
    type: Literal["text"]
    """

    prompt: str
    type: Literal["text"] = "text"

    def __str__(self) -> str:
        return self.prompt


class AgentRequestFile(BaseModel):
    """
    AgentRequestFile encapsulates a file attachment request to an agent

    file_data: str  : This could be base64 encoded string or url
    name: str : name of the file
    type: Literal["file"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the file
    """

    file_data: str  # This could be base64 encoded string or url
    name: str
    type: Literal["file"] = "file"
    mime_type: str | None = None  # Optional. The IANA standard MIME type of the source data


class AgentRequestImage(BaseModel):
    """
    AgentRequestImage encapsulates an image request to an agent

    image_data: str  : This should be base64 encoded string
    name: str : name of the image
    type: Literal["image"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the image
    """

    prompt: str = ""
    image_data: str
    name: str
    type: Literal["image"] = "image"
    mime_type: str | None = None


class AgentRequestAny(BaseModel):
    """
    AgentRequestAny encapsulates passing any type of request to be handled by the pre-execution hooks. These are not directly handled by the agent kernel runtime.

    content: Any : This could be base64 encoded string or bytes or url
    name: str : name of the data
    type: Literal["other"]
    """

    content: Any
    name: str
    type: Literal["other"] = "other"


class AgentRequestVoice(BaseModel):
    """
    AgentRequestVoice encapsulates a voice request to an agent

    audio_data: str  : This should be base64 encoded string or url
    name: str : name of the voice clip
    type: Literal["voice"]
    mime_type: str | None = None : Optional. The IANA standard MIME type of the voice clip
    """

    prompt: str = ""
    audio_data: str
    name: str
    type: Literal["voice"] = "voice"
    mime_type: str | None = None


class AgentRequestAttachmentRef(BaseModel):
    """
    AgentRequestAttachmentRef references an attachment whose bytes are already
    persisted in the AttachmentStore, carrying only its identifier — no raw data.

    Used on the thread-enabled path: ChatService stores an uploaded attachment's
    bytes up front and replaces the raw image/file request with this reference,
    so no raw bytes travel past storage. MultimodalPreHook reads the id, loads the
    bytes from the AttachmentStore to generate a description, then strips it before
    the agent runs. Handled only by pre-hooks, never passed to the agent itself.

    attachment_id: str : Identifier of the stored attachment.
    type: Literal["attachment_ref"]
    """

    attachment_id: str
    type: Literal["attachment_ref"] = "attachment_ref"


class AgentReplyText(AgentRequestText):
    """
    AgentReplyText encapsulates a text reply from an agent.

    response: str : This is the agent output text
    prompt: str : The text prompt sent to the agent

    Inherits `prompt` (input) and `type` from AgentRequestText, and `response` holds the agent output.
    """

    response: str = ""
    prompt: str = ""

    def __str__(self) -> str:
        return self.response


class AgentReplyImage(AgentRequestImage):
    """
    AgentReplyImage encapsulates a text & image reply from an agent.

    response: str : This is the agent output text

    Inherits `prompt` (input), `image_data`, `name`, `type`, and `mime_type` from
    AgentRequestImage, and `response` holds the agent output text.
    """

    response: str

    def __str__(self) -> str:
        return f"{self.response}. Image {self.name} is attached."


class ResumeDecision(BaseModel):
    """
    A human's answer to one PausedInterruption.

    id: str : the interruption being answered
    status: Literal["approved", "denied", "cancelled"] | None : the verb. Optional, because a pause
        asking for a value has nothing to approve; Runtime requires it only for the approval kinds
    message: str | None : the human's words — a free-text answer, or the reason for a refusal
    payload: JsonValue : the structured answer — option(s) chosen, overridden arguments. Any JSON
        value, not just an object: a framework may take a bare list or string as the answer, and
        wrapping it in a dict AK invented would not survive the round trip
    """

    id: str
    status: Optional[Literal["approved", "denied", "cancelled"]] = None
    message: Optional[str] = None
    payload: JsonValue = None


class _ResumeDecisions(BaseModel):
    """
    Shared shape and structural validation for the two types carrying decisions.

    Matching a decision to a pending interruption is deliberately not checked here: that needs the
    session and is a Runtime check with its own error.
    """

    run_id: Optional[str] = None
    decisions: List[ResumeDecision]

    @model_validator(mode="after")
    def _validate_decisions(self) -> "_ResumeDecisions":
        if not self.decisions:
            raise ValueError("resume requires at least one decision")
        ids = [d.id for d in self.decisions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"resume carries more than one decision for: {', '.join(duplicates)}")
        return self


class ResumeSpec(_ResumeDecisions):
    """
    Resume block on a chat request: answer a pause instead of starting a new turn.

    run_id: str | None : which paused run is being answered. Optional because the AG-UI protocol
        has no field for it; the runtime resolves the run from the decisions' interruption ids
    decisions: list[ResumeDecision] : one per interruption answered. Answering some now and the
        rest later is allowed — the remainder comes back as another pause
    """


class AgentResumeRequestAny(_ResumeDecisions):
    """
    A human decision travelling through the request pipeline.

    A member of the AgentRequest union rather than a subclass of AgentRequestAny, whose handling is
    *skip* — exactly wrong for a decision that must reach the runner.
    """

    type: Literal["resume"] = "resume"


type AgentRequest = Union[
    AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestVoice, AgentRequestAny, AgentRequestAttachmentRef, AgentResumeRequestAny
]
type AgentReply = Union[AgentReplyText, AgentReplyImage, AgentReplyAny]

AgentRequestUnion = Annotated[
    Union[
        AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestVoice, AgentRequestAny, AgentRequestAttachmentRef, AgentResumeRequestAny
    ],
    Field(discriminator="type"),
]


class AgentReplyAny(BaseModel):
    """
    AgentReplyAny encapsulates a structured (JSON) reply from an agent.

    content: dict : The structured agent output as a JSON-compatible dict
    prompt: str   : The text prompt sent to the agent
    type: Literal["other"]
    """

    content: dict
    prompt: str = ""
    type: Literal["other"] = "other"

    def __str__(self) -> str:
        return json.dumps(self.content, default=str)

    @classmethod
    def from_output(cls, value: Any, prompt: str = "") -> "AgentReplyAny | None":
        """
        Builds an AgentReplyAny from a framework output value if it is structured.
        Pydantic instances are converted with model_dump(mode="json") so the content
        dict is JSON-compatible; plain dicts are used as content directly.

        :param value: The framework output value to inspect.
        :param prompt: The text prompt sent to the agent.
        :return: An AgentReplyAny, or None when the value is not structured
        (the caller falls back to a text reply).
        """
        if isinstance(value, BaseModel):
            return cls(content=value.model_dump(mode="json"), prompt=prompt)
        if isinstance(value, dict):
            return cls(content=value, prompt=prompt)
        return None


class AgentPausedReplyAny(AgentReplyAny):
    """
    The run stopped and is waiting on a human.

    A subclass of AgentReplyAny rather than a new member of the AgentReply union, so the union and
    every isinstance tuple over it keep working untouched. Safe only because a reply is never
    re-validated from JSON anywhere in src/. Narrowing the inherited `type` Literal is a Liskov
    violation mypy flags; it is the accepted cost of the subclass (design.md, open question 1).

    run_id: str : which paused run this is; the client echoes it back with its decision
    session_id: str : the session holding the record
    agent: str : the agent that paused, which also identifies the framework
    interruptions: list[PausedInterruption] : what the human has to decide

    content is derived from the fields above and never set independently — a caller-supplied one is
    overwritten, so the two cannot drift. The opaque per-framework resume state is never on this
    model: a reply crosses the queue transport and reaches clients.
    """

    content: dict = Field(default_factory=dict)
    type: Literal["paused"] = "paused"  # type: ignore[assignment]
    run_id: str
    session_id: str
    agent: str
    interruptions: List[PausedInterruption]

    @model_validator(mode="after")
    def _derive_content(self) -> "AgentPausedReplyAny":
        """
        Rebuilds content from the typed fields, discarding anything the caller passed.

        Safe from recursion: the model does not enable validate_assignment, so assigning here does
        not re-run validation.
        """
        self.content = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "agent": self.agent,
            "interruptions": [interruption.model_dump(mode="json") for interruption in self.interruptions],
        }
        return self


class ExecutionMode(str, Enum):
    """How a request is executed and how its reply is delivered.

    The mode is a process-level configuration value (``execution.mode``), read wherever a
    component must branch on it; it is never carried on a request.

    - ``REST_SYNC`` / ``REST_ASYNC``: the reply is written to the response store and read back
      over REST.
    - ``ASYNC``: WebSocket delivery, whole replies.
    - ``STREAM``: token streaming (``StreamAgentRunner``), delivered over WebSocket.
    - ``REALTIME``: a persistent model socket (voice), streamed and delivered through an
      integration adapter such as the LiveKit gateway.
    """

    REST_SYNC = "rest_sync"
    REST_ASYNC = "rest_async"
    STREAM = "stream"
    ASYNC = "async"
    REALTIME = "realtime"


class StreamChunk(BaseModel):
    """
    A single frame of a streamed agent response.

    `delta` carries assistant prose only, and is the field plain text consumers concatenate.
    `event` carries the full typed event the runner emitted, for consumers that render tool calls,
    reasoning and message boundaries. `Runtime.stream` is the only place that populates the two
    together; `delta` is therefore a plain field rather than one derived from `event`, so a
    `StreamChunk(delta=...)` built directly still serialises as it always has.
    """

    delta: str | None = None
    event: StreamEvent | None = None
    done: bool = False
    error: str | None = None


class SystemTool(BaseModel):
    name: str
    description: str
    func: Callable


class FileData(BaseModel):
    """Represents a file attachment"""

    file_data: str  # base64 encoded string or URL
    name: str
    mime_type: Optional[str] = None


class ImageData(BaseModel):
    """Represents an image attachment"""

    image_data: str  # base64 encoded string
    name: str
    mime_type: Optional[str] = None


class ScheduleSpec(BaseModel):
    """Schedule block on a chat request: defer the execution instead of running it now.

    at: str | None : ISO-8601 local wall-clock timestamp for a one-time execution
    cron: str | None : standard 5-field cron expression for a recurring execution
    timezone: str : IANA timezone the expression is evaluated in
    session_mode: Literal["reuse", "new"] : run each occurrence in the originating
        session ("reuse") or in a fresh per-occurrence session ("new")

    Exactly one of at/cron must be given. Only structural validation lives here — cron
    syntax, timezone existence, and "at must be in the future" are checked by
    ScheduleManager, because they need the optional 'schedule' extra and core models
    must import without it.
    """

    at: Optional[str] = None
    cron: Optional[str] = None
    timezone: str = "UTC"
    session_mode: Literal["reuse", "new"] = "reuse"

    @model_validator(mode="after")
    def _exactly_one_occurrence(self) -> "ScheduleSpec":
        if bool(self.at) == bool(self.cron):
            raise ValueError("schedule requires exactly one of 'at' (one-time) or 'cron' (recurring)")
        if not self.timezone.strip():
            raise ValueError("schedule timezone must not be empty")
        return self


class BaseChatRequest(BaseModel):
    """Base model for chat requests with common fields.

    user_id is required when Conversation Thread Support is enabled (a 'thread'
    block is present in config.yaml); group_id and thread_name are optional and
    applied only when the thread is auto-created on the session's first request.

    A schedule block defers the request: instead of running the agent, the request
    is registered as a scheduled task and acknowledged with HTTP 202. It requires
    the scheduling capability (a 'schedule' block in config.yaml) and a user_id.

    A resume block answers a paused run instead of starting a new turn, so prompt
    defaults to empty rather than being required. ChatService rejects a request
    carrying neither, with the same error a missing prompt has always raised.
    """

    prompt: str = ""
    agent: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    group_id: Optional[str] = None
    thread_name: Optional[str] = None
    schedule: Optional[ScheduleSpec] = None
    resume: Optional[ResumeSpec] = None

    @model_validator(mode="after")
    def _require_a_prompt_or_a_resume(self) -> "BaseChatRequest":
        """
        Rejects a body carrying neither key, which is how a queue consumer spots a poison message.

        `prompt` is a required field everywhere else in the product, and every queue consumer relies
        on `BaseRunRequest.model_validate` raising to drive retry -> max_receive_count -> dead-letter
        (`pipeline/agent_runner.py`, both ECS runners, both serverless runners). Defaulting it so a
        decision can stand alone removed the only structural check distinguishing a run request from
        arbitrary JSON, and a poison message was then acked instead of dead-lettered.

        Keyed on `model_fields_set` rather than on the value, so `{"prompt": ""}` behaves exactly as
        it did before: an explicitly empty prompt is a run request, an absent one is not. A prebuilt
        `requests` list counts too — that is the shape a producer composing its own list sends, and it
        carries the turn without a prompt key.

        :return: This request, when it carries a prompt key, a prebuilt request list, or a resume.
        :raises ValueError: If it carries none of them, making it indistinguishable from unrelated JSON.
        """
        if not (self.model_fields_set & {"prompt", "requests"}) and self.resume is None:
            raise ValueError("a chat request must carry a 'prompt', a 'resume' block, or a prebuilt 'requests' list")
        return self


class BaseRunRequest(BaseChatRequest):
    """Chat request with file and image attachments (base64/URL format).

    scheduled_task_id and scheduled_time are set by a schedule provider on the trigger
    it delivers, identifying the task and the occurrence this run belongs to. They are
    typed fields (not extras) so an occurrence's metadata never reaches the agent as
    additional context.

    requests carries an already-built AgentRequest list, for producers that compose it
    themselves rather than leaving it to RequestBuilder: a messaging integration downloads
    its attachments at the edge and stores them, so what reaches the queue is a request list
    (including AgentRequestAttachmentRef entries, which files/images cannot express). Typed
    for the same reason as the scheduling fields: an extra would reach the agent as
    AgentRequestAny context.
    """

    files: Optional[List[FileData]] = None
    images: Optional[List[ImageData]] = None
    requests: Optional[List[AgentRequestUnion]] = None
    scheduled_task_id: Optional[str] = None
    scheduled_time: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class BaseRequest(BaseModel):
    request_id: Optional[str] = None
    route: Optional[str] = None  # RouteKey of the Websocket, needed for WS implementation
    body: Optional[BaseRunRequest] = None
    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_payload(cls, payload: "BaseRequest | BaseRunRequest | dict[str, Any]") -> "BaseRequest":
        if isinstance(payload, cls):
            return payload

        if isinstance(payload, BaseRunRequest):
            return cls(request_id=str(uuid.uuid4()), body=payload)

        if isinstance(payload, dict):
            request_id = payload.get("request_id") or str(uuid.uuid4())
            user_id = payload.get("user_id")
            route = payload.get("route")

            if "body" in payload and payload["body"] is not None:
                body = payload["body"]
                if isinstance(body, dict):
                    body = {key: value for key, value in body.items() if key not in {"request_id", "user_id", "route"}}
            else:
                body = {key: value for key, value in payload.items() if key not in {"request_id", "user_id", "route", "body"}}

            if not body:
                return cls(request_id=request_id, user_id=user_id, route=route)

            if not isinstance(body, BaseRunRequest):
                body = BaseRunRequest.model_validate(body)

            # The envelope user_id is authoritative — propagate it into the body so
            # body-level consumers (e.g. Conversation Thread Support) can read it.
            if user_id is not None:
                body.user_id = user_id

            return cls(request_id=request_id, user_id=user_id, route=route, body=body)

        raise TypeError(f"Unsupported payload type for BaseRequest: {repr(type(payload))}")
