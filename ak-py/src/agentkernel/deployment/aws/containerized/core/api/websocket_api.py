from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Callable, ClassVar, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from ......auth.handler import AuthValidator
from ......core.chat_service import ChatService
from ......core.config import AKConfig
from ......core.model import BaseRequest, BaseRunRequest
from ....core.sqs_handler import SQSHandler
from ....core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore


class ECSWebSocketHandlerBase(RESTRequestHandler):
    """Shared plumbing for the ECS WebSocket handlers: connection store, push endpoint construction, and response envelope.

    Store and handler are created lazily per instance (both point at the same DynamoDB table, which is
    stateless/safe). Abstract — ``get_router`` is left unimplemented, so it cannot be instantiated alone.
    """

    # WS $context headers injected by api_gateway_ws.tf.
    CONNECTION_ID_HEADER = "x-ws-connection-id"
    DOMAIN_NAME_HEADER = "x-ws-domain-name"
    STAGE_HEADER = "x-ws-stage"

    def __init__(self):
        """Validate the shared WebSocket config and set up lazy connection/handler slots."""
        self._config = AKConfig.get()

        ws_cfg = self._config.websocket_api
        if not ws_cfg.connection_table or not ws_cfg.connection_table.table_name:
            raise ValueError("websocket_api.connection_table.table_name is required for WebSocket mode")

        self._connection_store: Optional[WebSocketConnectionStore] = None
        self._ws_handler: Optional[AWSWebSocketHandler] = None

    def get_connection_store(self) -> WebSocketConnectionStore:
        """Lazily create the DynamoDB-backed WebSocket connection store."""
        if self._connection_store is None:
            ws_cfg = self._config.websocket_api
            self._connection_store = WebSocketConnectionStore(
                table_name=ws_cfg.connection_table.table_name,
                ttl=ws_cfg.connection_table.ttl,
            )
        return self._connection_store

    def get_websocket_handler(self) -> AWSWebSocketHandler:
        """Lazily create the AWS WebSocket handler."""
        if self._ws_handler is None:
            self._ws_handler = AWSWebSocketHandler(connection_store=self.get_connection_store())
        return self._ws_handler

    def _connection_id(self, request: Request) -> Optional[str]:
        return request.headers.get(self.CONNECTION_ID_HEADER)

    @staticmethod
    async def _offload(func: Callable, *args, **kwargs) -> Any:
        """Run a blocking boto3 call (DynamoDB/SQS/API Gateway Management API) in a worker thread
        so it doesn't block the uvicorn event loop for other in-flight requests."""
        return await asyncio.to_thread(func, *args, **kwargs)

    def _construct_endpoint_url(self, request: Request) -> Optional[str]:
        """Build the API Gateway management endpoint from x-ws-* headers, falling back to config."""
        domain_name = request.headers.get(self.DOMAIN_NAME_HEADER)
        stage = request.headers.get(self.STAGE_HEADER)
        if domain_name and stage:
            event = {"requestContext": {"domainName": domain_name, "stage": stage}}
            return self.get_websocket_handler().construct_endpoint_url(event)
        return self._config.websocket_api.endpoint_url

    @staticmethod
    def _body(msg: str, success: bool, user_id: Optional[str] = None) -> dict:
        body = {"status": "SUCCESS" if success else "FAILED", "message": msg}
        if user_id:
            body["user_id"] = user_id
        return body

    def _response(self, status_code: int, msg: str, success: bool, user_id: Optional[str] = None) -> JSONResponse:
        return JSONResponse(status_code=status_code, content=self._body(msg, success, user_id))

    def build_success_http_response(self, msg: str, user_id: Optional[str] = None, status_code: int = 200) -> JSONResponse:
        """Build the standard success response used by WebSocket routes."""
        return self._response(status_code, msg, success=True, user_id=user_id)

    def build_error_http_response(self, status_code: int, msg: str, user_id: Optional[str] = None) -> JSONResponse:
        """Build the standard error response used by WebSocket routes."""
        return self._response(status_code, msg, success=False, user_id=user_id)


