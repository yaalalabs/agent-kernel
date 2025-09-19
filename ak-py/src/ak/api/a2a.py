import logging
from typing import List

from a2a.server.apps.rest.rest_adapter import RESTAdapter
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..a2a.a2a import A2A


class A2ARESTRequestHandler:
    """
    Minimal A2A REST endpoints backed by ak.a2a.A2A utilities.
    Endpoints:
    - GET /a2a/health: Health check for A2A routes
    - GET /a2a/cards: List available A2A AgentCards (one per enabled agent)
    - POST /a2a/run: Execute a skill by name using mapped agent
      Payload JSON: { "skill": str, "input": str, "session_id": str | null }
    """

    _log = logging.getLogger("ak.api.a2a")

    @classmethod
    def get_catalog_router(cls) -> APIRouter:
        router = APIRouter(prefix="a2a")  # Update the configs to reflect the correct Agent URL

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
                    f'/{route[0]}', callback, methods=[route[1]]
                )

            # create the well-known (public) endpoint
            @router.get(f'/{AGENT_CARD_WELL_KNOWN_PATH}')
            async def get_agent_card(request: Request):
                card = A2A.get_card(agent)
                return card.model_dump()

            routers.append(router)
        return routers
