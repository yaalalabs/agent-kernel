"""WebSocket delivery for the pipeline (spec #495 §9).

Exports are lazy (same pattern as ``agentkernel.pipeline``) so that Lambda-facing code reaching
the ABCs through the ``deployment/common/websocket_service`` shim never drags in fastapi via
the route handler or the push endpoint.
"""

import importlib
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    "WebSocketConnectionStoreABC": ".base",
    "WebSocketHandlerABC": ".base",
    "LocalConnectionRegistry": ".registry",
    "PipelineWebSocketHandler": ".handler",
    "PodPushWebSocketHandler": ".push",
    "PushEndpointHandler": ".endpoint",
    "WebSocketGateway": ".gateway",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .base import WebSocketConnectionStoreABC, WebSocketHandlerABC
    from .endpoint import PushEndpointHandler
    from .gateway import WebSocketGateway
    from .handler import PipelineWebSocketHandler
    from .push import PodPushWebSocketHandler
    from .registry import LocalConnectionRegistry


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
