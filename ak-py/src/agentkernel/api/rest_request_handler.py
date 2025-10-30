from fastapi import APIRouter
from ..core import Runtime

class RESTRequestHandler:
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(Runtime.instance().agents().keys())}

        return router