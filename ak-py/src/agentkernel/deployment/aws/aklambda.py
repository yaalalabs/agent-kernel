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

    def __init__(self, api_base_path="api", api_version="v1", agent_endpoint="chat") -> None:
        self._log = logging.getLogger("ak.aws.lambda.router")
        self._api_base_path = api_base_path
        self._api_version = api_version
        self._agent_endpoint = agent_endpoint
        self._routes: Dict[str, Dict[str, Callable[[Dict[str, Any], Any], Any]]] = {
            f"{self._get_base_path()}/{self._agent_endpoint}": {"POST": self._handle_agent_chat}
        }

    def _get_base_path(self) -> str:
        return f"/{self._api_base_path}/{self._api_version}"

    def _get_agent_endpoint_path(self) -> str:
        return f"{self._get_base_path()}/{self._agent_endpoint}"

    def override_base_paths(
        self,
        api_base_path: str = "api",
        api_version: str = "v1",
        agent_endpoint: str = "chat",
    ) -> None:
        self._log.info(f"Agent Endpoint: '{agent_endpoint}'")

        old_base_path = self._get_base_path()
        old_agent_endpoint = self._get_agent_endpoint_path()

        self._api_base_path = api_base_path
        self._api_version = api_version
        self._agent_endpoint = agent_endpoint

        new_base_path = self._get_base_path()
        new_agent_endpoint = self._get_agent_endpoint_path()

        self._log.info(f"Old base path: '{old_base_path}', New base path: '{new_base_path}'")

        new_routes = {}

        for old_path, methods in self._routes.items():
            if old_path == old_agent_endpoint:
                new_path = new_agent_endpoint
            elif old_path.startswith(old_base_path):
                new_path = old_path.replace(old_base_path, new_base_path, 1)
            else:
                self._log.warning(f"Path '{old_path}' does not start with '{old_base_path}'. Skipping.")
                new_path = old_path

            self._log.info(f"'{old_path}' -> '{new_path}'")
            new_routes[new_path] = methods

        self._routes = new_routes

        self._log.info(f"Base paths updated from '{old_base_path}' to '{new_base_path}': {self._routes}")

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
        """Decorator to register a handler for a given path and method."""
        norm_path = self._normalize_path(path)
        if not norm_path.startswith(self._get_base_path()):
            norm_path = self._get_base_path() + norm_path
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

    def dispatch(self, event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
        method = self._normalize_method(event.get("httpMethod"))
        event_path = event.get("resource") or "/"
        self._log.info(f"Event path: {event_path}, Method: {method}")
        methods = self._routes.get(event_path)
        if not methods:
            self._log.warning(f"No registered route found for API Gateway path -> '{event_path}'")
            raise ValueError(f"No registered route found for API Gateway path -> '{event_path}'")
        handler = methods.get(method)
        if not handler:
            self._log.warning(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
            raise ValueError(f"No registered route found for API Gateway path -> '{event_path}' and method '{method}'")
        result = handler(event, context)
        self._log.debug(f"Wrapping Lambda function result: {result}")
        return Lambda._wrap_response(result)

    def _handle_agent_chat(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Existing default behavior for agent chat invocation."""
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
                            str(result)
                            if isinstance(result, (AgentReplyText, AgentReplyImage))
                            else "Non textual result received"
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
        """Expose router registration to applications: @Lambda.register('/app', 'GET')"""
        return cls._router.register(path, method)

    @classmethod
    def override_base_paths(cls, api_base_path="api", api_version="v1", agent_endpoint="chat") -> None:
        """
        Override the base paths for the router.
        """
        cls._router.override_base_paths(api_base_path, api_version, agent_endpoint)

    @staticmethod
    def _wrap_response(result: Any) -> Dict[str, Any]:
        """
        Normalize various handler return types into API Gateway compatible responses.
        Supported:
        - dict -> 200 with JSON body
        - (statusCode, dict|str) -> exact status and body
        - str -> 200 with text body
        - already-formed {statusCode, body} -> passthrough
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
        """
        cls._log.info("Agent Kernel Agent Lambda Handler started")
        cls._log.info(f"Registered Routes: {cls._router._routes}")
        # Attempting to dispatch to custom routes
        try:
            dispatched = cls._router.dispatch(event, context)
            if dispatched is not None:
                return dispatched
        except Exception as e:
            # Exception in custom route handler/Lmabda function raise 500
            cls._log.exception(f"Custom route handler failed: {e}")
            return {"statusCode": 500, "body": json.dumps({"error": f"Custom handler error: {e}"})}
