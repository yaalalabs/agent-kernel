"""
Agent Kernel Integration with Microsoft Teams

This package contains the Agent Kernel integration implementations for Microsoft Teams chat.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .teams_chat import AgentTeamsRequestHandler
