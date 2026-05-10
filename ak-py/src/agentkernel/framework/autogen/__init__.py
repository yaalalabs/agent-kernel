"""
Agent Kernel support for AutoGen.

This package contains Agent Kernel support for agents built with Microsoft AutoGen.
It provides the necessary classes and methods to integrate AutoGen agents into the Agent Kernel
framework, allowing for seamless interaction and execution of AutoGen based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .autogen import AutogenModule, AutogenToolBuilder

__all__ = ["AutogenModule", "AutogenToolBuilder"]
