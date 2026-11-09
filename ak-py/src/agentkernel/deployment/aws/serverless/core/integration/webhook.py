from typing import Any

from ......core.util.factory import AKConfigError
from ......integration.adapter.webhook import WebhookRESTRequestHandler
from .event_translator import LambdaEventTranslator
from .base import LambdaHost, LambdaHostGuard


class LambdaWebhookHost(LambdaHost):
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

    def __init__(self, handler: WebhookRESTRequestHandler, translator: LambdaEventTranslator | None = None):
        """Check the deployment can serve the handler, so a broken one fails its Lambda init loudly
        instead of dropping deliveries later.

        :param handler: The webhook handler to host.
        :param translator: The event <-> Starlette translator; a default one when omitted.
        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: See LambdaWebhookGuard.
        """
        self._handler = LambdaWebhookGuard().check(handler)
        super().__init__(translator)

    def handle(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        """Serve one platform delivery (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; unused.
        :return: The proxy response, with the status the platform expects.
        """
        return self._run(self._respond(self._handler.handle, event))

    def challenge(self, event: dict[str, Any], context: Any) -> dict[str, Any]:
        """Answer the platform's subscription handshake (the router's ``(event, context)`` contract).

        :param event: The API Gateway REST (v1) proxy event.
        :param context: The Lambda context; unused.
        :return: The proxy response.
        """
        return self._run(self._respond(self._handler.challenge, event))


class LambdaWebhookGuard(LambdaHostGuard):
    """The cold-start checks LambdaWebhookHost runs (#760): fail at import, not on the first delivery."""

    HOST_NAME = "LambdaWebhookHost"
    SUBJECT = "webhooks"
    COMPLETE_ONLY_REASON = "Platform adapters deliver whole messages"

    def check(self, handler: Any) -> WebhookRESTRequestHandler:
        """Run every check, in this order; return the handler, typed.

        :param handler: What the application passed to ``LambdaWebhookHost``.
        :return: The same handler.
        :raises TypeError: The handler is not a WebhookRESTRequestHandler.
        :raises AKConfigError: Mode, transport, base-path environment or verification settings.
        """
        webhook_handler = self._check_type(handler)
        self._check_deployment(webhook_handler)
        self._check_verification_settings(webhook_handler)
        return webhook_handler

    @staticmethod
    def _check_type(handler: Any) -> WebhookRESTRequestHandler:
        if not isinstance(handler, WebhookRESTRequestHandler):
            raise TypeError(f"LambdaWebhookHost serves WebhookRESTRequestHandler only; got {type(handler).__name__}")
        return handler

    @staticmethod
    def _check_verification_settings(handler: WebhookRESTRequestHandler) -> None:
        missing = handler.adapter.missing_verification_settings()
        if missing:
            raise AKConfigError(
                "LambdaWebhookHost refuses adapters that would accept deliveries they cannot authenticate "
                f"(the authorizer's integration bypass leaves the adapter's check as the only one): "
                f"{type(handler.adapter).__name__} needs {', '.join(missing)}"
            )
