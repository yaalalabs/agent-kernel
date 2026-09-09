"""The gateway's native WebSocket route (spec #495 §9).

``/ws`` is a plain FastAPI WebSocket endpoint: no API Gateway in front, so this handler owns the
whole lifecycle itself: accept, authenticate the ``token`` query parameter, register the
connection (the socket in the pod-local registry, the mapping with this pod's push endpoint in
the shared connection store), and dispatch each frame: the chat route parses a
:class:`BaseRequest` and enqueues it directly to the transport (the queue is the interface: no
REST hop, no return address on the message), custom routes run user functions registered with
the same decorator surface as ``AWSWebsocketAPI.register``.

Frames sent back to the client carry a ``type`` field: ``CHAT_QUEUED`` acks an accepted chat
request (the reply itself arrives later as ``CHAT_RESPONSE``/``STREAM_CHUNK`` frames pushed by
the Response Handler), ``SYSTEM_RESPONSE`` carries custom-route results and errors.
"""

import asyncio
import json
import logging
import re
import threading
import uuid
from typing import Any, Callable, ClassVar, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...api.handler import RESTRequestHandler
from ...auth.handler import AuthValidator
from ...core.config import AKConfig
from ...core.model import BaseRequest
from ...core.session.base import WSConnectionStore
from ..envelope import ATTR_REQUEST_ID, ATTR_USER_ID, QueueMessage, QueueName
from ..transport.base import QueueTransport, QueueTransportFactory
from .base import WebSocketHandlerABC
from .push import default_connection_store, pod_endpoint_url
from .registry import LocalConnectionRegistry

# WebSocket close code for policy violations (failed authentication).
_WS_POLICY_VIOLATION = 1008


