import logging

from .auth import AuthTokenValidator, ValidationContext
import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from ..core.config import AKConfig
from .handler import AgentRESTRequestHandler, RESTRequestHandler

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)


class RESTAPI:
    """
    Handles the initialization and running of the REST API server.
    Can run any FastAPI app instance or assemble one from routers.
    """

    _log = logging.getLogger("ak.api.http")
    _custom_routers = []
    _auth_token_validators = []

    @classmethod
    def _create_app(cls, routers, lifespan=None) -> FastAPI:
        """
        Assembles a FastAPI app from routers.
        :param routers: List of routers to include in the app.
        :param lifespan: Optional lifespan handler.
        """
        app = FastAPI(title="Agent Kernel REST API", debug=True, lifespan=lifespan, dependencies=cls._auth_token_validators if cls._auth_token_validators else None)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
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
    def add(cls, router: APIRouter):
        cls._log.debug(f"Adding custom router")
        for route in router.routes:
            cls._log.debug(f"Route: {route.path} [{route.methods}]")
        cls._custom_routers.append(router)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] = None):
        """
        Starts the REST API server.
        """
        if handlers is None:
            handlers = [AgentRESTRequestHandler()]
        host = AKConfig.get().api.host
        port = AKConfig.get().api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")

        routers = []
        for handler in handlers:
            if handler is not None:
                routers.append(handler.get_router())

        if AKConfig.get().a2a.enabled:
            from .a2a.handler import A2ARESTRequestHandler

            routers.append(A2ARESTRequestHandler.get_catalog_router())
            routers.extend(A2ARESTRequestHandler.get_agent_routers())
        if AKConfig.get().mcp.enabled:
            from .mcp.akmcp import MCP

            mcp_app = MCP.get_http_app()
            app = cls._create_app(routers=routers, lifespan=mcp_app.lifespan)
            app.mount("/mcp", mcp_app)
        else:
            app = cls._create_app(routers=routers)
        # Add custom routers
        for router in cls._custom_routers:
            app.include_router(router, prefix=AKConfig.get().api.custom_router_prefix)
        uvicorn.run(app=app, host=host, port=port, reload=False)

    @classmethod
    def add_token_validators(cls, auth_token_validators: list):
        """Adds AuthTokenValidators to the REST API.
        :param auth_token_validators: List of auth token validators to add."""
        def get_auth_function(token_validator: AuthTokenValidator):
            def verify_token(request: Request):
                auth_token = request.headers.get("authorization")
                cls._log.debug(f"Validating token: '{auth_token}'")
                if auth_token is None:
                    raise HTTPException(status_code=401, detail="Missing authorization header")
                auth_token = auth_token.replace("Bearer ", "").strip()
                result = token_validator.validate(token=auth_token, context=ValidationContext(path=str(request.url), http_method=request.method, headers=dict(request.headers)))
                if not result.is_valid:
                    raise HTTPException(status_code=401, detail=result.error or "Unauthorized")
                return result
            return verify_token
        for token_validator in auth_token_validators:
            cls._auth_token_validators.append(Depends(get_auth_function(token_validator)))

