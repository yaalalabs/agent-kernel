import json
import logging
import traceback
from collections.abc import Callable
from typing import Any, Optional

from pydantic import BaseModel

from ......core.chat_service import ChatService
from ......core.config import AKConfig
from ......core.model import BaseRequest, Principal, StreamChunk
from ......core.util.async_bridge import run_async_sync
from ......core.util.factory import AKConfigError
from ......identity.errors import AuthenticationError
from ......identity.provider.base import RequestContext
from ......identity.provider.request import RequestAuthenticator
from ....core.sqs_handler import SQSHandler
from ....core.websocket_service import AWSWebSocketHandler, WebSocketConnectionStore
from .common import BaseLambdaRouter


class LambdaWSHandler(AWSWebSocketHandler):
    """Base class for Lambda WebSocket route handlers; adds Lambda API Gateway event parsing to AWSWebSocketHandler."""

    class WSMessageInfo(BaseModel):
        """WebSocket message information: the frame's request and the connection's principal (``user_id`` is its subject)."""

        user_id: str
        request: BaseRequest
        principal: Principal

    def __init__(self):
        """Initialize the Lambda WebSocket handler from configuration."""
        config = AKConfig.get()
        if not config.websocket_api.connection_table or not config.websocket_api.connection_table.table_name:
            raise ValueError("websocket_api.connection_table.table_name is required for WebSocket handler")
        connection_store = WebSocketConnectionStore(
            table_name=config.websocket_api.connection_table.table_name,
            ttl=config.websocket_api.connection_table.ttl,
        )
        super().__init__(connection_store=connection_store)
        self._config = config
        self.CONNECT_ROUTE = "$connect"
        self.DISCONNECT_ROUTE = "$disconnect"
        self.DEFAULT_ROUTE = "$default"
        self.CHAT_ROUTE = config.websocket_api.chat_route

    def _parse_body(self, event: dict[str, Any]) -> BaseRequest:
        """
        Parse request body from WebSocket event.

        :param event: WebSocket event dictionary
        :return: Parsed BaseRequest object
        """
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) and body else (body or {})
        return BaseRequest.from_payload(body_dict)

    def _extract_connection_id(self, event: dict[str, Any]) -> str:
        """
        Extract connection ID from WebSocket event.

        :param event: WebSocket event dictionary
        :return: Connection ID string
        :raises ValueError: If connectionId is missing
        """
        request_context = event.get("requestContext", {})
        connection_id = request_context.get("connectionId")
        if not connection_id:
            raise ValueError("WebSocket event missing requestContext.connectionId")
        return connection_id

    def _parse_event_to_wsmessage(self, event: dict[str, Any]) -> "LambdaWSHandler.WSMessageInfo":
        """
        Parse WebSocket event to WSMessageInfo object.

        The connection's principal, stored at ``$connect``, becomes the request body's: ``from_payload``
        dropped anything the frame named.

        :param event: WebSocket event dictionary
        :return: WSMessageInfo object with the principal, its subject as user_id, and the request
        :raises ValueError: If connection_id is missing or no principal is stored for it
        """
        request = self._parse_body(event)
        principal = self._connection_principal(event)
        if request.body is not None:
            request.body.principal = principal
        return self.WSMessageInfo(user_id=principal.subject, request=request, principal=principal)

    def _connection_principal(self, event: dict[str, Any]) -> Principal:
        """The principal stored for the event's connection at ``$connect``.

        :param event: WebSocket event dictionary
        :return: The connection's principal
        :raises ValueError: If connection_id is missing or no principal is stored for it
        """
        connection_id = self._extract_connection_id(event)
        principal = self.get_principal(connection_id)
        if principal is None:
            raise ValueError(f"No principal found for connection_id: {connection_id}")
        return principal

    def _handle_msg_and_brdcst(
        self,
        event: dict[str, Any],
        operation: Callable[[WSMessageInfo], dict[str, Any]],
        message_type: Optional["LambdaWSHandler.MessageType"] = None,
    ) -> tuple[int, dict[str, Any]]:
        """
        Handle message and broadcast result to user.

        :param event: WebSocket event dictionary
        :param operation: Function to process the request
        :param message_type: Optional message type for broadcasting
        :return: Tuple of (status_code, response_body)
        """
        user_id = None
        try:
            ws_message_info = self._parse_event_to_wsmessage(event)
            user_id = ws_message_info.user_id
            brdcstin_msg = operation(ws_message_info)
            endpoint_url = LambdaWSHandler.construct_endpoint_url(event)
            self.broadcast(endpoint_url=endpoint_url, message=brdcstin_msg, user_id=user_id, message_type=message_type)
            return (
                200,
                self._build_lambda_response(user_id=user_id, msg="Request processed successfully", success=True),
            )
        except Exception as e:
            self._log.error(f"Request failed: {e}\n{traceback.format_exc()}")
            return (
                500,
                self._build_lambda_response(user_id=user_id, msg="Request processing failed", success=False),
            )

    def _build_lambda_response(
        self,
        user_id: str | None = None,
        msg: str | None = None,
        success: bool = True,
    ) -> dict[str, Any]:
        """
        Build a standardized response body.

        :param user_id: Optional user ID for tracking
        :param msg: Message to include in the response
        :param success: Whether the response is a success or failure
        :return: Standardized response dictionary
        """
        msg = msg or ("Operation successful" if success else "An unexpected error occurred")
        body = {"status": "SUCCESS", "message": msg} if success else {"status": "FAILED", "message": msg}
        if user_id:
            body["user_id"] = user_id
        return body


