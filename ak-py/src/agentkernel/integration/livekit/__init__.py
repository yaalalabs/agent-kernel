"""
Agent Kernel Integrations with LiveKit

This package contains the Agent Kernel integration implementations for LiveKit Voice Agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .livekit_handler import AgentKernelLLM, AgentLiveKitRequestHandler

__all__ = ["AgentLiveKitRequestHandler", "AgentKernelLLM"]
