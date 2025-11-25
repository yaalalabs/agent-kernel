"""
Agent Kernel support for LangGraph.

This package contains Agent Kernel support for agents built with LangGraph.
It provides the necessary classes and methods to integrate LangGraph agents into the Agent Kernel
framework, allowing for seamless interaction and execution of LangGraph based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .langgraph import LangGraphModule
