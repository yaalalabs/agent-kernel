"""
ECS WebSocket ingress handlers and WebSocket API.

API Gateway WebSocket proxies each frame (HTTP_PROXY -> VPC Link -> ALB) to this
container. Unlike the serverless Lambda (one function, dispatch on routeKey), the ECS
service exposes a **separate HTTP endpoint per WebSocket route** — the gateway maps each
route to its own backend path via overwrite:path, so no in-app dispatch is needed.

  $connect       -> POST /ws/connect     (auth + store connection)
  $disconnect    -> POST /ws/disconnect  (remove connection)
  $default       -> POST /ws/default     (notify client of unknown route)
  <chat route>   -> POST /ws/chat        (queue mode: enqueue; direct mode: run agent inline)
  <custom route> -> POST /ws/<route>     (added by subclassing — see below)

Routes are split across two handlers, mirroring the serverless side (ConnectionRoutesHandler /
SystemRoutesHandler over a shared base):

- ``ECSWebSocketSystemRequestHandler`` owns the framework-managed protocol routes
  ($connect/$disconnect/$default). $connect authenticates the handshake, so this handler owns the
  ``AuthValidator``. Applications never touch it — ``AWSWebsocketAPI`` wires it in automatically.
- ``ECSWebSocketRequestHandler`` owns the application routes: the built-in chat route plus any
  custom routes. This is the extension point — it needs no ``AuthValidator`` (the connection's user
  is resolved from the store, not re-authenticated per frame).

Both share ``ECSWebSocketHandlerBase``: the connection store, the push-endpoint construction, and
the response envelope.

Custom routes follow the same extension model as the containerized REST handlers: subclass
``ECSWebSocketRequestHandler``, call ``super().get_router()``, and add your own ``/ws/<route>`` POST
endpoints onto the returned router (see the class docstring for an example). Each custom route must
be declared in Terraform via ``ws_routes`` (which maps the route to POST /ws/<route>); both sides
must agree on the route name, exactly like the configurable chat route.

The WS $context (connection id, domain, stage) still arrives as x-ws-* headers.
Responses are pushed back over the connection by ECSOutputConsumer (ASYNC mode).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ......api.handler import RESTRequestHandler
from ......api.http import RESTAPI
from ......auth.handler import AuthValidator
from ......core.chat_service import ChatService
from ......core.config import AKConfig
from ......core.model import BaseRequest, BaseRunRequest
from ....core.sqs_handler import SQSHandler
from ....core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore


class ECSWebSocketHandlerBase(RESTRequestHandler):
    """Shared plumbing for the ECS WebSocket handlers.

    Both the system handler ($connect/$disconnect/$default) and the application handler (chat +
    custom routes) proxy through the same container and share the same connection store, push
    endpoint construction, and response envelope. That common machinery lives here; each subclass
    adds only its own routes and route-specific state.

    The connection store and WebSocket handler are created lazily per instance — the two handlers
    end up with their own clients pointing at the same DynamoDB table (same as the serverless
    LambdaWSHandler pattern), which is stateless and safe.

    Abstract: ``get_router`` is left unimplemented (inherited from RESTRequestHandler) so this
    class cannot be instantiated on its own.
    """

    # WS $context headers injected by api_gateway_ws.tf (context.* -> integration.request.header.*)
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
        """Lazily create the AWS WebSocket handler (API Gateway Management API + DynamoDB store)."""
        if self._ws_handler is None:
            self._ws_handler = AWSWebSocketHandler(connection_store=self.get_connection_store())
        return self._ws_handler

    def _connection_id(self, request: Request) -> Optional[str]:
        return request.headers.get(self.CONNECTION_ID_HEADER)

    def _construct_endpoint_url(self, request: Request) -> Optional[str]:
        """Build the API Gateway management endpoint from headers, falling back to config.

        Reuses AWSWebSocketHandler.construct_endpoint_url for the actual URL formatting by
        adapting the ECS x-ws-* headers into the requestContext shape it expects.
        """
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


class ECSWebSocketSystemRequestHandler(ECSWebSocketHandlerBase):
    """Framework-managed WebSocket protocol routes: $connect, $disconnect, $default.

    These are owned by the framework and are not an extension point — applications don't subclass
    this. $connect authenticates the handshake, so this handler owns the ``AuthValidator``.
    ``AWSWebsocketAPI`` builds it automatically from the validator registered via
    ``set_auth_handler``, so you normally never construct it directly.
    """

    # Backend paths — the WS API Gateway integration rewrites each route to one of these.
    CONNECT_PATH = "/ws/connect"
    DISCONNECT_PATH = "/ws/disconnect"
    DEFAULT_PATH = "/ws/default"

    def __init__(self, auth_validator: AuthValidator):
        """
        :param auth_validator: AuthValidator used to authenticate the WebSocket $connect handshake.
            Authentication is **mandatory** for WebSocket mode — the validator's ValidationResult
            must include a ``userId`` claim, which keys the connection so replies can be pushed back
            to the right client. Passing ``None`` raises ValueError.
        """
        super().__init__()
        self._log = logging.getLogger("ak.ecs.ws_system_handler")

        if auth_validator is None:
            raise ValueError(
                "auth_validator is required for WebSocket mode — authentication is mandatory. "
                "Pass an AuthValidator whose claims include a 'userId'."
            )
        self._auth_validator = auth_validator

    def get_router(self) -> APIRouter:
        """Return an APIRouter with one POST endpoint per framework protocol route."""
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
                return self._response(500, "Missing connection id", success=False)

            token = request.query_params.get("token")
            if not token:
                return self._response(401, "Authentication token is required", success=False)

            result = self._auth_validator.validate(token)
            if not result.is_valid:
                return self._response(401, result.error_msg or "Authentication failed", success=False)

            user_id = (result.claims or {}).get("userId")
            if not user_id:
                return self._response(401, "'userId' claim is required in token", success=False)

            self.get_websocket_handler().on_connect(connection_id=connection_id, user_id=user_id)
            return self._response(200, "WebSocket connection established", success=True, user_id=user_id)
        except Exception as e:
            self._log.exception(f"WebSocket $connect failed: {e}")
            return self._response(500, "Failed to establish WebSocket connection", success=False)

    async def _handle_disconnect(self, request: Request) -> JSONResponse:
        """Remove the connection ($disconnect)."""
        try:
            connection_id = self._connection_id(request)
            if connection_id:
                self.get_websocket_handler().on_disconnect(connection_id=connection_id)
            return self._response(200, "WebSocket connection closed", success=True)
        except Exception as e:
            self._log.exception(f"WebSocket $disconnect failed: {e}")
            return self._response(500, "Failed to close WebSocket connection", success=False)

    async def _handle_default(self, request: Request) -> JSONResponse:
        """Handle unknown routes ($default) by notifying the client over WebSocket."""
        try:
            connection_id = self._connection_id(request)
            if connection_id:
                user_id = self.get_websocket_handler().get_user_id(connection_id)
                endpoint_url = self._construct_endpoint_url(request)
                if user_id and endpoint_url:
                    self.get_websocket_handler().broadcast(
                        endpoint_url=endpoint_url,
                        message={"status": "FAILED", "message": "Route not found"},
                        user_id=user_id,
                        message_type=AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE,
                    )
        except Exception as e:
            self._log.warning(f"Failed to notify client on $default: {e}")
        return self._response(200, "Default route handled", success=True)


class ECSWebSocketRequestHandler(ECSWebSocketHandlerBase):
    """
    ECS + API Gateway WebSocket application handler for ASYNC mode — the built-in chat route plus
    any custom routes.

    This is the WebSocket extension point. The framework-managed protocol routes
    ($connect/$disconnect/$default) live on ``ECSWebSocketSystemRequestHandler``, which
    ``AWSWebsocketAPI`` wires in automatically — so this handler needs no ``AuthValidator``: the
    connection's user is resolved from the connection store (populated at $connect), not
    re-authenticated per frame.

    Two chat paths, chosen by whether an input queue is configured:
    - Queue mode: enqueue to SQS; ECSAgentRunner runs the agent and ECSOutputConsumer
      pushes the reply. This handler never touches ChatService.
    - Direct (non-queue) mode: run ChatService inline and broadcast the reply over the
      connection right away (mirrors serverless SystemRoutesHandler._handle_direct_chat).

    Custom routes are added the same way as the containerized REST handlers (see the crewai
    example, "Option 2"): subclass, call ``super().get_router()``, and add your own ``/ws/<route>``
    POST endpoints. ``build_route_context`` gives you the parsed frame, the authenticated user, and
    the push endpoint in one call; ``handle_route_error`` renders the standard error response. The
    route must also be declared in Terraform via ``ws_routes``. Example::

        class MyWSHandler(ECSWebSocketRequestHandler):
            def get_router(self) -> APIRouter:
                router = super().get_router()

                @router.post("/ws/status")            # Terraform: ws_routes = [{ route = "status" }]
                async def status(request: Request) -> JSONResponse:
                    try:
                        ctx = await self.build_route_context(request)
                    except self.WSRouteError as e:
                        return self.handle_route_error(e)
                    self.get_websocket_handler().broadcast(
                        endpoint_url=ctx.endpoint_url,
                        message={"status": "OK", "user_id": ctx.user_id},
                        user_id=ctx.user_id,
                        message_type=AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE,
                    )
                    return self.build_success_response("status processed", user_id=ctx.user_id)

                return router

        AWSWebsocketAPI.set_auth_handler(auth_validator=MyValidator()).run(handlers=[MyWSHandler()])
    """

    @dataclass
    class WSRouteContext:
        """Everything a WebSocket route endpoint needs, resolved from one inbound frame.

        Returned by ``build_route_context`` and used both by the built-in chat route and by custom
        routes added in subclasses.

        :param request: Parsed inbound frame (route, request_id, body).
        :param user_id: Authenticated user id resolved from the connection.
        :param connection_id: API Gateway WebSocket connection id.
        :param endpoint_url: Management API endpoint used to push replies back to the client.
        """

        request: BaseRequest
        user_id: str
        connection_id: str
        endpoint_url: str

    class WSRouteError(Exception):
        """Raised by ``build_route_context`` to short-circuit a route with an HTTP status.

        Custom route endpoints can let this propagate to ``handle_route_error`` (or catch it) to
        turn a failed context resolution (missing connection id, unauthenticated connection, etc.)
        into the right HTTP status instead of a generic 500.
        """

        def __init__(self, status_code: int, message: str):
            super().__init__(message)
            self.status_code = status_code
            self.message = message

    # Backend path — the WS API Gateway integration rewrites the chat route to this.
    CHAT_PATH = "/ws/chat"

    def __init__(self):
        """Validate the chat-route config; the connection store is set up by the base class."""
        super().__init__()
        self._log = logging.getLogger("ak.ecs.ws_handler")

        if not self._config.websocket_api.chat_route:
            raise ValueError("websocket_api.chat_route is required for WebSocket mode")

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
        """Return an APIRouter with the built-in chat POST endpoint.

        Subclasses add custom ``/ws/<route>`` routes by overriding this method, calling
        ``super().get_router()``, and registering their endpoints onto the returned router — the
        same extension model as the containerized REST handlers (see the class docstring).
        """
        router = APIRouter()
        router.add_api_route(self.CHAT_PATH, self._handle_chat, methods=["POST"])
        return router

    async def build_route_context(self, request: Request) -> "ECSWebSocketRequestHandler.WSRouteContext":
        """Parse the inbound frame and resolve the connection's user and push endpoint.

        Shared by the built-in chat route and available to custom routes added in subclasses — it
        turns the proxied HTTP request (x-ws-* headers + JSON body) into everything a route needs:
        the parsed frame, the authenticated user, and the push endpoint.

        :param request: The proxied WebSocket frame (FastAPI Request).
        :return: A fully-resolved WSRouteContext.
        :raises WSRouteError: If the connection id, user, or push endpoint cannot be resolved.
        """
        connection_id = self._connection_id(request)
        if not connection_id:
            raise self.WSRouteError(500, "Missing connection id")

        raw_body = await request.body()
        payload = json.loads(raw_body) if raw_body else {}
        ws_request = BaseRequest.from_payload(payload)

        user_id = self.get_websocket_handler().get_user_id(connection_id)
        if not user_id:
            raise self.WSRouteError(401, f"No user found for connection_id: {connection_id}")

        endpoint_url = self._construct_endpoint_url(request)
        if not endpoint_url:
            raise self.WSRouteError(500, "Unable to resolve WebSocket endpoint URL")

        return self.WSRouteContext(
            request=ws_request,
            user_id=user_id,
            connection_id=connection_id,
            endpoint_url=endpoint_url,
        )

    def handle_route_error(self, error: "ECSWebSocketRequestHandler.WSRouteError") -> JSONResponse:
        """Render a WSRouteError (raised by build_route_context) as the standard error response."""
        return self._response(error.status_code, error.message, success=False)

    def build_success_response(self, msg: str, user_id: Optional[str] = None) -> JSONResponse:
        """Build the standard 200 success response used by WebSocket routes."""
        return self._response(200, msg, success=True, user_id=user_id)

    def _enqueue_chat(self, body: BaseRunRequest, user_id: str, request_id: Optional[str], session_id: str, endpoint_url: str) -> JSONResponse:
        """Queue mode: send to the input queue; ECSOutputConsumer pushes the reply."""
        self._log.info(f"Enqueuing WS chat request: request_id={request_id}, session_id={session_id}, user_id={user_id}")

        SQSHandler.send_message_to_input_queue(
            message_body=body.model_dump(),
            message_group_id=session_id,
            message_deduplication_id=request_id,
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

        self.get_websocket_handler().broadcast(
            endpoint_url=endpoint_url,
            message=message,
            user_id=user_id,
            message_type=AWSWebSocketHandler.MessageType.CHAT_RESPONSE,
        )
        return self._response(status_code, "Request processed successfully", success=True, user_id=user_id)

    async def _handle_chat(self, request: Request) -> JSONResponse:
        """Handle a chat frame: enqueue it (queue mode) or run the agent inline (direct mode)."""
        try:
            ctx = await self.build_route_context(request)

            if ctx.request.body is None:
                return self._response(400, "body is required", success=False)

            session_id = ctx.request.body.session_id
            if not session_id:
                return self._response(400, "session_id is required", success=False)

            if self._is_queue_mode():
                return self._enqueue_chat(ctx.request.body, ctx.user_id, ctx.request.request_id, session_id, ctx.endpoint_url)
            return await self._process_chat_direct(ctx.request.body, ctx.user_id, ctx.endpoint_url)
        except self.WSRouteError as e:
            return self.handle_route_error(e)
        except Exception as e:
            self._log.exception(f"WebSocket chat request failed: {e}")
            return self._response(500, "Request processing failed", success=False)


class AWSWebsocketAPI(RESTAPI):
    """
    REST API for ECS containerized WebSocket deployments.

    Assembles two handlers: the framework-managed protocol handler
    (``ECSWebSocketSystemRequestHandler`` — $connect/$disconnect/$default) and the application
    handler (``ECSWebSocketRequestHandler`` — chat + custom routes). The system handler is **always
    injected automatically** from the registered ``AuthValidator``; callers only ever supply
    application handlers.

    The system handler is built lazily (never as a class attribute at import time): its constructor
    validates ``websocket_api`` config and requires an AuthValidator, so building it eagerly would
    break every import of this module in apps that haven't configured WebSocket mode.

    Authentication is **mandatory** for WebSocket mode. Register the validator once with
    ``set_auth_handler`` before calling ``run()`` (the validator's claims must include a ``userId``,
    which keys the connection so replies reach the right client)::

        from agentkernel.aws import AWSWebsocketAPI

        AWSWebsocketAPI.set_auth_handler(auth_validator=CustomAuthValidator()).run()

    To add custom WebSocket routes, subclass ``ECSWebSocketRequestHandler`` and pass an instance to
    run(). The system handler (with its validator) is added for you::

        AWSWebsocketAPI.set_auth_handler(auth_validator=CustomAuthValidator()).run(handlers=[MyWSHandler()])
    """

    # Set via set_auth_handler(); consumed to build the framework-managed system handler.
    _ws_auth_validator: Optional[AuthValidator] = None

    @classmethod
    def set_auth_handler(cls, auth_validator: AuthValidator) -> "type[AWSWebsocketAPI]":
        """Register the AuthValidator used to authenticate the WebSocket $connect handshake.

        Authentication is mandatory for WebSocket mode, and the framework-managed system handler is
        built from this validator on every ``run()``. Call this before ``run()``. Returns the class
        so it can be chained: ``AWSWebsocketAPI.set_auth_handler(validator).run()``.

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
        """The system handler plus the built-in application (chat) handler."""
        return [cls._build_system_handler(), ECSWebSocketRequestHandler()]

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] = None) -> None:
        """Start the WebSocket API server.

        The framework-managed system handler ($connect/$disconnect/$default) is always injected;
        any ``handlers`` passed here are treated as application handlers (chat + custom routes) and
        registered alongside it. With no ``handlers``, the built-in chat handler is used.

        :param handlers: Optional application handlers (e.g. subclasses of
            ``ECSWebSocketRequestHandler`` that add custom routes).
        """
        if handlers is None:
            handlers = cls.get_default_handlers()
        else:
            handlers = [cls._build_system_handler(), *handlers]
        super().run(handlers=handlers)
