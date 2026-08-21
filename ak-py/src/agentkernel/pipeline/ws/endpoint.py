"""The gateway's push endpoint (spec #495 §9): the ``PostToConnection`` analogue.

``POST /internal/push`` is how a Response Handler reaches a socket held by this gateway pod: the
poster names the connection (resolved from the shared connection store), this pod writes the
frame on it. It is pod-to-pod plumbing, never client-facing: the Helm chart keeps it
cluster-internal (NetworkPolicy) and every request must carry the shared
``websocket_api.push_auth_token``.
"""

import hmac
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...api.handler import RESTRequestHandler
from ...core.config import AKConfig
from .push import PUSH_PATH, PUSH_TOKEN_HEADER
from .registry import LocalConnectionRegistry


class PushEndpointHandler(RESTRequestHandler):
    """Mounts ``POST /internal/push`` over the gateway pod's local socket registry."""

    class PushRequest(BaseModel):
        connection_id: str
        message: Dict[str, Any]

    def __init__(self, registry: Optional[LocalConnectionRegistry] = None):
        self._registry = registry or LocalConnectionRegistry.instance()
        self._config = AKConfig.get()
        self._log = logging.getLogger("ak.pipeline.ws.push_endpoint")

    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(PUSH_PATH, self.push, methods=["POST"])
        return router

    def push(self, body: PushRequest, request: Request) -> dict:
        """Write one frame to the named local connection.

        A sync endpoint on purpose: FastAPI serves it on the threadpool, so the registry's
        ``run_coroutine_threadsafe`` delivery onto the uvicorn loop cannot deadlock.
        """
        expected = self._config.websocket_api.push_auth_token
        if not expected:
            # Fail closed: without a configured token nothing is allowed to push. Reached only
            # on the in_memory transport (broker topologies fail at startup without the token),
            # where delivery short-circuits in-process and never posts here.
            raise HTTPException(status_code=403, detail="push endpoint is disabled: websocket_api.push_auth_token is not configured")
        provided = request.headers.get(PUSH_TOKEN_HEADER)
        if not provided or not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid push token")

        if not self._registry.deliver_to_connection(body.connection_id, body.message):
            # The GoneException analogue: the poster deletes the stale mapping and moves on.
            raise HTTPException(status_code=404, detail=f"connection '{body.connection_id}' is not held by this pod")

        self._log.debug(f"Pushed frame to connection_id={body.connection_id}")
        return {"status": "SUCCESS"}
