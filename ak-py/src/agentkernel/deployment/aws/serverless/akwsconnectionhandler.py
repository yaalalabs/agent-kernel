import logging
from typing import Optional

from ....auth.handler import AuthValidator
from .aklambda import Lambda
from .core import WSLambdaRouter


class WebsocketConnectionHandler(Lambda):
    _log = logging.getLogger("ak.aws.serverless.websocket_connection_handler")
    _auth_validator: Optional[AuthValidator] = None

    @classmethod
    def set_auth_validator(cls, auth_validator: AuthValidator) -> "type[WebsocketConnectionHandler]":
        """
        Set the authentication validator for WebSocket connection handling.

        :param auth_validator: AuthValidator instance for JWT token validation
        :return: The WebsocketConnectionHandler class for method chaining
        """
        cls._auth_validator = auth_validator
        return cls

    @classmethod
    def _get_router(cls) -> WSLambdaRouter:
        """
        Get or create the WebSocket Lambda router with connection routes enabled.

        :param: None
        :return: WSLambdaRouter instance configured for connection handling
        """
        if cls._router is None:
            cls._router = WSLambdaRouter(connection_routes=True, system_routes=False, auth_validator=cls._auth_validator)
        return cls._router

    def register(self, route: str, method: Optional[str] = None) -> None:
        """
        Route registration is not supported for WebsocketConnectionHandler.

        This handler is designed for connection management events only.

        :param route: Route path (not used)
        :param method: HTTP method (not used)
        :return: None
        :raises NotImplementedError: Route registration is not supported
        """
        raise NotImplementedError(
            "WebsocketConnectionHandler does not support route registration. " "Use Lambda.register() for custom routes instead."
        )