class ECSWebSocketSystemRequestHandler(ECSWebSocketHandlerBase):
    """Framework-managed WebSocket protocol routes ($connect/$disconnect/$default); owns the ``AuthValidator`` used at $connect.

    Not an extension point — ``AWSWebsocketAPI`` builds it automatically from the validator set via ``set_auth_handler``.
    """

    # Backend paths the WS API Gateway integration rewrites each route to.
    CONNECT_PATH = "/ws/connect"
    DISCONNECT_PATH = "/ws/disconnect"
    DEFAULT_PATH = "/ws/default"

    def __init__(self, auth_validator: AuthValidator):
        """:param auth_validator: authenticates the $connect handshake; mandatory, and its claims must include a ``userId`` (keys the connection). ``None`` raises ValueError."""
        super().__init__()
        self._log = logging.getLogger("ak.ecs.ws_system_handler")

        if auth_validator is None:
            raise ValueError(
                "auth_validator is required for WebSocket mode — authentication is mandatory. "
                "Pass an AuthValidator whose claims include a 'userId'."
            )
        self._auth_validator = auth_validator

    def get_router(self) -> APIRouter:
        """Return an APIRouter with one POST endpoint per protocol route."""
        router = APIRouter()
        router.add_api_route(self.CONNECT_PATH, self._handle_connect, methods=["POST"])
        router.add_api_route(self.DISCONNECT_PATH, self._handle_disconnect, methods=["POST"])
        router.add_api_route(self.DEFAULT_PATH, self._handle_default, methods=["POST"])
        return router

    async def _handle_connect(self, request: Request) -> JSONResponse:
        """Authenticate ($connect) and store the connection. Non-2xx rejects the connection."""
        try:
            connection_id = self._connection_id(request)
            if not connection_id:
                return self.build_error_http_response(500, "Missing connection id")

            token = request.query_params.get("token")
            if not token:
                return self.build_error_http_response(401, "Authentication token is required")

            result = self._auth_validator.validate(token)
            if not result.is_valid:
                return self.build_error_http_response(401, result.error_msg or "Authentication failed")

            user_id = (result.claims or {}).get("userId")
            if not user_id:
                return self.build_error_http_response(401, "'userId' claim is required in token")

            await self._offload(self.get_websocket_handler().on_connect, connection_id=connection_id, user_id=user_id)
            return self.build_success_http_response("WebSocket connection established", user_id=user_id)
        except Exception as e:
            self._log.exception(f"WebSocket $connect failed: {e}")
            return self.build_error_http_response(500, "Failed to establish WebSocket connection")

    async def _handle_disconnect(self, request: Request) -> JSONResponse:
        """Remove the connection ($disconnect)."""
        try:
            connection_id = self._connection_id(request)
            if connection_id:
                await self._offload(self.get_websocket_handler().on_disconnect, connection_id=connection_id)
            return self.build_success_http_response("WebSocket connection closed")
        except Exception as e:
            self._log.exception(f"WebSocket $disconnect failed: {e}")
            return self.build_error_http_response(500, "Failed to close WebSocket connection")

    async def _handle_default(self, request: Request) -> JSONResponse:
        """Handle unknown routes ($default) by notifying the client over WebSocket."""
        try:
            connection_id = self._connection_id(request)
            if connection_id:
                user_id = await self._offload(self.get_websocket_handler().get_user_id, connection_id)
                endpoint_url = self._construct_endpoint_url(request)
                if user_id and endpoint_url:
                    await self._offload(
                        self.get_websocket_handler().broadcast,
                        endpoint_url=endpoint_url,
                        message={"status": "FAILED", "message": "Route not found"},
                        user_id=user_id,
                        message_type=AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE,
                    )
        except Exception as e:
            self._log.warning(f"Failed to notify client on $default: {e}")
        return self.build_success_http_response("Default route handled")


