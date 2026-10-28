"""
Agent Kernel support for Microsoft Agent Framework (MAF).

This package contains Agent Kernel support for agents built with Microsoft Agent Framework.
It provides the necessary classes and methods to integrate MAF agents into the Agent Kernel
framework, allowing for seamless interaction and execution of MAF based agents.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .maf import MAFModule, MAFToolBuilder
