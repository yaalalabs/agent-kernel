import logging
from typing import Optional

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
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        """Return the default handler(s) used by run() when none are provided; override to customize (e.g. lazy construction).

        :return: List of REST request handlers
        """
        return [AgentRESTRequestHandler()]

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
            route_path = getattr(route, "path", None)
            route_methods = getattr(route, "methods", None)
            if route_path is not None:
                cls._log.debug(f"Route: {route_path} [{route_methods}]")
        cls._custom_routers.append(router)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] = None):
        """Start the REST API server.

        With no explicit handlers on RESTAPI itself, an in_memory queue transport boots the
        single-process pipeline topology (#495): subclasses (AWSRestAPI, AWSWebsocketAPI) and
        explicit-handler callers keep their own paths.

        :param handlers: List of REST request handlers to use (default: AgentRESTRequestHandler)
        """
        if cls is RESTAPI and handlers is None:
            from ..pipeline.transport.base import QueueTransportFactory

            if QueueTransportFactory.resolve_type() == "in_memory":
                from ..pipeline.io_handler import IOHandler

                cls._log.info("in_memory queue transport resolved: starting the single-process pipeline topology")
                return IOHandler.run()

        handlers = handlers if handlers is not None else cls.get_default_handlers()
        cls._reject_pipeline_only_handlers(handlers)
        cls.reject_unqueued_protocols()

        host = AKConfig.get().api.host
        port = AKConfig.get().api.port
        cls._log.info(f"Agent Kernel REST API listening on http://{host}:{port}")
        uvicorn.run(app=cls.build_app(handlers), host=host, port=port, reload=False)

    @classmethod
    def _reject_pipeline_only_handlers(cls, handlers: list[RESTRequestHandler] = None) -> None:
        """Refuse to serve a handler that only works inside the queue pipeline.

        :param handlers: The handlers this run was asked to serve.
        :raises AKConfigError: If any of them declares ``requires_pipeline``.
        """
        offenders = sorted({type(handler).__name__ for handler in handlers or [] if getattr(handler, "requires_pipeline", False) is True})
        if offenders:
            from ..core.util.factory import AKConfigError

            raise AKConfigError(
                f"{', '.join(offenders)} require the queue pipeline: serve them with "
                "IOHandler.run(handlers=[...]) instead of RESTAPI.run([...]), which builds a bare "
                "API with no runner to drain what they enqueue"
            )

    @staticmethod
    def agent_protocol_surfaces(config: Optional[AKConfig] = None) -> list[str]:
        """The protocol surfaces that run agents for their callers: A2A, and MCP when it exposes agents.

        An MCP server serving only the application's own tools runs no agent, so it is not one.

        :param config: The configuration to read; defaults to ``AKConfig.get()``.
        :return: ``["A2A"]`` when ``a2a.enabled``, plus ``["MCP"]`` when ``mcp.enabled`` and ``mcp.expose_agents``.
        """
        config = config or AKConfig.get()
        surfaces = []
        if config.a2a.enabled:
            surfaces.append("A2A")
        if config.mcp.enabled and config.mcp.expose_agents:
            surfaces.append("MCP")
        return surfaces

    @classmethod
    def reject_unqueued_protocols(cls) -> None:
        """Refuse to serve A2A or agent MCP from an entry point that starts no agent runner.

        Their executors put each request on the input queue and wait for the runner's reply (#780),
        so on a bare API every call would wait out its budget and fail. Called by ``run`` past the
        ``cls is RESTAPI`` hand-off, so subclasses are covered, and by ``ECSIOHandler.run`` before
        it starts any thread.

        :raises AKConfigError: If ``agent_protocol_surfaces()`` is non-empty.
        """
        surfaces = cls.agent_protocol_surfaces()
        if surfaces:
            from ..core.util.factory import AKConfigError

            raise AKConfigError(
                f"{' and '.join(surfaces)} run agents on the queue pipeline's agent runner, which this entry point does not start: "
                "serve them with IOHandler.run(handlers=[...]), or a plain RESTAPI.run() on the in_memory transport"
            )

    @classmethod
    def build_app(cls, handlers: list[RESTRequestHandler] = None) -> FastAPI:
        """Assemble the complete FastAPI app (handlers, A2A/MCP mounts, custom routers) without serving it.

        Used by run(), and by the pipeline IOHandler, which serves the app through its own
        uvicorn.Server so its main-thread signal handlers can stop it (SIGTERM/SIGINT).

        :param handlers: List of REST request handlers to use (default: get_default_handlers())
        :return: The assembled FastAPI application
        """
        if handlers is None:
            handlers = cls.get_default_handlers()

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
        return app

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
