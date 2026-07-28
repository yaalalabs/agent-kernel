"""Framework-agnostic, pluggable sandbox capability.

One interface through which agents execute LLM-generated code, work in a persistent
isolated workspace, or attach to an existing runtime, with a first-class permission
boundary and an open provider-registration mechanism.

This module is the capability's public surface. The reusable provider contract suite lives
in ``agentkernel.sandbox.testing`` and is imported explicitly from test code (it depends on
pytest), so it is deliberately not re-exported here. The concrete factory, hooks, tools,
providers, and broker flavors stay internal.
"""

from . import errors
from .base import AttachedEnvironmentProvider, AttachedEnvironment, Sandbox, SandboxProvider
from .broker.base import ExecutionBroker
from .manager import ExecutionManager
from .model import (
    IsolationTier,
    SandboxCapabilities,
    SandboxFile,
    SandboxPolicy,
    SandboxPrincipal,
    SandboxResult,
    SandboxSession,
    SandboxTask,
)
from .principal import AgentPrincipalResolver, PrincipalResolver

__all__ = [
    "errors",
    "Sandbox",
    "SandboxProvider",
    "AttachedEnvironmentProvider",
    "AttachedEnvironment",
    "ExecutionBroker",
    "ExecutionManager",
    "PrincipalResolver",
    "AgentPrincipalResolver",
    "IsolationTier",
    "SandboxCapabilities",
    "SandboxFile",
    "SandboxPolicy",
    "SandboxPrincipal",
    "SandboxResult",
    "SandboxSession",
    "SandboxTask",
]
