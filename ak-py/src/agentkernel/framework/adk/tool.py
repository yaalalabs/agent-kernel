from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from ...core.tool import ToolContext


class ADKToolBuilder:
    """
    ADKToolBuilder provides a mechanism to bind generic tool functions
    to Google ADK, automatically injecting ToolContext when needed.

    This builder inspects tool functions to detect if they require a ToolContext
    parameter and wraps them to provide the context at runtime by accessing
    the ADK-specific context.
    """

    @staticmethod
    def bind(tools: list[Callable]) -> list[Callable]:
        """
        Bind generic tool functions for use with Google ADK.

        This method wraps each tool function to automatically inject ToolContext
        if the function signature includes a parameter of type ToolContext.
        The context is populated from ADK's get_current_context().

        :param tools: List of generic tool functions to bind.
        :return: List of wrapped tool functions compatible with Google ADK.
        """
        bindings = []

        for tool in tools:
            bindings.append(ADKToolBuilder._wrap_tool(tool))

        return bindings

    @staticmethod
    def _wrap_tool(tool: Callable) -> Callable:
        """
        Wrap a single tool function to inject ToolContext if needed.

        :param tool: The tool function to wrap.
        :return: Wrapped tool function.
        """
        # Check if the tool function expects a ToolContext parameter
        sig = inspect.signature(tool)
        needs_context = any(
            param.annotation is ToolContext or (hasattr(param.annotation, "__origin__") and param.annotation.__origin__ is ToolContext)
            for param in sig.parameters.values()
        )

        if not needs_context:
            # If no ToolContext is needed, return the original function
            return tool

        # Create a wrapper that injects the context from ADK
        if asyncio.iscoroutinefunction(tool):

            async def async_wrapper(**kwargs):
                try:
                    from google.adk.runtime.context import get_current_context

                    adk_ctx = get_current_context()
                    ctx = ToolContext(
                        runtime=adk_ctx.state.get("runtime"),
                        session=adk_ctx.state.get("session"),
                        agent=adk_ctx.state.get("agent"),
                        requests=adk_ctx.state.get("requests", []),
                        params=adk_ctx.state.get("params", {}),
                    )
                    return await tool(ctx=ctx, **kwargs)
                except Exception as e:
                    raise RuntimeError(f"Failed to get ADK context for tool '{tool.__name__}': {str(e)}")

            # Preserve function metadata
            async_wrapper.__name__ = tool.__name__
            async_wrapper.__doc__ = tool.__doc__
            async_wrapper.__module__ = tool.__module__
            return async_wrapper
        else:

            def sync_wrapper(**kwargs):
                try:
                    from google.adk.runtime.context import get_current_context

                    adk_ctx = get_current_context()
                    ctx = ToolContext(
                        runtime=adk_ctx.state.get("runtime"),
                        session=adk_ctx.state.get("session"),
                        agent=adk_ctx.state.get("agent"),
                        requests=adk_ctx.state.get("requests", []),
                        params=adk_ctx.state.get("params", {}),
                    )
                    return tool(ctx=ctx, **kwargs)
                except Exception as e:
                    raise RuntimeError(f"Failed to get ADK context for tool '{tool.__name__}': {str(e)}")

            # Preserve function metadata
            sync_wrapper.__name__ = tool.__name__
            sync_wrapper.__doc__ = tool.__doc__
            sync_wrapper.__module__ = tool.__module__
            return sync_wrapper
