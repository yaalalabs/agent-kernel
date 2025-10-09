import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from .agent import AgentRESTRequestHandler
from ..core.config import AKConfig

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)


class RESTAPI:
    """
    Handles the initialization and running of the REST API server.
    Can run any FastAPI app instance or assemble one from routers.
    """
    _log = logging.getLogger("ak.api.restapi")

    @classmethod
    def _create_app(cls, routers) -> FastAPI:
        """
        Assembles a FastAPI app from routers.
        :param routers: List of routers to include in the app.
        """
        app = FastAPI(title="Agent Kernel REST API", debug=True)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )

        for r in routers or []:
            app.include_router(r)

        @app.get("/openapi.json")
        async def get_openapi_endpoint():
            return get_openapi(
                title="Agent Kernel REST API",
                version="1.0.0",
                routes=app.routes,
            )

        return app

    @classmethod
    def run(cls):
        """
        Starts the REST API server.
        """
        host = AKConfig.get().api.host
        port = AKConfig.get().api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")

        routers = []
        if AKConfig.get().api.enabled_routes.agents:
            routers.append(AgentRESTRequestHandler.get_router())
        if AKConfig.get().a2a.enabled:
            from .a2a import A2ARESTRequestHandler
            routers.append(A2ARESTRequestHandler.get_catalog_router())
            routers.extend(A2ARESTRequestHandler.get_agent_routers())
        app = cls._create_app(routers=routers)
        if AKConfig.get().mcp.enabled:
            from ..mcp.akmcp import MCP
            app.mount("/mcp", MCP.get_http_app())
        uvicorn.run(app=app, host=host, port=port, reload=False)
