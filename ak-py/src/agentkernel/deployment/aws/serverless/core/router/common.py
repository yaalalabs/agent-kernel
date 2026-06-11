import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Tuple

from ......core.config import AKConfig


class BaseLambdaRouter(ABC):
    """
    Base class for AWS Lambda event routers.
    Contains common functionality shared between REST and WebSocket routers.
    """

    def __init__(self):
        """Initialize base Lambda router."""
        self._log = logging.getLogger("ak.aws.lambda.router")
        self._config = AKConfig.get()

    @staticmethod
    def _normalize_path(path: str) -> str:
        """
        Add leading '/' if not present and remove trailing '/' if present.

        :param path: Path string to normalize
        :return: Normalized path string
        """
        if not path:
            return "/"
        if not path.startswith("/"):
            path = "/" + path

        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path

    @staticmethod
    def normalize_ws_route(route: str) -> str:
        """
        Remove leading and trailing '/' from WebSocket route.

        :param route: WebSocket route string
        :return: Route string without leading or trailing '/'
        """
        return route.strip("/")

    def _get_base_paths_from_env(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get the base path from environment variables.

        :param: None
        :return: Tuple of (base_path, agent_endpoint_path) or (None, None) if not found
        """
        api_base_path = os.getenv("API_BASE_PATH")
        api_version = os.getenv("API_VERSION")
        agent_endpoint = os.getenv("AGENT_ENDPOINT")
        base_path = f"/{api_base_path}/{api_version}"
        if api_base_path and api_version and agent_endpoint:
            return base_path, f"{base_path}/{agent_endpoint}"
        return None, None

    @abstractmethod
    def register(self, route: str, method: Optional[str] = None) -> Callable[[Callable], Callable]:
        """
        Register a handler for a given route.

        :param route: Route path or key for the handler
        :param method: HTTP method (optional, only for WebSocket mode)
        :return: Decorator function that registers the handler and returns it unchanged
        """
        pass

    @abstractmethod
    def dispatch(self, event: Dict[str, Any], context: Any, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Dispatch incoming event to the appropriate registered handler.

        :param event: Event dictionary containing request information
        :param context: AWS Lambda context object
        :param kwargs: Additional keyword arguments (e.g. response_stream for streaming routers)
        :return: Formatted response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        pass
