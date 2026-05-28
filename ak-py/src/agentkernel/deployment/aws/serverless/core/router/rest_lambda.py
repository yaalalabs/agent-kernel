import json
import logging
import traceback
from typing import Any, Callable, Dict, Optional

from ......core.chat_service import ChatService
from ......core.config import AKConfig
from ......core.model import BaseRequest, ExecutionMode
from ....core.response_store import ResponseDBHandler
from ....core.sqs_handler import SQSHandler
from .common import BaseLambdaRouter


class DefaultEndpointsHandler:
    """Provides default endpoint routes depending on EXECUTION_MODE."""

    def __init__(self):
        """Initialize default REST endpoints handler."""
        self._log = logging.getLogger("ak.aws.lambda.default_endpoints")
        self._default_chat_path = "default_chat_path"
        self._default_chat_method = "POST"
        self._config = AKConfig.get()
        self._response_store = ResponseDBHandler().get_store() if self._config.execution.mode != ExecutionMode.ASYNC else None
        self._chat_service = ChatService()

    def get_default_endpoint_info(self):
        """
        Return default endpoint configuration.
        :return: Tuple of (default_chat_path, default_chat_method, default_user_polling_method)
        """
        default_user_polling_method = "GET" if self._config.execution.mode == ExecutionMode.REST_ASYNC else None
        return (
            self._default_chat_path,
            self._default_chat_method,
            default_user_polling_method,
        )

    def get_routes(self) -> Dict[str, Dict[str, Callable]]:
        """
        Return route mappings based on execution mode.
        :return: Dictionary mapping paths → HTTP methods → handler functions
        """

        input_queue_url = SQSHandler.get_input_queue_url()
        exec_mode = self._config.execution.mode

        if not input_queue_url:
            self._log.info("Queues not configured. Therefore, using Request Handler lambda for chat processing")
            return {self._default_chat_path: {self._default_chat_method: self._handle_agent_chat}}

        if exec_mode == ExecutionMode.REST_SYNC:
            self._log.info("Initialized REST_SYNC endpoint.")
            return {self._default_chat_path: {self._default_chat_method: self._handle_rest_sync}}

        if exec_mode == ExecutionMode.REST_ASYNC:
            self._log.info("Initialized REST_ASYNC endpoints.")
            default_user_polling_method = "GET" if exec_mode == ExecutionMode.REST_ASYNC else None
            return {
                self._default_chat_path: {
                    self._default_chat_method: self._handle_async_submit,
                    default_user_polling_method: self._handle_async_poll,
                }
            }

        if exec_mode == ExecutionMode.STREAM:
            self._log.info("Initialized STREAM endpoint.")
            return {self._default_chat_path: {self._default_chat_method: self._handle_stream}}

        raise ValueError(f"Unsupported EXECUTION_MODE: {exec_mode}")

    def _parse_body(self, event: Dict[str, Any]) -> BaseRequest:
        """
        Parse request body from API Gateway event.

        :param event: API Gateway event
        :return: Parsed BaseRequest object
        """
        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) else (body or {})
        return BaseRequest.from_payload(body_dict)

    def _build_failure_body(self, request_id: Optional[str] = None, status: Optional[str] = None, message: Optional[str] = None) -> Dict[str, Any]:
        """
        Build standardized error response body.

        :param request_id: Optional request ID to include
        :param status: Optional status code to include
        :param message: Error message
        :return: Error response dictionary
        """
        error_body = {"error": message or "An unexpected error occurred"}
        if status is not None:
            error_body["status"] = status
        if request_id is not None:
            error_body["request_id"] = request_id
        return error_body

    def _handle_request(self, event: Dict[str, Any], operation: Callable[[BaseRequest], Dict[str, Any]]) -> tuple[int, Dict[str, Any]]:
        """
        Execute operation with standard request parsing and error handling.

        :param event: API Gateway event
        :param operation: Function executed with parsed payload
        :return: API Gateway formatted response (statusCode, body)
        """
        request_id = None
        try:
            request = self._parse_body(event)
            request_id = request.request_id
            result = operation(request)
            return (200, result)  # (statusCode, body) will be handled in aklambda.py

        # Log and hide unexpected failures behind a generic 500 response.
        except Exception as e:
            self._log.error(f"Request failed: {e}\n{traceback.format_exc()}")
            return (500, self._build_failure_body(request_id))  # (statusCode, body) will be handled in aklambda.py

    def _send_to_queue(self, payload: BaseRequest) -> Dict[str, Any]:
        """
        Send request payload to SQS queue.

        :param payload: Request payload containing a request_id and nested run body
        :return: Queue submission status
        :raises ValueError: If body, request_id, or session_id is missing
        """
        request_body = payload.body
        if request_body is None:
            raise ValueError("body is required")
        if not payload.request_id:
            raise ValueError("request_id is required")

        session_id = request_body.session_id
        if not session_id:
            raise ValueError("session_id is required")

        response = SQSHandler.send_message_to_input_queue(
            message_body=request_body,
            message_group_id=session_id,
            message_deduplication_id=payload.request_id,
            request_id=payload.request_id,
            user_id=payload.user_id,
        )
        return response

    def _get_message(self, payload: BaseRequest) -> Dict[str, Any]:
        """
        Fetch messages from response database.

        :param payload: Request payload containing request_id
        :return: Message for request
        :raises ValueError: If request_id is missing
        """
        request_id = payload.request_id
        if not request_id:
            raise ValueError("request_id is required")
        return self._response_store.get_message_with_retry(request_id=request_id, get_and_delete=True)

    def _handle_rest_sync(self, event: Dict[str, Any], context: Any) -> tuple[int, Dict[str, Any]]:
        """
        Send request to queue and immediately fetch response.

        :param event: API Gateway event
        :param context: Lambda context
        :return: Tuple of (status_code, response_body)
        """

        def sync_operation(payload: BaseRequest) -> Dict[str, Any]:
            request_id = payload.request_id
            self._log.info(f"Performing REST_SYNC operation for payload: '{payload}'")
            queue_result = self._send_to_queue(payload)
            self._log.info(f"Message sent to input queue, response from send_message function: '{queue_result}'")

            message = self._get_message(payload)
            self._log.info(f"Fetched message from database: {message}")
            message = (
                message
                if message
                else self._build_failure_body(
                    request_id=request_id,
                    status="NOT_FOUND",
                    message=f"No response message found for request_id: '{request_id}'. Try increasing the retry_count or delay in the response store configuration.",
                )
            )
            self._log.info(f"Returning response for REST_SYNC operation: '{message}'")

            return message

        return self._handle_request(event, sync_operation)

    def _handle_async_submit(self, event: Dict[str, Any], context: Any) -> tuple[int, Dict[str, Any]]:
        """
        Submit message to queue (async mode).

        :param event: API Gateway event
        :param context: Lambda context
        :return: Tuple of (status_code, response_body)
        """

        def submit_operation(payload: BaseRequest) -> Dict[str, Any]:
            self._log.info(f"Performing REST_ASYNC submit operation for payload: '{payload}'")
            queue_result = self._send_to_queue(payload)

            self._log.info(f"Message sent to input queue, response from send_message function: '{queue_result}'")
            response_body = {"status": "ACCEPTED", "request_id": payload.request_id}

            self._log.info(f"Returning response for REST_ASYNC submit operation: '{response_body}'")
            return response_body

        return self._handle_request(event, submit_operation)

    def _handle_async_poll(self, event: Dict[str, Any], context: Any) -> tuple[int, Dict[str, Any]]:
        """
        Poll database for messages (async mode).

        :param event: API Gateway event
        :param context: Lambda context
        :return: Tuple of (status_code, response_body)
        """

        def poll_operation(payload: BaseRequest) -> Dict[str, Any]:
            self._log.info(f"Performing REST_ASYNC poll operation for payload: '{payload}'")

            request_id = payload.request_id
            message = self._get_message(payload)
            self._log.info(f"Fetched message from database: {message}")
            response_body = (
                message
                if message
                else self._build_failure_body(
                    request_id=request_id,
                    status="NOT_FOUND",
                    message=f"No response message found for request_id '{request_id}'. The message may be unavailable. Please try again.",
                )
            )

            self._log.info(f"Returning response for REST_ASYNC poll operation: '{response_body}'")
            return response_body

        return self._handle_request(event, poll_operation)

    def _handle_agent_chat(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Process chat request directly without queue.

        :param event: API Gateway event
        :param context: Lambda context
        :return: API Gateway formatted response with statusCode and body
        """

        try:
            request = self._parse_body(event)
            if request.body is None:
                raise ValueError("body is required")
            status_code, res_body = self._chat_service.process_chat_request(request.body)

            return {
                "statusCode": status_code,
                "body": json.dumps(res_body),
            }

        except Exception as e:
            self._log.error(f"Chat error: {e}\n{traceback.format_exc()}")

            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Error processing request", "session_id": None}),
            }

    def _handle_stream(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle streaming request.

        :param event: API Gateway event
        :param context: Lambda context
        :return: API Gateway formatted response
        :raises NotImplementedError: STREAM mode is not yet implemented
        """
        raise NotImplementedError("STREAM mode is not yet implemented")


class RESTLambdaRouter(BaseLambdaRouter):
    """
    Router for AWS Lambda events coming from API Gateway REST API v1.
    - Register handlers per (method, route) for REST endpoints.
    - Route can be provided in multiple forms and will be normalized.
    - If no handler match is found, the router raises ValueError.
    """

    def __init__(self):
        """Initialize REST Lambda router."""
        super().__init__()
        self._default_chat_path = None
        self._default_chat_method = None
        self._default_user_polling_method = None
        self._routes: Dict[str, Dict[str, Callable[[Dict[str, Any], Any], Any]]] = {}

        self._endpoints_handler = DefaultEndpointsHandler()
        (
            self._default_chat_path,
            self._default_chat_method,
            self._default_user_polling_method,
        ) = self._endpoints_handler.get_default_endpoint_info()
        self._routes = self._endpoints_handler.get_routes()
        self._log.info(f"Registered REST Routes: {self._routes}")

    @staticmethod
    def _normalize_method(method: Optional[str]) -> str:
        """
        Normalize HTTP method to uppercase.

        :param method: HTTP method string
        :return: Uppercase method string, defaults to GET
        """
        return (method or "GET").upper()

    def register(self, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a handler for a given HTTP route and method.

        :param route: URL route for the handler
        :param method: HTTP method (defaults to "GET")
        :return: Decorator function that registers the handler and returns it unchanged
        :raises ValueError: If HTTP method is not provided
        """
        if method is None:
            raise ValueError("HTTP method is required for REST routes")

        norm_route = self._normalize_path(route)
        norm_method = self._normalize_method(method)

        def _decorator(func: Callable[[Dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering route {norm_method} {norm_route} -> {func.__name__}")

            methods = self._routes.setdefault(norm_route, {})
            if norm_method in methods:
                self._log.warning(f"Route {norm_method} {norm_route} already exists. Skipping.")
                return func
            methods[norm_method] = func
            return func

        return _decorator

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming API Gateway REST event to the appropriate registered handler.

        :param event: API Gateway event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        self._log.info("Dispatching REST endpoint")
        method = self._normalize_method(event.get("httpMethod"))
        event_path = event.get("path") or event.get("resource") or "/"
        self._log.info(f"Event path: {event_path}, Method: {method}")

        converted_event_path = self._default_chat_path
        env_base_path, env_agent_endpoint = self._get_base_paths_from_env()
        if env_base_path and env_agent_endpoint:
            converted_event_path = (
                self._default_chat_path
                if event_path == env_agent_endpoint and method in [self._default_chat_method, self._default_user_polling_method]
                else event_path.removeprefix(env_base_path)
            )
        else:
            self._log.warning("Environment variables not provided; using default agent handler")
            method = self._default_user_polling_method if method == self._default_user_polling_method else self._default_chat_method

        self._log.info(f"Converted event path: {converted_event_path}")
        methods = self._routes.get(converted_event_path, {})
        handler = methods.get(method)
        if not methods or not handler:
            self._log.warning(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
            raise ValueError(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
        result = handler(event, context)
        self._log.debug(f"Lambda function result: {result}")
        return result
