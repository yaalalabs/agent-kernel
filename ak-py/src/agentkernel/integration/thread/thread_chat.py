"""
Conversation Thread Support as an integration-style handler.

Two chat surfaces, one per execution topology, both mounted instead of the
default chat handler — mounting is what enables threads, on either:

    RESTAPI.run(handlers=[AgentThreadRequestHandler()])           # direct, in-process
    IOHandler.run(request_handler=ThreadRequestHandler())         # queue pipeline

AgentThreadRequestHandler runs the agent inside its own route, so it brackets
one call: pre_run -> execute -> post_run. ThreadRequestHandler cannot, because
the agent runs on the far side of the input queue: it records the user message
before enqueueing and marks the message, and AgentRunner records the reply.
Both serve the thread read routes.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ...api.handler import AgentRESTRequestHandler, AuthorisedRESTRequestHandler
from ...auth.authoriser import Authoriser
from ...core import Config
from ...core.chat_service import RequestBuilder, ResponseBuilder
from ...core.model import BaseChatRequest, BaseRunRequest, ExecutionMode, StreamChunk
from ...core.service import AgentService
from ...pipeline.envelope import ATTR_THREAD
from ...pipeline.producer import RequestProducer
from ...pipeline.request_handler import RequestHandler
from .manager import ConversationThreadManager
from .recorder import ThreadRecorder


class AgentThreadRequestHandler(AgentRESTRequestHandler):
    """
    Chat handler with Conversation Thread Support: the inherited chat routes gain
    thread recording around the ChatService execution core, and the thread read
    routes are served from the same handler. Applications enable threads by
    mounting this handler instead of the default AgentRESTRequestHandler; the
    'thread' config block only parameterizes the store backend and naming.

    Endpoints:
    - GET /api/v1/agents: List available agents
    - POST /api/v1/chat: Run an agent with thread recording (SSE when execution.mode=stream)
    - POST /api/v1/chat-multipart: Same as /api/v1/chat with multipart file/image uploads
    - GET /api/v1/threads: List threads (see ThreadRESTRequestHandler)
    - GET /api/v1/threads/{session_id}: Get a thread with message history
    """

    def __init__(self, authoriser: Optional[Authoriser] = None):
        """
        Initializes an AgentThreadRequestHandler instance. Fails fast when
        Conversation Thread Support is not configured.

        :param authoriser: Optional user-supplied Authoriser protecting the thread read routes.
        :raises ValueError: If no 'thread' block is present in the configuration.
        """
        super().__init__()
        self._log = logging.getLogger("ak.integration.thread")
        manager = ConversationThreadManager.get()
        if manager is None:
            raise ValueError("Conversation Thread Support is not configured. Add a 'thread' block to config.yaml")
        self._recorder = ThreadRecorder(manager)
        self._read_handler = ThreadRESTRequestHandler(authoriser=authoriser)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance: the inherited chat/agents routes plus the
        thread read routes.
        """
        router = super().get_router()
        router.include_router(self._read_handler.get_router())
        return router

    async def run(self, body: BaseRunRequest):
        if Config.get().execution.mode == ExecutionMode.STREAM:
            try:
                gen = await self._stream_with_recording(body)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
        return await self._run_with_recording(body)

    async def run_multipart(
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
        req = AgentRESTRequestHandler.BaseMultimodalRunRequest(
            prompt=prompt,
            agent=agent,
            session_id=session_id,
            user_id=user_id,
            group_id=group_id,
            thread_name=thread_name,
            files=files,
            images=images,
        )
        if Config.get().execution.mode == ExecutionMode.STREAM:
            try:
                gen = await self._stream_with_recording(req)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
        return await self._run_with_recording(req)

    async def _run_with_recording(self, req: BaseChatRequest):
        """Non-stream chat with thread recording around the ChatService core.

        :param req: The chat request (JSON body or multipart form)
        :return: The success response dict; errors raise HTTPException (rest_api_mode)
        """
        try:
            self._validate_chat_request(req)
            self._check_agent_available(req.agent)
            if req.schedule is not None:
                # A deferred request produces no conversation: the thread and its messages are
                # recorded when an occurrence actually runs, not when the schedule is created.
                result, session_id = await self.chat_service.execute(req)
                return ResponseBuilder.build_response(202, session_id, True, result=result)
            requests = await RequestBuilder.from_base_request_async(req)
            requests, _ = self._recorder.pre_run(req, requests)
            result, session_id = await self.chat_service.execute(req, requests=requests)
            self._recorder.post_run(req, result)
            return ResponseBuilder.build_response(200, session_id, True, result=result)
        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}")
            return ResponseBuilder.build_response(400, req.session_id, True, error=ve)
        except HTTPException:
            raise
        except Exception as e:
            self._log.error(f"Error processing request: {e}")
            return ResponseBuilder.build_response(500, req.session_id, True, error=e)

    async def _stream_with_recording(self, req: BaseChatRequest):
        """Streaming chat with thread recording: validates, records the user message,
        streams SSE frames, and appends the accumulated assistant message at stream
        end. A halted/errored stream (error chunk, no raise) or an empty one must not
        record a blank assistant message in the thread.

        :param req: The chat request
        :return: Async generator yielding SSE-formatted frames
        :raises ValueError: If validation fails, no agent is available, or pre_run rejects
        """
        self._validate_chat_request(req)
        self._check_agent_available(req.agent)
        if req.schedule is not None:
            return self._acknowledgement_frames(await self.chat_service.execute_stream(req), req.session_id)
        requests = await RequestBuilder.from_base_request_async(req)
        requests, _ = self._recorder.pre_run(req, requests)
        chunks = await self.chat_service.execute_stream(req, requests=requests)
        session_id = req.session_id
        recorder = self._recorder

        async def _stream():
            deltas: List[str] = []
            error_seen = False
            try:
                async for chunk in chunks:
                    if chunk.error:
                        error_seen = True
                    if chunk.delta:
                        deltas.append(chunk.delta)
                    yield ResponseBuilder.stream_chunk(chunk, session_id, sse_format=True)
                if not error_seen and deltas:
                    recorder.post_run(req, "".join(deltas))
            except Exception as e:
                error_chunk = StreamChunk(error=str(e), done=True)
                yield ResponseBuilder.stream_chunk(error_chunk, session_id, sse_format=True)

        return _stream()

    @staticmethod
    async def _acknowledgement_frames(chunks, session_id: Optional[str]):
        """Frame a deferred request's acknowledgement chunk as SSE, without any recording.

        :param chunks: The single-chunk stream returned by the ChatService for a deferred request
        :param session_id: Session identifier echoed on the frame
        :return: Async generator yielding the acknowledgement as one SSE frame
        """
        async for chunk in chunks:
            yield ResponseBuilder.stream_chunk(chunk, session_id, sse_format=True)

    @staticmethod
    def _validate_chat_request(req: BaseChatRequest) -> None:
        """Validate the request envelope before any thread write.

        :param req: The chat request to validate
        :raises ValueError: If session_id or prompt is missing
        """
        if not req.session_id:
            raise ValueError("No session_id is provided in the request")
        if not req.prompt:
            raise ValueError("No prompt provided in the request")

    @staticmethod
    def _check_agent_available(name: Optional[str]) -> None:
        """Agent-availability precheck before any thread write, keeping a missing agent
        from leaving a phantom thread with an unanswered user message. The rule itself is
        shared with the other commit-before-running surfaces (AgentService.ensure_agent_available).

        :param name: The requested agent name, or None for the default agent
        :raises ValueError: If no matching agent is available
        """
        AgentService.ensure_agent_available(name)


