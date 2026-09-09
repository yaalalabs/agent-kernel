"""The WebSocket Gateway (spec #495 §9): the tier that owns client sockets.

On multi-pod topologies this is its own container/Deployment: it serves the client-facing
``/ws`` route and the cluster-internal push endpoint, and nothing else. It runs no consumer
loops: chat frames are enqueued directly to the transport, and replies arrive as pushes from
whichever pod's Response Handler consumed them. The IO handler's API stays plain REST.

This entry point is broker-only: on the ``in_memory`` transport a separate gateway process
cannot share the in-process queue, so it fails fast and points at the single-process topology
(``IOHandler.run(auth_validator=...)``), which co-hosts these same handlers alongside the REST
API, runner, and Response Handler for local testing.
"""

import logging
from typing import Optional

import uvicorn
from fastapi import FastAPI

from ...auth.handler import AuthValidator
from ...core.config import AKConfig
from ...core.model import ExecutionMode
from ...core.util.factory import AKConfigError
from ..thread_runner import ThreadRunner
from ..transport.base import QueueTransportFactory
from .endpoint import PushEndpointHandler
from .handler import PipelineWebSocketHandler
from .push import default_connection_store
from .registry import LocalConnectionRegistry


class WebSocketGateway:
    """Container entry point for the gateway tier: ``WebSocketGateway.run(auth_validator=...)``."""

    _log = logging.getLogger("ak.pipeline.ws.gateway")

    @classmethod
    def run(cls, auth_validator: AuthValidator) -> None:
        """Serve the gateway: ``/ws``, ``/internal/push``, and a ``/health`` probe.

        :param auth_validator: Authenticates every ``/ws`` handshake; claims must include a
            ``userId``. Mandatory.
        """
        config = AKConfig.get()
        transport_type = QueueTransportFactory.resolve_type()
        cls._validate(auth_validator, transport_type, config)

        registry = LocalConnectionRegistry.instance()
        connection_store = default_connection_store()  # raises AKConfigError on session backends without one
        if not connection_store.shared:
            raise AKConfigError(
                "a standalone WebSocket gateway needs a shared connection store: configure session.type "
                "redis, valkey or dynamodb so Response Handlers on other pods can find this pod's connections"
            )

        app = cls._build_app(
            PipelineWebSocketHandler(auth_validator=auth_validator, registry=registry, connection_store=connection_store),
            PushEndpointHandler(registry=registry),
        )

        host, port = config.api.host, config.api.port
        cls._log.info(f"Agent Kernel WebSocket Gateway listening on http://{host}:{port} (transport={transport_type})")
        # uvicorn runs on the main thread here, so its own SIGTERM/SIGINT handling applies; the
        # shared ThreadRunner handlers are still installed so a drain exits 0 like the other
        # pipeline container mains.
        server = uvicorn.Server(uvicorn.Config(app=app, host=host, port=port))
        ThreadRunner.install_shutdown_signal_handlers(cls._log, on_shutdown_signal=lambda: setattr(server, "should_exit", True))
        server.run()

    @staticmethod
    def _build_app(*handlers) -> FastAPI:
        app = FastAPI()
        app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"])
        for handler in handlers:
            app.include_router(handler.get_router())
        return app

    @classmethod
    def _validate(cls, auth_validator: Optional[AuthValidator], transport_type: str, config) -> None:
        """Fail fast on an unusable gateway configuration (spec §9)."""
        if auth_validator is None:
            raise ValueError(
                "auth_validator is required for the WebSocket gateway: authentication is mandatory. "
                "Call WebSocketGateway.run(auth_validator=...) with a validator whose claims include a 'userId'."
            )
        if transport_type == "in_memory":
            raise AKConfigError(
                "a standalone WebSocket gateway cannot run on the in_memory transport (the queue is "
                "process-local): run the single-process topology instead, IOHandler.run(auth_validator=...)"
            )
        if config.execution.mode not in (ExecutionMode.ASYNC, ExecutionMode.STREAM):
            raise AKConfigError(
                f"the WebSocket gateway serves ASYNC/STREAM modes; execution.mode is {config.execution.mode}: "
                "replies in REST modes go to the response store and would never reach a WebSocket client"
            )
        if not config.websocket_api.push_auth_token:
            raise AKConfigError(
                "the WebSocket gateway requires websocket_api.push_auth_token: Response Handlers " "authenticate their pushes to this pod with it"
            )
        push_port = config.websocket_api.push_port
        if push_port is not None and push_port != config.api.port:
            # This gateway serves /ws and /internal/push on one server bound to api.port, so a
            # different advertised push port would record endpoints in the connection store
            # that nothing answers, and every reply push would fail.
            raise AKConfigError(
                f"websocket_api.push_port ({push_port}) differs from api.port ({config.api.port}): leave it unset "
                "here. It exists for custom gateways that mount PushEndpointHandler on their own separate listener"
            )
