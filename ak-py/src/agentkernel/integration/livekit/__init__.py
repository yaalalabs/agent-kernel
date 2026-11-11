"""
Agent Kernel Integration with LiveKit

This package contains the Agent Kernel integration implementation for LiveKit Realtime Voice.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .adapter import LiveKitEdgeGateway
