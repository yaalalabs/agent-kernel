from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import Agent, Session
    from .model import AgentRequest
    from .runtime import Runtime


@dataclass(frozen=True)
class ToolContext:
    """
    ToolContext provides access to the runtime context for tool functions.

    This context is immutable and provides access to the runtime, session, agent,
    requests, and custom parameters. Tool functions can optionally accept this
    context by declaring a parameter of type ToolContext.

    Attributes:
        runtime: The Runtime instance under which the tool function is being executed.
        session: The Session instance for the current agent invocation.
        agent: The Agent instance invoking the tool function.
        requests: The list of AgentRequest objects that triggered the agent invocation.
        params: Additional custom parameters that may be passed to the tool context.

    Note:
        While runtime, session, and agent are typed as non-optional, they may be None
        in some contexts. Tool functions should handle None values appropriately or
        ensure the context is properly initialized before use.
    """

    runtime: Runtime | None
    session: Session | None
    agent: Agent | None
    requests: list[AgentRequest]
    params: dict[str, Any]
