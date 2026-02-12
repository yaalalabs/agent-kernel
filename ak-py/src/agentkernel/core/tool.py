"""
Generic tool binding support for Agent Kernel.

This module provides the ToolContext and ToolBuilder classes that enable
framework-agnostic tool function definitions. Tool functions can optionally
accept a ToolContext parameter to access the runtime and session context.
"""

import asyncio
import functools
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from .base import Session
from .runtime import Runtime

log = logging.getLogger("ak.core.tool")


@dataclass(frozen=True)
class ToolContext:
    """
    Immutable context object passed to generic tool functions.

    Provides access to the runtime and session in which the tool function
    is being invoked.
    """

    runtime: Runtime
    session: Session


class ToolBuilder:
    """
    Base class for framework-specific tool builders.

    Provides common functionality for detecting ToolContext parameters in
    function signatures, building ToolContext instances, and wrapping generic
    tool functions with context injection.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind a list of generic tool functions to framework-specific tool definitions.

        :param funcs: List of generic tool functions to bind.
        :return: List of framework-specific tool definitions.
        :raises NotImplementedError: If called on the base ToolBuilder class.
        """
        raise NotImplementedError("bind() must be implemented by framework-specific subclasses")

    @staticmethod
    def _needs_tool_context(func: Callable) -> tuple[bool, str | None]:
        """
        Inspect a function signature to determine if it declares a ToolContext parameter.

        Detection is based on type annotation, not parameter name.

        :param func: The function to inspect.
        :return: A tuple of (needs_context, param_name) where needs_context is True
                 if the function has a ToolContext parameter, and param_name is the
                 name of that parameter (or None).
        """
        try:
            hints = get_type_hints(func)
        except Exception:
            return False, None

        for param_name, param_type in hints.items():
            if param_type is ToolContext:
                return True, param_name

        return False, None

    @staticmethod
    def _build_tool_context() -> ToolContext:
        """
        Build a ToolContext from the current runtime and session.

        Framework-specific subclasses may override this to use alternative
        context initialization mechanisms.

        :return: A ToolContext instance.
        :raises RuntimeError: If the current session cannot be resolved.
        """
        runtime = Runtime.current()
        session = Session.current()
        return ToolContext(runtime=runtime, session=session)

    @classmethod
    def _wrap(cls, func: Callable) -> Callable:
        """
        Wrap a generic tool function with ToolContext injection.

        If the function declares a parameter of type ToolContext, the wrapper
        will build a ToolContext and inject it when the function is called.
        The wrapper preserves async/sync semantics of the original function.

        :param func: The generic tool function to wrap.
        :return: A wrapped function with context injection.
        :raises TypeError: If func is not callable.
        """
        if not callable(func):
            raise TypeError(f"Expected a callable, got {type(func).__name__}")

        needs_context, param_name = cls._needs_tool_context(func)

        if not needs_context:
            return func

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(**kwargs: Any) -> Any:
                kwargs[param_name] = cls._build_tool_context()
                return await func(**kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(**kwargs: Any) -> Any:
                kwargs[param_name] = cls._build_tool_context()
                return func(**kwargs)

            return sync_wrapper
