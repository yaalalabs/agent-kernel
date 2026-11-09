import asyncio
import os
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any, ClassVar

from starlette.requests import Request

from .....api.handler import RESTRequestHandler
from .....core.config import AKConfig
from .....core.model import ExecutionMode, ReplyMessageType
from .....core.util.factory import AKConfigError
from .....pipeline.transport.base import QueueTransportFactory
from .event_translator import LambdaEventTranslator


class LambdaHost:
    """Base for the hosts that serve a RESTRequestHandler's endpoints from Lambda routes.

    Translates the API Gateway event to a Starlette request, awaits the endpoint on a per-class
    event loop, and translates the answer (or the exception) back to a proxy response.
    """

    # One per host class per execution environment, reused across warm invocations, like
    # uvicorn's single loop on the other surfaces. Never made the thread's current loop, so
    # run_async_sync elsewhere in the process sees what it saw before.
    _loop: ClassVar[asyncio.AbstractEventLoop | None] = None

    def __init__(self, translator: LambdaEventTranslator | None = None):
        """:param translator: The event <-> Starlette translator; a default one when omitted."""
        self._translator = translator or LambdaEventTranslator()

    async def _respond(self, endpoint: Callable[[Request], Awaitable[Any]], event: Mapping[str, Any]) -> dict[str, Any]:
        """Translate the event, call the endpoint, and translate its answer or its exception.

        Every failure becomes a proxy response: an unhandled exception would reach
        ``Lambda.handler``'s catch-all, which answers 500 with the exception text.
        """
        request = None
        try:
            request = self._translator.to_request(event)
            return await self._translator.to_proxy_response(request, await endpoint(request))
        except Exception as exc:  # HTTPException included: its status is the answer
            return await self._translator.error_to_proxy_response(exc, request)

    @classmethod
    def _run(cls, coro: Coroutine) -> Any:
        """Drive a coroutine on the execution environment's loop, replacing a closed one."""
        if cls._loop is None or cls._loop.is_closed():
            cls._loop = asyncio.new_event_loop()
        return cls._loop.run_until_complete(coro)


class LambdaHostGuard:
    """The deployment checks every LambdaHost runs at cold start: fail at import, not on the first request."""

    HOST_NAME: ClassVar[str]
    SUBJECT: ClassVar[str]
    COMPLETE_ONLY_REASON: ClassVar[str]  # why the host refuses delta replies, ends the message_type error
    REST_MODES = (ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC)
    BASE_PATH_ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

    def _check_deployment(self, handler: RESTRequestHandler) -> None:
        """Run the mode, transport and base-path environment checks, in this order.

        :raises AKConfigError: The first check that fails.
        """
        self._check_mode()
        self._check_transport(handler)
        self._check_base_path_env()

    def _check_mode(self) -> None:
        execution = AKConfig.get().execution
        mode = execution.mode
        if mode not in self.REST_MODES:
            raise AKConfigError(
                f"{self.HOST_NAME} serves {self.SUBJECT} in execution.mode rest_sync or rest_async only; got {mode.value if mode else 'unset'}. "
                "Lambda routes the other modes' events to WSLambdaRouter"
            )
        message_type = execution.resolved_message_type
        if message_type != ReplyMessageType.COMPLETE:
            raise AKConfigError(
                f"{self.HOST_NAME} serves {self.SUBJECT} with execution.message_type complete only; got {message_type.value}. "
                + self.COMPLETE_ONLY_REASON
            )

    def _check_transport(self, handler: RESTRequestHandler) -> None:
        if not handler.requires_pipeline:
            return
        transport_type = QueueTransportFactory.resolve_type()
        if transport_type != "sqs":
            raise AKConfigError(
                f"{self.HOST_NAME} needs the sqs queue transport, but execution.queues resolves to '{transport_type}': "
                "the serverless agent runner consumes the input queue through an SQS event source mapping. "
                "Set queue_mode = true in the ak-serverless Terraform module and execution.queues.type: sqs in config.yaml"
            )

    def _check_base_path_env(self) -> None:
        missing = [name for name in self.BASE_PATH_ENV if not os.getenv(name)]
        if missing:
            raise AKConfigError(
                f"{self.HOST_NAME} needs {', '.join(missing)} in the environment: without them the router sends every "
                f"{self.SUBJECT.removesuffix('s')} to the chat handler. The ak-serverless Terraform module sets them on the request-handler Lambda"
            )
