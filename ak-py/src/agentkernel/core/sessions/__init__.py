"""
Agent Kernel Core.

This package contains the Agent Kernel session store implementation.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .in_memory import InMemorySessionStore
from .base import SessionStore
from .redis import RedisSessionStore
