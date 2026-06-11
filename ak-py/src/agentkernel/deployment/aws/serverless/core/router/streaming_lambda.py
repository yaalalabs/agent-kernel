import asyncio
import json
from typing import Any, Callable, Dict, Optional

from ......core.chat_service import ChatService
from ......core.model import BaseRequest, StreamChunk
from .common import BaseLambdaRouter


class StreamingLambdaRouter(BaseLambdaRouter):
    """
    Router for Lambda Function URL streaming (InvokeMode: RESPONSE_STREAM).
    Dispatches SSE streaming requests through a response_stream object.
    Custom routes can also be registered and will receive their result written
    as a single JSON response body chunk.
    """

    _SSE_ROUTE_KEY = "default_sse_stream_path"
    _SSE_METHOD = "POST"

    def __init__(self):
        """Initialize streaming Lambda router with default SSE endpoint."""
        super().__init__()
        self._chat_service = ChatService()
        self._routes: Dict[str, Dict[str, Callable[[Dict[str, Any], Any], Any]]] = {
            self._SSE_ROUTE_KEY: {self._SSE_METHOD: self._handle_sse_stream}
        }
        self._log.info("StreamingLambdaRouter initialized with default SSE endpoint")

    @staticmethod
    def _normalize_method(method: Optional[str]) -> str:
        """
        Normalize HTTP method to uppercase.

        :param method: HTTP method string
        :return: Uppercase method string, defaults to POST
        """
        return (method or "POST").upper()

    def register(self, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a custom streaming handler for a given HTTP route and method.
        Handlers must accept 3 params: (event, context, response_stream).

        :param route: URL route for the handler
        :param method: HTTP method (defaults to "POST")
        :return: Decorator function that registers the handler and returns it unchanged
        :raises ValueError: If HTTP method is not provided
        """
        if method is None:
            raise ValueError("HTTP method is required for streaming routes")

        norm_route = self._normalize_path(route)
        norm_method = self._normalize_method(method)

        def _decorator(func: Callable[[Dict[str, Any], Any, Any], Any]) -> Callable:
            self._log.info(f"Registering streaming route {norm_method} {norm_route} -> {func.__name__}")
            methods = self._routes.setdefault(norm_route, {})
            if norm_method in methods:
                self._log.warning(f"Route {norm_method} {norm_route} already exists. Skipping.")
                return func
            methods[norm_method] = func
            return func

        return _decorator

    def dispatch(self, event: Dict[str, Any], context: Any, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming Lambda Function URL event to the appropriate registered handler.
        Requires response_stream to write SSE frames or JSON body chunks.

        :param event: Lambda Function URL event dictionary
        :param context: AWS Lambda context object
        :param kwargs: Must include response_stream for streaming output
        :return: (400, error_dict) if response_stream is missing, otherwise None
        """
        response_stream = kwargs.get("response_stream")
        if response_stream is None:
            return (400, {"error": "Use streaming_handler + Lambda Function URL with InvokeMode: RESPONSE_STREAM"})

        method = self._normalize_method(event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method"))
        event_path = event.get("path") or event.get("rawPath") or "/"
        self._log.info(f"Streaming dispatch - path: {event_path}, method: {method}")

        converted_event_path = self._SSE_ROUTE_KEY
        env_base_path, env_agent_endpoint = self._get_base_paths_from_env()
        if env_base_path and env_agent_endpoint:
            converted_event_path = (
                self._SSE_ROUTE_KEY
                if event_path == env_agent_endpoint and method == self._SSE_METHOD
                else event_path.removeprefix(env_base_path)
            )
        else:
            normalized = self._normalize_path(event_path)
            if normalized in self._routes:
                converted_event_path = normalized
            else:
                self._log.warning("Environment variables not provided; routing to default SSE handler")

        self._log.info(f"Resolved route key: {converted_event_path}")
        methods = self._routes.get(converted_event_path, {})
        handler = methods.get(method)

        if not methods or not handler:
            self._log.warning(f"No registered route found for path '{event_path}' and method '{method}'")
            self._write_json_response(response_stream, 404, {"error": f"No registered route for path '{event_path}' and method '{method}'"})
            return None

        handler(event, context, response_stream)
        return None

    def _write_json_response(self, response_stream: Any, status_code: int, body: Any) -> None:
        """
        Write HTTP metadata and JSON body to the response stream.

        :param response_stream: awslambdaric response stream object
        :param status_code: HTTP status code
        :param body: Response body (dict, list, or str)
        """
        metadata = {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
        }
        response_stream.write(json.dumps(metadata).encode())
        if isinstance(body, (dict, list)):
            response_stream.write(json.dumps(body).encode())
        else:
            response_stream.write(str(body).encode())

    def _handle_sse_stream(self, event: Dict[str, Any], context: Any, response_stream: Any) -> None:
        """
        Handle SSE streaming request by driving the async generator synchronously.
        Writes HTTP metadata with SSE content type, then streams frames to response_stream.

        :param event: Lambda Function URL event
        :param context: AWS Lambda context object
        :param response_stream: awslambdaric response stream object with .write(bytes) method
        """
        metadata = {
            "statusCode": 200,
            "headers": {"Content-Type": "text/event-stream"},
        }
        response_stream.write(json.dumps(metadata).encode())

        body = event.get("body")
        body_dict = json.loads(body) if isinstance(body, str) else (body or {})
        base_request = BaseRequest.from_payload(body_dict)
        req = base_request.body
        session_id = req.session_id if req else None

        asyncio.run(self._stream_to_response(req, session_id, response_stream))

    async def _stream_to_response(self, req: Any, session_id: Optional[str], response_stream: Any) -> None:
        """
        Drive the async SSE generator and write each frame to response_stream.

        :param req: BaseRunRequest parsed from event body
        :param session_id: Session ID for error frames
        :param response_stream: awslambdaric response stream object
        """
        try:
            result = self._chat_service.process_stream_chat_request(req)
            if asyncio.iscoroutine(result):
                gen = await result
            else:
                gen = result
            async for frame in gen:
                response_stream.write(frame.encode() if isinstance(frame, str) else frame)
        except Exception as e:
            self._log.error(f"Streaming error: {e}")
            error_chunk = StreamChunk(error=str(e), done=True, session_id=session_id)
            error_frame = ChatService.format_sse_frame(error_chunk)
            response_stream.write(error_frame.encode())
