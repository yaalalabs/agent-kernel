"""
Agent Kernel support for GoogleADK Agents.

This package contains Agent Kernel support for agents built with GoogleADK Agents.
It provides the necessary classes and methods to integrate GoogleADK agents into the Agent Kernel
framework, allowing for seamless interaction and execution of GoogleADK based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .adk import GoogleADKModule