"""
Agent Kernel Core.

This package contains the Agent Kernel core implementation.
"""
import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .config import AKConfig as Config
from .base import Agent, Runner, Session
from .module import Module
from .runtime import Runtime
from .sessions.redis import RedisDriver, RedisSessionSerde
from .service import AgentService
