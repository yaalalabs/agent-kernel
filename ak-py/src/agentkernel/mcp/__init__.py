"""
Agent Kernel MCP package.

This package contains the MCP implementation for exposing Agents.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .akmcp import MCP
