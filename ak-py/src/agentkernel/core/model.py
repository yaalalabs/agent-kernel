import json
import uuid
from collections.abc import Callable
from enum import Enum, StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .event import PausedInterruption, StreamEvent
from .util.payload import JSONPayload


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
    status: Literal["approved", "denied", "cancelled"] | None = None
    message: str | None = None
    payload: JsonValue = None


class _ResumeDecisions(BaseModel):
    """
    Shared shape and structural validation for the two types carrying decisions.

    Matching a decision to a pending interruption is deliberately not checked here: that needs the
    session and is a Runtime check with its own error.
    """

    run_id: str | None = None
    decisions: list[ResumeDecision]

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


type AgentRequest = AgentRequestText | AgentRequestFile | AgentRequestImage | AgentRequestVoice | AgentRequestAny | AgentRequestAttachmentRef | AgentResumeRequestAny
type AgentReply = AgentReplyText | AgentReplyImage | AgentReplyAny

AgentRequestUnion = Annotated[
    AgentRequestText | AgentRequestFile | AgentRequestImage | AgentRequestVoice | AgentRequestAny | AgentRequestAttachmentRef | AgentResumeRequestAny,
    Field(discriminator="type"),
]


class AgentReplyAny(BaseModel):
    """
    AgentReplyAny encapsulates a structured (JSON) reply from an agent.

    content: dict | list : The structured agent output, normalised to plain JSON types on
                           validation. A value with a canonical JSON form (datetime, Decimal, UUID,
                           Enum, set, UTF-8 bytes, a non-string key) coerces silently; one with
                           none — including NaN and the infinities — raises here rather than
                           somewhere down the pipeline. Replacing this field with
                           ``model_copy(update={"content": ...})`` skips that validation, so build a
                           new reply instead; updating only ``media_type`` by copy is safe.
    media_type: str|None : The format of ``content``, as a media type string. Unset by
                           default, and never set by a framework adapter — a post-hook applies it.
                           Surfaces that can carry an object do so only when this is set; with it
                           unset every surface behaves exactly as it did before the field existed.
    prompt: str   : The text prompt sent to the agent
    type: Literal["other"]
    """

    content: JSONPayload
    media_type: str | None = None
    prompt: str = ""
    type: Literal["other"] = "other"

    def __str__(self) -> str:
        return json.dumps(self.content, default=str)

    @classmethod
    def from_output(cls, value: Any, prompt: str = "") -> "AgentReplyAny | None":
        """
        Builds an AgentReplyAny from a framework output value if it is structured.
        Pydantic instances are converted with model_dump(mode="json"); plain dicts are used as
        content directly and reach the same normalisation through field validation, so both routes
        produce equal content for equal values.

        A bare list stays unstructured here even though ``content`` accepts one: a framework
        returning a list has always produced a text reply, and promoting it would change ``result``
        for an agent that never opted in. A caller that means to send an array builds the reply
        itself.

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
    interruptions: list[PausedInterruption]

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
    """How a request is invoked, which also fixes the transport its reply travels on.

    The mode is a process-level configuration value (``execution.mode``), read wherever a
    component must branch on it; it is never carried on a request.

    - ``REST_SYNC`` / ``REST_ASYNC``: over REST (JSON reply, submit + poll, or SSE for delta replies).
    - ``ASYNC``: over WebSocket only.
    - ``REALTIME``: a persistent model socket (voice) through an integration gateway.

    How much of the reply each message carries is ``execution.message_type`` (``ReplyMessageType``).
    """

    REST_SYNC = "rest_sync"
    REST_ASYNC = "rest_async"
    ASYNC = "async"
    REALTIME = "realtime"


class ReplyMessageType(str, Enum):
    """How much of the reply each delivered message carries (``execution.message_type``)."""

    COMPLETE = "complete"  # one message with the whole reply
    DELTA = "delta"  # one message per StreamChunk, ending with the done chunk


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


class AccessLevel(StrEnum):
    """The capability tier a principal drives an agent at: ``read`` < ``write`` < ``admin``.

    Levels are cumulative, so a principal granted ``write`` may use every tool tiered ``read`` or
    ``write``. The order is defined over the three members only: comparing a level with a plain
    string is refused rather than falling back to alphabetical order, which would put ``admin``
    below ``read``.
    """

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        """The position of this level in the capability order, lowest first."""
        return _ACCESS_LEVEL_RANK[self]

    def _rank_of(self, other: object) -> int:
        if not isinstance(other, AccessLevel):
            raise TypeError(f"'{type(other).__name__}' cannot be ordered against AccessLevel; compare AccessLevel members")
        return other.rank

    def __lt__(self, other: object) -> bool:
        return self.rank < self._rank_of(other)

    def __le__(self, other: object) -> bool:
        return self.rank <= self._rank_of(other)

    def __gt__(self, other: object) -> bool:
        return self.rank > self._rank_of(other)

    def __ge__(self, other: object) -> bool:
        return self.rank >= self._rank_of(other)


_ACCESS_LEVEL_RANK: dict[AccessLevel, int] = {AccessLevel.READ: 0, AccessLevel.WRITE: 1, AccessLevel.ADMIN: 2}

ANONYMOUS_PROVIDER = "anonymous"


class Principal(BaseModel):
    """Who a run acts as, established by the surface that authenticated the request.

    subject: str : the stable identifier the identity provider resolved (an OIDC ``sub``, a
        static-provider subject, a messaging platform's sender id)
    kind: Literal["user", "agent", "service"] : what the subject is
    provider: str : the identity provider's short name, ``messaging:<platform>`` or
        ``realtime:<gateway>`` for an edge, or ``anonymous``
    namespace: str | None : the scope the subject is unique within (an OIDC issuer, ``static``,
        a platform scope such as a Slack team id); ``None`` only for the anonymous principal
    groups, roles: list[str] : facts from the provider, and the roles a configured role mapper
        derived from them; Agent Kernel stores neither
    claims: dict[str, Any] : provider-specific facts kept for authorizers and tools
    actor: Principal | None : the party acting on the subject's behalf (the agent running for the
        user)
    credential_ref: str | None : the handle under which the inbound credential is retained; never
        the credential itself

    The model is frozen: a hook or tool holding a principal cannot mutate it, and the copy helpers
    are what the runtime and the surfaces use to derive one.
    """

    model_config = ConfigDict(frozen=True)

    # Provider prefixes of the edge adapters whose sessions are the platform's own conversations,
    # shared by everyone in them: the owner such a principal records binds the session to its
    # platform scope, and the ownership gate admits any principal from the same provider and
    # namespace rather than that one sender.
    SHARED_CHANNEL_PREFIXES: ClassVar[tuple[str, ...]] = ("messaging:", "realtime:")

    # The stable identifier the provider resolved: an OIDC ``sub``, a static-provider subject, a
    # messaging platform's sender id. It is unique only within ``namespace``, never on its own.
    subject: str
    # What the subject is. A run's principal is the user; the agent running on their behalf is its
    # ``actor``. An agent or service is a subject of its own only when it calls in directly.
    kind: Literal["user", "agent", "service"] = "user"
    # Who vouched for the subject: the configured provider's short name (``oidc``, ``cognito``,
    # ``entra``, ``firebase``, ``static``), ``messaging:<platform>`` or ``realtime:<gateway>`` for
    # an edge adapter, or ``anonymous`` when nothing authenticated the request.
    provider: str
    # The scope within which ``subject`` is unique. Every provider sets it from whatever issued the
    # subject, so the same subject string under two namespaces is two different principals:
    #   oidc / cognito / entra / firebase   the token's issuer (``iss``)
    #   static                              the literal ``"static"``
    #   messaging:slack                     the workspace's team id
    #   messaging:teams                     the tenant id
    #   messaging:gmail                     the inbox address the poller reads
    #   messaging:whatsapp                  the business ``phone_number_id``
    #   messaging:messenger / instagram     the page id of the delivery
    #   messaging:telegram                  the bot id
    #   realtime:livekit                    the API key id
    # Ownership checks compare ``namespace`` and ``subject`` together, and the omnichannel link
    # (#243) keys a person on provider + namespace + subject. ``None`` only for the anonymous
    # principal.
    namespace: str | None = None
    # Group memberships exactly as the provider reported them (a ``groups`` claim, Cognito's
    # ``cognito:groups``). Agent Kernel never stores or edits them.
    groups: list[str] = Field(default_factory=list)
    # Roles the configured role mapper derived from the provider's facts; empty without a mapper.
    roles: list[str] = Field(default_factory=list)
    # Provider-specific facts kept verbatim for authorizers and tools (selected token claims, a
    # Gmail ``Authentication-Results`` header).
    claims: dict[str, Any] = Field(default_factory=dict)
    # The party acting on the subject's behalf (RFC 8693's ``act`` claim): during a run, the agent
    # principal (``kind="agent"``, provider ``agentkernel``), set by Runtime, never by a surface.
    actor: "Principal | None" = None
    # The handle the inbound credential is retained under in the credential store. The token
    # itself never rides on the principal, a queue body or a log line.
    credential_ref: str | None = None

    @classmethod
    def anonymous(cls) -> "Principal":
        """The principal of a request no provider authenticated."""
        return cls(subject=ANONYMOUS_PROVIDER, provider=ANONYMOUS_PROVIDER)

    @property
    def is_anonymous(self) -> bool:
        return self.provider == ANONYMOUS_PROVIDER

    @property
    def is_shared_channel(self) -> bool:
        """Whether the principal arrived through a messaging or realtime edge, whose sessions any principal of the same platform scope may continue."""
        return self.provider.startswith(self.SHARED_CHANNEL_PREFIXES)

    @classmethod
    def subject_of(cls, principal: "Principal | None") -> str | None:
        """The subject of an authenticated principal, or None for a missing or anonymous one.

        What the owner-keyed records (threads, schedules, the WebSocket routing attribute) store.
        """
        return None if principal is None or principal.is_anonymous else principal.subject

    def with_actor(self, actor: "Principal") -> "Principal":
        """A copy of this principal acting on behalf of ``actor``."""
        return self.model_copy(update={"actor": actor})

    def with_credential_ref(self, ref: str | None) -> "Principal":
        """A copy of this principal carrying (or, with ``None``, dropping) a credential handle."""
        return self.model_copy(update={"credential_ref": ref})


class SessionOwner(BaseModel):
    """The principal a session was first used by, recorded for ownership checks only.

    Two subjects are the same owner only when their provider namespaces match too, since a
    subject is unique within its namespace and not across providers.
    """

    # Copied from the first non-anonymous principal that ran in the session. Nothing else is kept:
    # the owner is an enforcement key, not a profile.
    subject: str
    provider: str
    # Same meaning as ``Principal.namespace``, compared together with ``subject``: an OIDC ``sub``
    # and a Slack sender id that happen to be the same string are still different owners.
    namespace: str | None = None


class ToolFilter(BaseModel):
    """The per-run tool decision the runtime publishes; adapters only read it.

    level: AccessLevel : the level the current principal holds on the agent
    allowed: frozenset[str] : the tool names the principal may call at that level
    reasons: dict[str, str] : the reason a denied tool is denied, by tool name
    """

    model_config = ConfigDict(frozen=True)

    # The level the current principal holds on the agent being run.
    level: AccessLevel
    # The tool names callable at that level after the policy's allow and deny lists are applied.
    allowed: frozenset[str]
    # Why each denied tool is denied, by tool name; what the adapters hand back to the model.
    reasons: dict[str, str] = Field(default_factory=dict)

    def allows(self, name: str) -> bool:
        return name in self.allowed

    def reason(self, name: str) -> str:
        """Why ``name`` is denied: the recorded reason, or a generic one for a name never listed."""
        return self.reasons.get(name) or f"Tool '{name}' is not available to the current principal"


class AgentSkillDescriptor(BaseModel):
    """One skill an agent advertises in its catalog entry and A2A card."""

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class AgentIdentitySpec(BaseModel):
    """How an agent identifies itself when it acts as a principal.

    subject: str | None : the agent's own subject; defaults to the descriptor id at build time
    client_id, client_secret_key: str | None : the client credential the agent exchanges tokens
        with, the secret named by key and resolved through the secret capability
    """

    subject: str | None = None
    client_id: str | None = None
    client_secret_key: str | None = None


AgentSurface = Literal["rest", "a2a", "mcp", "agui"]


class AgentDescriptor(BaseModel):
    """The catalog entry of an agent: what the registry stores and the surfaces read.

    description is catalog text for people and other agents, never the agent's instructions.
    surfaces is the list of protocol surfaces the agent is exposed on; ``None`` means every
    surface, an empty list none. updated_at is set by store-backed registries.
    """

    # The registry key; the agent's name as the framework reports it, unless an overlay renames it.
    id: str
    name: str
    version: str = "0.0.0"
    # Catalog text for people and other agents. Never the agent's instructions.
    description: str = ""
    # The subject that owns the agent, when the overlay names one.
    owner: str | None = None
    # Free-form labels; ``tag:<name>`` in a grant selects every agent carrying ``name``.
    tags: list[str] = Field(default_factory=list)
    # Who may see the agent in the catalog; a synthesized catalog permission that confers no level.
    visibility: Literal["private", "internal", "public"] = "private"
    # The protocol surfaces the agent is served on. ``None`` means every surface, ``[]`` none.
    surfaces: list[AgentSurface] | None = None
    skills: list[AgentSkillDescriptor] = Field(default_factory=list)
    # The tool names the adapter reports for the agent, as the authorization policy names them.
    tools: list[str] = Field(default_factory=list)
    # The framework adapter's runner name (``openai``, ``langgraph``, ...).
    runner: str = ""
    supports_streaming: bool = True
    identity: AgentIdentitySpec = Field(default_factory=AgentIdentitySpec)
    # Set by store-backed registries on every write; ``None`` for the in-memory registry.
    updated_at: str | None = None

    def exposed_on(self, surface: str) -> bool:
        """Whether the agent is served on ``surface`` (``rest``, ``a2a``, ``mcp`` or ``agui``)."""
        return True if self.surfaces is None else surface in self.surfaces


class SystemTool(BaseModel):
    name: str
    description: str
    func: Callable
    tier: AccessLevel = AccessLevel.READ


class FileData(BaseModel):
    """Represents a file attachment"""

    file_data: str  # base64 encoded string or URL
    name: str
    mime_type: str | None = None


class ImageData(BaseModel):
    """Represents an image attachment"""

    image_data: str  # base64 encoded string
    name: str
    mime_type: str | None = None


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

    at: str | None = None
    cron: str | None = None
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

    principal is assigned by the surface after authentication, never read from the client; a
    non-anonymous principal is required when Conversation Thread Support is enabled (a 'thread'
    block is present in config.yaml). group_id and thread_name are optional and applied only
    when the thread is auto-created on the session's first request.

    A schedule block defers the request: instead of running the agent, the request
    is registered as a scheduled task and acknowledged with HTTP 202. It requires
    the scheduling capability (a 'schedule' block in config.yaml) and a non-anonymous
    principal, who owns the task.

    user_id is not a request field: a body or envelope carrying one is refused, since the acting
    user comes from the credential the surface authenticated.

    A resume block answers a paused run instead of starting a new turn, so prompt
    defaults to empty rather than being required. ChatService rejects a request
    carrying neither, with the same error a missing prompt has always raised.
    """

    prompt: str = ""
    agent: str | None = None
    session_id: str | None = None
    principal: Principal | None = None
    """Assigned by the surface after authentication; a value arriving from a client is overwritten, never read."""
    group_id: str | None = None
    thread_name: str | None = None
    schedule: ScheduleSpec | None = None
    resume: ResumeSpec | None = None

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

    files: list[FileData] | None = None
    images: list[ImageData] | None = None
    requests: list[AgentRequestUnion] | None = None
    scheduled_task_id: str | None = None
    scheduled_time: str | None = None
    model_config = ConfigDict(extra="allow")


