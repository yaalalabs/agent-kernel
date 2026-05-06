from .core import WSLambdaRouter
from ....auth.handler import AuthValidator
from .aklambda import Lambda
import logging
from typing import Optional

class WebsocketConnectionHandler(Lambda):
    _log = logging.getLogger("ak.aws.serverless.websocket_connection_handler")
    _auth_validator: Optional[AuthValidator] = None

    @classmethod
    def set_auth_validator(cls, auth_validator: AuthValidator) -> "type[WebsocketConnectionHandler]":
        cls._auth_validator = auth_validator
        return cls

    @classmethod
    def _get_router(cls) -> WSLambdaRouter:
        if cls._router is None:
            cls._router = WSLambdaRouter(
                connection_routes=True,
                system_routes=False,
                auth_validator=cls._auth_validator
            )
        return cls._router

    def register(self, route: str, method: Optional[str] = None) -> None:
        """
        Route registration is not supported for WebsocketConnectionHandler.
        This handler is designed for connection management events only.
        """
        raise NotImplementedError(
            "WebsocketConnectionHandler does not support route registration. "
            "Use Lambda.register() for custom routes instead."
        )