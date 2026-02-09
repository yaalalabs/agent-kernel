"""
Utility functions for tool binding and context injection.

This module provides shared utilities for framework-specific tool builders
to detect context requirements and wrap tool functions appropriately.
"""

from __future__ import annotations

import asyncio
import functools
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
    return any(param.annotation is ToolContext for param in sig.parameters.values())


def get_tool_context_param_name(tool: Callable) -> str | None:
    """
    Get the parameter name for ToolContext in a tool function.

    :param tool: The tool function to inspect.
    :return: The parameter name if found, None otherwise.
    """
    sig = inspect.signature(tool)
    for param_name, param in sig.parameters.items():
        if param.annotation is ToolContext:
            return param_name
    return None


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
    Otherwise, creates a wrapper that injects the context using the
    actual parameter name from the function signature.

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

    # Get the actual parameter name for ToolContext
    context_param_name = get_tool_context_param_name(tool)
    if context_param_name is None:
        return tool

    if asyncio.iscoroutinefunction(tool):

        @functools.wraps(tool)
        async def async_wrapper(**kwargs):
            ctx = ToolContext(
                runtime=runtime,
                session=session,
                agent=agent,
                requests=requests,
                params=params,
            )
            # Use the actual parameter name from the function signature
            kwargs[context_param_name] = ctx
            return await tool(**kwargs)

        return async_wrapper
    else:

        @functools.wraps(tool)
        def sync_wrapper(**kwargs):
            ctx = ToolContext(
                runtime=runtime,
                session=session,
                agent=agent,
                requests=requests,
                params=params,
            )
            # Use the actual parameter name from the function signature
            kwargs[context_param_name] = ctx
            return tool(**kwargs)

        return sync_wrapper
