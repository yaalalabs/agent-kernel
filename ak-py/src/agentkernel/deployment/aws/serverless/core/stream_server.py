import logging

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from .....api.handler import RESTRequestHandler
from .....api.http import RESTAPI
from .....core.config import AKConfig
from .....core.util.factory import AKConfigError
from .....pipeline.io_handler import IOHandler
from .....pipeline.request_handler import RequestHandler
from .....pipeline.transport.base import QueueTransportFactory
from .paths import LambdaPaths


class LambdaStreamGuard:
    """The cold-start checks LambdaStreamServer runs (#894): fail at init, not on the first request."""

    def check(self, config: AKConfig) -> LambdaPaths:
        """Run every check, in this order; return the chat-path rule.

        :param config: The loaded AKConfig
        :return: The chat-path rule built from the environment
        :raises AKConfigError: Mode, transport, base-path environment, then ``IOHandler.check_deployment``'s
        """
        self._check_mode(config)
        self._check_transport()
        paths = self._check_base_path_env()
        IOHandler.check_deployment("sqs", config, pod_push=False)
        return paths

    @staticmethod
    def _check_mode(config: AKConfig) -> None:
        execution = config.execution
        if not execution.is_sse:
            mode = execution.mode.value if execution.mode else "unset"
            raise AKConfigError(
                "LambdaStreamServer serves execution.mode rest_sync with message_type delta (SSE) only; "
                f"got {mode} + {execution.resolved_message_type.value}. Other modes use Lambda.handler"
            )

    @staticmethod
    def _check_transport() -> None:
        transport_type = QueueTransportFactory.resolve_type()
        if transport_type != "sqs":
            raise AKConfigError(
                f"LambdaStreamServer needs the sqs queue transport, but execution.queues resolves to '{transport_type}': "
                "the serverless agent runner consumes the input queue through an SQS event source mapping. "
                "Set queue_mode = true in the ak-serverless Terraform module and execution.queues.type: sqs in config.yaml"
            )

    @staticmethod
    def _check_base_path_env() -> LambdaPaths:
        paths = LambdaPaths.from_env()
        if paths is None:
            raise AKConfigError(
                f"LambdaStreamServer needs {', '.join(LambdaPaths.missing_env())} in the environment to map the chat path. "
                "The ak-serverless Terraform module sets them on the request-handler Lambda"
            )
        return paths


class LambdaChatPathMiddleware:
    """ASGI middleware: the configured chat path reaches RequestHandler.CHAT_PATH; other paths pass unchanged.

    The Lambda counterpart of ECS's gateway overwrite_path (ak-aws/containerized/state.tf)."""

    def __init__(self, app: ASGIApp, paths: LambdaPaths):
        self._app = app
        self._chat_path = paths.chat_path.rstrip("/") or "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (scope["path"].rstrip("/") or "/") == self._chat_path:
            target = RequestHandler.CHAT_PATH
            scope = {**scope, "path": target, "raw_path": target.encode()}
        await self._app(scope, receive, send)


class LambdaStreamServer:
    """Serves the pipeline's REST app from the request-handler Lambda through the Lambda Web Adapter (#894).

    The REST half of IOHandler.run: RESTAPI.build_app with the pipeline RequestHandler, served by uvicorn.
    No response-handler thread and no agent runner: on Lambda they are their own functions.

    This module imports FastAPI, Starlette and uvicorn at module scope, so ``agentkernel.aws`` exports it
    lazily: ``from agentkernel.aws import Lambda`` stays fastapi-free."""

    _log = logging.getLogger("ak.aws.lambda.stream")

    @classmethod
    def build_app(cls, handlers: list[RESTRequestHandler] | None = None) -> ASGIApp:
        """Run LambdaStreamGuard, then return the wrapped app (separate from ``run`` so tests drive it).

        :param handlers: Extra REST handlers served beside the pipeline ``RequestHandler``
        :return: The ASGI app, with the chat-path rule applied
        :raises AKConfigError: When a cold-start check fails
        """
        config = AKConfig.get()
        paths = LambdaStreamGuard().check(config)
        app = RESTAPI.build_app(handlers=[RequestHandler(), *(handlers or [])])
        return LambdaChatPathMiddleware(app, paths)

    @classmethod
    def run(cls, handlers: list[RESTRequestHandler] | None = None) -> None:
        """Build the app and serve it on api.host:api.port until LWA stops the process.

        A guard failure is logged in full, then re-raised: LWA reports only a readiness timeout.

        :param handlers: Extra REST handlers served beside the pipeline ``RequestHandler``
        """
        config = AKConfig.get()
        try:
            app = cls.build_app(handlers)
        except AKConfigError:
            cls._log.exception("LambdaStreamServer refused to start; LWA will report a readiness timeout")
            raise
        uvicorn.Server(uvicorn.Config(app=app, host=config.api.host, port=config.api.port)).run()
