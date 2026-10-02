"""
Agent Kernel REST package.

This package contains the REST API implementation for exposing Agent Kernel over HTTP.

Exports are lazy (the ``agentkernel.integration.adapter`` pattern) so importing one piece never
drags in another's dependencies: a webhook host on Lambda imports ``api.handler`` and has no use
for ``api.http``'s uvicorn server.
"""

import importlib
import importlib.metadata
from typing import TYPE_CHECKING, Any

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

_LAZY_EXPORTS = {
    "AgentRESTRequestHandler": ".handler",
    "RESTRequestHandler": ".handler",
    "RESTAPI": ".http",
}

__all__ = sorted(_LAZY_EXPORTS)

if TYPE_CHECKING:  # pragma: no cover: static resolution only, preserves laziness at runtime
    from .handler import AgentRESTRequestHandler, RESTRequestHandler
    from .http import RESTAPI


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
