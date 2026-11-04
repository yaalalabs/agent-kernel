import logging
from typing import List

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from fastapi import APIRouter
from starlette.routing import BaseRoute, Route

from .a2a import A2A


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
    """

    _log = logging.getLogger("ak.api.a2a")

    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        router = APIRouter(prefix="/a2a")  # Update the configs to reflect the correct Agent URL

        @router.get("/catalog")
        def list_cards():
            cards = A2A.get_cards()
            card_dicts = [agent_card_to_dict(card) for card in cards]

            return {"cards": card_dicts}

        return router

    @classmethod
    def get_agent_routers(cls) -> List[APIRouter]:
        routers = []
        for agent in A2A.get_agent_names():
            card = A2A.get_card(agent)
            request_handler = DefaultRequestHandler(
                agent_executor=A2A.get_executor(agent),
                task_store=A2A.get_task_store(),
                agent_card=card,
            )
            router = APIRouter(prefix=f"/a2a/{agent}")
            # A2A protocol mandated routes, then the agent's well-known (public) card
            for route in [*create_rest_routes(request_handler), *create_agent_card_routes(card)]:
                cls._add_route(router, route)
            routers.append(router)
        return routers

    @classmethod
    def _add_route(cls, router: APIRouter, route: BaseRoute) -> None:
        """
        Re-register one of the SDK's Starlette routes on the agent's router.

        Only plain routes are served: the SDK's ``/{tenant}`` mount is skipped, since Agent Kernel
        serves no multi-tenant A2A. HEAD is dropped, as the SDK's own FastAPI helper does, because
        Starlette adds it beside GET and FastAPI would register a duplicate operation id.
        :param router: The agent's router.
        :param route: A route from the SDK's route factories.
        """
        if not isinstance(route, Route) or not route.methods:
            cls._log.debug(f"Skipping A2A route {type(route).__name__} {getattr(route, 'path', '')}")
            return
        router.add_api_route(route.path, route.endpoint, methods=sorted(m for m in route.methods if m != "HEAD"))
