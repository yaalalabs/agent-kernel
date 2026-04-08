"""
Agent Kernel support for Smolagents.

This package contains Agent Kernel support for agents built with Hugging Face Smolagents.
It provides the necessary classes and methods to integrate Smolagents agents into the Agent Kernel
framework, allowing for seamless interaction and execution of Smolagents based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .smolagents import SmolagentsModule, SmolagentsToolBuilder
