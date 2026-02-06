from __future__ import annotations

from typing import Any, Callable

from ...core.tool_util import wrap_tool_with_context


class CrewAIToolBuilder:
    """
    CrewAIToolBuilder provides a mechanism to bind generic tool functions
    to CrewAI, automatically injecting ToolContext when needed.

    This builder inspects tool functions to detect if they require a ToolContext
    parameter and wraps them to provide the context at runtime.
    """

    @staticmethod
    def bind(
        tools: list[Callable],
        runtime: Any = None,
        session: Any = None,
        agent: Any = None,
        requests: list = None,
        params: dict[str, Any] = None,
    ) -> list[Callable]:
        """
        Bind generic tool functions for use with CrewAI.

        This method wraps each tool function to automatically inject ToolContext
        if the function signature includes a parameter of type ToolContext.

        :param tools: List of generic tool functions to bind.
        :param runtime: Optional Runtime instance to pass in the context.
        :param session: Optional Session instance to pass in the context.
        :param agent: Optional Agent instance to pass in the context.
        :param requests: Optional list of AgentRequest objects to pass in the context.
        :param params: Optional dictionary of custom parameters to pass in the context.
        :return: List of wrapped tool functions compatible with CrewAI.
        """
        bindings = []
        requests = requests or []
        params = params or {}

        for tool in tools:
            bindings.append(wrap_tool_with_context(tool, runtime, session, agent, requests, params))

        return bindings
