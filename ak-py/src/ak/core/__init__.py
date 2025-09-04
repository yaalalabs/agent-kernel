"""
Agent Kernel Core.

This package contains the Agent Kernel core implementation.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("ak")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .base import Agent, Runner, Session
from .module import Module
from .runtime import Runtime, _MemoryType
from .sessions.redis import RedisDriver, RedisSessionSerde
from .service import AgentService
