"""
Agent Kernel CLI.

This package contains the Agent Kernel CLI that allows users to execute and interact with agents
running under the Agent Kernel framework.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .cli import CLI
