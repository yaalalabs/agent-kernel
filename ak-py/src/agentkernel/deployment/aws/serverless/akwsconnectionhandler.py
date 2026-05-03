from .core import WSLambdaRouter
from .aklambda import Lambda
import logging
from typing import Optional

class WebsocketConnectionHandler(Lambda):
    _log = logging.getLogger("ak.aws.serverless.websocket_connection_handler")

    @classmethod
    def _get_router(cls) -> WSLambdaRouter:
        if cls._router is None:
            cls._router = WSLambdaRouter(connection_routes=True, system_routes=False)
        return cls._router

    @classmethod
    def register(cls, route: str, method: Optional[str] = None) -> None:
        """
        Route registration is not supported for WebsocketConnectionHandler.
        This handler is designed for connection management events only.
        """
        raise NotImplementedError(
            "WebsocketConnectionHandler does not support route registration. "
            "Use Lambda.register() for custom routes instead."
        )