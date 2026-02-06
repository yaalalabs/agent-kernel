from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from ...core.tool import ToolContext


class OpenAIToolBuilder:
    """
    OpenAIToolBuilder provides a mechanism to bind generic tool functions
    to OpenAI Agent SDK, automatically injecting ToolContext when needed.

    This builder inspects tool functions to detect if they require a ToolContext
    parameter and wraps them to provide the context at runtime.
    """

    @staticmethod
    def bind(
        tools: list[Callable], runtime: Any = None, session: Any = None, agent: Any = None, requests: list = None, params: dict[str, Any] = None
    ) -> list[Callable]:
        """
        Bind generic tool functions for use with OpenAI Agent SDK.

        This method wraps each tool function to automatically inject ToolContext
        if the function signature includes a parameter of type ToolContext.

        :param tools: List of generic tool functions to bind.
        :param runtime: Optional Runtime instance to pass in the context.
        :param session: Optional Session instance to pass in the context.
        :param agent: Optional Agent instance to pass in the context.
        :param requests: Optional list of AgentRequest objects to pass in the context.
        :param params: Optional dictionary of custom parameters to pass in the context.
        :return: List of wrapped tool functions compatible with OpenAI Agent SDK.
        """
        bindings = []
        requests = requests or []
        params = params or {}

        for tool in tools:
            bindings.append(OpenAIToolBuilder._wrap_tool(tool, runtime, session, agent, requests, params))

        return bindings

    @staticmethod
    def _wrap_tool(tool: Callable, runtime: Any, session: Any, agent: Any, requests: list, params: dict[str, Any]) -> Callable:
        """
        Wrap a single tool function to inject ToolContext if needed.

        :param tool: The tool function to wrap.
        :param runtime: Runtime instance for the context.
        :param session: Session instance for the context.
        :param agent: Agent instance for the context.
        :param requests: List of AgentRequest objects for the context.
        :param params: Dictionary of custom parameters for the context.
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

        # Create a wrapper that injects the context
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
