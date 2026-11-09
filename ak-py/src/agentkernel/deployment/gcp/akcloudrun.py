from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:  # pragma: no cover: typing only, so importing this module stays light
    from ...api.handler import RESTRequestHandler

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)


class CloudRun:
    """
    CloudRun provides a GCP Cloud Run interface for deploying agents.

    GCP equivalent of the AWS Lambda class. Unlike Lambda (which processes
    API Gateway JSON events), Cloud Run receives standard HTTP requests handled
    by a FastAPI web server. This class provides a consistent registration API
    and starts the pipeline's IO process:

    - on the default ``in_memory`` transport, the whole pipeline in one instance;
    - on a broker transport (``execution.queues.type: pubsub``), the queue-mode edge: the REST
      API plus the response handler. The agents run in a separate worker pool whose entry point
      is ``agentkernel.pipeline.AgentRunner.run()``.

    Usage::

        from agentkernel.gcp import CloudRun

        @CloudRun.register("/custom", method="GET")
        def my_handler() -> dict[str, str]:
            return {"status": "ok"}

        def main() -> None:
            CloudRun.run()
    """

    _log = logging.getLogger("ak.gcp.cloudrun")
    _router: APIRouter = APIRouter()

    @classmethod
    def register(cls, path: str, method: str = "GET") -> Callable:
        """
        Decorator that registers a custom HTTP route on the Cloud Run service.

        Equivalent of ``Lambda.register()`` for AWS or ``@app.route()`` for Azure
        Functions. The handler is a plain FastAPI route function.

        :param path: URL path for the route (e.g. ``"/custom"``).
        :param method: HTTP method — GET, POST, PUT, DELETE, or PATCH (case-insensitive).
        :return: Decorator that registers the handler and returns it unchanged.
        """
        norm_path = path if path.startswith("/") else f"/{path}"
        http_method = method.lower()
        if not hasattr(cls._router, http_method):
            raise ValueError(f"Unsupported HTTP method: {method}")
        cls._log.info("Registering Cloud Run route %s %s", method.upper(), norm_path)
        return getattr(cls._router, http_method)(norm_path)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
        """
        Start the Cloud Run HTTP server through the pipeline's ``IOHandler``.

        Registers any custom routes added via :meth:`register`, then starts the pipeline's IO
        process. With no arguments on the default ``in_memory`` transport this is exactly the
        single-process topology ``RESTAPI.run()`` started before. On a broker transport it is the
        queue-mode edge (REST API plus response handler), which needs a shared response store.
        This is the entry point equivalent of ``Lambda.handler()`` for AWS.

        REST authentication stays on ``GCPAuthorizer(...).register()``, which applies to every
        route this server mounts.

        Call this from your ``main()`` function::

            def main() -> None:
                CloudRun.run()

        :param handlers: Optional REST handlers mounted alongside the pipeline's chat route,
            for example a schedule or thread read handler.
        :raises AKConfigError: For ``async`` (WebSocket) or ``realtime`` mode on a broker
            transport, before anything starts.
        """
        cls._reject_undeliverable_modes()

        from ...api.http import RESTAPI
        from ...pipeline.io_handler import IOHandler

        cls._log.info("Agent Kernel Cloud Run service starting")
        if cls._router.routes:
            RESTAPI.add(cls._router)
        IOHandler.run(handlers=handlers)

    @classmethod
    def _reject_undeliverable_modes(cls) -> None:
        """Refuse the modes whose replies Cloud Run cannot deliver across instances.

        In ``async`` and ``realtime`` modes a reply is pushed to the instance that holds the
        client's socket, by that instance's address. Cloud Run instances are not individually
        addressable, so on a broker transport, where the runner is another instance, the reply
        could never arrive. On ``in_memory`` everything is one process and ``IOHandler`` applies
        its own checks.

        :raises AKConfigError: If the configured mode cannot be delivered.
        """
        from ...core.config import AKConfig
        from ...core.model import ExecutionMode
        from ...core.util.factory import AKConfigError
        from ...pipeline.transport.base import QueueTransportFactory

        transport_type = QueueTransportFactory.resolve_type()
        if transport_type == "in_memory":
            return
        execution = AKConfig.get().execution
        if execution.is_websocket or execution.mode == ExecutionMode.REALTIME:
            raise AKConfigError(
                f"execution.mode {execution.mode.value} is not supported on Cloud Run with the {transport_type} transport: "
                "its replies are pushed to the instance holding the client's socket, and Cloud Run instances are not "
                "individually addressable. Use execution.mode rest_sync or rest_async"
            )
