import importlib
import importlib.metadata
from typing import TYPE_CHECKING, Any

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

# name -> submodule providing it. Resolved lazily via __getattr__ below so that importing one
# deployment target (e.g. `from agentkernel.aws import Lambda`, serverless-only) never pulls in
# the other target's dependencies (e.g. containerized/ECS's fastapi/uvicorn requirement).
_LAZY_EXPORTS = {
    # containerized (ECS)
    "AWSRestAPI": ".containerized",
    "AWSWebsocketAPI": ".containerized",
    "ECSAgentRunner": ".containerized",
    "ECSIOHandler": ".containerized",
    "ECSOutputConsumer": ".containerized",
    "ECSWebSocketSystemRequestHandler": ".containerized",
    "ECSSQSConsumer": ".containerized.core",
    # serverless (Lambda)
    "APIGatewayAuthorizer": ".serverless",
    "Lambda": ".serverless",
    "ResponseHandler": ".serverless",
    "ServerlessAgentRunner": ".serverless",
    "WebsocketConnectionHandler": ".serverless",
    "LambdaSQSConsumer": ".serverless.core",
    # shared
    "SQSHandler": ".core.sqs_handler",
}

__all__ = sorted(_LAZY_EXPORTS)

# Not executed at runtime (preserves laziness) — lets mypy/IDEs resolve these names statically.
if TYPE_CHECKING:
    from .containerized import (
        AWSRestAPI,
        AWSWebsocketAPI,
        ECSAgentRunner,
        ECSIOHandler,
        ECSOutputConsumer,
        ECSWebSocketSystemRequestHandler,
    )
    from .containerized.core import ECSSQSConsumer
    from .core.sqs_handler import SQSHandler
    from .serverless import (
        APIGatewayAuthorizer,
        Lambda,
        ResponseHandler,
        ServerlessAgentRunner,
        WebsocketConnectionHandler,
    )
    from .serverless.core import LambdaSQSConsumer


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
