import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
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

        router = APIRouter()

        @router.get("/api/v1/agents")
        def list_agents():
            from ..core.runtime import Runtime
            return {"agents": list(Runtime.current().agents().keys())}

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

    class BaseMultimodalRunRequest(BaseChatRequest):
        """Chat request with multipart file and image uploads (UploadFile format)."""

        files: Optional[List[UploadFile]] = None
        images: Optional[List[UploadFile]] = None
        model_config = ConfigDict(extra="allow")

    def __init__(self):
        self._log = logging.getLogger("ak.api.agent")
        self._max_file_size = Config.get().api.max_file_size
        self.chat_service = ChatService(rest_api_mode=True)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """

        router = APIRouter()

        @router.get("/api/v1/agents")
        def list_agents():
            return {"agents": list(Runtime.current().agents().keys())}

        @router.post("/api/v1/chat")
        async def run(body: BaseRunRequest):
            if Config.get().execution.mode == ExecutionMode.STREAM:
                try:
                    gen = await self.chat_service.process_stream_chat_async(req=body, sse_format=True)
                    return StreamingResponse(gen, media_type="text/event-stream")
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
            return await self.chat_service.process_async_chat_request(req=body)

        @router.post("/api/v1/chat-multipart")
        async def run_multipart(
            prompt: str = Form(...),
            agent: Optional[str] = Form(None),
            session_id: Optional[str] = Form(None),
            files: Optional[List[UploadFile]] = File(None),
            images: Optional[List[UploadFile]] = File(None),
        ):
            req = AgentRESTRequestHandler.BaseMultimodalRunRequest(
                prompt=prompt,
                agent=agent,
                session_id=session_id,
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

        return router