class ThreadRequestHandler(RequestHandler):
    """
    Pipeline chat handler with Conversation Thread Support: the queue-mode
    counterpart of AgentThreadRequestHandler. Mount it in place of the pipeline's
    own RequestHandler, which it extends, so the chat route stays a single route:

        IOHandler.run(request_handler=ThreadRequestHandler())

    The recording is split across the queue because the run is: the user message,
    the thread itself and the attachment offload happen here, before anything is
    enqueued, and AgentRunner appends the assistant message on the other side (it
    is the only process holding the reply). The `thread` message attribute carries
    that intent across, so a request enqueued by any other producer grows no thread.

    Endpoints: the inherited pipeline chat/agents/poll routes, plus the thread read
    routes (see ThreadRESTRequestHandler).
    """

    def __init__(self, authoriser: Optional[Authoriser] = None):
        """
        :param authoriser: Optional user-supplied Authoriser protecting the thread read routes.
        :raises ValueError: If no 'thread' block is present in the configuration.
        """
        super().__init__()
        self._log = logging.getLogger("ak.integration.thread.pipeline")
        manager = ConversationThreadManager.get()
        if manager is None:
            raise ValueError("Conversation Thread Support is not configured. Add a 'thread' block to config.yaml")
        self._recorder = ThreadRecorder(manager)
        self._read_handler = ThreadRESTRequestHandler(authoriser=authoriser)

    def get_router(self) -> APIRouter:
        """The inherited pipeline chat routes plus the thread read routes."""
        router = super().get_router()
        router.include_router(self._read_handler.get_router())
        return router

    def _enqueue_request(self, body: BaseRunRequest, request_id: str):
        """Enqueue, marking the message for reply recording unless the request was deferred.

        A `schedule` block registers a task instead of running it, so there is no exchange to
        record — and the 202 acknowledgement must never be appended to a thread as if the agent
        had said it. Its occurrences reach the queue from the schedule provider, which stamps no
        thread marker, so they are not recorded either.
        """
        attributes = {} if body.schedule is not None else {ATTR_THREAD: "1"}
        return RequestProducer(self.get_transport()).enqueue(body, request_id, attributes=attributes)

    async def run_chat(self, body: BaseRunRequest):
        """POST /api/v1/chat: record the user message, then enqueue as the pipeline normally does."""
        if not body.session_id:
            raise HTTPException(status_code=400, detail={"error": "No session_id is provided in the request"})
        if not body.prompt:
            raise HTTPException(status_code=400, detail={"error": "No prompt provided in the request", "session_id": body.session_id})
        if body.schedule is None:
            await self._record_user_message(body)
        return await super().run_chat(body)

    async def _record_user_message(self, body: BaseRunRequest) -> None:
        """Do the pre-run thread work at the edge and rewrite the body for the queue.

        The rebuilt request list replaces `files`/`images` on the body: `pre_run` has already
        stored the bytes and swapped in AgentRequestAttachmentRef entries, so leaving the
        originals on the body would send every attachment through the broker a second time
        (where a real broker's message-size limit is waiting), for a field the runner ignores
        once `requests` is set.

        :param body: The chat request, mutated in place into its queue-ready form.
        :raises HTTPException: 400 when the agent is unavailable, `user_id` is missing, or the
            attachment configuration rejects the request — all of them before any thread write,
            so an unanswerable request leaves no phantom thread behind.
        """
        try:
            AgentService.ensure_agent_available(body.agent)
            requests = await RequestBuilder.from_base_request_async(body)
            requests, _ = self._recorder.pre_run(body, requests)
        except ValueError as e:
            self._log.error(f"Rejected before recording: {e}")
            raise HTTPException(status_code=400, detail={"error": str(e), "session_id": body.session_id})
        body.requests = requests
        body.files = None
        body.images = None


