import logging
from abc import ABC, abstractmethod

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ConfigDict

from ..core import Config
from ..core.chat_service import ChatService
from ..core.model import USER_ID_NOT_A_FIELD, BaseChatRequest, ChatRunRequest, Principal
from ..core.runtime import Runtime
from ..core.util.factory import AKConfigError
from ..identity.provider.factory import IdentityProviderFactory
from ..identity.provider.request import BEARER_CHALLENGE


class RESTRequestHandler(ABC):
    requires_pipeline: bool = False
    # True for a handler whose routes verify their own callers, such as a messaging platform's signed
    # webhook: RESTAPI mounts its router without the identity dependency, so a platform credential in
    # ``Authorization`` (a Teams Bot Framework token) reaches the handler's check instead of a 401.
    authenticates_itself: bool = False

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


class AuthorisedRESTRequestHandler(RESTRequestHandler):
    """
    Base for route handlers that serve authenticated callers only: the ones that run an agent on
    a caller's behalf or manage records a caller owns (conversation threads, scheduled tasks,
    AG-UI). The identity dependency ``RESTAPI`` installs on every router has already turned the
    request's credential into ``request.state.principal`` (spec #603, section 8.2); this base
    reads it back and refuses the anonymous principal, so the routes never have to parse a
    header. Because the routes are meaningless without someone to authenticate, construction
    requires an ``identity`` block.
    """

    def __init__(self):
        """
        Initializes an AuthorisedRESTRequestHandler instance.
        :raises AKConfigError: If no identity provider is configured. With nobody able to
            authenticate, mounting the routes is a configuration error rather than an open surface.
        """
        if IdentityProviderFactory.get() is None:
            raise AKConfigError(f"{type(self).__name__} requires an identity block: it serves authenticated callers only")

    @staticmethod
    def _resolve_user(request: Request) -> Principal:
        """
        Resolve the caller: the principal the identity dependency put on the request.
        :param request: The incoming FastAPI request.
        :return: The authenticated principal.
        :raises HTTPException: 401 when the request carries no authenticated principal (no
            credential, or a router mounted without the identity dependency).
        """
        principal = getattr(request.state, "principal", None)
        if principal is None or principal.is_anonymous:
            raise HTTPException(status_code=401, detail="Authentication required", headers=BEARER_CHALLENGE)
        return principal


class AgentRESTRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /api/v1/agents: List available agents
    - POST /api/v1/chat: Run an agent (streams SSE when execution.message_type is delta, otherwise returns JSON)
    - POST /api/v1/chat-multipart: Same as /api/v1/chat but accepts multipart form data with file/image uploads
    """

    # Endpoint paths — shared with subclasses so route paths stay consistent.
    AGENTS_PATH = "/api/v1/agents"
    CHAT_PATH = "/api/v1/chat"
    CHAT_MULTIPART_PATH = "/api/v1/chat-multipart"

    class BaseMultimodalRunRequest(BaseChatRequest):
        """Chat request with multipart file and image uploads (UploadFile format)."""

        files: list[UploadFile] | None = None
        images: list[UploadFile] | None = None
        model_config = ConfigDict(extra="allow")

    def __init__(self):
        self._log = logging.getLogger("ak.api.agent")
        self._max_file_size = Config.get().api.max_file_size
        self.chat_service = ChatService(rest_api_mode=True)

    def list_agents(self):
        return {"agents": list(Runtime.current().agents().keys())}

    async def run(self, body: ChatRunRequest, request: Request):
        # The surface decides who is calling: a principal the client put in the body is overwritten
        # with the one the identity dependency RESTAPI installs put on the request (the anonymous
        # principal without an identity block). The default covers a router mounted on a bare app.
        body.principal = getattr(request.state, "principal", None)
        if Config.get().execution.is_sse:
            try:
                gen = await self.chat_service.process_stream_chat_async(req=body, sse_format=True)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except PermissionError as e:
                raise HTTPException(status_code=403, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")
        return await self.chat_service.process_async_chat_request(req=body)

    @staticmethod
    async def _reject_user_id_form(request: Request) -> None:
        """Refuse a multipart form carrying ``user_id``, as a JSON body carrying it is refused.

        FastAPI drops a form field the route does not declare, so without reading the raw form a
        client sending the old field would get a 200 and silently act as nobody. The form is
        already parsed and cached on the request, so this costs no second read.

        :param request: The incoming request.
        :raises ValueError: If the form carries ``user_id``.
        """
        if "user_id" in await request.form():
            raise ValueError(USER_ID_NOT_A_FIELD)

    async def run_multipart(
        self,
        request: Request,
        prompt: str = Form(...),
        agent: str | None = Form(None),
        session_id: str | None = Form(None),
        group_id: str | None = Form(None),
        thread_name: str | None = Form(None),
        files: list[UploadFile] | None = File(None),
        images: list[UploadFile] | None = File(None),
    ):
        try:
            await self._reject_user_id_form(request)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        req = AgentRESTRequestHandler.BaseMultimodalRunRequest(
            prompt=prompt,
            agent=agent,
            session_id=session_id,
            group_id=group_id,
            thread_name=thread_name,
            files=files,
            images=images,
            principal=getattr(request.state, "principal", None),
        )
        if Config.get().execution.is_sse:
            try:
                gen = await self.chat_service.process_stream_chat_async(req=req, sse_format=True)
                return StreamingResponse(gen, media_type="text/event-stream")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except PermissionError as e:
                raise HTTPException(status_code=403, detail=str(e))
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
