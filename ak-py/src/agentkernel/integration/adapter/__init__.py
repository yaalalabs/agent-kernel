"""Messaging-integration adapter seam (spec #524).

A platform integration is an ``InboundAdapter``/``OutboundAdapter`` pair with the pipeline's
queue between them: the inbound half verifies and normalizes a platform delivery at the edge,
the Agent Runner executes it platform-agnostically, and the outbound half delivers the reply.

Exports are lazy (the ``agentkernel.pipeline`` pattern) so importing one piece never drags in
another's dependencies: a Gmail poller container has no reason to import fastapi.
"""

import importlib
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    "InboundAdapter": ".base",
    "InboundParseResult": ".base",
    "InboundRequest": ".base",
    "OutboundAdapter": ".base",
    "PollingInboundAdapter": ".base",
    "Source": ".base",
    "IntegrationAdapterFactory": ".factory",
    "IntegrationProducer": ".producer",
    "PollerRunner": ".poller",
    "WebhookRESTRequestHandler": ".webhook",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .base import InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter, PollingInboundAdapter, Source
    from .factory import IntegrationAdapterFactory
    from .poller import PollerRunner
    from .producer import IntegrationProducer
    from .webhook import WebhookRESTRequestHandler


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
