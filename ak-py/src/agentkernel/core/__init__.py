"""
Agent Kernel Core.

This package contains the Agent Kernel core implementation.
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("agentkernel")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

from .base import Agent, Runner, RunOptionsFactory, Session
from .realtime import RealtimeRunner
from .event import (
    DataMessage,
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StepEnd,
    StepStart,
    StreamEvent,
    StreamEventBase,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from .model import (
    AccessLevel,
    AgentDescriptor,
    AgentIdentitySpec,
    AgentRequest,
    AgentRequestAny,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentRequestVoice,
    AgentReply,
    AgentReplyAny,
    AgentReplyText,
    AgentReplyImage,
    AgentSkillDescriptor,
    Principal,
    SessionOwner,
    StreamChunk,
    ToolFilter,
)
from .config import AKConfig as Config
from .module import Module
from .runtime import Runtime
from .service import AgentService
from .hooks import PreHook, PostHook, StreamHalt
from .tool import ToolContext, ToolBuilder
from .util.key_value_cache import KeyValueCache
from .chat_service import ChatService
