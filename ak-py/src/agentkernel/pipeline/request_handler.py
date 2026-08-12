import asyncio
import base64
import json
import logging
import uuid
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..api.handler import AgentRESTRequestHandler
from ..core.config import AKConfig
from ..core.model import BaseRunRequest, ExecutionMode, FileData, ImageData
from .envelope import ATTR_REQUEST_ID, ATTR_USER_ID, QueueMessage, QueueName
from .response_store.base import ResponseStore
from .response_store.handler import ResponseDBHandler
from .response_store.in_memory import InMemoryResponseStore
from .transport.base import QueueTransport, QueueTransportFactory

if TYPE_CHECKING:  # QueueHandler stays in deployment.common — typing-only, no runtime coupling
    from ..deployment.common.queue_handler import QueueHandler

# Retry budget for awaiting a response when no execution.response_store block is configured;
# mirrors _ResponseStoreConfig's defaults (retry_count=5, delay=5).
_DEFAULT_RESPONSE_RETRY = (5, 5.0)


class RestHandler(AgentRESTRequestHandler):
    """Queue-aware REST handler; adds queue-based enqueue/poll chat routes when an input queue is configured."""

    # Poll route reuses the chat path (GET vs the enqueue POST).
    CHAT_POLL_PATH = AgentRESTRequestHandler.CHAT_PATH

    def __init__(self, logger_name: str = "ak.deployment.queue_handler"):
        super().__init__()
        # Override base logger with the deployment-specific one.
        self._log = logging.getLogger(logger_name)
        self._config = AKConfig.get()

    @abstractmethod
    def get_response_store(self) -> ResponseStore:
        """Return the ResponseStore implementation used to poll for responses."""
        pass

    @abstractmethod
    def get_queue_handler(self) -> "QueueHandler":
        """Return the QueueHandler implementation used to enqueue requests."""
        pass

    def _is_queue_mode(self) -> bool:
        """True when an input queue is configured (enqueue mode); False for direct mode."""
        return self._config.execution.queues.input.url is not None

    def _effective_mode(self) -> Optional[ExecutionMode]:
        """The execution mode governing the chat routes. Subclasses may map unset to a default."""
        return self._config.execution.mode

    async def _await_response_record(self, request_id: str):
        """Wait for the response for ``request_id`` and return it (or None on timeout)."""
        return await self.get_response_store().get_message_with_retry(request_id=request_id, get_and_delete=True, async_mode=True)

    def _build_sync_response(self, record: Any) -> Any:
        """Map a stored response record to the HTTP response body. Subclasses may override
        (e.g. to honor a stored status code)."""
        return record.get("body", record)

    async def enqueue_and_wait(self, body: BaseRunRequest):
        """Enqueue request; REST_SYNC waits for the response, REST_ASYNC returns request_id immediately."""
        try:
            if not body.session_id:
                raise HTTPException(status_code=400, detail="session_id is required")
            if not body.prompt:
                raise HTTPException(status_code=400, detail="prompt is required")

            # Unique request_id, distinct from session_id.
            request_id = str(uuid.uuid4())

            self._log.info(f"[REQUEST START] session_id={body.session_id}, request_id={request_id}, agent={body.agent}, prompt={body.prompt[:50]}")

            # Offload the sync send so it doesn't block the event loop.
            queue_result = await asyncio.to_thread(
                self.get_queue_handler().send_message_to_input_queue,
                message_body=body.model_dump(),
                attributes={"message_group_id": body.session_id, "message_deduplication_id": request_id},
                request_id=request_id,  # This becomes a custom message attribute
            )

            self._log.info(f"[ENQUEUED] MessageId={queue_result.get('MessageId')}, request_id={request_id}")

            mode = self._effective_mode()
            if mode == ExecutionMode.REST_SYNC:
                # Wait for the response in the response store.
                self._log.info(f"[WAITING] Polling response store for request_id={request_id}")

                response = await self._await_response_record(request_id)

                if not response:
                    raise HTTPException(
                        status_code=504,
                        detail={
                            "error": f"No response received for request_id: {request_id}",
                            "session_id": body.session_id,
                            "request_id": request_id,
                        },
                    )

                self._log.info(f"[RESPONSE FOUND] request_id={request_id}, response_keys={list(response.keys())}")

                return self._build_sync_response(response)

            elif mode == ExecutionMode.REST_ASYNC:
                # Return request_id for later polling.
                return {"status": "ACCEPTED", "request_id": request_id, "session_id": body.session_id}

            else:
                raise HTTPException(status_code=500, detail=f"Unsupported execution mode: {mode}")

        except HTTPException:
            raise
        except Exception as e:
            self._log.error(f"Error processing request: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail={"error": str(e), "session_id": body.session_id if body else None})

    async def poll_response(self, request_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        Poll for response (REST_ASYNC mode only).

        :param request_id: Specific request to poll for (query parameter)
        :param session_id: Optional session identifier (query parameter, used for logging/errors)
        """
        try:
            if self._effective_mode() != ExecutionMode.REST_ASYNC:
                raise HTTPException(status_code=404, detail="GET endpoint only available in REST_ASYNC mode")

            if not request_id:
                raise HTTPException(status_code=400, detail={"error": "request_id is required", "session_id": session_id})

            self._log.info(f"Polling for response: request_id={request_id}, session_id={session_id}")

            response = await self._await_response_record(request_id)

            if not response:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "NOT_FOUND",
                        "message": f"No response message found for request_id '{request_id}'. The message may be unavailable. Please try again.",
                        "request_id": request_id,
                        "session_id": session_id,
                    },
                )

            return self._build_sync_response(response)

        except HTTPException:
            raise
        except Exception as e:
            self._log.error(f"Error polling response: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail={"error": str(e), "session_id": session_id})

    def get_router(self) -> APIRouter:
        """Return the APIRouter: inherited direct-mode routes, or agents plus queue-based chat routes in queue mode."""
        if not self._is_queue_mode():
            return super().get_router()

        router = APIRouter()
        router.add_api_route(self.AGENTS_PATH, self.list_agents, methods=["GET"])
        router.add_api_route(self.CHAT_PATH, self.enqueue_and_wait, methods=["POST"])
        router.add_api_route(self.CHAT_POLL_PATH, self.poll_response, methods=["GET"])
        return router


class _TransportQueueHandler:
    """Adapts ``QueueTransport.send`` to the QueueHandler send-side signature RestHandler uses."""

    def __init__(self, transport: QueueTransport):
        self._transport = transport

    def send_message_to_input_queue(
        self,
        message_body: Dict[str, Any],
        attributes: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_message_attributes: Optional[List[Any]] = None,
        **extra_kwargs: Any,
    ) -> Dict[str, Any]:
        message_attributes: Dict[str, str] = {}
        if request_id is not None:
            message_attributes[ATTR_REQUEST_ID] = request_id
        if user_id is not None:
            message_attributes[ATTR_USER_ID] = user_id
        for custom_attribute in custom_message_attributes or []:
            message_attributes[custom_attribute.name] = str(custom_attribute.value)

        send_attributes = attributes or {}
        message = QueueMessage(
            body=json.dumps(message_body),
            attributes=message_attributes,
            group_id=send_attributes.get("message_group_id") or message_body.get("session_id"),
            dedup_id=send_attributes.get("message_deduplication_id"),
        )
        return self._transport.send(QueueName.INPUT, message) or {}


class RequestHandler(RestHandler):
    """Pipeline REST surface (spec #495 §8): enqueues to the configured transport and serves
    the poll/SSE routes. Always queue mode; the transport decides the topology."""

    def __init__(self):
        super().__init__(logger_name="ak.pipeline.request_handler")
        self._transport_type = QueueTransportFactory.resolve_type()
        self._transport: Optional[QueueTransport] = None
        self._queue_handler: Optional[_TransportQueueHandler] = None
        self._response_store: Optional[ResponseStore] = None

    # -- wiring ---------------------------------------------------------------------------

    def _get_transport(self) -> QueueTransport:
        if self._transport is None:
            self._transport = QueueTransportFactory.create()
        return self._transport

    def get_queue_handler(self) -> _TransportQueueHandler:
        if self._queue_handler is None:
            self._queue_handler = _TransportQueueHandler(self._get_transport())
        return self._queue_handler

    def get_response_store(self) -> ResponseStore:
        if self._response_store is None:
            response_store_config = self._config.execution.response_store
            unset = response_store_config is None or response_store_config.type in (None, "in_memory")
            if unset and self._transport_type == "in_memory":
                self._response_store = InMemoryResponseStore()
            else:
                self._response_store = ResponseDBHandler().get_store()
        return self._response_store

    def _is_queue_mode(self) -> bool:
        return True

    def _effective_mode(self) -> ExecutionMode:
        # Unset mode runs as REST_SYNC through the pipeline (spec §12 change 5).
        return self._config.execution.mode or ExecutionMode.REST_SYNC

    # -- response mapping (direct-mode wire parity) ----------------------------------------

    def _response_retry_config(self) -> tuple[int, float]:
        response_store_config = self._config.execution.response_store
        if response_store_config is None:
            return _DEFAULT_RESPONSE_RETRY
        return response_store_config.retry_count, response_store_config.delay

    async def _await_response_record(self, request_id: str):
        store = self.get_response_store()
        if isinstance(store, InMemoryResponseStore):
            retry_count, delay = self._response_retry_config()
            for attempt in range(retry_count):
                record = await asyncio.to_thread(store.get_record, request_id, True)
                if record is not None:
                    return record
                if attempt < retry_count - 1:
                    await asyncio.sleep(delay)
            return None
        return await super()._await_response_record(request_id)

    def _build_sync_response(self, record: Any) -> Any:
        if isinstance(record, dict) and "body" in record:
            status_code = int(record.get("status_code") or 200)
            body = record["body"]
            if status_code >= 400:
                # Restore the direct-mode error contract (ResponseBuilder raises in rest_api_mode).
                raise HTTPException(status_code=status_code, detail=body)
            return body
        return super()._build_sync_response(record)

    # -- routes ----------------------------------------------------------------------------

    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(self.AGENTS_PATH, self.list_agents, methods=["GET"])
        router.add_api_route(self.CHAT_PATH, self.run_chat, methods=["POST"])
        router.add_api_route(self.CHAT_POLL_PATH, self.poll_response, methods=["GET"])
        if self._transport_type == "in_memory":
            # Multipart uploads fit in-process messages; broker transports keep the ECS behavior
            # (no multipart route) because of broker message-size limits.
            router.add_api_route(self.CHAT_MULTIPART_PATH, self.run_multipart_chat, methods=["POST"])
        return router

    async def run_chat(self, body: BaseRunRequest):
        """POST /api/v1/chat — enqueue; SSE stream in STREAM mode, JSON otherwise."""
        # Direct-mode parity: same validation messages and error shape as ChatService._validate
        # (ValueError -> HTTPException(400, detail={"error": ...})).
        if not body.session_id:
            raise HTTPException(status_code=400, detail={"error": "No session_id is provided in the request"})
        if not body.prompt:
            raise HTTPException(status_code=400, detail={"error": "No prompt provided in the request", "session_id": body.session_id})

        if self._effective_mode() == ExecutionMode.STREAM:
            return await self._run_chat_stream(body)
        return await self.enqueue_and_wait(body)

    async def _run_chat_stream(self, body: BaseRunRequest) -> StreamingResponse:
        request_id = str(uuid.uuid4())
        self._log.info(f"[STREAM REQUEST] session_id={body.session_id}, request_id={request_id}")
        await asyncio.to_thread(
            self.get_queue_handler().send_message_to_input_queue,
            message_body=body.model_dump(),
            attributes={"message_group_id": body.session_id, "message_deduplication_id": request_id},
            request_id=request_id,
        )
        return StreamingResponse(self._sse_stream(request_id, body.session_id), media_type="text/event-stream")

    async def _sse_stream(self, request_id: str, session_id: Optional[str]) -> AsyncGenerator[str, None]:
        store = self.get_response_store()  # InMemoryResponseStore — validated at IOHandler startup
        chunk_iterator = store.stream(request_id)
        try:
            while True:
                chunk = await asyncio.to_thread(next, chunk_iterator, None)
                if chunk is None:
                    return
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:  # TimeoutError from the store, or anything unexpected
            error_chunk = {"error": str(e), "done": True, "session_id": session_id}
            yield f"data: {json.dumps(error_chunk)}\n\n"

    async def run_multipart_chat(
        self,
        prompt: str = Form(...),
        agent: Optional[str] = Form(None),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        group_id: Optional[str] = Form(None),
        thread_name: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
        images: Optional[List[UploadFile]] = File(None),
    ):
        """POST /api/v1/chat-multipart — uploads become base64 FileData/ImageData and flow as JSON."""
        try:
            file_data = [
                FileData(file_data=await self._read_upload(upload), name=upload.filename or "unknown", mime_type=upload.content_type)
                for upload in files or []
            ]
            image_data = []
            for upload in images or []:
                if upload.content_type and not upload.content_type.startswith("image/"):
                    raise ValueError(f"Invalid image type: {upload.content_type}")
                image_data.append(
                    ImageData(image_data=await self._read_upload(upload), name=upload.filename or "unknown", mime_type=upload.content_type)
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"error": str(e), "session_id": session_id})

        request = BaseRunRequest(
            prompt=prompt,
            agent=agent,
            session_id=session_id,
            user_id=user_id,
            group_id=group_id,
            thread_name=thread_name,
            files=file_data or None,
            images=image_data or None,
        )
        return await self.run_chat(request)

    async def _read_upload(self, upload: UploadFile) -> str:
        content = await upload.read()
        if len(content) > self._config.api.max_file_size:
            raise ValueError(f"File {upload.filename} exceeds maximum size ({len(content) / (1024 * 1024):.2f} MB)")
        return base64.b64encode(content).decode("utf-8")
