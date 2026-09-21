"""Unified queue execution pipeline (#495).

Hosts the five-component chat execution pipeline: Request Handler, Input Queue, Agent Runner,
Output Queue, Response Handler: and its supporting pieces (queue transports, response stores,
WebSocket delivery, ThreadRunner). See docs/specs/495-onprem-kubernetes/ for the design.

Exports are lazy (same pattern as agentkernel.deployment.aws) so that importing one pipeline
submodule (e.g. the ThreadRunner shim used by Lambda-facing code) never drags in another
component's dependencies (e.g. fastapi via the request handler).
"""

import importlib
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    "AgentRunner": ".agent_runner",
    "StreamAgentRunner": ".agent_runner",
    "ConsumerLoop": ".consumer",
    "QueueMessage": ".envelope",
    "QueueName": ".envelope",
    "RequestProducer": ".producer",
    "IOHandler": ".io_handler",
    "RequestHandler": ".request_handler",
    "RestHandler": ".request_handler",
    "ResponseHandler": ".response_handler",
    "ThreadRunner": ".thread_runner",
    "InMemoryTransport": ".transport.in_memory",
    "QueueTransport": ".transport.base",
    "QueueTransportFactory": ".transport.base",
    "TransportConsumer": ".transport.base",
    "LocalConnectionRegistry": ".ws.registry",
    "PipelineWebSocketHandler": ".ws.handler",
    "PodPushWebSocketHandler": ".ws.push",
    "PushEndpointHandler": ".ws.endpoint",
    "WebSocketGateway": ".ws.gateway",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .agent_runner import AgentRunner, StreamAgentRunner
    from .consumer import ConsumerLoop
    from .envelope import QueueMessage, QueueName
    from .io_handler import IOHandler
    from .producer import RequestProducer
    from .request_handler import RequestHandler, RestHandler
    from .response_handler import ResponseHandler
    from .thread_runner import ThreadRunner
    from .transport.base import QueueTransport, QueueTransportFactory, TransportConsumer
    from .transport.in_memory import InMemoryTransport
    from .ws.endpoint import PushEndpointHandler
    from .ws.gateway import WebSocketGateway
    from .ws.handler import PipelineWebSocketHandler
    from .ws.push import PodPushWebSocketHandler
    from .ws.registry import LocalConnectionRegistry


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
