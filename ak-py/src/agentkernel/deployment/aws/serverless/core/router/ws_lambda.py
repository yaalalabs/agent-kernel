import json
import logging
import traceback
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from pydantic import BaseModel

from ......auth.handler import AuthValidator
from ......core.chat_service import ChatService
from ......core.config import AKConfig, ExecutionMode
from ......core.model import BaseRequest, StreamChunk
from ....core.sqs_handler import SQSHandler
from ....core.websocket_service import WebSocketHandler
from .common import BaseLambdaRouter


class BaseWSHandler:
    """Base class for WebSocket route handlers with shared functionality."""

    class MessageType(Enum):
        """WebSocket message types."""

        CHAT_RESPONSE = "CHAT_RESPONSE"
        CHAT_QUEUED = "CHAT_QUEUED"
        SYSTEM_RESPONSE = "SYSTEM_RESPONSE"
        STREAM_CHUNK = "STREAM_CHUNK"

    class WSMessageInfo(BaseModel):
        """WebSocket message information."""

        user_id: str
        request: BaseRequest

    def __init__(self):
        """Initialize base WebSocket handler."""
        self._config = AKConfig.get()
        if not self._config.websocket_api.connection_table or not self._config.websocket_api.connection_table.table_name:
            raise ValueError("websocket_api.connection_table.table_name is required for WebSocket handler")
        self.ws_handler = WebSocketHandler(
            conn_table_name=self._config.websocket_api.connection_table.table_name,
            ttl=self._config.websocket_api.connection_table.ttl,
        )
        self.CONNECT_ROUTE = "$connect"
        self.DISCONNECT_ROUTE = "$disconnect"
        self.DEFAULT_ROUTE = "$default"
        self.CHAT_ROUTE = self._config.websocket_api.chat_route

    def _parse_body(self, event: Dict[str, Any]) -> BaseRequest:
        """
        Parse request body from WebSocket event.

        :param event: WebSocket event dictionary
        :return: Parsed BaseRequest object
        """
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) and body else (body or {})
        return BaseRequest.from_payload(body_dict)

    def _extract_connection_id(self, event: Dict[str, Any]) -> str:
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

    def _parse_event_to_wsmessage(self, event: Dict[str, Any]) -> "BaseWSHandler.WSMessageInfo":
        """
        Parse WebSocket event to WSMessageInfo object.

        :param event: WebSocket event dictionary
        :return: WSMessageInfo object with user_id and request
        :raises ValueError: If connection_id is missing or user_id cannot be found
        """
        request = self._parse_body(event)
        connection_id = self._extract_connection_id(event)
        user_id = self.ws_handler.get_user_id(connection_id)
        if not user_id:
            raise ValueError(f"No user_id found for connection_id: {connection_id}")
        return self.WSMessageInfo(user_id=user_id, request=request)
    

    def broadcast_message(
        self,
        endpoint_url: str,
        user_id: str,
        message_type: Optional["BaseWSHandler.MessageType"] = None,
        message: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """
        Build and broadcast a message to a WebSocket user.

        :param endpoint_url: API Gateway WebSocket endpoint URL
        :param user_id: Target user identifier
        :param message_type: Optional envelope type; wraps payload when provided
        :param message: Optional message payload dict; mutually exclusive with kwargs
        :param kwargs: Message payload fields when not passing a dict via `message`
        """
        payload = message if message is not None else kwargs
        final_message = self._build_broadcasting_message(message_type, **payload) if message_type else payload
        self.ws_handler.broadcast(endpoint_url=endpoint_url, message=final_message, user_id=user_id)

    def _build_broadcasting_message(self, message_type: "BaseWSHandler.MessageType", **kwargs) -> Dict[str, Any]:
        """
        Build a standardized broadcast message format.

        :param message_type: The type of message from MessageType enum
        :param kwargs: Additional fields to include in the message
        :return: Standardized message dictionary
        """
        message = {
            "type": message_type.value,
        }
        message.update(kwargs)
        return message

    def _handle_msg_and_brdcst(
        self,
        event: Dict[str, Any],
        operation: Callable[[WSMessageInfo], Dict[str, Any]],
        message_type: Optional[MessageType] = None,
    ) -> Tuple[int, Dict[str, Any]]:
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
            endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)
            self.broadcast_message(endpoint_url, user_id, message_type=message_type, message=brdcstin_msg)
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
        user_id: Optional[str] = None,
        msg: Optional[str] = None,
        success: bool = True,
    ) -> Dict[str, Any]:
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


