import asyncio
import base64
import json
import logging
from collections.abc import AsyncGenerator, Generator
from typing import Any, Dict, List, Optional, Union

from .config import AKConfig
from .model import (
    AgentReply,
    AgentReplyAny,
    AgentReplyImage,
    AgentReplyText,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    BaseChatRequest,
    BaseRunRequest,
    StreamChunk,
)
from .service import AgentService


class RequestBuilder:
    """Constructs AgentRequest object lists from various input sources."""

    _log = logging.getLogger("ak.chatservice.requestbuilder")

    @staticmethod
    def _max_file_size() -> int:
        # Read on demand: importing agentkernel must not load AKConfig
        return AKConfig.get().api.max_file_size

    @staticmethod
    def from_base_request_sync(req: BaseRunRequest) -> List[Any]:
        """Build agent request list from BaseRunRequest synchronously.

        :param req: Base run request containing prompt, images, files, and additional context
        :return: List of AgentRequest objects for processing
        """
        requests = [AgentRequestText(prompt=req.prompt)]
        RequestBuilder._add_images(requests, req.images)
        RequestBuilder._add_files(requests, req.files)
        RequestBuilder._attach_additional_context(req, requests)
        return requests

    @staticmethod
    async def from_base_request_async(req: BaseChatRequest) -> List[Any]:
        """Build agent request list from a BaseChatRequest asynchronously.

        :param req: Base chat request (may be a BaseRunRequest with FileData/ImageData
                    or a multipart/upload-style request defined elsewhere)
        :return: List of AgentRequest objects for processing
        """
        requests = [AgentRequestText(prompt=req.prompt)]

        # If this is a BaseRunRequest, it contains FileData/ImageData objects
        # (base64 or URLs) — handle them synchronously. Otherwise, assume
        # multipart/upload-style objects and attempt to process them
        # via the async multipart handlers.
        if isinstance(req, BaseRunRequest):
            RequestBuilder._add_images(requests, req.images)
            RequestBuilder._add_files(requests, req.files)
            RequestBuilder._attach_additional_context(req, requests)
        else:
            # For other subclasses (e.g., upload objects) try async multipart
            await RequestBuilder._add_multipart_files(requests, getattr(req, "files", None))
            await RequestBuilder._add_multipart_images(requests, getattr(req, "images", None))

        return requests

    @staticmethod
    def _add_images(requests: List[Any], images):
        """Add image requests to the request list.

        :param requests: List to append image requests to
        :param images: List of image objects with image_data, name, and mime_type
        :return: None
        """
        if not images:
            return
        for image in images:
            RequestBuilder._log.debug(f"Adding image: {image.name}")
            if not image.image_data.startswith(("http://", "https://", "data:", "s3://")) and not image.mime_type:
                raise ValueError("mime_type is missing for image input, either in the base64 or explicitly")
            requests.append(
                AgentRequestImage(
                    image_data=image.image_data,
                    name=image.name,
                    mime_type=image.mime_type,
                )
            )

    @staticmethod
    def _add_files(requests: List[Any], files):
        """Add file requests to the request list.

        :param requests: List to append file requests to
        :param files: List of file objects with file_data, name, and mime_type
        :return: None
        """
        if not files:
            return
        for file in files:
            RequestBuilder._log.debug(f"Adding file attachment: {file.name}")
            if not file.file_data.startswith(("http://", "https://", "data:", "s3://")) and not file.mime_type:
                raise ValueError("mime_type is missing for file input, either in the base64 or explicitly")
            requests.append(
                AgentRequestFile(
                    file_data=file.file_data,
                    name=file.name,
                    mime_type=file.mime_type,
                )
            )

    @staticmethod
    def _attach_additional_context(req: BaseRunRequest, requests: List[Any]):
        """Attach additional context fields from request as AgentRequestAny objects.

        :param req: Base run request containing additional context fields
        :param requests: List to append context requests to
        :return: None
        """
        known_fields = {
            "request_id",
            "user_id",
            "group_id",
            "thread_name",
            "prompt",
            "agent",
            "session_id",
            "images",
            "files",
            # Scheduling envelope: the schedule block is consumed before the agent runs, and the
            # trigger metadata describes the occurrence, not the user's request.
            "schedule",
            "scheduled_task_id",
            "scheduled_time",
        }
        for key, value in req.model_dump().items():
            if key in known_fields:
                continue
            RequestBuilder._log.info(f"Adding additional context: {key}={value}")
            requests.append(AgentRequestAny(name=key, content=value))

    @staticmethod
    async def _add_multipart_files(requests: List[Any], files: Optional[List[Any]]):
        """Process and add multipart uploaded files to request list.

        :param requests: List to append file requests to
        :param files: Optional list of uploaded file objects from multipart form
        :return: None
        """
        if not files:
            return
        for file in files:
            RequestBuilder._log.debug(f"Processing uploaded file: {file.filename}")
            content = await file.read()
            if len(content) > RequestBuilder._max_file_size():
                raise ValueError(f"File {file.filename} exceeds maximum size ({len(content) / (1024 * 1024):.2f} MB)")
            requests.append(
                AgentRequestFile(
                    file_data=base64.b64encode(content).decode("utf-8"),
                    name=file.filename or "unknown",
                    mime_type=file.content_type,
                )
            )

    @staticmethod
    async def _add_multipart_images(requests: List[Any], images: Optional[List[Any]]):
        """Process and add multipart uploaded images to request list.

        :param requests: List to append image requests to
        :param images: Optional list of uploaded image objects from multipart form
        :return: None
        """
        if not images:
            return
        for image in images:
            RequestBuilder._log.debug(f"Processing uploaded image: {image.filename}")
            content = await image.read()
            if len(content) > RequestBuilder._max_file_size():
                raise ValueError(f"Image {image.filename} exceeds maximum size ({len(content) / (1024 * 1024):.2f} MB)")
            if image.content_type and not image.content_type.startswith("image/"):
                raise ValueError(f"Invalid image type: {image.content_type}")
            requests.append(
                AgentRequestImage(
                    image_data=base64.b64encode(content).decode("utf-8"),
                    name=image.filename or "unknown",
                    mime_type=image.content_type,
                )
            )


