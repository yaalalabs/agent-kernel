"""
Agent Kernel support for Pydantic AI.

This package contains Agent Kernel support for agents built with Pydantic AI.
It provides the necessary classes and methods to integrate Pydantic AI agents into the Agent
Kernel framework, allowing for seamless interaction and execution of Pydantic AI based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .pydanticai import PydanticAIModule, PydanticAIToolBuilder
