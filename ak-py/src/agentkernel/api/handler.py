from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Annotated, List, Optional

from pydantic import ConfigDict

from ..core import Config
from ..core.chat_service import ChatService
from ..core.model import BaseChatRequest, BaseRunRequest, ExecutionMode
from ..core.runtime import Runtime


class RESTRequestHandler(ABC):
    @abstractmethod
    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance which has configured routes
        E.g.:
        - GET /api/v1/agents: List available agents

        def list_agents(self):
            from ..core.runtime import Runtime
            return {"agents": list(Runtime.current().agents().keys())}

        def get_router(self) -> APIRouter:
            router = APIRouter()
            router.add_api_route("/api/v1/agents", self.list_agents, methods=["GET"])
            return router

        """
        pass


class AgentRESTRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /api/v1/agents: List available agents
    - POST /api/v1/chat: Run an agent (streams SSE when execution.mode=stream, otherwise returns JSON)
    - POST /api/v1/chat-multipart: Same as /api/v1/chat but accepts multipart form data with file/image uploads
    """

    # Endpoint paths — shared with subclasses so route paths stay consistent.
    AGENTS_PATH = "/api/v1/agents"
    CHAT_PATH = "/api/v1/chat"
    CHAT_MULTIPART_PATH = "/api/v1/chat-multipart"

    class BaseMultimodalRunRequest(BaseChatRequest):
        """Chat request with multipart file and image uploads (UploadFile format)."""

        files: Optional[List[UploadFile]] = None
        images: Optional[List[UploadFile]] = None
        model_config = ConfigDict(extra="allow")

    @classmethod
    def _lazy_load_deps(cls):
        """Import fastapi lazily so it isn't required until a handler is actually constructed.

        ``BaseMultimodalRunRequest``'s ``UploadFile`` fields are left unresolved at class-definition
        time (forward refs, thanks to ``from __future__ import annotations``); ``model_rebuild()``
        here resolves them now that the real ``UploadFile`` is in the module's globals.
        """
        global APIRouter, File, Form, HTTPException, StreamingResponse, UploadFile
        from fastapi import APIRouter, File, Form, HTTPException, UploadFile
        from fastapi.responses import StreamingResponse

        cls.BaseMultimodalRunRequest.model_rebuild()

    def __init__(self):
        self._lazy_load_deps()
        self._log = logging.getLogger("ak.api.agent")
        self._max_file_size = Config.get().api.max_file_size
        self.chat_service = ChatService(rest_api_mode=True)

    def list_agents(self):
        return {"agents": list(Runtime.current().agents().keys())}

    async def run(self, body: BaseRunRequest):
        if Config.get().execution.mode == ExecutionMode.STREAM:
            try:
                gen = await self.chat_service.process_stream_chat_async(req=body, sse_format=True)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
        return await self.chat_service.process_async_chat_request(req=body)

    async def run_multipart(
        self,
        # Form(...)/File(...) live inside Annotated (the annotation), not as the plain default value —
        # with `from __future__ import annotations` that annotation is a lazy string, only resolved by
        # FastAPI when get_router() registers the route, by which point __init__ has already imported them.
        prompt: Annotated[str, Form()],
        agent: Annotated[Optional[str], Form()] = None,
        session_id: Annotated[Optional[str], Form()] = None,
        user_id: Annotated[Optional[str], Form()] = None,
        group_id: Annotated[Optional[str], Form()] = None,
        thread_name: Annotated[Optional[str], Form()] = None,
        files: Annotated[Optional[List[UploadFile]], File()] = None,
        images: Annotated[Optional[List[UploadFile]], File()] = None,
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
                gen = await self.chat_service.process_stream_chat_async(req=req, sse_format=True)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
        return await self.chat_service.process_async_chat_request(req=req)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()
        router.add_api_route(self.AGENTS_PATH, self.list_agents, methods=["GET"])
        router.add_api_route(self.CHAT_PATH, self.run, methods=["POST"])
        router.add_api_route(self.CHAT_MULTIPART_PATH, self.run_multipart, methods=["POST"])
        return router
