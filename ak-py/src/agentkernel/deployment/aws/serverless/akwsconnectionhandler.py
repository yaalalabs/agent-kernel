import logging

from .aklambda import Lambda
from .core import WSLambdaRouter


class WebsocketConnectionHandler(Lambda):
    """The Lambda entry point for the WebSocket ``$connect`` and ``$disconnect`` routes.

    ``$connect`` authenticates through the configured identity provider (the ``identity`` block), so
    the function needs no code beyond pointing at ``WebsocketConnectionHandler.handler``.
    """

    _log = logging.getLogger("ak.aws.serverless.websocket_connection_handler")

    @classmethod
    def _get_router(cls) -> WSLambdaRouter:
        """
        Get or create the WebSocket Lambda router with connection routes enabled.

        :return: WSLambdaRouter instance configured for connection handling
        :raises AKConfigError: If no identity provider is configured
        """
        if cls._router is None:
            cls._router = WSLambdaRouter(connection_routes=True, system_routes=False)
        return cls._router

    def register(self, route: str, method: str | None = None) -> None:
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