class ThreadRESTRequestHandler(AuthorisedRESTRequestHandler):
    """
    API router that exposes endpoints to read conversation threads.
    Endpoints:
    - GET /api/v1/threads: List threads filtered by user_id and/or group_id
    - GET /api/v1/threads/{session_id}: Get a thread with full message history

    Threads are renamed via the chat request's thread_name field, not through
    this router. When an Authoriser is supplied, every request must carry a
    Bearer token that the Authoriser resolves to a user_id (the inherited
    _resolve_user); listings are scoped to that user and thread reads enforce
    ownership. Without an Authoriser, routes are open.
    """

    def __init__(self, authoriser: Optional[Authoriser] = None):
        """
        Initializes a ThreadRESTRequestHandler instance.
        :param authoriser: Optional user-supplied Authoriser protecting the thread routes.
        """
        super().__init__(authoriser)
        self._log = logging.getLogger("ak.api.thread")

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/api/v1/threads")
        def list_threads(
            request: Request,
            user_id: Optional[str] = None,
            group_id: Optional[str] = None,
            limit: Optional[int] = None,
            cursor: Optional[str] = None,
        ):
            manager = ConversationThreadManager.get()
            if manager is None:
                raise HTTPException(status_code=404, detail="Thread support is not enabled")
            resolved_user_id = self._resolve_user(request)
            if resolved_user_id is not None:
                user_id = resolved_user_id  # listings are forced to the authorised user
            try:
                page = manager.list_threads(user_id=user_id, group_id=group_id, limit=limit, cursor=cursor)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {
                "threads": [thread.model_dump(mode="json", exclude={"messages"}) for thread in page.threads],
                "next_cursor": page.next_cursor,
            }

        @router.get("/api/v1/threads/{session_id}")
        def get_thread(session_id: str, request: Request, limit: Optional[int] = None, cursor: Optional[str] = None):
            manager = ConversationThreadManager.get()
            if manager is None:
                raise HTTPException(status_code=404, detail="Thread support is not enabled")
            resolved_user_id = self._resolve_user(request)
            try:
                thread = manager.get_thread(session_id, user_id=resolved_user_id)
            except PermissionError:
                raise HTTPException(status_code=403, detail="Thread is not owned by the authorised user")
            if thread is None:
                raise HTTPException(status_code=404, detail=f"Thread {session_id} not found")
            try:
                page = manager.get_messages(session_id, limit=limit, cursor=cursor)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            body = thread.model_dump(mode="json", exclude={"messages"})
            body["messages"] = [message.model_dump(mode="json") for message in page.messages]
            body["next_cursor"] = page.next_cursor
            return body

        return router
