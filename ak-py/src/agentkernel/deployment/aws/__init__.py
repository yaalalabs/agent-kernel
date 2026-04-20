"""
Agent Kernel.

This package contains the Agent Kernel AWS lambda implementation.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .core.sqs_handler import SQSHandler
from .serverless import APIGatewayAuthorizer, Lambda, ResponseHandler, ServerlessAgentRunner
from .serverless.core import LambdaSQSConsumer
