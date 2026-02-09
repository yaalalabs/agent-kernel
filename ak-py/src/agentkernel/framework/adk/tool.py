from __future__ import annotations

import asyncio
import functools
from typing import Callable

from ...core.tool import ToolContext
from ...core.tool_util import get_tool_context_param_name, needs_tool_context


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
    def _get_adk_context() -> ToolContext:
        """
        Retrieve and build ToolContext from ADK's current context.

        :return: ToolContext instance with ADK state.
        :raises RuntimeError: If ADK context cannot be retrieved or is not properly initialized.
        """
        try:
            from google.adk.runtime.context import get_current_context
        except ImportError as e:
            raise RuntimeError("Failed to import ADK context module. " "Make sure google-genai-adk is installed.") from e

        try:
            adk_ctx = get_current_context()
        except Exception as e:
            raise RuntimeError("Failed to get ADK current context. " "Ensure the tool is being called within an ADK agent execution context.") from e

        # Retrieve context values
        runtime = adk_ctx.state.get("runtime")
        session = adk_ctx.state.get("session")
        agent = adk_ctx.state.get("agent")
        requests = adk_ctx.state.get("requests", [])
        params = adk_ctx.state.get("params", {})

        # Validate required fields
        if runtime is None or session is None or agent is None:
            raise RuntimeError(
                "ADK context is not properly initialized. " "Required fields (runtime, session, agent) are missing from adk_ctx.state."
            )

        return ToolContext(
            runtime=runtime,
            session=session,
            agent=agent,
            requests=requests,
            params=params,
        )

    @staticmethod
    def _wrap_tool(tool: Callable) -> Callable:
        """
        Wrap a single tool function to inject ToolContext if needed.

        :param tool: The tool function to wrap.
        :return: Wrapped tool function.
        """
        if not needs_tool_context(tool):
            # If no ToolContext is needed, return the original function
            return tool

        # Get the actual parameter name for ToolContext
        context_param_name = get_tool_context_param_name(tool)
        if context_param_name is None:
            return tool

        # Create a wrapper that injects the context from ADK
        if asyncio.iscoroutinefunction(tool):

            @functools.wraps(tool)
            async def async_wrapper(**kwargs):
                ctx = ADKToolBuilder._get_adk_context()
                # Use the actual parameter name from the function signature
                kwargs[context_param_name] = ctx
                return await tool(**kwargs)

            return async_wrapper
        else:

            @functools.wraps(tool)
            def sync_wrapper(**kwargs):
                ctx = ADKToolBuilder._get_adk_context()
                # Use the actual parameter name from the function signature
                kwargs[context_param_name] = ctx
                return tool(**kwargs)

            return sync_wrapper
