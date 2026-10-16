"""
Agent Kernel Integration with AG-UI

This package contains the Agent Kernel integration implementations for the AG-UI protocol.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .handler import AGUIRequestHandler
from .pipeline import AGUIPipelineRequestHandler
from .state import AGUIState
