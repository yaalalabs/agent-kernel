"""
Agent Kernel.

This package contains the Agent Kernel AWS lambda implementation.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .serverless import Lambda
from .serverless import ServerlessAgentRunner