class PipelineWebSocketHandler(RESTRequestHandler):
    """Mounts the ``/ws`` route: authenticated chat entry plus registered custom routes."""

    WS_PATH = "/ws"
    # Route key selecting the chat dispatch when websocket_api.chat_route is not configured.
    DEFAULT_CHAT_ROUTE = "chat"

    _custom_routes: ClassVar[Dict[str, Callable]] = {}

    def __init__(
        self,
        auth_validator: AuthValidator,
        registry: Optional[LocalConnectionRegistry] = None,
        transport: Optional[QueueTransport] = None,
        connection_store: Optional[WSConnectionStore] = None,
    ):
        """:param auth_validator: authenticates the handshake; mandatory, and its claims must
        include a ``userId`` (keys the connection). ``None`` raises ValueError."""
        if auth_validator is None:
            raise ValueError(
                "auth_validator is required for WebSocket mode: authentication is mandatory. "
                "Pass an AuthValidator whose claims include a 'userId'."
            )
        self._auth_validator = auth_validator
        self._registry = registry or LocalConnectionRegistry.instance()
        self._transport = transport
        self._connection_store = connection_store
        self._config = AKConfig.get()
        self._chat_route = self._config.websocket_api.chat_route or self.DEFAULT_CHAT_ROUTE
        self._endpoint_url = pod_endpoint_url()  # recorded per connection in the store, never on messages
        self._log = logging.getLogger("ak.pipeline.ws.handler")

    # -- custom routes ------------------------------------------------------------------------

    @classmethod
    def register(cls, route: str) -> Callable[[Callable], Callable]:
        """Decorator registering a custom WebSocket route (same surface as ``AWSWebsocketAPI.register``).

        The function (sync or async) receives a dict with ``message`` (the frame's raw JSON
        body, unparsed) and ``user_id`` (the authenticated user). A dict return is sent back to
        the calling connection as a ``SYSTEM_RESPONSE`` frame; ``None`` sends nothing.
        Re-registering the same route keeps the first registration.

        :param route: Bare route name (e.g. ``"status"``), selected by the frame's ``route`` field.
        """
        cls._validate_route_name(route)

        def _decorator(func: Callable) -> Callable:
            if route in cls._custom_routes:
                logging.getLogger("ak.pipeline.ws.handler").warning(
                    f"WebSocket route '{route}' is already registered. Keeping the first registration."
                )
                return func
            cls._custom_routes[route] = func
            return func

        return _decorator

    @classmethod
    def _validate_route_name(cls, route: str) -> None:
        """Validate a custom route name, raising ValueError on any violation (see ``register``)."""
        if not isinstance(route, str) or not route:
            raise ValueError("WebSocket route name must be a non-empty string.")
        if route.startswith("/"):
            raise ValueError(f"WebSocket route '{route}' must be a bare route name, not a path: it is selected by the frame's 'route' field.")
        if route == cls.DEFAULT_CHAT_ROUTE:
            raise ValueError(f"WebSocket route name '{route}' is the built-in chat route and cannot be reused.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", route):
            raise ValueError(f"Invalid WebSocket route name '{route}': only letters, digits, '_' and '-' are allowed.")

    # -- plumbing -------------------------------------------------------------------------------

    def get_transport(self) -> QueueTransport:
        if self._transport is None:
            self._transport = QueueTransportFactory.create()
        return self._transport

    def get_connection_store(self) -> WSConnectionStore:
        if self._connection_store is None:
            self._connection_store = default_connection_store()
        return self._connection_store

    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_websocket_route(self.WS_PATH, self._serve)
        return router

    # -- connection lifecycle ---------------------------------------------------------------

    async def _serve(self, websocket: WebSocket) -> None:
        """One connection's whole life: authenticate, register, dispatch frames, deregister."""
        await websocket.accept()
        user_id = await self._authenticate(websocket)
        if user_id is None:
            return

        connection_id = str(uuid.uuid4())
        # The socket stays here; the shared store tells Response Handlers on any pod where to
        # push for this connection. Registry first (a store mapping must never point at a pod
        # not yet holding the socket), and the try starts before the store write so a store
        # failure still tears the registry entry down in the finally: the registry has no TTL,
        # and with no store mapping no push would ever target the entry to trigger the
        # drop-on-failed-send cleanup.
        self._registry.add_connection(user_id, connection_id, websocket=websocket, loop=asyncio.get_running_loop())
        try:
            await asyncio.to_thread(self.get_connection_store().add_connection, user_id, connection_id, self._endpoint_url)
            self._log.info(f"Connected: user_id={user_id}, connection_id={connection_id}")
            while True:
                raw_frame = await websocket.receive_text()
                await self._dispatch(websocket, user_id, raw_frame)
        except WebSocketDisconnect:
            pass
        finally:
            self._registry.delete_connection(user_id, connection_id)
            # Fire-and-forget on a daemon thread: this finally also runs under task cancellation
            # (server shutdown tearing the connection down), where an await would raise
            # immediately and skip the cleanup, and a synchronous call would stall the event
            # loop behind driver connect/retry backoffs when the store is unreachable, freezing
            # every other socket on the pod exactly when clients are churning.
            threading.Thread(
                target=self._delete_connection_mapping,
                args=(user_id, connection_id),
                daemon=True,
                name=f"ws-deregister-{connection_id[:8]}",
            ).start()
            self._log.info(f"Disconnected: user_id={user_id}, connection_id={connection_id}")

    def _delete_connection_mapping(self, user_id: str, connection_id: str) -> None:
        try:
            self.get_connection_store().delete_connection(user_id, connection_id)
        except Exception:
            # The mapping's TTL reaps it if the store is briefly unreachable at disconnect.
            self._log.exception(f"Failed to deregister connection mapping: connection_id={connection_id}")

    async def _authenticate(self, websocket: WebSocket) -> Optional[str]:
        """Validate the ``token`` query parameter; a failure closes the socket (policy violation)."""
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=_WS_POLICY_VIOLATION, reason="Authentication token is required")
            return None
        result = self._auth_validator.validate(token)
        if not result.is_valid:
            await websocket.close(code=_WS_POLICY_VIOLATION, reason=result.error_msg or "Authentication failed")
            return None
        user_id = (result.claims or {}).get("userId")
        if not user_id:
            await websocket.close(code=_WS_POLICY_VIOLATION, reason="'userId' claim is required in token")
            return None
        return user_id

    # -- frame dispatch -----------------------------------------------------------------------

    async def _dispatch(self, websocket: WebSocket, user_id: str, raw_frame: str) -> None:
        try:
            payload = json.loads(raw_frame)
        except json.JSONDecodeError:
            await self._send_system(websocket, "Invalid frame: not JSON")
            return

        # Route off the raw payload: only chat frames are parsed into a BaseRequest; custom
        # routes receive their body unparsed, with no schema imposed (ECS contract).
        route = payload.get("route") if isinstance(payload, dict) else None
        if route is None or route == self._chat_route:
            try:
                request = BaseRequest.from_payload(payload)
            except Exception as e:
                await self._send_system(websocket, f"Invalid request: {e}")
                return
            await self._handle_chat(websocket, user_id, request)
        elif route in self._custom_routes:
            await self._handle_custom(websocket, user_id, route, payload)
        else:
            await self._send_system(websocket, f"Route '{route}' not found")

    async def _handle_chat(self, websocket: WebSocket, user_id: str, request: BaseRequest) -> None:
        """Enqueue a chat frame; the Response Handler pushes the reply back to this pod."""
        body = request.body
        if body is None:
            await self._send_system(websocket, "body is required")
            return
        if not body.session_id:
            await self._send_system(websocket, "session_id is required")
            return

        request_id = request.request_id or str(uuid.uuid4())
        # USER_ID doubles as the WS-entered marker (spec §2 invariant): the Response Handler
        # resolves delivery from the connection store, so no return address is stamped.
        message = QueueMessage(
            body=json.dumps(body.model_dump(exclude_none=True)),
            attributes={ATTR_REQUEST_ID: request_id, ATTR_USER_ID: user_id},
            group_id=body.session_id,
            dedup_id=request_id,
        )
        try:
            # Offload the sync send so a slow broker doesn't block the event loop for
            # every other connection.
            await asyncio.to_thread(self.get_transport().send, QueueName.INPUT, message)
        except Exception:
            self._log.exception(f"Failed to enqueue WebSocket chat request: request_id={request_id}")
            await self._send_system(websocket, "Request processing failed")
            return

        self._log.info(f"[ENQUEUED] request_id={request_id}, session_id={body.session_id}, user_id={user_id}")
        await websocket.send_json(
            {
                "status": "SUCCESS",
                "message": "Request queued successfully",
                "user_id": user_id,
                "request_id": request_id,
                "type": WebSocketHandlerABC.MessageType.CHAT_QUEUED.value,
            }
        )

    async def _handle_custom(self, websocket: WebSocket, user_id: str, route: str, payload: Any) -> None:
        """Run a registered route function; a dict result goes back as a SYSTEM_RESPONSE frame."""
        try:
            result = self._custom_routes[route]({"message": payload, "user_id": user_id})
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None:
                await websocket.send_json({**result, "type": WebSocketHandlerABC.MessageType.SYSTEM_RESPONSE.value})
        except Exception:
            self._log.exception(f"WebSocket custom route '{route}' failed")
            await self._send_system(websocket, "Route handler encountered an error")

    async def _send_system(self, websocket: WebSocket, message_text: str) -> None:
        await websocket.send_json({"status": "FAILED", "message": message_text, "type": WebSocketHandlerABC.MessageType.SYSTEM_RESPONSE.value})
