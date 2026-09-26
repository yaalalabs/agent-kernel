import logging

from ...core.util.async_bridge import run_async_sync
from .base import GatewayAdapter, Source
from .factory import IntegrationAdapterFactory


class GatewayRunner:
    """Hosts a stateful :class:`GatewayAdapter` (spec #524 §7).

    The bidirectional sibling of :class:`WebhookRESTRequestHandler` and ``PollerRunner``: a
    gateway owns a long-lived platform connection, feeds the input queue with what it reads, and
    delivers replies back through that same connection. ``start()`` runs the adapter's own loop
    on an already-constructed instance.

    A gateway must run in the same process as the Response Handler: it registers itself as the
    platform's outbound adapter as it starts, so replies route back to its live connection.
    """

    _log = logging.getLogger("ak.integration.gateway_runner")

    def __init__(self, adapter: GatewayAdapter):
        """
        :param adapter: The gateway adapter to host.
        :raises ValueError: If the adapter's ``source`` is not ``Source.REALTIME``.
        """
        if adapter.source is not Source.REALTIME:
            raise ValueError(
                f"{type(adapter).__name__} is a {adapter.source} adapter: "
                "host it with WebhookRESTRequestHandler or PollerRunner, not GatewayRunner"
            )
        self._adapter = adapter

    @property
    def adapter(self) -> GatewayAdapter:
        """The hosted adapter (IOHandler names its thread after it)."""
        return self._adapter

    def start(self) -> None:
        """Register the outbound adapter, then run the gateway's blocking loop.

        The registration is what lets the Response Handler resolve this live connection by the
        adapter's ``name``. It happens here rather than in the adapter's constructor so the side
        effect is tied to being hosted, not to merely existing.
        """
        IntegrationAdapterFactory.register_outbound(self._adapter.name, self._adapter)
        run_async_sync(self._adapter.start())
