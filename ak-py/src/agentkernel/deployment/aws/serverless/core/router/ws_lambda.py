import json
import logging
import traceback
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from ......core.config import AKConfig
from ......core.model import BaseRequest
from .....common.chat_service import ChatService
from ....core.websocket_service import WebSocketHandler
from ....core.sqs_handler import SQSHandler
from .common import BaseLambdaRouter


class DefaultWSRoutesHandler:
    _log = logging.getLogger("ak.aws.serverless.default_ws_endpoints")

    class MessageType(Enum):
        """WebSocket message types."""
        CHAT_RESPONSE = "chat_response"
        CHAT_QUEUED = "chat_queued"

    def __init__(self):
        self._config = AKConfig.get()
        self._chat_service = ChatService()
        self.ws_handler = WebSocketHandler(
            endpoint_url=self._config.websocket_api.endpoint_url,
            conn_table_name=self._config.websocket_api.connection_table_name,
        )

    def _parse_body(self, event: Dict[str, Any]) -> BaseRequest:
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) and body else (body or {})
        return BaseRequest.from_payload(body_dict)

    def _extract_connection_id(self, event: Dict[str, Any]) -> str:
        request_context = event.get("requestContext", {})
        connection_id = request_context.get("connectionId")
        if not connection_id:
            raise ValueError("WebSocket event missing requestContext.connectionId")
        return connection_id

    def _is_queue_mode(self) -> bool:
        """Check if queue mode is enabled (queues are configured)."""
        return (
            self._config.execution.queues.input.url is not None
            and self._config.execution.queues.output.url is not None
        )

    def _build_broadcasting_message(self, message_type: MessageType, **kwargs) -> Dict[str, Any]:
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
    
    def _build_lambda_response(self, user_id: Optional[str]=None, msg:Optional[str]=None, success:bool=True) -> Dict[str, Any]:
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

    def _handle_msg_and_brdcst(self, event: Dict[str, Any], operation: Callable[[BaseRequest], Dict[str, Any]], message_type: Optional[MessageType]=None) -> Tuple[int, Dict[str, Any]]:
        user_id = None
        try:
            request = self._parse_body(event)
            user_id = request.user_id
            brdcstin_msg = operation(request)
            if message_type:
                brdcstin_msg = self._build_broadcasting_message(message_type, **brdcstin_msg)
            self.ws_handler.broadcast(
                message=brdcstin_msg,
                user_id=user_id,
            )
            return (200, self._build_lambda_response(user_id=user_id, msg="Request processed successfully", success=True))

        except Exception as e:
            self._log.error(f"Request failed: {e}\n{traceback.format_exc()}")
            return (500, self._build_lambda_response(user_id=user_id, msg="Request processing failed", success=False))  # (statusCode, body) will be handled in aklambda.py

    def get_routes(self) -> Dict[str, Callable[[Dict[str, Any], Any], Any]]:
        return {
            "/$connect": self._handle_connect,
            "/$disconnect": self._handle_disconnect,
            "/$default": self._handle_default,
            "/chat": self._handle_queue_mode_chat if self._is_queue_mode() else self._handle_direct_chat,
        }

    def _handle_connect(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = self._extract_connection_id(event)

            request = self._parse_body(event)
            user_id = request.user_id

            self.ws_handler.on_connect(connection_id=connection_id, user_id=user_id)

            return 200, self._build_lambda_response(user_id=user_id, msg="WebSocket connection established", success=True)
        except Exception as e:
            self._log.error(f"WebSocket $connect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to establish WebSocket connection", success=False)

    def _handle_disconnect(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            connection_id = self._extract_connection_id(event)

            self.ws_handler.on_disconnect(connection_id=connection_id)
            return 200, self._build_lambda_response(msg="WebSocket connection closed", success=True)
        except Exception as e:
            self._log.error(f"WebSocket $disconnect failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to close WebSocket connection", success=False)

    def _handle_default(self) -> Tuple[int, Dict[str, Any]]:
        try:
            self.ws_handler.on_default()
            return 200, self._build_lambda_response(msg="Default route handled successfully", success=True)
        except Exception as e:
            self._log.error(f"WebSocket $default failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to handle default route", success=False)

    def _handle_direct_chat(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            request = self._parse_body(event)
            if request.body is None:
                raise ValueError("body is required")

            _, res_body = self._chat_service.process_chat_request(
                request.body.model_dump(exclude_none=True)
            )

            self.ws_handler.broadcast(
                message=self._build_broadcasting_message(
                    message_type=self.MessageType.CHAT_RESPONSE,
                    **res_body,
                ),
                user_id=request.user_id,
            )

            return 200, self._build_lambda_response(user_id=request.user_id, msg="Chat response sent successfully", success=True)
        except Exception as e:
            self._log.error(f"WebSocket chat failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to process chat request", success=False)

    def _handle_queue_mode_chat(self, event: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """
        Handle chat request in queue mode - send message to SQS input queue.
        :param event: WebSocket event
        :return: Tuple of status code and response body
        """
        try:
            connection_id = self._extract_connection_id(event)
            request = self._parse_body(event)
            request_body = request.body
            if request_body is None:
                raise ValueError("body is required")
            if not request.request_id:
                raise ValueError("request_id is required")

            session_id = request_body.session_id
            if not session_id:
                raise ValueError("session_id is required")

            self._log.info(f"Sending WebSocket chat request to queue: request_id={request.request_id}, session_id={session_id}")

            response = SQSHandler.send_message_to_input_queue(
                message_body=request_body,
                message_group_id=session_id,
                message_deduplication_id=request.request_id,
                request_id=request.request_id,
                user_id=request.user_id,
            )

            self._log.info(f"Message sent to input queue successfully: {response}")

            self.ws_handler.broadcast(
                message=self._build_broadcasting_message(
                    message_type=self.MessageType.CHAT_QUEUED,
                    status="ACCEPTED",
                    request_id=request.request_id,
                ),
                connection_ids=[connection_id],
            )

            response = self._build_lambda_response(user_id=request.user_id, msg="Chat request queued for processing", success=True)
            response["request_id"] = request.request_id
            return 200, response
        except Exception as e:
            self._log.error(f"WebSocket queue mode chat failed: {e}\n{traceback.format_exc()}")
            return 500, self._build_lambda_response(msg="Failed to queue chat request", success=False)


class WSLambdaRouter(BaseLambdaRouter):
    """
    Router for AWS Lambda events coming from API Gateway WebSocket APIs.
    - Register handlers per route for WebSocket endpoints.
    - Route can be provided in multiple forms and will be normalized.
    - If no handler match is found, the router raises ValueError.
    """

    def __init__(self):
        super().__init__()
        self._log.info("Initializing default WebSocket routes")
        self._ws_routes_handler = DefaultWSRoutesHandler()
        self._websocket_routes: Dict[str, Callable[[Dict[str, Any], Any], Any]] = self._ws_routes_handler.get_routes()

    def _get_ws_handler_function(self, handler_logic_func: Callable[[Dict[str, Any], Any], Any]):
        def _handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
            try:
                user_id = self._ws_routes_handler._parse_body(event).user_id
                res_msg_to_brdcst = handler_logic_func(event, context)
                self._ws_routes_handler.ws_handler.broadcast(
                    message=res_msg_to_brdcst,
                    user_id=user_id,
                )
                return 200, self._ws_routes_handler._build_lambda_response(user_id=user_id, msg="Message broadcast successfully", success=True)
            except Exception as e:
                self._log.error(f"WebSocket handler failed: {e}\n{traceback.format_exc()}")
                return 500, self._ws_routes_handler._build_lambda_response(msg="WebSocket handler encountered an error", success=False)
        return _handler

    def register(self, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a WebSocket handler for a given route.
        WebSocket routes do not use HTTP methods, only the route.
        :param route: Route key for the WebSocket route
        :param method: Not used for WebSocket routes (kept for interface compatibility)
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        if method is not None:
            raise ValueError("HTTP method is not allowed in WebSocket mode")
        
        norm_route = self._normalize_path(route)

        def _decorator(wrapped_func: Callable[[Dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering WebSocket route {norm_route} -> {wrapped_func.__name__}")
            
            wrapped_func = self._get_ws_handler_function(handler_logic_func=wrapped_func)

            if norm_route in self._websocket_routes:
                self._log.warning(f"WebSocket route {norm_route} already exists. Skipping.")
                return wrapped_func
            
            self._websocket_routes[norm_route] = wrapped_func
            return wrapped_func

        return _decorator

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming API Gateway WebSocket event to the appropriate registered handler.
        :param event: API Gateway WebSocket event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        self._log.info("Dispatching WebSocket endpoint")
        request_context = event.get("requestContext", {})
        route_key = request_context.get("routeKey")
        connection_id = request_context.get("connectionId")
        
        self._log.info(f"WebSocket event - Route Key: {route_key}, Connection ID: {connection_id}")
        
        if not route_key:
            self._log.warning("WebSocket event missing routeKey")
            raise ValueError("WebSocket event missing routeKey")
        
        norm_route_key = self._normalize_path(route_key)
        handler = self._websocket_routes.get(norm_route_key)
        
        if not handler:
            self._log.warning(f"No registered WebSocket route found for route key -> '{route_key}'")
            raise ValueError(f"No registered WebSocket route found for route key -> '{route_key}'")
        
        result = handler(event, context)
        self._log.debug(f"WebSocket handler result: {result}")
        return result
