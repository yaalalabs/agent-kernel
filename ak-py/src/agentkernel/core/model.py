import json
import uuid
from enum import Enum
from typing import Any, Callable, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator


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


type AgentRequest = Union[AgentRequestText, AgentRequestFile, AgentRequestImage, AgentRequestAny, AgentRequestAttachmentRef]
type AgentReply = Union[AgentReplyText, AgentReplyImage, AgentReplyAny]


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


class ExecutionMode(str, Enum):
    """
    Execution mode enumeration for Lambda function behavior.
    """

    REST_SYNC = "rest_sync"
    REST_ASYNC = "rest_async"
    STREAM = "stream"
    ASYNC = "async"


class StreamChunk(BaseModel):
    delta: str | None = None
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
    """

    prompt: str
    agent: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    group_id: Optional[str] = None
    thread_name: Optional[str] = None
    schedule: Optional[ScheduleSpec] = None


class BaseRunRequest(BaseChatRequest):
    """Chat request with file and image attachments (base64/URL format).

    scheduled_task_id and scheduled_time are set by a schedule provider on the trigger
    it delivers, identifying the task and the occurrence this run belongs to. They are
    typed fields (not extras) so an occurrence's metadata never reaches the agent as
    additional context.
    """

    files: Optional[List[FileData]] = None
    images: Optional[List[ImageData]] = None
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