USER_ID_NOT_A_FIELD = "user_id is not a request field; the acting user comes from the credential"


class BaseRequest(BaseModel):
    request_id: str | None = None
    route: str | None = None  # RouteKey of the Websocket, needed for WS implementation
    body: BaseRunRequest | None = None
    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_payload(cls, payload: "BaseRequest | BaseRunRequest | dict[str, Any]") -> "BaseRequest":
        """
        Wraps a client payload in the envelope.

        :param payload: An envelope, a bare run request, or a dict in either shape.
        :return: The envelope, with the body validated when the payload carries one. A ``principal``
            key in a dict payload is dropped: the surface assigns the principal after it has
            parsed the payload, so a client cannot name one.
        :raises ValueError: If the envelope or the body carries a ``user_id`` key: the acting user
            is established by the surface from the credential, never taken from the client.
        :raises TypeError: If the payload is of another type.
        """
        if isinstance(payload, cls):
            return payload

        if isinstance(payload, BaseRunRequest):
            return cls(request_id=str(uuid.uuid4()), body=payload)

        if isinstance(payload, dict):
            if "user_id" in payload:
                raise ValueError(USER_ID_NOT_A_FIELD)
            request_id = payload.get("request_id") or str(uuid.uuid4())
            route = payload.get("route")

            if "body" in payload and payload["body"] is not None:
                body = payload["body"]
                if isinstance(body, dict):
                    if "user_id" in body:
                        raise ValueError(USER_ID_NOT_A_FIELD)
                    body = {key: value for key, value in body.items() if key not in {"request_id", "route", "principal"}}
            else:
                body = {key: value for key, value in payload.items() if key not in {"request_id", "route", "body", "principal"}}

            if not body:
                return cls(request_id=request_id, route=route)

            if not isinstance(body, BaseRunRequest):
                body = BaseRunRequest.model_validate(body)

            return cls(request_id=request_id, route=route, body=body)

        raise TypeError(f"Unsupported payload type for BaseRequest: {repr(type(payload))}")
