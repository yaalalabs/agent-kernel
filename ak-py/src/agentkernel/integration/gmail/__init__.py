"""This package contains the Agent Kernel integration implementations for Gmail API."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .gmail_chat import AgentGmailRequestHandler
