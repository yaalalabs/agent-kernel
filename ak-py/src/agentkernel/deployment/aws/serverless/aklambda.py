from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple
from ....core.config import AKConfig, ExecutionMode


class LambdaRouter:
    """
    A router for AWS Lambda events coming from API Gateway (REST API v1 and WebSocket APIs).
    - Register handlers per (method, path) for REST endpoints.
    - Register handlers per route key for WebSocket endpoints.
    - Path can be provided in multiple forms and will be normalized.
    - If no handler match is found, the router returns None and caller can fallback.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.aws.lambda.router")
        self._default_chat_path = "default_chat_path"
        self._default_chat_method = "POST"
        self._default_user_polling_method = None
        self._config = AKConfig().get()

        from .core import DefaultEndpointsHandler

        (
            self._default_chat_path,
            self._default_chat_method,
            self._default_user_polling_method,
        ) = DefaultEndpointsHandler.get_default_endpoint_info()
        self._routes: Dict[str, Dict[str, Callable[[Dict[str, Any], Any], Any]]] = DefaultEndpointsHandler.get_routes()
        self._websocket_routes: Dict[str, Callable[[Dict[str, Any], Any], Any]] = {}

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Add leading '/' if not present and remove trailing '/' if present"""
        if not path:
            return "/"
        if not path.startswith("/"):
            path = "/" + path

        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path

    @staticmethod
    def _normalize_method(method: Optional[str]) -> str:
        return (method or "GET").upper()
    
    def _is_websocket_mode(self) -> bool:
        return self._config.execution.mode == ExecutionMode.ASYNC

    def register(self, path: str, method: str = None) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a handler for a given HTTP path and method.
        :param path: URL path for the route
        :param method: HTTP method (defaults to "GET")
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        if self._is_websocket_mode():
            raise ValueError("REST routes cannot be registered in WebSocket mode, Current mode: " + self._config.execution.mode.value)

        norm_path = self._normalize_path(path)
        norm_method = self._normalize_method(method)

        def _decorator(func: Callable[[Dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering route {norm_method} {norm_path} -> {func.__name__}")

            methods = self._routes.setdefault(norm_path, {})
            if norm_method in methods:
                self._log.warning(f"Route {norm_method} {norm_path} already exists. Skipping.")
                return func
            methods[norm_method] = func
            return func

        return _decorator

    def register_websocket(self, route_key: str) -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a WebSocket handler for a given route key.
        WebSocket routes do not use HTTP methods, only the route key.
        :param route_key: Route key for the WebSocket route
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        if not self._is_websocket_mode():
            raise ValueError("WebSocket routes can only be registered in 'ASYNC' mode, Current mode: " + self._config.execution.mode.value)

        norm_route_key = self._normalize_path(route_key)

        def _decorator(func: Callable[[Dict[str, Any], Any], Any]) -> Callable:
            self._log.info(f"Registering WebSocket route {norm_route_key} -> {func.__name__}")

            if norm_route_key in self._websocket_routes:
                self._log.warning(f"WebSocket route {norm_route_key} already exists. Skipping.")
                return func
            self._websocket_routes[norm_route_key] = func
            return func

        return _decorator

    def _get_base_paths_from_env(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the base path from environment variables.
        :return: Tuple of (base_path, agent_endpoint_path) or (None, None) if not found
        """
        api_base_path = os.getenv("API_BASE_PATH")
        api_version = os.getenv("API_VERSION")
        agent_endpoint = os.getenv("AGENT_ENDPOINT")
        base_path = f"/{api_base_path}/{api_version}"
        if api_base_path and api_version and agent_endpoint:
            return base_path, f"{base_path}/{agent_endpoint}"
        return None, None

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming event to the appropriate registered handler.
        Detects whether the event is from API Gateway REST or WebSocket and routes accordingly.
        :param event: Event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        # WebSocket events have requestContext with routeKey, REST events have httpMethod
        if self._is_websocket_mode():
            self._log.info("Dispatching WebSocket endpoint")
            return self._dispatch_websocket_endpoint(event, context)
        self._log.info("Dispatching REST endpoint")
        return self._dispatch_rest_endpoint(event, context)

    def _dispatch_rest_endpoint(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming API Gateway REST event to the appropriate registered handler.
        :param event: API Gateway event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
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

    def _dispatch_websocket_endpoint(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming API Gateway WebSocket event to the appropriate registered handler.
        :param event: API Gateway WebSocket event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
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


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Supports both REST API and WebSocket API Gateway events.
    Includes a handler method for AWS Lambda function integration.
    """

    _log = logging.getLogger("ak.aws.lambda")
    _router: Optional[LambdaRouter] = None

    @classmethod
    def _get_router(cls) -> LambdaRouter:
        if cls._router is None:
            cls._router = LambdaRouter()
        return cls._router

    @classmethod
    def register(cls, path: str, method: str = "GET") -> Callable[[Callable], Callable]:
        """
        Class method decorator that delegates route registration to the internal LambdaRouter.
        :param path: URL path for the route (normalized with leading slash, no trailing slash)
        :param method: HTTP method (defaults to "GET", case-insensitive)
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        return cls._get_router().register(path, method)

    @classmethod
    def register_websocket(cls, route_key: str) -> Callable[[Callable], Callable]:
        """
        Class method decorator that delegates WebSocket route registration to the internal LambdaRouter.
        :param route_key: WebSocket route key that must be sent as "routeKey" in the request message payload to trigger this handler
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        return cls._get_router().register_websocket(route_key)

    @staticmethod
    def _wrap_response(result: Any) -> Dict[str, Any]:
        """
        Normalize various handler return types into API Gateway compatible responses.
        :param result: Handler return value (dict, tuple, str, or list)
        :return: API Gateway compatible response dictionary with statusCode and body
        """
        if isinstance(result, dict) and "statusCode" in result and "body" in result:
            return result  # already well-formed
        if isinstance(result, tuple) and len(result) == 2:
            status, body = result
            if isinstance(body, (dict, list)):
                return {"statusCode": int(status), "body": json.dumps(body)}
            return {"statusCode": int(status), "body": str(body)}
        if isinstance(result, (dict, list)):
            return {"statusCode": 200, "body": json.dumps(result)}
        return {"statusCode": 200, "body": str(result)}

    @classmethod
    def handler(cls, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        AWS Lambda handler function to process incoming requests.
        :param event: API Gateway event dictionary containing request information
        :param context: AWS Lambda context object
        :return: API Gateway response dictionary with status code and body
        """
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        # Attempting to dispatch to custom routes
        try:
            router = cls._get_router()
            cls._log.info(f"Registered REST Routes: {router._routes}")
            cls._log.info(f"Registered WebSocket Routes: {router._websocket_routes}")
            result = router.dispatch(event, context)
            return cls._wrap_response(result)
        except Exception as e:
            # Exception in custom route handler/Lambda function raise 500
            cls._log.exception(f"Custom route handler failed: {e}")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Custom handler error: {e}"}),
            }
