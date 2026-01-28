from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Any, Callable, Dict, Optional, Tuple

from agentkernel.core.model import AgentReplyImage, AgentReplyText, AgentRequestAny, AgentRequestText

from ...core import AgentService

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)


class LambdaRouter:
    """
    A router for AWS Lambda events coming from API Gateway (REST API v1).

    - Register handlers per (method, path).
    - Path can be provided in multiple forms and will be normalized.
    - If no handler match is found, the router returns None and caller can fallback.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.aws.lambda.router")
        self._default_agent_registered_path = "default_agent_registered_path"
        self._default_agent_registered_method = "POST"
        self._routes: Dict[str, Dict[str, Callable[[Dict[str, Any], Any], Any]]] = {
            self._default_agent_registered_path: {self._default_agent_registered_method: self._handle_agent_chat}
        }

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

    def register(self, path: str, method: str = "GET") -> Callable[[Callable], Callable]:
        """
        Factory function that creates a decorator to register a handler for a given HTTP path and method.
        :param path: URL path for the route
        :param method: HTTP method (defaults to "GET")
        :return: Decorator function that registers the handler and returns it unchanged.
        """
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

    def _get_base_paths_from_stage_vars(self, event: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the base path from stage variables.
        :param event: API Gateway event dictionary containing stage variables
        :return: Tuple of (base_path, agent_endpoint) or (None, None) if not found
        """
        stage_vars = event.get("stageVariables", {})
        api_base_path = stage_vars.get("api_base_path")
        api_version = stage_vars.get("api_version")
        agent_endpoint = stage_vars.get("agent_endpoint")
        base_path = f"/{api_base_path}/{api_version}"
        if api_base_path and api_version and agent_endpoint:
            return base_path, f"{base_path}/{agent_endpoint}"
        return None, None

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming API Gateway event to the appropriate registered handler.
        :param event: API Gateway event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted API Gateway response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        method = self._normalize_method(event.get("httpMethod"))
        event_path = event.get("path") or event.get("resource") or "/"
        self._log.info(f"Event path: {event_path}, Method: {method}")

        stage_var_base_path, stage_var_agent_endpoint = self._get_base_paths_from_stage_vars(event)
        converted_event_path = event_path
        if stage_var_base_path and stage_var_agent_endpoint:
            if stage_var_agent_endpoint == event_path and method == self._default_agent_registered_method:
                converted_event_path = self._default_agent_registered_path
            else:
                converted_event_path = event_path.replace(stage_var_base_path, "")

        self._log.info(f"Converted event path: {converted_event_path}")
        methods = self._routes.get(converted_event_path, {})
        handler = methods.get(method)
        if not methods or not handler:
            self._log.warning(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
            raise ValueError(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
        result = handler(event, context)
        self._log.debug(f"Wrapping Lambda function result: {result}")
        return Lambda._wrap_response(result)

    def _handle_agent_chat(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Handle agent chat invocation with default behavior.
        :param event: API Gateway event dictionary containing request body
        :param context: AWS Lambda context object
        :return: API Gateway response dictionary with status code and body
        """
        service = AgentService()
        try:
            body = json.loads(event.get("body", "{}"))
            prompt = body.get("prompt", None)
            agent = body.get("agent", None)
            session_id = body.get("session_id", None)

            if session_id is None:
                raise ValueError("No session_id is provided in the request")

            requests = []
            if prompt:
                requests.append(AgentRequestText(text=prompt))
            else:
                raise ValueError("No prompt provided in the request")

            for key, value in body.items():
                if key in ["prompt", "agent", "session_id"]:
                    continue
                self._log.info(f"Adding additional context: {key}={value}")
                requests.append(AgentRequestAny(name=key, content=value))

            service.select(session_id, agent)
            if not service.agent:
                raise ValueError("No agent available")
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    result = asyncio.run(service.run_multi(requests=requests))
                else:
                    result = loop.run_until_complete(service.run_multi(requests=requests))
            except RuntimeError:
                result = asyncio.run(service.run_multi(requests=requests))
            self._log.debug(f"Result: {result}")

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "result": (
                            str(result) if isinstance(result, (AgentReplyText, AgentReplyImage)) else "Non textual result received"
                        ),  # sending image is not supported at the moment
                        "session_id": service.get_response_session_id(session_id),
                    }
                ),
            }

        except ValueError as ve:
            self._log.error(f"ValueError processing request: {ve}\n{traceback.format_exc()}")
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": str(ve),
                        "session_id": service.get_response_session_id(None),
                    }
                ),
            }
        except Exception as e:
            self._log.error(f"Error processing request: {e}\n{traceback.format_exc()}")
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "error": str(e),
                        "session_id": service.get_response_session_id(None),
                    }
                ),
            }


class Lambda:
    """
    Lambda class provides an AWS Lambda interface for interacting with agents.
    Includes a handler method for AWS Lambda function integration.
    """

    _log = logging.getLogger("ak.aws.lambda")
    _router = LambdaRouter()

    @classmethod
    def register(cls, path: str, method: str = "GET") -> Callable[[Callable], Callable]:
        """
        Class method decorator that delegates route registration to the internal LambdaRouter.
        :param path: URL path for the route (normalized with leading slash, no trailing slash)
        :param method: HTTP method (defaults to "GET", case-insensitive)
        :return: Decorator function that registers the handler and returns it unchanged.
        """
        return cls._router.register(path, method)

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
        cls._log.info(f"Registered Routes: {cls._router._routes}")
        # Attempting to dispatch to custom routes
        try:
            dispatched = cls._router.dispatch(event, context)
            if dispatched is not None:
                return dispatched
        except Exception as e:
            # Exception in custom route handler/Lambda function raise 500
            cls._log.exception(f"Custom route handler failed: {e}")
            return {"statusCode": 500, "body": json.dumps({"error": f"Custom handler error: {e}"})}
