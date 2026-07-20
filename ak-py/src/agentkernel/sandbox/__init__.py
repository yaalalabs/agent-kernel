"""Framework-agnostic, pluggable sandbox capability.

One interface through which agents execute LLM-generated code, work in a persistent
isolated workspace, or attach to an existing runtime, with a first-class permission
boundary and an open provider-registration mechanism.

This module is the capability's public surface. As the implementation lands across
iterations it grows to export the ``Sandbox``/``SandboxProvider``/``SandboxBroker``/
``PrincipalResolver`` ABCs, ``SandboxManager``, and the ``testing`` contract suite.
The concrete factory, hooks, tools, providers, and brokers stay internal.
"""

from . import errors
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

__all__ = [
    "errors",
    "IsolationTier",
    "SandboxCapabilities",
    "SandboxFile",
    "SandboxPolicy",
    "SandboxPrincipal",
    "SandboxResult",
    "SandboxSession",
    "SandboxTask",
]
