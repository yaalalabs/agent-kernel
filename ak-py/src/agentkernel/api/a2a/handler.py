import contextvars
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import AgentCard
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Match, Route
from starlette.types import Scope

from ...core.model import Principal
from ...core.registry import AgentNotFoundError
from ...core.runtime import Runtime
from ...identity.provider.request import RequestAuthenticator
from .a2a import A2A


class AKCallContextBuilder(DefaultServerCallContextBuilder):
    """Carries the request's principal into the SDK's call context.

    The A2A routers are included by ``RESTAPI``, so the identity dependency has already put the
    principal on ``request.state`` when the SDK builds the context for a call; the executor reads
    it from ``call_context.state["principal"]`` (spec #603, section 8.7). The SDK's own state
    (headers, the auth scope) is kept.
    """

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        context.state["principal"] = getattr(request.state, "principal", None)
        return context


class UnservedA2ARoute(APIRoute):
    """The route behind every agent's own: it takes whatever under ``/a2a/<name>/`` no A2A route served.

    An agent's routes are mounted under its own id, so the router itself answers differently for a
    name that is mounted and one that is not, before any check of Agent Kernel's runs: a method a
    route does not serve is a 405 naming the methods it does, and a credential the provider refuses
    is a 401 from the identity dependency, where an unmounted name is a 404 either way. With an
    ``authorization`` block those answers tell anyone whether a hidden agent exists. This route is
    what an unmounted name, an unserved path and an unserved method all fall through to, so they
    get one answer, and being an ordinary route it sits behind the identity dependency like the rest.

    It claims the request whatever the method. A route that matched the path and not the method is
    only a second choice, and the router would prefer an agent's own route that matched the same
    way, whose 405 names that route's methods. A method outside ``METHODS`` (one that is no HTTP
    method) is then this route's own 405, the same for every name.

    It stands aside without an ``authorization`` block, where nothing is hidden and the router's
    own answers are the ones a client should get, and for a path with nothing after the name, so
    the catalog's trailing-slash redirect is left alone.
    """

    METHODS: ClassVar[tuple[str, ...]] = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE")
    """
    The methods the route answers with its 404: every method an HTTP client sends
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match is Match.NONE:
            return match, child_scope
        # The path is under /a2a/<name>/ from here on, so the gate is asked about for those requests alone.
        if not child_scope["path_params"].get("rest") or Runtime.access_gate() is None:
            return Match.NONE, {}
        return Match.FULL, child_scope


class A2ARESTRequestHandler:
    """
    Minimal A2A REST endpoints backed by ak.a2a.A2A utilities. Serves A2A 1.0 only.
    Endpoints:
    - GET /a2a/catalog: Get cards of all agents

    The following endpoints are available per each agent:
    - GET /a2a/{agent_name}/.well-known/agent-card.json - Agent card download
    - POST /a2a/{agent_name}/message:send - Send a message to the agent
    - POST /a2a/{agent_name}/message:stream - Stream a message to the agent (refused: cards declare no streaming)
    - POST /a2a/{agent_name}/tasks/{id}:cancel - Cancel a specific task
    - GET|POST /a2a/{agent_name}/tasks/{id}:subscribe - Subscribe to task updates
    - GET /a2a/{agent_name}/tasks/{id} - Get task details
    - GET|DELETE /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs/{push_id} - Get or delete a push notification config
    - POST /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs - Set push notification config
    - GET /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs - List push notifications
    - GET /a2a/{agent_name}/tasks - List all tasks
    - GET /a2a/{agent_name}/extendedAgentCard - Get authenticated agent card (if supported)

    With an ``authorization`` block every route answers for the caller (spec #603, section 8.7). The
    catalog lists the cards of the agents the caller may see, and a card carries the skills it is
    offered. An agent the caller may not see answers 404 on all of its routes, card included, with
    the response of a path that is not mounted, so a hidden agent is not told apart from one that
    does not exist. An agent it may see and holds no level on serves its card and answers 403 on
    the protocol routes, before the SDK or the executor is reached. Every other request under
    ``/a2a/<name>/`` (a name that is not mounted, a path or a method no route serves) gets that same
    404 from one route behind the agents' own (``UnservedA2ARoute``), so neither a wrong method nor a
    refused credential tells a mounted name from one that is not. Without the block nothing here
    changes what is served.
    """

    VARY_BY_CALLER = "Authorization"
    """
    The ``Vary`` value of a response that depends on who asked: the catalog and a card, under an
    ``authorization`` block. A shared cache must not serve one caller's card to another
    """

    _log = logging.getLogger("ak.api.a2a")
    _card_caller: ClassVar[contextvars.ContextVar[Principal | None]] = contextvars.ContextVar("ak_a2a_card_caller", default=None)
    """
    The caller of the card request being served, for the SDK's ``card_modifier``, which is handed the card
    and not the request
    """

    @staticmethod
    def _caller(request: Request) -> Principal:
        """
        The principal a request acts as: the one the identity dependency put on it, else the request's
        contextvar, else the anonymous principal (a router mounted with no identity dependency).

        :param request: The incoming request.
        :return: The caller's principal.
        """
        principal = getattr(request.state, "principal", None)
        if isinstance(principal, Principal):
            return principal
        return RequestAuthenticator.current() or Principal.anonymous()

    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        router = APIRouter(prefix="/a2a")  # Update the configs to reflect the correct Agent URL

        @router.get("/catalog")
        def list_cards(request: Request, response: Response) -> dict[str, Any]:
            """The cards of the agents served over A2A: every one, or with an ``authorization`` block the caller's own."""
            if Runtime.access_gate() is not None:
                cls._vary_by_caller(response)
            cards = A2A.get_cards(cls._caller(request))
            card_dicts = [agent_card_to_dict(card) for card in cards]

            return {"cards": card_dicts}

        return router

    @classmethod
    def get_agent_routers(cls) -> list[APIRouter]:
        routers = []
        for agent in A2A.get_agent_names():
            card = A2A.get_card(agent)
            request_handler = DefaultRequestHandler(
                agent_executor=A2A.get_executor(agent),
                task_store=A2A.get_task_store(),
                agent_card=card,
            )
            router = APIRouter(prefix=f"/a2a/{agent}")
            # A2A protocol mandated routes: using the agent, so each asks the access gate first
            for route in create_rest_routes(request_handler, context_builder=AKCallContextBuilder()):
                cls._add_route(router, route, dependencies=[Depends(cls._usable_by_the_caller(agent))])
            # then the agent's well-known card: seeing the agent is enough, and the card is the caller's own
            for route in create_agent_card_routes(card, card_modifier=cls._card_of_the_caller(agent)):
                cls._add_route(router, route, endpoint=cls._card_endpoint(route.endpoint))
            routers.append(router)
        # Last, so every route above is tried first: what none of them served, whatever the name.
        routers.append(cls._unserved_router())
        return routers

    @classmethod
    def _unserved_router(cls) -> APIRouter:
        """
        The router that answers for every A2A path and method the agents' routers did not serve.

        One route, ``UnservedA2ARoute``, which answers the 404 of a path that is not mounted. It is
        returned after the agents' routers and must be included after them. Included like them, it
        runs the identity dependency first, so a refused credential is a 401 for every name.

        :return: The router.
        """
        router = APIRouter(prefix="/a2a", route_class=UnservedA2ARoute)

        @router.api_route("/{agent_name}/{rest:path}", methods=list(UnservedA2ARoute.METHODS), include_in_schema=False)
        async def unserved(agent_name: str, rest: str) -> None:
            """Answer as a path that is not mounted, with no detail of our own."""
            raise HTTPException(status_code=404)

        return router

    @classmethod
    def _usable_by_the_caller(cls, agent: str) -> Callable[[Request], Awaitable[None]]:
        """
        The dependency in front of an agent's protocol routes: whether the caller may use the agent.

        Asked before the SDK parses anything, so a refusal is an HTTP answer and nothing reaches the
        executor. The agent is decided by the descriptor its routes were mounted with, with no registry
        read. A no-op without an ``authorization`` block.

        :param agent: The agent id the router serves.
        :return: The dependency, raising 404 with the body of a path that is not mounted for an agent
            the caller may not see, and 403 with the gate's reason for one it sees and holds no level on.
        """

        async def usable_by_the_caller(request: Request) -> None:
            gate = Runtime.access_gate()
            if gate is None:
                return
            try:
                await gate.authorize_agent_async(cls._caller(request), agent, descriptor=A2A.get_descriptor(agent))
            except AgentNotFoundError:
                # No detail of our own: the answer of a route that does not exist, which is what the caller is to see.
                raise HTTPException(status_code=404) from None
            except PermissionError as refusal:
                raise HTTPException(status_code=403, detail=str(refusal)) from None

        return usable_by_the_caller

    @classmethod
    def _card_of_the_caller(cls, agent: str) -> Callable[[AgentCard], Awaitable[AgentCard]]:
        """
        The SDK's per-request card modifier for an agent: the card as the request's caller is served it.

        The SDK computes the card's ``ETag`` after this, so the tag is of the card as served and two
        callers offered different skills never share one. A caller with no card to be served (the
        agent is hidden from it) gets the 404 of a path that is not mounted: the one place the
        card is decided, so a request asks about it once.

        :param agent: The agent id.
        :return: The modifier.
        """

        async def card_of_the_caller(card: AgentCard) -> AgentCard:
            shown = await A2A.card_for(cls._card_caller.get(), agent)
            if shown is None:
                # No detail of our own: the answer of a route that does not exist.
                raise HTTPException(status_code=404)
            return shown

        return card_of_the_caller

    @classmethod
    def _card_endpoint(cls, serve_card: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        """
        Wrap the SDK's card endpoint so that it answers for the caller.

        Without an ``authorization`` block it is the SDK's endpoint, unchanged. With one, the SDK's
        modifier is told who is asking (it is handed the card, not the request), so the card and its
        ``ETag`` are the caller's own, and every answer (the card, or a 304 for it) says that it
        varies by caller. A caller who may not see the agent gets the modifier's 404.

        :param serve_card: The SDK's endpoint, built with ``_card_of_the_caller`` as its modifier.
        :return: The endpoint to mount.
        """

        async def agent_card(request: Request) -> Response:
            if Runtime.access_gate() is None:
                return await serve_card(request)
            asked_by = cls._card_caller.set(cls._caller(request))
            try:
                response = await serve_card(request)
            finally:
                cls._card_caller.reset(asked_by)
            cls._vary_by_caller(response)
            return response

        return agent_card

    @classmethod
    def _vary_by_caller(cls, response: Response) -> None:
        """
        Mark a response as depending on who asked, keeping whatever it already varies by.

        :param response: The response about to be sent.
        """
        varies_by = [value.strip() for value in response.headers.get("Vary", "").split(",") if value.strip()]
        if cls.VARY_BY_CALLER.lower() not in (value.lower() for value in varies_by):
            response.headers["Vary"] = ", ".join([*varies_by, cls.VARY_BY_CALLER])

    @classmethod
    def _add_route(
        cls, router: APIRouter, route: BaseRoute, *, endpoint: Callable[..., Any] | None = None, dependencies: list[Any] | None = None
    ) -> None:
        """
        Re-register one of the SDK's Starlette routes on the agent's router.

        Only plain routes are served: the SDK's ``/{tenant}`` mount is skipped, since Agent Kernel
        serves no multi-tenant A2A. HEAD is dropped, as the SDK's own FastAPI helper does, because
        Starlette adds it beside GET and FastAPI would register a duplicate operation id.
        :param router: The agent's router.
        :param route: A route from the SDK's route factories.
        :param endpoint: The endpoint to serve the route with; the SDK's own when omitted.
        :param dependencies: Dependencies to run before the endpoint.
        """
        if not isinstance(route, Route) or not route.methods:
            cls._log.debug(f"Skipping A2A route {type(route).__name__} {getattr(route, 'path', '')}")
            return
        router.add_api_route(
            route.path, endpoint or route.endpoint, methods=sorted(m for m in route.methods if m != "HEAD"), dependencies=dependencies
        )
