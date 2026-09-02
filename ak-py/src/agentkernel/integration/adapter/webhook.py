import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Request

from ...api.handler import RESTRequestHandler
from .base import InboundAdapter, Source
from .factory import IntegrationAdapterFactory
from .producer import IntegrationProducer


class WebhookRESTRequestHandler(RESTRequestHandler):
    """Hosts a webhook :class:`InboundAdapter` on the REST surface (spec #524 §7).

    One generic handler for every push-based platform: it mounts the adapter's routes, verifies,
    parses, acknowledges and enqueues, then answers the platform immediately. The agent runs on
    the other side of the queue, so a slow run can no longer exceed a platform's delivery
    timeout and cause a redelivery.

    Joins the ``*RESTRequestHandler`` family, so it is mounted the same way as the thread and
    schedule handlers — but only inside a pipeline topology::

        IOHandler.run(handlers=[WebhookRESTRequestHandler(SlackInboundAdapter())])
    """
    requires_pipeline = True

    _log = logging.getLogger("ak.integration.webhook")

    def __init__(self, adapter: InboundAdapter, producer: Optional[IntegrationProducer] = None):
        """
        :param adapter: The platform's inbound adapter. The application constructs it, so
            bringing your own is just passing a different instance.
        :param producer: Input-queue producer; defaults to the configured transport.
        :raises ValueError: If the adapter is not a webhook adapter or declares no route.
        """
        if adapter.source is not Source.WEBHOOK:
            raise ValueError(f"{type(adapter).__name__} is a {adapter.source} adapter: host it with PollerRunner, not WebhookRESTRequestHandler")
        if not adapter.webhook_path:
            raise ValueError(f"{type(adapter).__name__} must declare a webhook_path for its platform's deliveries")
        self._adapter = adapter
        self._producer = producer or IntegrationProducer()

    def get_router(self) -> APIRouter:
        """Mount the adapter's delivery route, plus its handshake route when it has one."""
        router = APIRouter()
        router.add_api_route(self._adapter.webhook_path, self.handle, methods=["POST"])
        if self._adapter.challenge_path:
            router.add_api_route(self._adapter.challenge_path, self.challenge, methods=["GET"])
        return router

    async def challenge(self, request: Request) -> Any:
        """Answer the platform's subscription handshake."""
        return await self._adapter.challenge(request)

    async def handle(self, request: Request) -> Any:
        """Verify, parse and enqueue one platform delivery, then answer the platform.

        :param request: The incoming webhook request.
        :return: The SDK's own response when the adapter produced one, else the adapter's
            success body.
        :raises HTTPException: Raised by the adapter's ``verify`` (or its SDK's dispatch) for a
            delivery that must be rejected; the platform sees its expected status.
        """
        name = self._adapter.name
        await self._adapter.verify(request)
        result = await self._adapter.parse(request)

        if result.requests:
            outbound = IntegrationAdapterFactory.create_outbound(name)
            for inbound in result.requests:
                inbound.reply_context.update(await outbound.acknowledge(inbound.reply_context))
                try:
                    await asyncio.to_thread(self._producer.enqueue, name, inbound)
                except Exception:
                    self._log.exception(f"Failed to enqueue: integration={name}, session_id={inbound.session_id}, request_id={inbound.request_id}")
                    raise
        else:
            self._log.debug(f"Ignored delivery: integration={name}")

        return result.response if result.response is not None else self._adapter.success_response()
