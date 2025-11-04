from abc import abstractmethod

from fastapi import APIRouter


class RESTRequestHandler:
    @abstractmethod
    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance which has configured routes
        E.g.:
        - GET /health: Health check
        - GET /agents: List available agents

        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(Runtime.instance().agents().keys())}

        """
        pass
