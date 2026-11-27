import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ConfigDict

from ..core import Config
from ..core.chat_service import ChatService
from ..core.model import USER_ID_NOT_A_FIELD, BaseChatRequest, ChatRunRequest, Principal
from ..core.registry import AgentDescriptorPage, AgentNotFoundError
from ..core.runtime import Runtime
from ..core.util.factory import AKConfigError
from ..core.util.pagination import decode_cursor
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

    @staticmethod
    def _validate_access() -> None:
        """
        Check the `authorization` policy against the agents this process hosts and the registry, as the
        routes are mounted. A no-op without the block. A handler whose routes run agents calls it first
        in `get_router()`: the chat handlers and the AG-UI handlers do.

        Mounting is where a process starts serving its agents with every module loaded, so this is the
        check that can compare the policy with the whole registry (`Module.load` checks each module's own
        agents as it loads, when later modules have not registered): a grant naming an agent or a tag no
        descriptor carries is warned about here. A process that hosts no agent, the accepting side of a
        split deployment, makes only those registry-wide findings.
        :raises AKConfigError: If the policy cannot be enforced for a hosted agent: a tool policy naming a
            tool the agent does not have, or an agent with tools Agent Kernel cannot gate.
        """
        gate = Runtime.access_gate()
        if gate is not None:
            gate.validate_configuration(Runtime.current().registry.agents().values())


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

    def list_agents(
        self, request: Request, cursor: str | None = None, limit: int | None = None, tags: Annotated[list[str] | None, Query()] = None
    ) -> dict[str, Any]:
        """
        The agent catalog: one page of the descriptors of the agents exposed on the REST surface, ordered by id.
        Served from the registry, so it lists agents this process does not host. An entry is the agent's
        descriptor without its `identity`, which is the agent's own and not a caller's to read.

        With an `authorization` block the catalog is the caller's own: the agents its principal holds a level
        on or whose visibility admits it, each entry's `tools` the ones it is offered and its `skills`
        narrowed with them. An agent the caller may not see is left out before the page is cut, so a page is
        never short because of it. Without the block every agent on the surface is listed whole.
        :param request: The incoming request; the identity dependency put the caller's principal on it.
        :param cursor: The `next_cursor` of the page before; omitted for the first page.
        :param limit: The page size, clamped to the shared maximum.
        :param tags: Keep only the agents carrying every one of these tags (repeat the parameter for several).
        :return: `{"agents": [<catalog entry>, ...], "next_cursor": <cursor or null>}`.
        :raises HTTPException: 400 for a malformed cursor.
        """
        try:
            # Before the registry is read: a malformed cursor is the caller's 400 whatever the store answers.
            decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        gate = Runtime.access_gate()
        # A router mounted on a bare app has no principal on the request: the caller is nobody.
        principal = getattr(request.state, "principal", None) or Principal.anonymous()
        known = Runtime.current().registry.descriptors() if gate is None else gate.visible_agents(principal)
        page = AgentDescriptorPage.of([descriptor for descriptor in known if descriptor.exposed_on("rest")], cursor=cursor, limit=limit, tags=tags)
        if gate is not None:
            # Only what the page shows: narrowing asks the authorizer about each agent's tools.
            page = page.model_copy(update={"agents": gate.narrow(principal, page.agents)})
        return page.catalog()

    async def run(self, body: ChatRunRequest, request: Request):
        # The surface decides who is calling: a principal the client put in the body is overwritten
        # with the one the identity dependency RESTAPI installs put on the request (the anonymous
        # principal without an identity block). The default covers a router mounted on a bare app.
        body.principal = getattr(request.state, "principal", None)
        # And where the request came in: only an agent whose descriptor is on `rest` is served to it.
        body.surface = "rest"
        if Config.get().execution.is_sse:
            return await self._stream_reply(body, lambda: self.chat_service.process_stream_chat_async(req=body, sse_format=True))
        return await self._reply(body, lambda: self.chat_service.process_async_chat_request(req=body))

    @staticmethod
    async def _stream_reply(req: BaseChatRequest, start: Callable[[], Awaitable[AsyncGenerator[str, None]]]) -> StreamingResponse:
        """
        Start a run's SSE stream and answer with it, mapping a refusal raised before the stream starts to its status.

        A refused request's credential is released (#603): no run took it over. Once the stream starts, the run owns it
        and ``Runtime.stream`` releases it.

        :param req: The chat request.
        :param start: Starts the stream; raises what the chat service refuses with.
        :return: The streaming response.
        :raises HTTPException: 400, 403, 404 or 500 for a request refused before the stream starts.
        """
        from ..identity.credential.manager import CredentialManager

        try:
            async with CredentialManager.released_on_error(req.principal):
                gen = await start()
            return StreamingResponse(gen, media_type="text/event-stream")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except AgentNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")

    @staticmethod
    async def _reply(req: BaseChatRequest, answer: Callable[[], Awaitable[Any]]) -> Any:
        """
        Answer a chat request in this process. The run, if one started, is over when this returns, so the credential
        is released however it ended (#603): a request refused before its run is not left for ``Runtime`` to release,
        and for one that ran the second delete is a no-op.

        :param req: The chat request.
        :param answer: Produces the reply.
        :return: The reply.
        """
        from ..identity.credential.manager import CredentialManager

        try:
            return await answer()
        finally:
            await CredentialManager.release_unclaimed(req.principal)

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
            from ..identity.credential.manager import CredentialManager

            await CredentialManager.release_unclaimed(getattr(request.state, "principal", None))
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
            surface="rest",
        )
        if Config.get().execution.is_sse:
            return await self._stream_reply(req, lambda: self.chat_service.process_stream_chat_async(req=req, sse_format=True))
        return await self._reply(req, lambda: self.chat_service.process_async_chat_request(req=req))

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        :raises AKConfigError: If an `authorization` block cannot be enforced for an agent this process hosts.
        """
        self._validate_access()
        router = APIRouter()
        router.add_api_route(self.AGENTS_PATH, self.list_agents, methods=["GET"])
        router.add_api_route(self.CHAT_PATH, self.run, methods=["POST"])
        router.add_api_route(self.CHAT_MULTIPART_PATH, self.run_multipart, methods=["POST"])
        return router
