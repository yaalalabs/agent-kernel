import importlib.metadata
from typing import TYPE_CHECKING, Any

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .deployment import aws as _deployment_aws

__all__ = _deployment_aws.__all__

# Not executed at runtime (preserves laziness) — lets mypy/IDEs resolve these names statically.
if TYPE_CHECKING:
    from .deployment.aws import (
        APIGatewayAuthorizer,
        AWSRestAPI,
        AWSWebsocketAPI,
        ECSAgentRunner,
        ECSIOHandler,
        ECSOutputConsumer,
        ECSSQSConsumer,
        ECSWebSocketSystemRequestHandler,
        Lambda,
        LambdaSQSConsumer,
        ResponseHandler,
        ServerlessAgentRunner,
        SQSHandler,
        WebsocketConnectionHandler,
    )


def __getattr__(name: str) -> Any:
    """Delegate to deployment.aws's own lazy __getattr__ so `from agentkernel.aws import Lambda`
    doesn't eagerly import the containerized (ECS) target, and vice versa."""
    return getattr(_deployment_aws, name)


def __dir__() -> list[str]:
    return sorted(__all__)
