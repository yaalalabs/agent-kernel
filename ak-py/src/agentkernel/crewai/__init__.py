"""
Agent Kernel support for CrewAI.

This package contains Agent Kernel support for agents built with CrewAI.
It provides the necessary classes and methods to integrate CrewAI agents into the Agent Kernel
framework, allowing for seamless interaction and execution of CrewAI-based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .crewai import CrewAIModule
