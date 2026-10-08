import asyncio
import os
from typing import Any, Awaitable, Callable, ClassVar, Coroutine, Dict, Mapping, Optional

from starlette.requests import Request

from .....core.config import AKConfig
from .....core.model import ExecutionMode
from .....core.util.factory import AKConfigError
from .....integration.adapter.webhook import WebhookRESTRequestHandler
from .....pipeline.transport.base import QueueTransportFactory
from .event_translator import LambdaEventTranslator


class LambdaWebhookHost:
    """Serves one WebhookRESTRequestHandler from routes the application registers (#760).

    Build it at module scope and register its endpoints with ``Lambda.register``::

        slack = LambdaWebhookHost(WebhookRESTRequestHandler(SlackInboundAdapter()))

        @Lambda.register("/slack/events", method="POST")
        def slack_events(event, context):
            return slack.handle(event, context)

    Wraps the handler and copies none of it: verify, parse, acknowledge and enqueue stay in
    WebhookRESTRequestHandler.handle, shared with the pipeline IOHandler.

    This module imports FastAPI and Starlette at module scope, so ``agentkernel.aws`` exports it
    lazily: ``from agentkernel.aws import Lambda`` stays fastapi-free.
    """

    # One per execution environment, shared by every host and reused across warm
    # invocations, like uvicorn's single loop on the other surfaces. Never made the thread's
    # current loop, so run_async_sync elsewhere in the process sees what it saw before.
    _loop: ClassVar[Optional[asyncio.AbstractEventLoop]] = None

    def __init__(self, handler: WebhookRESTRequestHandler, translator: Optional[LambdaEventTranslator] = None):
        """Check the deployment can serve the handler, so a broken one fails its Lambda init loudly
        instead of dropping deliveries later.

        :param handler: The webhook handler to host.
        :param translator: The event <-> Starlette translator; a default one when omitted.
        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: See LambdaWebhookGuard.
        """
        self._handler = LambdaWebhookGuard().check(handler)
        self._translator = translator or LambdaEventTranslator()

    def handle(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Serve one platform delivery (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; unused.
        :return: The proxy response, with the status the platform expects.
        """
        return self._run(self._respond(self._handler.handle, event))

    def challenge(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Answer the platform's subscription handshake (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; unused.
        :return: The proxy response.
        """
        return self._run(self._respond(self._handler.challenge, event))

    async def _respond(self, endpoint: Callable[[Request], Awaitable[Any]], event: Mapping[str, Any]) -> Dict[str, Any]:
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


class LambdaWebhookGuard:
    """The cold-start checks LambdaWebhookHost runs (#760): fail at import, not on the first delivery."""

    REST_MODES = (ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC)
    BASE_PATH_ENV = ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT")

    def check(self, handler: Any) -> WebhookRESTRequestHandler:
        """Run every check, in this order; return the handler, typed.

        :param handler: What the application passed to ``LambdaWebhookHost``.
        :return: The same handler.
        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: Mode, transport, base-path environment or verification settings.
        """
        webhook_handler = self._check_type(handler)
        self._check_mode()
        self._check_transport(webhook_handler)
        self._check_base_path_env()
        self._check_verification_settings(webhook_handler)
        return webhook_handler

    @staticmethod
    def _check_type(handler: Any) -> WebhookRESTRequestHandler:
        if not isinstance(handler, WebhookRESTRequestHandler):
            raise TypeError(f"LambdaWebhookHost serves WebhookRESTRequestHandler only; got {type(handler).__name__}")
        return handler

    def _check_mode(self) -> None:
        mode = AKConfig.get().execution.mode
        if mode not in self.REST_MODES:
            raise AKConfigError(
                f"LambdaWebhookHost serves webhooks in execution.mode rest_sync or rest_async only; got {mode.value if mode else 'unset'}. "
                "Lambda routes the other modes' events to WSLambdaRouter"
            )

    @staticmethod
    def _check_transport(handler: WebhookRESTRequestHandler) -> None:
        if not handler.requires_pipeline:
            return
        transport_type = QueueTransportFactory.resolve_type()
        if transport_type != "sqs":
            raise AKConfigError(
                f"LambdaWebhookHost needs the sqs queue transport, but execution.queues resolves to '{transport_type}': "
                "the serverless agent runner consumes the input queue through an SQS event source mapping. "
                "Set queue_mode = true in the ak-serverless Terraform module and execution.queues.type: sqs in config.yaml"
            )

    def _check_base_path_env(self) -> None:
        missing = [name for name in self.BASE_PATH_ENV if not os.getenv(name)]
        if missing:
            raise AKConfigError(
                f"LambdaWebhookHost needs {', '.join(missing)} in the environment: without them the router sends every "
                "webhook to the chat handler. The ak-serverless Terraform module sets them on the request-handler Lambda"
            )

    @staticmethod
    def _check_verification_settings(handler: WebhookRESTRequestHandler) -> None:
        missing = handler.adapter.missing_verification_settings()
        if missing:
            raise AKConfigError(
                "LambdaWebhookHost refuses adapters that would accept deliveries they cannot authenticate "
                f"(the authorizer's integration bypass leaves the adapter's check as the only one): "
                f"{type(handler.adapter).__name__} needs {', '.join(missing)}"
            )
