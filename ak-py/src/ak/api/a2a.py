import logging
from typing import List

from fastapi import APIRouter
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

    class RunRequest(BaseModel):
        task_id: str
        method: str
        params: dict
        input: List[dict]
        context: dict
        options: dict

    @classmethod
    def _ensure_built(cls):
        # Build A2A cards/mappings/executors once based on config/runtime
        try:
            A2A._build()
        except Exception as e:
            cls._log.error(f"Failed to initialize A2A: {e}")
            raise

    @classmethod
    def get_router(cls) -> APIRouter:
        cls._ensure_built()
        router = APIRouter()

        @router.get("/a2a/cards")
        def list_cards():
            cards: List[BaseModel] = A2A.get_cards() or []
            result = []
            for c in cards:
                result.append(c.model_dump())
            return {"cards": result}

        @router.post("/a2a/task")
        async def execute_task(req: A2ARESTRequestHandler.RunRequest):
            # Resolve skill to agent name
            mapping = A2A.get_skill_to_agent_mapping() or {}
            agent_name = mapping.get(req.method)
            if not agent_name:
                return {"error": f"No agent found for skill '{req.method}'"}

            executor: A2A.Executor = await A2A.get_executor(agent_name)

            return {}

        return router
