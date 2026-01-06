"""
Agent Kernel Core.

This package contains the Agent Kernel core implementation.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .base import Agent, Runner, Session
from .model import (
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentReply,
    AgentReplyText,
    AgentReplyImage,
)
from .config import AKConfig as Config
from .module import Module
from .runtime import Runtime, AuxiliaryCache
from .service import AgentService
from .hooks import PreHook, PostHook
from .util.key_value_cache import KeyValueCache
