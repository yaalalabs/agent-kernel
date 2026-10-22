"""
Agent Kernel support for the Claude Agent SDK.

This package contains Agent Kernel support for agents built with the Claude Agent SDK.
It provides the necessary classes and methods to integrate Claude Agent SDK agents into the Agent
Kernel framework, allowing for seamless interaction and execution of Claude Agent SDK based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .claude import ClaudeAgentSpec, ClaudeModule, ClaudeTelemetry, ClaudeToolBuilder, ClaudeToolContext
