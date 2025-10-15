import logging
from typing import List

from a2a.server.apps.rest.rest_adapter import RESTAdapter
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH
from fastapi import APIRouter
from pydantic import BaseModel

from ..a2a.a2a import A2A


class A2ARESTRequestHandler:
    """
    Minimal A2A REST endpoints backed by ak.a2a.A2A utilities.
    Endpoints:
    - GET /a2a/catalog: Get cards of all agents

    The following endpoints are available per each agent:
    - GET /a2a/{agent_name}/.well-known/agent-card.json - Agent card download
    - POST /a2a/{agent_name}/v1/message:send - Send a message to the agent
    - POST /a2a/{agent_name}/v1/message:stream - Stream a message to the agent
    - POST /a2a/{agent_name}/v1/tasks/{id}:cancel - Cancel a specific task
    - GET /a2a/{agent_name}/v1/tasks/{id}:subscribe - Subscribe to task updates
    - GET /a2a/{agent_name}/v1/tasks/{id} - Get task details
    - GET /a2a/{agent_name}/v1/tasks/{id}/pushNotificationConfigs/{push_id} - Get push notification config
    - POST /a2a/{agent_name}/v1/tasks/{id}/pushNotificationConfigs - Set push notification config
    - GET /a2a/{agent_name}/v1/tasks/{id}/pushNotificationConfigs - List push notifications
    - GET /a2a/{agent_name}/v1/tasks - List all tasks
    - GET /a2a/{agent_name}/v1/card - Get authenticated agent card (if supported)
    """

    _log = logging.getLogger("ak.api.a2a")

    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        router = APIRouter(prefix="/a2a")  # Update the configs to reflect the correct Agent URL

        @router.get("/catalog")
        def list_cards():
            cards: List[BaseModel] = A2A.get_cards() or []
            result = []
            for c in cards:
                result.append(c.model_dump())
            return {"cards": result}

        return router

    @classmethod
    def get_agent_routers(cls) -> List[APIRouter]:
        agents = A2A.get_agent_names()
        routers = []
        for agent in agents:
            adapter = RESTAdapter(
                agent_card=A2A.get_card(agent),
                http_handler=DefaultRequestHandler(
                    agent_executor=A2A.get_executor(agent),
                    task_store=A2A.get_task_store()
                )
            )
            router = APIRouter(prefix=f"/a2a/{agent}")
            # Create A2A protocol mandated routes including authenticated card
            for route, callback in adapter.routes().items():
                router.add_api_route(
                    f'{route[0]}', callback, methods=[route[1]]
                )
            routers.append(router)

        # Create the well-known (public) endpoint
        card_router = APIRouter(prefix="/a2a")

        @card_router.get(f'/{{agent_name}}{AGENT_CARD_WELL_KNOWN_PATH}')
        async def get_agent_card(agent_name: str):
            card = A2A.get_card(agent_name)
            return card.model_dump()

        routers.append(card_router)
        return routers