class ConnectionRoutesHandler(LambdaWSHandler):
    """Handles WebSocket connection lifecycle routes ($connect, $disconnect).

    Authentication is mandatory: ``$connect`` validates the ``token`` query parameter through the
    configured identity provider and keys the connection by the principal's subject, storing the
    whole principal for the frames that follow.
    """

    _log = logging.getLogger("ak.aws.serverless.connection_routes")

    def __init__(self):
        """Build the handler over the configured identity provider.

        :raises AKConfigError: If no identity provider is configured: the connection is keyed by the
            authenticated subject, so a handshake nobody can authenticate cannot be served.
        """
        super().__init__()
        self._authenticator = RequestAuthenticator.from_config()
        if self._authenticator.provider is None:
            raise AKConfigError("the WebSocket connection routes require an identity block: the connection is keyed by the authenticated subject")

    def _extract_auth_token(self, event: dict[str, Any]) -> str | None:
        """
        Extract authentication token from WebSocket event query string.

        :param event: WebSocket event dictionary
        :return: Token string if found, None otherwise
        """
        query_params = event.get("queryStringParameters", {})
        if isinstance(query_params, dict):
            return query_params.get("token")
        return None

    def get_routes(self) -> dict[str, Callable[[dict[str, Any], Any], Any]]:
        """
        Get registered connection route handlers.

        :param: None
        :return: Dictionary mapping route keys to handler functions
        """
        return {
            self.CONNECT_ROUTE: self._handle_connect,
            self.DISCONNECT_ROUTE: self._handle_disconnect,
        }

    def _handle_connect(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle WebSocket $connect route with mandatory authentication.

        The token is validated by the configured identity provider; the provider's reason for a
        refusal goes to the log and the client sees a generic 401, as on HTTP.

        :param event: WebSocket connect event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        try:
            connection_id = self._extract_connection_id(event)

            token = self._extract_auth_token(event)
            if not token:
                return 401, self._build_lambda_response(msg="Authentication token is required", success=False)

            try:
                principal = run_async_sync(self._authenticator.authenticate_token(token, RequestContext(path=self.CONNECT_ROUTE)))
            except AuthenticationError as exc:
                self._log.info(f"Refused WebSocket credential: {exc}")
                return 401, self._build_lambda_response(msg="Authentication failed", success=False)
            if principal.is_anonymous:
                # Unreachable with the provider the constructor demanded; refused rather than keyed on "anonymous".
                return 401, self._build_lambda_response(msg="Authentication failed", success=False)

            self.on_connect(connection_id=connection_id, principal=principal)

            return 200, self._build_lambda_response(user_id=principal.subject, msg="WebSocket connection established", success=True)

        except Exception as e:
            self._log.error(f"WebSocket $connect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to establish WebSocket connection", success=False)

    def _handle_disconnect(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle WebSocket $disconnect route.

        :param event: WebSocket disconnect event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        try:
            connection_id = self._extract_connection_id(event)

            self.on_disconnect(connection_id=connection_id)
            return 200, self._build_lambda_response(msg="WebSocket connection closed", success=True)
        except Exception as e:
            self._log.error(f"WebSocket $disconnect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to close WebSocket connection", success=False)


class SystemRoutesHandler(LambdaWSHandler):
    """Handles WebSocket application routes ($default, /chat).

    This handler is responsible for application-level WebSocket operations
    like chat processing. Connection authentication is assumed to be already
    validated by the connection handler.
    """

    _log = logging.getLogger("ak.aws.serverless.system_routes")

    def __init__(self):
        """Initialize system routes handler."""
        super().__init__()
        if not self.CHAT_ROUTE:
            raise ValueError("websocket_api.chat_route must be configured")
        self._chat_service = ChatService()

    def _is_queue_mode(self) -> bool:
        """
        Check if queue mode is enabled (queues are configured).

        :param: None
        :return: True if both input and output queues are configured
        """
        return self._config.execution.queues.input.url is not None

    def get_routes(self) -> dict[str, Callable[[dict[str, Any], Any], Any]]:
        """
        Get registered system route handlers.

        :param: None
        :return: Dictionary mapping route keys to handler functions
        """
        return {
            self.DEFAULT_ROUTE: self._handle_default,
            self.CHAT_ROUTE: self._get_chat_handler_by_mode(),
        }

    def _get_chat_handler_by_mode(self) -> Callable:
        """
        Return the appropriate chat handler based on execution mode and queue configuration.

        :param: None
        :return: Chat handler callable
        """
        if self._config.execution.is_delta:
            return self._handle_queue_mode if self._is_queue_mode() else self._handle_stream_direct
        return self._handle_queue_mode if self._is_queue_mode() else self._handle_direct_chat

    def _handle_default(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle WebSocket $default route.

        :param event: WebSocket default route event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """

        def _process_default(ws_message_info: "LambdaWSHandler.WSMessageInfo") -> dict[str, Any]:
            self.on_default()
            requested_route = ws_message_info.request.route
            return {"status": "FAILED", "message": f"Route '{requested_route}' not found"}

        return self._handle_msg_and_brdcst(
            event,
            _process_default,
            self.MessageType.SYSTEM_RESPONSE,
        )

    def _handle_direct_chat(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle direct chat request without queue.

        :param event: WebSocket chat event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """

        def _process_chat(ws_message_info: "LambdaWSHandler.WSMessageInfo") -> dict[str, Any]:
            request = ws_message_info.request
            if request.body is None:
                raise ValueError("body is required")
            _, res_body = self._chat_service.process_chat_request(request.body)
            return res_body

        return self._handle_msg_and_brdcst(
            event,
            _process_chat,
            message_type=self.MessageType.CHAT_RESPONSE,
        )

    def _handle_stream_direct(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle direct streaming chat request without queue (non-queue async + delta).

        Streams agent response chunks directly via WebSocket.

        :param event: WebSocket chat event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        user_id = None
        session_id = None
        try:
            ws_message_info = self._parse_event_to_wsmessage(event)
            user_id = ws_message_info.user_id
            request = ws_message_info.request
            if request.body is None:
                raise ValueError("body is required")
            session_id = request.body.session_id

            endpoint_url = LambdaWSHandler.construct_endpoint_url(event)

            for raw_chunk in self._chat_service.process_stream_chat_sync(req=request.body):
                chunk_dict = json.loads(raw_chunk)
                self.broadcast(endpoint_url=endpoint_url, message=chunk_dict, user_id=user_id, message_type=self.MessageType.STREAM_CHUNK)

            return 200, self._build_lambda_response(user_id=user_id, msg="Stream completed successfully", success=True)
        except Exception as e:
            self._log.error(f"Stream direct request failed: {e}\n{traceback.format_exc()}")
            try:
                endpoint_url = LambdaWSHandler.construct_endpoint_url(event)
                error_chunk = StreamChunk(error=str(e), done=True)
                error_chunk_dict = error_chunk.model_dump(exclude_none=True)
                if session_id:
                    error_chunk_dict["session_id"] = session_id
                self.broadcast(endpoint_url=endpoint_url, message=error_chunk_dict, user_id=user_id, message_type=self.MessageType.STREAM_CHUNK)
            except Exception:
                pass
            return 500, self._build_lambda_response(user_id=user_id, msg="Stream request processing failed", success=False)

    def _handle_queue_mode(self, event: dict[str, Any], context: Any | None = None) -> tuple[int, dict[str, Any]]:
        """
        Handle chat request in queue mode - send message to SQS input queue.

        Used for both delta and complete replies when queues are configured.
        Response will arrive via output queue -> ResponseHandler -> WebSocket.

        :param event: WebSocket event
        :param context: Lambda context object
        :return: Tuple of status code and response body
        """
        user_id = None
        try:
            ws_message_info = self._parse_event_to_wsmessage(event)
            user_id = ws_message_info.user_id
            request = ws_message_info.request
            request_body = request.body
            if request_body is None:
                raise ValueError("body is required")
            if not request.request_id:
                raise ValueError("request_id is required")

            session_id = request_body.session_id
            if not session_id:
                raise ValueError("session_id is required")

            self._log.info(f"Sending WebSocket request to queue: request_id={request.request_id}, session_id={session_id}")

            endpoint_url = LambdaWSHandler.construct_endpoint_url(event)

            response = SQSHandler.send_message_to_input_queue(
                message_body=request_body.model_dump(exclude_none=True),
                attributes={"message_deduplication_id": request.request_id},
                request_id=request.request_id,
                user_id=user_id,
                custom_message_attributes=[
                    SQSHandler.CustomAttribute(name="endpoint_url", value=endpoint_url, datatype=SQSHandler.AttributeDataType.STRING)
                ],
            )

            self._log.info(f"Request sent to input queue successfully: {response}")

            response_body = self._build_lambda_response(user_id=user_id, msg="Request queued successfully", success=True)
            response_body["request_id"] = request.request_id

            return 200, response_body
        except Exception as e:
            self._log.error(f"Queue request failed: {e}\n{traceback.format_exc()}")
            return (
                500,
                self._build_lambda_response(user_id=user_id, msg="Request processing failed", success=False),
            )


class WSLambdaRouter(BaseLambdaRouter):
    """
    Router for AWS Lambda events coming from API Gateway WebSocket APIs.
    - Register handlers per route for WebSocket endpoints.
    - Route can be provided in multiple forms and will be normalized.
    - If no handler match is found, the router raises ValueError.
    """

    def __init__(self, connection_routes: bool = False, system_routes: bool = True):
        """Initialize WebSocket Lambda router.

        :param connection_routes: Include $connect and $disconnect routes, which authenticate through the configured identity provider
        :param system_routes: Include $default and /chat routes
        :raises AKConfigError: If connection_routes is True and no identity provider is configured
        """
        super().__init__()
        self._log.info("Initializing WebSocket routes")

        self._base_route_handler = LambdaWSHandler()

        self._websocket_routes: dict[str, Callable[[dict[str, Any], Any], Any]] = {}

        if connection_routes:
            self._log.info("Initializing connection routes handler")
            self._websocket_routes.update(ConnectionRoutesHandler().get_routes())

        if system_routes:
            self._log.info("Initializing system routes handler")
            self._websocket_routes.update(SystemRoutesHandler().get_routes())

        self._log.info(f"Registered WebSocket Routes: {self._websocket_routes}")

    def _get_ws_handler_function(self, handler_logic_func: Callable[[dict[str, Any], Any], Any]):
        """Wrap handler function with WebSocket broadcasting.

        :param handler_logic_func: Handler function to wrap
        :return: Wrapped handler function
        """

        def _handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
            try:
                # The frame is the route's own payload, not a chat request: the route reads ``event["body"]``
                # itself, so only the connection's principal is resolved here (parsing the frame as a chat
                # body refused the documented ``{"route": ..., "data": ...}`` shape with a 500).
                principal = self._base_route_handler._connection_principal(event)
                user_id = principal.subject
                # WebSocket events carry no authorizer context: put the connection's principal where
                # ``Lambda.principal(event)`` reads it, as the REST authorizer does for an HTTP route.
                request_context = dict(event.get("requestContext") or {})
                request_context["authorizer"] = {
                    **(request_context.get("authorizer") or {}),
                    "principal": principal.model_dump_json(),
                }
                event = {**event, "requestContext": request_context}
                res_msg_to_brdcst = handler_logic_func(event, context)
                endpoint_url = LambdaWSHandler.construct_endpoint_url(event)
                self._base_route_handler.broadcast(endpoint_url=endpoint_url, message=res_msg_to_brdcst, user_id=user_id)
                return 200, self._base_route_handler._build_lambda_response(user_id=user_id, msg="Message broadcast successfully", success=True)
            except Exception as e:
                self._log.error(f"WebSocket handler failed: {e}\n{traceback.format_exc()}")
                return 500, self._base_route_handler._build_lambda_response(msg="WebSocket handler encountered an error", success=False)

        return _handler

    def register(self, route: str, method: str | None = None) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a WebSocket handler for a given route.

        WebSocket routes do not use HTTP methods, only the route.

        :param route: Route key for the WebSocket route
        :param method: Not used for WebSocket routes (kept for interface compatibility)
        :return: Decorator function that registers the handler and returns it unchanged
        :raises ValueError: If HTTP method is provided
        """
        if method is not None:
            raise ValueError("HTTP method is not allowed in WebSocket mode")

        norm_route = self.normalize_ws_route(route)

        def _decorator(wrapped_func: Callable[[dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering WebSocket route {norm_route} -> {wrapped_func.__name__}")

            wrapped_func = self._get_ws_handler_function(handler_logic_func=wrapped_func)

            if norm_route in self._websocket_routes:
                self._log.warning(f"WebSocket route {norm_route} already exists. Skipping.")
                return wrapped_func

            self._websocket_routes[norm_route] = wrapped_func
            return wrapped_func

        return _decorator

    def _broadcast_error(self, event: dict[str, Any], error_message: str) -> None:
        """
        Broadcast an error message to the WebSocket client.

        :param event: WebSocket event dictionary
        :param error_message: Error message to broadcast
        :return: None
        """
        try:
            request_context = event.get("requestContext", {})
            connection_id = request_context.get("connectionId")

            if not connection_id:
                self._log.warning("Cannot broadcast error: missing connectionId")
                return

            user_id = self._base_route_handler.get_user_id(connection_id)
            if not user_id:
                self._log.warning(f"Cannot broadcast error: no user_id found for connection_id: {connection_id}")
                return

            endpoint_url = LambdaWSHandler.construct_endpoint_url(event)
            self._base_route_handler.broadcast(
                endpoint_url=endpoint_url,
                message={"status": "FAILED", "message": error_message},
                user_id=user_id,
                message_type=LambdaWSHandler.MessageType.SYSTEM_RESPONSE,
            )
            self._log.info(f"Error broadcasted to user {user_id}: {error_message}")
        except Exception as e:
            self._log.error(f"Failed to broadcast error: {e}\n{traceback.format_exc()}")

    def dispatch(self, event: dict[str, Any], context: Any) -> dict[str, Any] | None:
        """
        Dispatch incoming API Gateway WebSocket event to the appropriate registered handler.

        :param event: API Gateway WebSocket event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        try:
            self._log.info("Dispatching WebSocket endpoint")
            request_context = event.get("requestContext", {})
            route_key = request_context.get("routeKey")
            connection_id = request_context.get("connectionId")

            if not route_key:
                self._log.warning("WebSocket event missing routeKey")
                raise ValueError("WebSocket event missing routeKey")

            norm_route_key = self.normalize_ws_route(route_key)
            self._log.info(f"Normalized route key: '{route_key}', Connection ID: '{connection_id}'")
            handler = self._websocket_routes.get(norm_route_key)

            if not handler:
                self._log.warning(f"No registered WebSocket route found for route key -> '{route_key}'")
                raise ValueError(f"No registered WebSocket route found for route key -> '{route_key}'")

            result = handler(event, context)
            self._log.debug(f"WebSocket handler result: {result}")
            return result
        except Exception as e:
            self._log.error(f"Error during dispatch: {e}\n{traceback.format_exc()}")
            self._broadcast_error(event, str(e))
            raise
