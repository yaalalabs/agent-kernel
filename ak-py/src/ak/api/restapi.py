import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .a2a import A2ARESTRequestHandler
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
    _log = logging.getLogger("ak.api.resapi")

    @classmethod
    def _create_app(cls, routers) -> FastAPI:
        """
        Assembles a FastAPI app from routers.
        :param routers: List of routers to include in the app.
        """
        app = FastAPI(title="Agent Kernel REST API")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"]
        )

        for r in routers or []:
            app.include_router(r)

        return app

    @classmethod
    def run(cls):
        """
        Starts the REST API server.
        - You can pass an existing FastAPI `app` instance.
        - Or supply `routers` to assemble a new app via create_app().
        - `enable_default_endpoints` toggles the built-in Agent endpoints.
        """
        host = AKConfig.get().api.host
        port = AKConfig.get().api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")

        routers = []
        if AKConfig.get().api.enabled_routes.agents:
            routers.append(AgentRESTRequestHandler.get_router())
        if AKConfig.get().a2a.enabled:
            routers.append(A2ARESTRequestHandler.get_router())
        app = cls._create_app(routers=routers)
        uvicorn.run(app=app, host=host, port=port, reload=False)