class AgentHandler:
    """Manages AgentService lifecycle: selection, validation, and execution."""

    _log = logging.getLogger("ak.chatservice.agenthandler")

    def __init__(self):
        """Initialize AgentHandler with no active service.

        :return: None
        """
        self.service: Optional[AgentService] = None

    def initialize(self, session_id: str, agent: Optional[str]):
        """Initialize AgentService with session and agent selection.

        :param session_id: Session identifier for the agent
        :param agent: Optional agent name/identifier to select
        :return: None
        :raises ValueError: If no agent is available after selection
        """
        self.service = AgentService()
        self.service.select(session_id, agent)
        if not self.service.agent:
            raise ValueError("No agent available")

    @staticmethod
    def _run_async_sync(coro) -> Any:
        """Run an async coroutine from sync code, handling event loop state.

        Only a RuntimeError from get_event_loop() itself (no loop in this thread) falls back to
        asyncio.run: a RuntimeError raised by the coroutine must propagate as-is, not trigger a
        second await of the already-consumed coroutine.

        :param coro: Coroutine to execute
        :return: Result of the coroutine
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return asyncio.run(coro)
        if loop.is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
            return asyncio.run(coro)
        return loop.run_until_complete(coro)

    def run_sync(self, requests: List[Any], acting_user_id: Optional[str] = None) -> Any:
        """Run agent requests synchronously.

        :param requests: List of AgentRequest objects to process
        :param acting_user_id: When given, published as the run's acting user (see Runtime.run)
        :return: Agent execution result
        """
        return AgentHandler._run_async_sync(self.service.run_multi(requests=requests, acting_user_id=acting_user_id))

    async def run_async(self, requests: List[Any], acting_user_id: Optional[str] = None) -> Any:
        """Run agent requests asynchronously.

        :param requests: List of AgentRequest objects to process
        :param acting_user_id: When given, published as the run's acting user (see Runtime.run)
        :return: Agent execution result
        """
        return await self.service.run_multi(requests=requests, acting_user_id=acting_user_id)

    def run_stream_sync(self, requests: List[Any], acting_user_id: Optional[str] = None) -> List[Any]:
        """Run agent streaming requests synchronously.

        Manages event loop lifecycle internally and returns all chunks as a list.

        :param requests: List of AgentRequest objects to process
        :param acting_user_id: When given, published as the run's acting user (see Runtime.stream)
        :return: List of StreamChunk objects
        """

        async def _collect():
            chunks = []
            async for chunk in self.service.stream_multi(requests=requests, acting_user_id=acting_user_id):
                chunks.append(chunk)
            return chunks

        return AgentHandler._run_async_sync(_collect())

    async def run_stream_async(self, requests: List[Any], acting_user_id: Optional[str] = None) -> AsyncGenerator[Any, None]:
        """Run agent streaming requests asynchronously.

        :param requests: List of AgentRequest objects to process
        :param acting_user_id: When given, published as the run's acting user (see Runtime.stream)
        :return: AsyncGenerator yielding StreamChunk objects
        """
        async for chunk in self.service.stream_multi(requests=requests, acting_user_id=acting_user_id):
            yield chunk

    def get_response_session_id(self, session_id: Optional[str]) -> Optional[str]:
        """Get the session ID for the response.

        :param session_id: Original session ID from request
        :return: Response session ID from service or original if service unavailable
        """
        return self.service.get_response_session_id(session_id) if self.service else session_id


class ResponseBuilder:
    """Formats agent results and errors into response dicts."""

    @staticmethod
    def build_response(status_code: int, session_id: Optional[str], rest_api_mode: bool, result: Any = None, error: Optional[Exception] = None):
        """Build response from agent result or error.

        :param status_code: HTTP status code
        :param session_id: Session identifier for the response
        :param rest_api_mode: If True, return dict only on success or raise HTTPException on error; if False, return tuple
        :param result: Agent execution result (mutually exclusive with error)
        :param error: Exception that occurred (mutually exclusive with result)
        :return: Response dict or (status_code, response_dict) tuple; raises HTTPException if error in rest_api_mode
        """
        if error:
            response_dict = {"error": str(error)}
        else:
            response_dict = {
                "result": str(result) if isinstance(result, (AgentReplyText, AgentReplyImage, AgentReplyAny)) else "Non textual result received"
            }

        if session_id:
            response_dict["session_id"] = session_id

        if error and rest_api_mode:
            from fastapi import HTTPException

            raise HTTPException(status_code=status_code, detail=response_dict)

        if rest_api_mode and status_code != 200:
            # A success that is not a plain 200 — the 202 acknowledging a deferred request — has to
            # reach the client with its status, which a returned dict cannot carry.
            from fastapi.responses import JSONResponse

            return JSONResponse(content=response_dict, status_code=status_code)

        return response_dict if rest_api_mode else (status_code, response_dict)

    @staticmethod
    def stream_chunk(chunk: StreamChunk, session_id: str, sse_format: bool = False) -> str:
        """Format a StreamChunk as JSON or SSE.

        :param chunk: StreamChunk to format
        :param session_id: Session identifier to include in the payload
        :param sse_format: When True, wrap the JSON payload as an SSE frame.
        :return: JSON string or SSE-formatted string with excluded None values
        """
        payload_dict = chunk.model_dump(exclude_none=True)
        payload_dict["session_id"] = session_id
        payload = json.dumps(payload_dict)
        return f"data: {payload}\n\n" if sse_format else payload


class ChatService:
    def __init__(self, rest_api_mode: bool = False):
        """Initialize ChatService.

        :param rest_api_mode: If True, use FastAPI error handling; if False, use tuple responses
        :return: None
        """
        self._log = logging.getLogger("ak.chatservice")
        self.rest_api_mode = rest_api_mode

    async def execute(self, req: BaseChatRequest, requests: Optional[List[AgentRequest]] = None) -> tuple[AgentReply, Optional[str]]:
        """Validate, build (unless prebuilt), select the agent, and run the request.

        Transport-neutral execution core: returns the typed reply and lets exceptions
        propagate, so callers own their response shaping and error handling.

        :param req: Chat request carrying prompt, agent, and session_id
        :param requests: Optional prebuilt AgentRequest list. When given, RequestBuilder is
                         skipped and prompt is optional; the list must be non-empty.
        :return: Tuple of (typed agent reply, response session id)
        :raises ValueError: If validation fails or no agent is available
        """
        scheduled = self._maybe_schedule(req)
        if scheduled is not None:
            return scheduled, req.session_id
        self._record_trigger(req)
        requests = await self._prepare_async(req, requests)
        handler = AgentHandler()
        handler.initialize(req.session_id, req.agent)
        result = await handler.run_async(requests, acting_user_id=req.user_id)
        return result, handler.get_response_session_id(req.session_id)

    def execute_sync(self, req: BaseRunRequest, requests: Optional[List[AgentRequest]] = None) -> tuple[AgentReply, Optional[str]]:
        """Synchronous counterpart of execute().

        :param req: Run request carrying prompt, agent, and session_id
        :param requests: Optional prebuilt AgentRequest list (see execute())
        :return: Tuple of (typed agent reply, response session id)
        :raises ValueError: If validation fails or no agent is available
        """
        scheduled = self._maybe_schedule(req)
        if scheduled is not None:
            return scheduled, req.session_id
        self._record_trigger(req)
        requests = self._prepare_sync(req, requests)
        handler = AgentHandler()
        handler.initialize(req.session_id, req.agent)
        result = handler.run_sync(requests, acting_user_id=req.user_id)
        return result, handler.get_response_session_id(req.session_id)

    async def execute_stream(self, req: BaseChatRequest, requests: Optional[List[AgentRequest]] = None) -> AsyncGenerator[StreamChunk, None]:
        """Streaming counterpart of execute(): yields raw StreamChunk objects, no framing.

        Validates and selects the agent eagerly, so invalid input raises at call time,
        before the generator is returned. A failure inside the stream is yielded as a
        final StreamChunk carrying the error instead of raising.

        :param req: Chat request carrying prompt, agent, and session_id
        :param requests: Optional prebuilt AgentRequest list (see execute())
        :return: Async generator yielding raw StreamChunk objects
        :raises ValueError: If validation fails or no agent is available
        """
        scheduled = self._maybe_schedule(req)
        if scheduled is not None:
            return self._acknowledgement_stream(scheduled)
        self._record_trigger(req)
        requests = await self._prepare_async(req, requests)
        handler = AgentHandler()
        handler.initialize(req.session_id, req.agent)

        async def _stream() -> AsyncGenerator[StreamChunk, None]:
            try:
                async for chunk in handler.run_stream_async(requests, acting_user_id=req.user_id):
                    yield chunk
            except Exception as e:
                yield StreamChunk(error=str(e), done=True)

        return _stream()

    def execute_stream_sync(self, req: BaseRunRequest, requests: Optional[List[AgentRequest]] = None) -> Generator[StreamChunk, None, None]:
        """Synchronous counterpart of execute_stream().

        Preserves the sync path's buffering semantics: AgentHandler.run_stream_sync collects
        all chunks before this generator yields the first one.

        :param req: Run request carrying prompt, agent, and session_id
        :param requests: Optional prebuilt AgentRequest list (see execute())
        :return: Generator yielding raw StreamChunk objects
        :raises ValueError: If validation fails or no agent is available
        """
        scheduled = self._maybe_schedule(req)
        if scheduled is not None:
            return self._acknowledgement_stream_sync(scheduled)
        self._record_trigger(req)
        requests = self._prepare_sync(req, requests)
        handler = AgentHandler()
        handler.initialize(req.session_id, req.agent)

        def _stream() -> Generator[StreamChunk, None, None]:
            try:
                for chunk in handler.run_stream_sync(requests, acting_user_id=req.user_id):
                    yield chunk
            except Exception as e:
                yield StreamChunk(error=str(e), done=True)

        return _stream()

    def _maybe_schedule(self, req: BaseChatRequest) -> Optional[AgentReplyAny]:
        """Register a request that carries a schedule block instead of running it.

        The interception point for every chat surface: whatever transport delivered the request,
        a schedule block means "not now", and the caller gets an acknowledgement carrying the
        task id it can manage the schedule by.

        :param req: The incoming chat request.
        :return: The acknowledgement reply when the request was deferred, None when it must run now.
        :raises ValueError: If the request carries a schedule block while the capability is disabled,
                            or the schedule itself is unusable.
        """
        if req.schedule is None:
            return None
        # Imported inside the enabled-check: core must not load the capability (nor its optional
        # dependencies) in processes that never schedule anything.
        from ..schedule.manager import ScheduleManager

        manager = ScheduleManager.get()
        if manager is None:
            raise ValueError("Scheduling is not configured. Add a 'schedule' block to config.yaml")
        task = manager.create_from_request(req)
        self._log.info(f"Deferred request as scheduled task {task.task_id}")
        return AgentReplyAny(content={"status": "SCHEDULED", "scheduled_task_id": task.task_id, "session_id": task.session_id})

    def _record_trigger(self, req: BaseChatRequest) -> None:
        """Record the occurrence a scheduled trigger is running, when this request is one.

        Never raises: the occurrence bookkeeping is advisory, so a store that cannot take it must
        not fail the run the trigger started.

        :param req: The incoming chat request, carrying trigger metadata when it is an occurrence.
        """
        task_id = getattr(req, "scheduled_task_id", None)
        if not task_id:
            return
        try:
            from ..schedule.manager import ScheduleManager

            manager = ScheduleManager.get()
            if manager is None:
                self._log.warning(f"Trigger of scheduled task {task_id} arrived while scheduling is not configured")
                return
            manager.record_trigger(task_id, request_id=getattr(req, "request_id", None), occurred_at=getattr(req, "scheduled_time", None))
        except Exception as e:
            self._log.error(f"Failed to record trigger of scheduled task {task_id}: {e}")

    @staticmethod
    async def _acknowledgement_stream(ack: AgentReplyAny) -> AsyncGenerator[StreamChunk, None]:
        """Stream a deferred request's acknowledgement as the single terminal chunk.

        Deliberately not an error chunk: deferring the request is the requested outcome, so a
        streaming client sees one final delta carrying the acknowledgement.

        :param ack: The acknowledgement built by :meth:`_maybe_schedule`.
        :return: Async generator yielding exactly one done chunk.
        """
        yield StreamChunk(delta=str(ack), done=True)

    @staticmethod
    def _acknowledgement_stream_sync(ack: AgentReplyAny) -> Generator[StreamChunk, None, None]:
        """Synchronous counterpart of _acknowledgement_stream().

        :param ack: The acknowledgement built by :meth:`_maybe_schedule`.
        :return: Generator yielding exactly one done chunk.
        """
        yield StreamChunk(delta=str(ack), done=True)

    @staticmethod
    def _success_status(req: BaseChatRequest) -> int:
        """Return the status a successful response carries: 202 when the request was deferred.

        :param req: The processed chat request.
        :return: 202 for a deferred request (accepted, not executed), 200 for one that ran.
        """
        return 202 if req.schedule is not None else 200

    @staticmethod
    def _propagate_acting_user(handler: AgentHandler, req: BaseChatRequest) -> None:
        """Publish the request's user as the run's acting user in the session volatile cache.

        Called after the handler has selected its session, so hooks and tools running inside the
        run can attribute work to the caller. The cache is volatile: ``Runtime.run``/``stream``
        clear it when the run ends, so the key never leaks into the next run of the same session.

        :param handler: The initialized agent handler owning the session
        :param req: The request whose user_id is published (a request without one publishes nothing)
        :return: None
        """
        if not req.user_id or not handler.service or not handler.service.session:
            return
        handler.service.session.get_volatile_cache().set(ACTING_USER_CACHE_KEY, req.user_id)

    async def _prepare_async(self, req: BaseChatRequest, requests: Optional[List[AgentRequest]]) -> List[AgentRequest]:
        """Validate the request and return the effective request list (built or prebuilt).

        :param req: Chat request to validate
        :param requests: Optional prebuilt AgentRequest list
        :return: The request list to run the agent with
        :raises ValueError: If validation fails
        """
        self._validate(req, requests)
        return await RequestBuilder.from_base_request_async(req) if requests is None else requests

    def _prepare_sync(self, req: BaseRunRequest, requests: Optional[List[AgentRequest]]) -> List[AgentRequest]:
        """Synchronous counterpart of _prepare_async().

        :param req: Run request to validate
        :param requests: Optional prebuilt AgentRequest list
        :return: The request list to run the agent with
        :raises ValueError: If validation fails
        """
        self._validate(req, requests)
        return RequestBuilder.from_base_request_sync(req) if requests is None else requests

    def process_chat_request(self, req: BaseRunRequest) -> Union[tuple[int, Dict[str, Any]], Dict[str, Any]]:
        """Process a chat request synchronously.

        :param req: Base run request with prompt, session_id, agent, and attachments
        :return: When rest_api_mode=False: tuple of (status_code, response_dict).
                 When rest_api_mode=True: response_dict only.
        """
        try:
            result, session_id = self.execute_sync(req)
            return ResponseBuilder.build_response(self._success_status(req), session_id, self.rest_api_mode, result=result)
        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return ResponseBuilder.build_response(400, req.session_id, self.rest_api_mode, error=ve)
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return ResponseBuilder.build_response(500, req.session_id, self.rest_api_mode, error=e)

    async def process_async_chat_request(self, req: BaseChatRequest) -> Union[tuple[int, Dict[str, Any]], Dict[str, Any]]:
        """Process a chat request asynchronously.

        :param req: Base chat request (could be a BaseRunRequest or another subclass
                    that represents multipart/upload requests).
        :return: When rest_api_mode=False: tuple of (status_code, response_dict).
                 When rest_api_mode=True: response_dict only.
        """
        try:
            result, session_id = await self.execute(req)
            return ResponseBuilder.build_response(self._success_status(req), session_id, self.rest_api_mode, result=result)
        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return ResponseBuilder.build_response(400, req.session_id, self.rest_api_mode, error=ve)
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return ResponseBuilder.build_response(500, req.session_id, self.rest_api_mode, error=e)

    async def process_stream_chat_async(
        self,
        req: BaseChatRequest,
        sse_format: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Process a streaming chat request asynchronously.

        Validate, initialize, and return a streaming chat response generator.

        :param req: Base chat request with prompt, session_id, agent, and optional attachments
        :param sse_format: When True, yield Server-Sent Events formatted frames.
                           When False, yield raw StreamChunk JSON payloads.
        :return: Async generator yielding StreamChunk payloads as JSON or SSE-formatted strings
        :raises ValueError: If session_id or prompt is missing, or no agent is available
        """
        session_id = req.session_id
        chunks = await self.execute_stream(req)

        async def _stream() -> AsyncGenerator[str, None]:
            try:
                async for chunk in chunks:
                    yield ResponseBuilder.stream_chunk(chunk, session_id, sse_format=sse_format)
            except Exception as e:
                error_chunk = StreamChunk(error=str(e), done=True)
                yield ResponseBuilder.stream_chunk(error_chunk, session_id, sse_format=sse_format)

        return _stream()

    def process_stream_chat_sync(
        self,
        req: BaseRunRequest,
        sse_format: bool = False,
    ) -> Generator[str, None, None]:
        """Process a streaming chat request synchronously.

        Validates and initializes eagerly (before returning the generator), then
        yields formatted streaming chunks. Mirrors the async version's pattern so
        ValueError is raised at call time, not deferred until the first iteration.

        :param req: Base run request with prompt, session_id, agent, and attachments
        :param sse_format: When True, yield Server-Sent Events formatted frames.
                           When False, yield raw StreamChunk JSON payloads.
        :return: Generator yielding StreamChunk payloads as JSON or SSE-formatted strings
        :raises ValueError: If session_id or prompt is missing, or no agent is available
        """
        session_id = req.session_id
        chunks = self.execute_stream_sync(req)

        def _stream() -> Generator[str, None, None]:
            try:
                for chunk in chunks:
                    yield ResponseBuilder.stream_chunk(chunk, session_id, sse_format=sse_format)
            except Exception as e:
                error_chunk = StreamChunk(error=str(e), done=True)
                yield ResponseBuilder.stream_chunk(error_chunk, session_id, sse_format=sse_format)

        return _stream()

    @staticmethod
    def _validate(req: BaseChatRequest, requests: Optional[List[AgentRequest]]) -> None:
        """Validate that required fields are present in the request.

        :param req: Chat request to validate
        :param requests: Optional prebuilt AgentRequest list; when given, prompt is
                         optional but the list must be non-empty
        :return: None
        :raises ValueError: If session_id is missing, prompt is missing on the built path,
                            or a prebuilt request list is empty
        """
        if not req.session_id:
            raise ValueError("No session_id is provided in the request")
        if requests is None:
            if not req.prompt:
                raise ValueError("No prompt provided in the request")
        elif not requests:
            raise ValueError("No requests provided in the request")
