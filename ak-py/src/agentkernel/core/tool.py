"""
Generic tool binding support for Agent Kernel.

This module provides the ToolBuilder classes that enable framework-agnostic
tool function definitions.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import TYPE_CHECKING, Any, Callable, ClassVar, List, Self

from .base import Agent, AgentRequest, Session
from .config import AKConfig
from .model import SystemTool

if TYPE_CHECKING:
    from .runtime import Runtime


class ToolContext:
    """
    Execution context for tool functions.

    Provides access to the execution context of the tool, including the runtime, session, agent,
    and the request being processed. This allows tool functions to interact with the broader
    agent execution environment in a consistent way across different frameworks.
    """

    _context: ClassVar[contextvars.ContextVar[Self | None]] = contextvars.ContextVar("tool_context", default=None)
    _cache: ClassVar[dict[str, Self]] = {}

    def __init__(self, runtime: Runtime, agent: Agent, session: Session, requests: list[AgentRequest]):
        """
        Initialize the ToolContext with the given runtime, agent, session, and requests.
        :param runtime: The Runtime instance representing the current execution context.
        :param agent: The Agent instance representing the current agent.
        :param session: The Session instance representing the current session.
        :param requests: The list of AgentRequest instances representing the current requests being processed.
        """
        self._id = uuid.uuid4().hex
        self._runtime: Runtime = runtime
        self._agent: Agent = agent
        self._session: Session = session
        self._requests: list[AgentRequest] = requests
        self._token: contextvars.Token[Self | None] | None = None

    @property
    def id(self) -> str:
        """
        Get the unique identifier for this ToolContext instance.
        :return: The unique identifier as a string.
        """
        return self._id

    @property
    def runtime(self) -> Runtime:
        """
        Get the Runtime instance representing the current execution context.
        :return: The current Runtime instance.
        """
        return self._runtime

    @property
    def agent(self) -> Agent:
        """
        Get the Agent instance representing the current agent.
        :return: The current Agent instance.
        """
        return self._agent

    @property
    def session(self) -> Session:
        """
        Get the Session instance representing the current session.
        :return: The current Session instance.
        """
        return self._session

    @property
    def requests(self) -> list[AgentRequest]:
        """
        Get the list of AgentRequest instances representing the current requests being processed.
        :return: The current list of AgentRequest instances.
        """
        return self._requests

    @classmethod
    def get(cls) -> Self:
        """
        Get the current ToolContext instance from the context variable.

        :return: The current ToolContext instance.
        :raises RuntimeError: If there is no ToolContext set in the current context.
        """
        context = cls._context.get()
        if context is None:
            raise RuntimeError("No ToolContext is set in the current context")
        return context

    def set(self) -> Self:
        """
        Set this ToolContext instance in the context variable.
        """
        self._token = ToolContext._context.set(self)

        return self

    def reset(self) -> None:
        """
        Reset the context variable to the previous value before this ToolContext was set.
        """
        if self._token is not None:
            ToolContext._context.reset(self._token)
            self._token = None

    def __enter__(self) -> Self:
        """
        Add the ToolContext instance in to the cache.
        """
        ToolContext._cache[self.id] = self
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        Remove the ToolContext instance from the cache.
        """
        ToolContext._cache.pop(self.id, None)

    @classmethod
    def fetch(cls, id: str) -> Self:
        """
        Fetch a cached ToolContext instance by its ID.
        :param id: The unique identifier of the ToolContext instance to fetch.
        :return: The cached ToolContext instance.
        :raises KeyError: If no ToolContext instance is found for the given ID.
        """
        if id not in cls._cache:
            raise KeyError(f"No ToolContext found for id: {id}")
        return cls._cache[id]


class ToolBuilder:
    """
    Base class for framework-specific tool builders.

    Provides common functionality that bind regular synchronous and asynchronous functions
    into framework specific tool functions. It also makes sure execution context behaves in the
    same manner across different frameworks.
    """

    @classmethod
    def bind(cls, funcs: list[Callable]) -> list[Any]:
        """
        Bind a list of tool functions to framework-specific tool definitions.

        :param funcs: List of callable tool functions to bind.
        :return: List of framework-specific tool definitions.
        :raises NotImplementedError: If called on the base ToolBuilder class.
        """
        raise NotImplementedError("bind() must be implemented by framework-specific subclasses")


