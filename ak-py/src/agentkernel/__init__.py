"""
Agent Kernel Python Distribution.

This package provides a unified framework for working with different agent implementations and SDKs.
It includes core functionality for agent execution, modular integration, and runtime management.

Features:
- Support for multiple agent frameworks (OpenAI, CrewAI, LangGraph)
- Modular architecture for easy extension
- Unified runtime environment
- CLI interface for agent interaction
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .core import *
