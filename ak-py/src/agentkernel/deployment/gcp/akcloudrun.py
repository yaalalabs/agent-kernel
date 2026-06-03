from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter

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
    and starts the underlying RESTAPI server.

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
    def run(cls) -> None:
        """
        Start the Cloud Run HTTP server.

        Registers any custom routes added via :meth:`register` and then starts
        the RESTAPI (FastAPI/uvicorn) server. This is the entry point equivalent
        of ``Lambda.handler()`` for AWS.

        Call this from your ``main()`` function::

            def main() -> None:
                CloudRun.run()
        """
        from ...api.http import RESTAPI

        cls._log.info("Agent Kernel Cloud Run service starting")
        if cls._router.routes:
            RESTAPI.add(cls._router)
        RESTAPI.run()
