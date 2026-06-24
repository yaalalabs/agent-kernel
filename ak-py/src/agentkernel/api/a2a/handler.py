import logging
from typing import List

from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH
from fastapi import APIRouter
from google.protobuf.json_format import MessageToDict
from starlette.routing import Route as StarletteRoute

from .a2a import A2A


class A2ARESTRequestHandler:
    """
    Minimal A2A REST endpoints backed by ak.a2a.A2A utilities.
    Endpoints:
    - GET /a2a/catalog: Get cards of all agents

    The following endpoints are available per each agent:
    - GET /a2a/{agent_name}/.well-known/agent-card.json - Agent card download
    - POST /a2a/{agent_name}/message:send - Send a message to the agent
    - POST /a2a/{agent_name}/message:stream - Stream a message to the agent
    - POST /a2a/{agent_name}/tasks/{id}:cancel - Cancel a specific task
    - GET /a2a/{agent_name}/tasks/{id}:subscribe - Subscribe to task updates
    - GET /a2a/{agent_name}/tasks/{id} - Get task details
    - GET /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs/{push_id} - Get push notification config
    - POST /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs - Set push notification config
    - GET /a2a/{agent_name}/tasks/{id}/pushNotificationConfigs - List push notifications
    - GET /a2a/{agent_name}/tasks - List all tasks
    - GET /a2a/{agent_name}/extendedAgentCard - Get authenticated agent card (if supported)
    """

    _log = logging.getLogger("ak.api.a2a")

    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        router = APIRouter(prefix="/a2a")

        @router.get("/catalog")
        def list_cards():
            cards = A2A.get_cards() or []
            result = []
            for c in cards:
                result.append(MessageToDict(c))
            return {"cards": result}

        return router

    @classmethod
    def get_agent_routers(cls) -> List[APIRouter]:
        agents = A2A.get_agent_names()
        routers = []
        for agent in agents:
            handler = DefaultRequestHandlerV2(
                agent_executor=A2A.get_executor(agent),
                task_store=A2A.get_task_store(),
                agent_card=A2A.get_card(agent),
            )
            router = APIRouter(prefix=f"/a2a/{agent}")
            for route in create_rest_routes(handler):
                if isinstance(route, StarletteRoute):
                    router.add_api_route(route.path, route.endpoint, methods=list(route.methods or []), include_in_schema=False)
            routers.append(router)

        # Create the well-known (public) endpoint
        card_router = APIRouter(prefix="/a2a")

        @card_router.get(f"/{{agent_name}}{AGENT_CARD_WELL_KNOWN_PATH}")
        async def get_agent_card(agent_name: str):
            from fastapi import HTTPException

            card = A2A.get_card(agent_name)
            if card is None:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
            return MessageToDict(card)

        routers.append(card_router)
        return routers