class ConnectionRoutesHandler(BaseWSHandler):
    """Handles WebSocket connection lifecycle routes ($connect, $disconnect).

    This handler is responsible for managing WebSocket connections and requires
    authentication tokens before allowing connections.

    Authentication is mandatory for WebSocket connections. The auth_validator
    must be provided and will validate JWT tokens. user_id is extracted from the
    JWT token's user_id claim after signature verification. The JWT token should
    include a user_id claim containing the user's identifier (email, username,
    or any other identifier).
    """

    _log = logging.getLogger("ak.aws.serverless.connection_routes")

    def __init__(self, auth_validator: AuthValidator):
        """Initialize connection routes handler.

        :param auth_validator: Required auth validator for $connect route
        """
        super().__init__()
        self.auth_validator = auth_validator

    def _extract_auth_token(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Extract authentication token from WebSocket event query string.

        :param event: WebSocket event dictionary
        :return: Token string if found, None otherwise
        """
        query_params = event.get("queryStringParameters", {})
        if isinstance(query_params, dict):
            return query_params.get("token")
        return None

    def get_routes(self) -> Dict[str, Callable[[Dict[str, Any], Any], Any]]:
        """
        Get registered connection route handlers.

        :param: None
        :return: Dictionary mapping route keys to handler functions
        """
        return {
            self.CONNECT_ROUTE: self._handle_connect,
            self.DISCONNECT_ROUTE: self._handle_disconnect,
        }

    def _handle_connect(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle WebSocket $connect route with mandatory authentication.

        user_id is extracted from the JWT token's user_id claim after validation.
        The JWT token structure should include a user_id claim containing email, username, or any identifier.

        :param event: WebSocket connect event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        try:
            connection_id = self._extract_connection_id(event)

            token = self._extract_auth_token(event)
            if not token:
                return 401, self._build_lambda_response(msg="Authentication token is required", success=False)

            validation_result = self.auth_validator.validate(token)
            if not validation_result.is_valid:
                return 401, self._build_lambda_response(msg=validation_result.error_msg or "Authentication failed", success=False)

            user_id = None
            if validation_result.claims:
                user_id = validation_result.claims.get("userId")
            if not user_id:
                return 401, self._build_lambda_response(msg="'userId' claim is required in JWT token", success=False)

            self.ws_handler.on_connect(connection_id=connection_id, user_id=user_id)

            return 200, self._build_lambda_response(user_id=user_id, msg="WebSocket connection established", success=True)

        except Exception as e:
            self._log.error(f"WebSocket $connect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to establish WebSocket connection", success=False)

    def _handle_disconnect(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle WebSocket $disconnect route.

        :param event: WebSocket disconnect event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        try:
            connection_id = self._extract_connection_id(event)

            self.ws_handler.on_disconnect(connection_id=connection_id)
            return 200, self._build_lambda_response(msg="WebSocket connection closed", success=True)
        except Exception as e:
            self._log.error(f"WebSocket $disconnect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to close WebSocket connection", success=False)


class SystemRoutesHandler(BaseWSHandler):
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

    def get_routes(self) -> Dict[str, Callable[[Dict[str, Any], Any], Any]]:
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
        if self._config.execution.mode == ExecutionMode.STREAM:
            return self._handle_queue_mode if self._is_queue_mode() else self._handle_stream_direct
        return self._handle_queue_mode if self._is_queue_mode() else self._handle_direct_chat

    def _handle_default(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle WebSocket $default route.

        :param event: WebSocket default route event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """

        def _process_default(ws_message_info: "BaseWSHandler.WSMessageInfo") -> Dict[str, Any]:
            self.ws_handler.on_default()
            requested_route = ws_message_info.request.route
            return {"status": "FAILED", "message": f"Route '{requested_route}' not found"}

        return self._handle_msg_and_brdcst(
            event,
            _process_default,
            self.MessageType.SYSTEM_RESPONSE,
        )

    def _handle_direct_chat(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle direct chat request without queue.

        :param event: WebSocket chat event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """

        def _process_chat(ws_message_info: "BaseWSHandler.WSMessageInfo") -> Dict[str, Any]:
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

    def _handle_stream_direct(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle direct streaming chat request without queue (non-queue STREAM mode).

        Streams agent response chunks directly via WebSocket.

        :param event: WebSocket chat event
        :param context: Lambda context object
        :return: Tuple of (status_code, response_body)
        """
        user_id = None
        try:
            ws_message_info = self._parse_event_to_wsmessage(event)
            user_id = ws_message_info.user_id
            request = ws_message_info.request
            if request.body is None:
                raise ValueError("body is required")

            endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)

            for raw_chunk in self._chat_service.process_stream_chat_sync(req=request.body):
                chunk_dict = json.loads(raw_chunk)
                self.broadcast_message(endpoint_url, user_id, message_type=self.MessageType.STREAM_CHUNK, message=chunk_dict)

            return 200, self._build_lambda_response(user_id=user_id, msg="Stream completed successfully", success=True)
        except Exception as e:
            self._log.error(f"Stream direct request failed: {e}\n{traceback.format_exc()}")
            try:
                endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)
                error_chunk = StreamChunk(error=str(e), done=True)
                self.broadcast_message(endpoint_url, user_id, message_type=self.MessageType.STREAM_CHUNK, message=error_chunk.model_dump(exclude_none=True))
            except Exception:
                pass
            return 500, self._build_lambda_response(user_id=user_id, msg="Stream request processing failed", success=False)

    def _handle_queue_mode(self, event: Dict[str, Any], context: Optional[Any] = None) -> Tuple[int, Dict[str, Any]]:
        """
        Handle chat request in queue mode - send message to SQS input queue.

        Used for both STREAM and non-STREAM execution modes when queues are configured.
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

            endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)

            response = SQSHandler.send_message_to_input_queue(
                message_body=request_body,
                message_group_id=session_id,
                message_deduplication_id=request.request_id,
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

    def __init__(self, connection_routes: bool = False, system_routes: bool = True, auth_validator: Optional[AuthValidator] = None):
        """Initialize WebSocket Lambda router.

        :param connection_routes: Include $connect and $disconnect routes (requires auth_validator)
        :param system_routes: Include $default and /chat routes
        :param auth_validator: Required auth validator for $connect route when connection_routes is True
        :raises ValueError: If connection_routes is True but auth_validator is not provided
        """
        super().__init__()
        self._log.info("Initializing WebSocket routes")

        self._base_route_handler = BaseWSHandler()

        self._websocket_routes: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {}

        if connection_routes:
            if not auth_validator:
                raise ValueError("auth_validator is required when connection_routes is True")
            self._log.info("Initializing connection routes handler")
            self._websocket_routes.update(ConnectionRoutesHandler(auth_validator=auth_validator).get_routes())

        if system_routes:
            self._log.info("Initializing system routes handler")
            self._websocket_routes.update(SystemRoutesHandler().get_routes())

        self._log.info(f"Registered WebSocket Routes: {self._websocket_routes}")

    def _get_ws_handler_function(self, handler_logic_func: Callable[[Dict[str, Any], Any], Any]):
        """Wrap handler function with WebSocket broadcasting.

        :param handler_logic_func: Handler function to wrap
        :return: Wrapped handler function
        """

        def _handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
            try:
                ws_message_info = self._base_route_handler._parse_event_to_wsmessage(event)
                user_id = ws_message_info.user_id
                res_msg_to_brdcst = handler_logic_func(event, context)
                endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)
                self._base_route_handler.broadcast_message(endpoint_url, user_id, message=res_msg_to_brdcst)
                return 200, self._base_route_handler._build_lambda_response(user_id=user_id, msg="Message broadcast successfully", success=True)
            except Exception as e:
                self._log.error(f"WebSocket handler failed: {e}\n{traceback.format_exc()}")
                return 500, self._base_route_handler._build_lambda_response(msg="WebSocket handler encountered an error", success=False)

        return _handler

    def register(self, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
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

        def _decorator(wrapped_func: Callable[[Dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering WebSocket route {norm_route} -> {wrapped_func.__name__}")

            wrapped_func = self._get_ws_handler_function(handler_logic_func=wrapped_func)

            if norm_route in self._websocket_routes:
                self._log.warning(f"WebSocket route {norm_route} already exists. Skipping.")
                return wrapped_func

            self._websocket_routes[norm_route] = wrapped_func
            return wrapped_func

        return _decorator

    def _broadcast_error(self, event: Dict[str, Any], error_message: str) -> None:
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

            user_id = self._base_route_handler.ws_handler.get_user_id(connection_id)
            if not user_id:
                self._log.warning(f"Cannot broadcast error: no user_id found for connection_id: {connection_id}")
                return

            endpoint_url = WebSocketHandler.construct_endpoint_url_from_event(event)
            self._base_route_handler.broadcast_message(
                endpoint_url, user_id,
                message_type=BaseWSHandler.MessageType.SYSTEM_RESPONSE,
                message={"status": "FAILED", "message": error_message},
            )
            self._log.info(f"Error broadcasted to user {user_id}: {error_message}")
        except Exception as e:
            self._log.error(f"Failed to broadcast error: {e}\n{traceback.format_exc()}")

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
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
