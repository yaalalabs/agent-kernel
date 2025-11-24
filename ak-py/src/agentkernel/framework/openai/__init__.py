"""
Agent Kernel support for OpenAI Agents SDK.

This package contains Agent Kernel support for agents built with OpenAI Agents SDK.
It provides the necessary classes and methods to integrate OpenAI agents into the Agent Kernel
framework, allowing for seamless interaction and execution of OpenAI based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .openai import OpenAIModule
