import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ......core.config import AKConfig
from ..paths import LambdaPaths


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

    def _get_base_paths_from_env(self) -> tuple[str | None, str | None]:
        """
        Get the base path from environment variables.

        :param: None
        :return: Tuple of (base_path, agent_endpoint_path) or (None, None) if not found
        """
        paths = LambdaPaths.from_env()
        if paths is None:
            return None, None
        return paths.base_path, paths.chat_path

    @abstractmethod
    def register(self, route: str, method: str | None = None) -> Callable[[Callable], Callable]:
        """
        Register a handler for a given route.

        :param route: Route path or key for the handler
        :param method: HTTP method (optional, only for WebSocket mode)
        :return: Decorator function that registers the handler and returns it unchanged
        """
        pass

    @abstractmethod
    def dispatch(self, event: dict[str, Any], context: Any) -> dict[str, Any] | None:
        """
        Dispatch incoming event to the appropriate registered handler.

        :param event: Event dictionary containing request information
        :param context: AWS Lambda context object
        :return: Formatted response dictionary or None if no route matches
        :raises ValueError: If no registered route matches the request
        """
        pass
