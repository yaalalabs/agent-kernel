import importlib
import importlib.metadata

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


def __getattr__(name):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)