class ECSWebSocketRequestHandler(ECSWebSocketHandlerBase):
    """ECS + API Gateway WebSocket application handler (async mode): the built-in chat route plus custom routes.

    Framework-managed (not a subclassing extension point); the user is resolved from the connection store, not
    re-authenticated per frame. Chat has two paths by config: queue mode enqueues to SQS (never touches ChatService),
    direct mode runs ChatService inline and broadcasts the reply. Custom routes are registered via
    ``@AWSWebsocketAPI.register`` and must also be declared in Terraform ``ws_routes``.
    """

    class WSRouteContext(BaseModel):
        """Everything a WebSocket route resolves from one inbound frame; used internally by the framework.

        Custom routes never receive this object directly (see ``_wrap_custom_route``) — they get
        ``model_dump(exclude={"connection_id", "endpoint_url"})`` of it instead, i.e. a plain
        ``{"message": ..., "user_id": ...}`` dict.

        :param message: The chat route gets the parsed ``BaseRequest`` (route, request_id, body); custom
            routes get the frame's raw JSON body as a ``dict`` (no schema imposed, so callers can use
            whatever body shape they want).
        :param user_id: Authenticated user id resolved from the connection.
        :param connection_id: API Gateway WebSocket connection id; internal-only (needed for ``broadcast``).
        :param endpoint_url: Management API endpoint used to push replies to the client; internal-only.
        """

        message: Any
        user_id: str
        connection_id: str
        endpoint_url: str

    class WSRouteError(Exception):
        """Raised by ``build_route_context`` to short-circuit a route with a specific HTTP status."""

        def __init__(self, status_code: int, message: str):
            super().__init__(message)
            self.status_code = status_code
            self.message = message

    # Backend path the WS API Gateway integration rewrites the chat route to.
    CHAT_PATH = "/ws/chat"

    def __init__(self, custom_routes: Optional[dict[str, Callable]] = None):
        """The connection store is set up by the base class.

        :param custom_routes: Mapping of ``route name -> user function`` (from ``AWSWebsocketAPI.register``); each becomes a ``POST /ws/<route>`` endpoint.
        """
        super().__init__()
        self._log = logging.getLogger("ak.ecs.ws_handler")

        self._custom_routes: dict[str, Callable] = dict(custom_routes or {})
        self._chat_service: Optional[ChatService] = None

    def _is_queue_mode(self) -> bool:
        """True when an input queue is configured (enqueue mode); False for direct mode."""
        return self._config.execution.queues.input.url is not None

    def get_chat_service(self) -> ChatService:
        """Lazily create the ChatService used for direct (non-queue) mode."""
        if self._chat_service is None:
            self._chat_service = ChatService()
        return self._chat_service

    def get_router(self) -> APIRouter:
        """Return an APIRouter: chat at ``POST /ws/chat`` plus each registered custom route at ``POST /ws/<route>``."""
        router = APIRouter()
        router.add_api_route(self.CHAT_PATH, self._handle_chat, methods=["POST"])
        for route_name, func in self._custom_routes.items():
            router.add_api_route(f"/ws/{route_name}", self._wrap_custom_route(func), methods=["POST"])
        return router

    def _wrap_custom_route(self, func: Callable) -> Callable:
        """Wrap a user route function into a FastAPI endpoint.

        Resolves the ``WSRouteContext`` and invokes ``func(msg)`` (awaiting if awaitable) with
        ``msg = ctx.model_dump(exclude={"connection_id", "endpoint_url"})`` — a plain
        ``{"message": ..., "user_id": ...}`` dict; the function never sees the connection id or push
        endpoint. A ``dict`` return is broadcast as ``SYSTEM_RESPONSE`` (``None`` broadcasts nothing),
        and the 200 envelope is returned; a ``WSRouteError`` maps to its status, any other exception
        logs, broadcasts an error, and returns 500.
        """

        async def _endpoint(request: Request) -> JSONResponse:
            ctx: ECSWebSocketRequestHandler.WSRouteContext | None = None
            try:
                ctx = await self.build_route_context(request)
                msg = ctx.model_dump(exclude={"connection_id", "endpoint_url"})
                result = func(msg)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None:
                    await self._offload(
                        self.get_websocket_handler().broadcast,
                        endpoint_url=ctx.endpoint_url,
                        message=result,
                        user_id=ctx.user_id,
                        message_type=AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE,
                    )
                return self.build_success_http_response("Message processed successfully", user_id=ctx.user_id)
            except self.WSRouteError as e:
                return self.build_error_http_response(e.status_code, e.message)
            except Exception as e:
                self._log.exception(f"WebSocket custom route failed: {e}")
                if ctx is not None:
                    try:
                        await self._offload(
                            self.get_websocket_handler().broadcast,
                            endpoint_url=ctx.endpoint_url,
                            message={"status": "FAILED", "message": "Route handler encountered an error"},
                            user_id=ctx.user_id,
                            message_type=AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE,
                        )
                    except Exception as broadcast_error:
                        self._log.warning(f"Failed to broadcast error to client: {broadcast_error}")
                return self.build_error_http_response(500, "Route processing failed")

        return _endpoint

    async def build_route_context(self, request: Request, *, is_chat_request: bool = False) -> "ECSWebSocketRequestHandler.WSRouteContext":
        """Parse the inbound frame and resolve the connection's user and push endpoint.

        :param request: The proxied WebSocket frame (FastAPI Request).
        :param is_chat_request: True for the chat route: ``message`` is parsed into a ``BaseRequest``. False
            (custom routes) leaves ``message`` as the frame's raw JSON body (``dict``), unparsed.
        :return: A fully-resolved WSRouteContext.
        :raises WSRouteError: If the connection id, user, or push endpoint cannot be resolved.
        """
        connection_id = self._connection_id(request)
        if not connection_id:
            raise self.WSRouteError(500, "Missing connection id")

        raw_body = await request.body()
        payload = json.loads(raw_body) if raw_body else {}
        message = BaseRequest.from_payload(payload) if is_chat_request else payload

        user_id = await self._offload(self.get_websocket_handler().get_user_id, connection_id)
        if not user_id:
            raise self.WSRouteError(401, f"No user found for connection_id: {connection_id}")

        endpoint_url = self._construct_endpoint_url(request)
        if not endpoint_url:
            raise self.WSRouteError(500, "Unable to resolve WebSocket endpoint URL")

        return self.WSRouteContext(
            message=message,
            user_id=user_id,
            connection_id=connection_id,
            endpoint_url=endpoint_url,
        )

    async def _enqueue_chat(self, body: BaseRunRequest, user_id: str, request_id: Optional[str], session_id: str, endpoint_url: str) -> JSONResponse:
        """Queue mode: send to the input queue; ECSOutputConsumer pushes the reply."""
        self._log.info(f"Enqueuing WS chat request: request_id={request_id}, session_id={session_id}, user_id={user_id}")

        await self._offload(
            SQSHandler.send_message_to_input_queue,
            message_body=body.model_dump(),
            attributes={"message_group_id": session_id, "message_deduplication_id": request_id},
            request_id=request_id,
            user_id=user_id,
            custom_message_attributes=[
                SQSHandler.CustomAttribute(name="endpoint_url", value=endpoint_url, datatype=SQSHandler.AttributeDataType.STRING)
            ],
        )

        response = self._body("Request queued successfully", success=True, user_id=user_id)
        response["request_id"] = request_id
        return JSONResponse(status_code=200, content=response)

    async def _process_chat_direct(self, body: BaseRunRequest, user_id: str, endpoint_url: str) -> JSONResponse:
        """Direct (non-queue) mode: run the agent inline and broadcast the reply over the connection."""
        self._log.info(f"Processing WS chat request inline (direct mode) for user_id={user_id}")

        # ChatService(rest_api_mode=False) returns (status_code, response_dict)
        status_code, res_body = await self.get_chat_service().process_async_chat_request(body)
        message = res_body if isinstance(res_body, dict) else {"response": res_body}

        await self._offload(
            self.get_websocket_handler().broadcast,
            endpoint_url=endpoint_url,
            message=message,
            user_id=user_id,
            message_type=AWSWebSocketHandler.MessageType.CHAT_RESPONSE,
        )
        return self.build_success_http_response("Request processed successfully", user_id=user_id, status_code=status_code)

    async def _handle_chat(self, request: Request) -> JSONResponse:
        """Handle a chat frame: enqueue it (queue mode) or run the agent inline (direct mode)."""
        try:
            ctx = await self.build_route_context(request, is_chat_request=True)

            if ctx.message.body is None:
                return self.build_error_http_response(400, "body is required")

            session_id = ctx.message.body.session_id
            if not session_id:
                return self.build_error_http_response(400, "session_id is required")

            if self._is_queue_mode():
                return await self._enqueue_chat(ctx.message.body, ctx.user_id, ctx.message.request_id, session_id, ctx.endpoint_url)
            return await self._process_chat_direct(ctx.message.body, ctx.user_id, ctx.endpoint_url)
        except self.WSRouteError as e:
            return self.build_error_http_response(e.status_code, e.message)
        except Exception as e:
            self._log.exception(f"WebSocket chat request failed: {e}")
            return self.build_error_http_response(500, "Request processing failed")