class SystemToolFactory:
    @staticmethod
    def _agent_allowed(config: Any, agent_name: str | None) -> bool:
        """
        Per-capability agent filter: a capability's optional ``agents`` list restricts its
        tools/prompt to the named agents; an absent list means all agents (an empty list
        means none). Anonymous callers (``agent_name`` None, e.g. a ToolBuilder binding
        outside any agent context) are not filtered — filtering happens at agent wrap time,
        where the name is known.
        """
        allowed = getattr(config, "agents", None)
        return allowed is None or agent_name is None or agent_name in allowed

    @staticmethod
    def get_all(agent_name: str | None = None) -> list[SystemTool]:
        """
        Retrieves the enabled system tools (e.g., multimodal, sandbox).

        :param agent_name: When given, capabilities restricted via their `agents` config
                           list are included only for the named agent.
        """
        tools: list[SystemTool] = []

        config = AKConfig.get().multimodal
        if config and config.enabled and SystemToolFactory._agent_allowed(config, agent_name):
            from .multimodal import AnalyzeAttachmentsTool

            tools.append(AnalyzeAttachmentsTool())

        sandbox_config = getattr(AKConfig.get(), "sandbox", None)
        if sandbox_config and sandbox_config.enabled and SystemToolFactory._agent_allowed(sandbox_config, agent_name):
            from ..sandbox.tools import get_sandbox_tools

            tools.extend(get_sandbox_tools())

        # Presence of the block is the enablement signal for scheduling (there is no `enabled`
        # flag), matching how the capability is switched on everywhere else.
        schedule_config = getattr(AKConfig.get(), "schedule", None)
        if schedule_config is not None and SystemToolFactory._agent_allowed(schedule_config, agent_name):
            from ..schedule.tools import get_schedule_tools

            tools.extend(get_schedule_tools())

        # Deliberately not passed through _agent_allowed: that helper reads a flat `agents`
        # list, and OKF's scoping is per (agent, database) and lives in its own role registry.
        # Passing the block would silently allow every agent, since it has no `agents` field.
        okf_config = getattr(AKConfig.get(), "okf", None)
        if okf_config is not None:
            from ..knowledgebase.okf.tools import OKFToolFactory

            tools.extend(OKFToolFactory.get_tools(agent_name))

        agui_config = getattr(AKConfig.get(), "agui", None)
        state_config = getattr(agui_config, "state", None)
        if state_config and state_config.enabled and SystemToolFactory._agent_allowed(state_config, agent_name):
            from ..integration.agui.state import AGUIState

            tools.extend(AGUIState.state_tools())

        client_context_config = getattr(agui_config, "client_context", None)
        if client_context_config and client_context_config.enabled and SystemToolFactory._agent_allowed(client_context_config, agent_name):
            from ..integration.agui.state import AGUIState

            tools.extend(AGUIState.client_context_tools())

        return tools

    @staticmethod
    def get_prompt_sections(agent_name: str | None = None) -> list[str]:
        """
        Collect the prompt sections capabilities contribute directly, outside any tool.

        A capability whose instructions describe the capability itself rather than one of its
        tools belongs here: the text is written into the agent's system prompt instead of being
        carried on a `SystemTool.description`, which the frameworks never read.

        :param agent_name: When given, sections are scoped to that agent.
        :return: The non-empty sections, in the order they are appended to the prompt.
        """
        sections: list[str] = []

        # Lazily imported behind the same enabled-check the tools branch uses, so a process
        # with no `okf` block never pays for the knowledgebase tier.
        okf_config = getattr(AKConfig.get(), "okf", None)
        if okf_config is not None:
            from ..knowledgebase.okf.prompts import OKFPromptComposer

            sections.append(OKFPromptComposer.for_agent(agent_name))

        return [section for section in sections if section]

    @staticmethod
    def get_system_prompt_suffix(agent_name: str | None = None) -> str:
        """
        Generate the system prompt suffix from the enabled capabilities.

        Two sources are concatenated: the descriptions of the enabled system tools, and the
        sections capabilities contribute directly via :meth:`get_prompt_sections`.

        :param agent_name: When given, capabilities restricted via their `agents` config
                           list contribute to the suffix only for the named agent.
        :return: A string containing the concatenated sections, or an empty string when no
                 capability contributes anything.
        """

        tools: List[SystemTool] = SystemToolFactory.get_all(agent_name)

        # A capability may carry its whole prompt section on one tool and leave the
        # others' descriptions empty (the sandbox pattern) — skip the empties.
        sections = [tool.description for tool in tools or [] if tool.description]
        sections.extend(SystemToolFactory.get_prompt_sections(agent_name))
        return "\n".join(sections)
