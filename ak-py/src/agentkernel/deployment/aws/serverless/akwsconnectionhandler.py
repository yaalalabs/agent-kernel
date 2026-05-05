from .core import WSLambdaRouter
from ....auth.handler import AuthValidator
from .aklambda import Lambda
import logging
from typing import Optional

class WebsocketConnectionHandler(Lambda):
    _log = logging.getLogger("ak.aws.serverless.websocket_connection_handler")

    def __init__(self, auth_validator: Optional[AuthValidator] = None):
        super().__init__()
        self._auth_validator = auth_validator

    def _get_router(self) -> WSLambdaRouter:
        if self._router is None:
            self._router = WSLambdaRouter(
                connection_routes=True,
                system_routes=False,
                auth_validator=self._auth_validator
            )
        return self._router

    def register(self, route: str, method: Optional[str] = None) -> None:
        """
        Route registration is not supported for WebsocketConnectionHandler.
        This handler is designed for connection management events only.
        """
        raise NotImplementedError(
            "WebsocketConnectionHandler does not support route registration. "
            "Use Lambda.register() for custom routes instead."
        )