import logging

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from ..auth import AuthValidator, ValidationContext
from ..core.config import AKConfig
from .handler import AgentRESTRequestHandler, RESTRequestHandler


class RESTAPI:
    """
    Handles the initialization and running of the REST API server.
    Can run any FastAPI app instance or assemble one from routers.
    """

    _log = logging.getLogger("ak.api.http")
    _custom_routers = []
    _auth_token_validators = []

    @classmethod
    def _get_router_dependencies(cls):
        """Get dependencies to apply to APIRouters.
        :return: List of dependencies or None if no auth validators are configured
        """
        return cls._auth_token_validators if cls._auth_token_validators else None

    @classmethod
    def _create_app(cls, routers, lifespan=None) -> FastAPI:
        """
        Assembles a FastAPI app from routers.
        :param routers: List of routers to include in the app.
        :param lifespan: Optional lifespan handler.

        Global endpoints:
        - GET /health: Health check
        - GET /openapi.json: OpenAPI specification
        """
        app = FastAPI(title="Agent Kernel REST API", debug=True, lifespan=lifespan)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/health")
        def health():
            return {"status": "ok"}

        for r in routers or []:
            app.include_router(router=r, dependencies=cls._get_router_dependencies())

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
        """Add a custom router to the REST API.
        :param router: FastAPI router to add to the API
        """
        cls._log.debug(f"Adding custom router")
        for route in router.routes:
            cls._log.debug(f"Route: {route.path} [{route.methods}]")
        cls._custom_routers.append(router)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] = None):
        """Start the REST API server.
        :param handlers: List of REST request handlers to use (default: AgentRESTRequestHandler)
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
            app.include_router(router, prefix=AKConfig.get().api.custom_router_prefix, dependencies=cls._get_router_dependencies())
        uvicorn.run(app=app, host=host, port=port, reload=False)

    @classmethod
    def add_auth_handlers(cls, auth_validators: list[AuthValidator]):
        """Add authentication validators to the REST API.
        :param auth_validators: List of auth validators to add for token validation
        """

        def get_auth_function(token_validator: AuthValidator):
            def verify_token(request: Request):
                """Verify authentication token for incoming requests.
                :param request: FastAPI Request object
                :return: ValidationResult if token is valid
                :raises: HTTPException if authentication fails
                """
                request_url = str(request.url)
                cls._log.debug(f"Validating token for request: {request.method} {request_url}")
                auth_token = request.headers.get("authorization")
                if auth_token is None:
                    raise HTTPException(status_code=401, detail="Missing authorization header")
                auth_token = auth_token.replace("Bearer ", "").strip()
                result = token_validator.validate(
                    token=auth_token, context=ValidationContext(path=request_url, http_method=request.method, headers=dict(request.headers))
                )
                if not result.is_valid:
                    raise HTTPException(status_code=401, detail=result.error_msg or "Unauthorized")
                return result

            return verify_token

        for token_validator in auth_validators:
            cls._auth_token_validators.append(Depends(get_auth_function(token_validator)))
