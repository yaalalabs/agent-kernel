import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .containerized import (
    AWSRestAPI,
    AWSWebsocketAPI,
    ECSAgentRunner,
    ECSIOHandler,
    ECSOutputConsumer,
    ECSWebSocketRequestHandler,
    ECSWebSocketSystemRequestHandler,
)
from .containerized.core import ECSSQSConsumer
from .core.sqs_handler import SQSHandler
from .serverless import APIGatewayAuthorizer, Lambda, ResponseHandler, ServerlessAgentRunner, WebsocketConnectionHandler
from .serverless.core import LambdaSQSConsumer