class AWSWebsocketAPI(RESTAPI):
    """REST API for ECS containerized WebSocket deployments.

    Assembles the framework-managed system handler ($connect/$disconnect/$default, built lazily from the
    registered ``AuthValidator``) and one application handler (chat + every route registered via ``register``).
    Authentication is mandatory: call ``set_auth_handler`` (claims must include a ``userId``) before ``run()``.
    """

    _RESERVED_ROUTES: ClassVar[set[str]] = {
        ECSWebSocketSystemRequestHandler.CONNECT_PATH.rsplit("/", 1)[-1],
        ECSWebSocketSystemRequestHandler.DISCONNECT_PATH.rsplit("/", 1)[-1],
        ECSWebSocketSystemRequestHandler.DEFAULT_PATH.rsplit("/", 1)[-1],
        ECSWebSocketRequestHandler.CHAT_PATH.rsplit("/", 1)[-1],
    }

    _ws_auth_validator: Optional[AuthValidator] = None
    _ws_custom_routes: ClassVar[dict[str, Callable]] = {}

    @classmethod
    def register(cls, route: str) -> Callable[[Callable], Callable]:
        """Decorator that registers a custom WebSocket route (bare route name only).

        The function (sync or async) receives a ``dict`` with ``message`` (the frame's raw JSON body,
        unparsed — no ``BaseRequest``/schema imposed, so any custom request shape works) and ``user_id``
        (the authenticated user id). It does not receive the connection id or push endpoint. A ``dict``
        return is broadcast to the client, ``None`` broadcasts nothing. The name is validated at
        decoration time (see ``_validate_route_name``); re-registering the same route keeps the first.
        The route must also be declared in Terraform ``ws_routes``.

        :param route: Bare route name (e.g. ``"status"``), mapped to ``POST /ws/<route>``.
        :return: The decorator; returns the wrapped function unchanged.
        """
        cls._validate_route_name(route)

        def _decorator(func: Callable) -> Callable:
            if route in cls._ws_custom_routes:
                logging.getLogger("ak.ecs.ws_api").warning(f"WebSocket route '{route}' is already registered. Keeping the first registration.")
                return func
            cls._ws_custom_routes[route] = func
            return func

        return _decorator

    @classmethod
    def _validate_route_name(cls, route: str) -> None:
        """Validate a custom route name, raising ValueError on any violation (see ``register``)."""
        if not isinstance(route, str) or not route:
            raise ValueError("WebSocket route name must be a non-empty string.")
        if route.startswith("/"):
            raise ValueError(
                f"WebSocket route '{route}' must be a bare route name, not a path — do not prefix "
                "it with '/ws/' (the framework maps it to POST /ws/<route> automatically)."
            )
        if route in cls._RESERVED_ROUTES:
            raise ValueError(
                f"WebSocket route name '{route}' is already registered by the framework "
                "($connect/$disconnect/$default or chat) and cannot be reused."
            )
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", route):
            raise ValueError(f"Invalid WebSocket route name '{route}': only letters, digits, '_' and '-' are allowed.")

    @classmethod
    def set_auth_handler(cls, auth_validator: AuthValidator) -> "type[AWSWebsocketAPI]":
        """Register the AuthValidator used to authenticate the $connect handshake (call before ``run()``).

        :param auth_validator: AuthValidator whose ValidationResult claims include a ``userId``.
        :return: The class itself, to allow chaining with ``run()``.
        """
        cls._ws_auth_validator = auth_validator
        return cls

    @classmethod
    def _build_system_handler(cls) -> ECSWebSocketSystemRequestHandler:
        """Build the framework-managed system handler from the registered validator."""
        if cls._ws_auth_validator is None:
            raise ValueError(
                "WebSocket authentication is mandatory. Register a validator with "
                "AWSWebsocketAPI.set_auth_handler(auth_validator=...) before calling run()."
            )
        return ECSWebSocketSystemRequestHandler(auth_validator=cls._ws_auth_validator)

    @classmethod
    def get_default_handlers(cls) -> list[RESTRequestHandler]:
        """The system handler plus the single application handler carrying every registered route."""
        return [cls._build_system_handler(), ECSWebSocketRequestHandler(custom_routes=cls._ws_custom_routes)]

    @classmethod
    def run(cls) -> None:
        """Start the WebSocket API server with the system handler plus the chat/custom-route application handler."""
        super().run(handlers=cls.get_default_handlers())
