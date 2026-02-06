"""
Utility functions for tool binding and context injection.

This module provides shared utilities for framework-specific tool builders
to detect context requirements and wrap tool functions appropriately.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from .tool import ToolContext


def needs_tool_context(tool: Callable) -> bool:
    """
    Check if a tool function requires a ToolContext parameter.

    :param tool: The tool function to inspect.
    :return: True if the function has a ToolContext parameter, False otherwise.
    """
    sig = inspect.signature(tool)
    return any(
        param.annotation is ToolContext or (hasattr(param.annotation, "__origin__") and param.annotation.__origin__ is ToolContext)
        for param in sig.parameters.values()
    )


def wrap_tool_with_context(
    tool: Callable,
    runtime: Any,
    session: Any,
    agent: Any,
    requests: list,
    params: dict[str, Any],
) -> Callable:
    """
    Wrap a tool function to inject ToolContext if needed.

    If the tool doesn't need context, returns it unchanged.
    Otherwise, creates a wrapper that injects the context.

    :param tool: The tool function to wrap.
    :param runtime: Runtime instance for the context.
    :param session: Session instance for the context.
    :param agent: Agent instance for the context.
    :param requests: List of AgentRequest objects for the context.
    :param params: Dictionary of custom parameters for the context.
    :return: The wrapped tool function, or the original if no context is needed.
    """
    if not needs_tool_context(tool):
        return tool

    if asyncio.iscoroutinefunction(tool):

        async def async_wrapper(**kwargs):
            ctx = ToolContext(
                runtime=runtime,
                session=session,
                agent=agent,
                requests=requests,
                params=params,
            )
            return await tool(ctx=ctx, **kwargs)

        # Preserve function metadata
        async_wrapper.__name__ = tool.__name__
        async_wrapper.__doc__ = tool.__doc__
        async_wrapper.__module__ = tool.__module__
        return async_wrapper
    else:

        def sync_wrapper(**kwargs):
            ctx = ToolContext(
                runtime=runtime,
                session=session,
                agent=agent,
                requests=requests,
                params=params,
            )
            return tool(ctx=ctx, **kwargs)

        # Preserve function metadata
        sync_wrapper.__name__ = tool.__name__
        sync_wrapper.__doc__ = tool.__doc__
        sync_wrapper.__module__ = tool.__module__
        return sync_wrapper
