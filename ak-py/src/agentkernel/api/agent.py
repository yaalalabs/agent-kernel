import logging
import traceback
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import AgentService, Runtime


class AgentRESTRequestHandler:
    """
    API routers that expose endpoints to interact with Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents
    - POST /run: Run an agent with a prompt
      Payload JSON: { "prompt": str, "agent": str | null, "session_id": str | null }
    """

    _log = logging.getLogger("ak.api.agent")

    class RunRequest(BaseModel):
        prompt: str
        agent: Optional[str] = None
        session_id: Optional[str] = None

    @classmethod
    def get_router(cls) -> APIRouter:
        """
        Returns the APIRouter instance.
        """

        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(Runtime.instance().agents().keys())}

        @router.post("/run")
        async def run(req: AgentRESTRequestHandler.RunRequest):
            return await cls.run(req)

        return router

    @classmethod
    async def run(cls, req: RunRequest):
        """
        Async method to run the agent.
        :param req: Request an object containing the prompt and optional agent name.
        """
        service = AgentService()
        try:
            service.select(req.session_id, req.agent)
            if not service.agent:
                service.select(req.session_id)
                if not service.agent:
                    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail={
                        "error": "No agent available",
                        "session_id": service.get_response_session_id(req.session_id)
                    })
            result = await service.run(req.prompt)

            if hasattr(result, 'raw'):
                payload = {
                    "result": str(result.raw),
                    "session_id": service.get_response_session_id(req.session_id)
                }
            else:
                payload = {
                    "result": result,
                    "session_id": service.get_response_session_id(req.session_id)
                }
            return payload
        except HTTPException:
            raise
        except Exception as e:
            cls._log.error(f"POST /run error: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail={
                "error": str(e),
                "session_id": service.get_response_session_id(None)
            })
