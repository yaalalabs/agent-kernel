from abc import ABC, abstractmethod
from typing import Any, List, Self

from ..core.hooks import PostHook, PreHook
from .base import Agent, RunOptionsFactory
from .runtime import Runtime


class Module(ABC):
    """
    Module is the base class for all agent modules.

    An agent module is a Python module containing a set of agents built using a supported agent
    framework. Agent Kernel provides an implementation of the Module class for each supported agent
    framework, allowing the agents to be registered and managed in a framework-agnostic manner.
    """

    def __init__(self):
        """
        Initializes a Module instance.
        """
        self._agents = []

    @property
    def agents(self) -> list[Agent]:
        """
        Returns the list of agents in the module.
        """
        return self._agents

    def unload(self):
        """
        Unloads and deregisters all agents in the module
        """
        for agent in self._agents:
            Runtime.current().deregister(agent)
        self._agents.clear()

    def get_agent(self, name: str) -> Agent | None:
        """
        Returns an agent by name from the module.
        :param name: The name of the agent to retrieve.
        :return: The agent with the specified name, or None if not found.
        """
        for agent in self._agents:
            if agent.name == name:
                return agent
        return None

    @abstractmethod
    def _wrap(self, agent: Any, agents: List[Any]) -> Agent:
        """
        Wraps an agent in a framework-specific wrapper.
        :param agent: The agent to wrap.
        :return: The wrapped agent.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, agents: list[Any]) -> "Module":
        """
        Loads and registers all agents to the runtime by replacing the current agents.
        :param agents: List of agents to load.
        """
        self.unload()
        registered = []
        for agent in agents:
            try:
                wrapped = self._wrap(agent, agents)
                Runtime.current().register(wrapped)
                registered.append(wrapped)
            except Exception:
                self._agents = registered
                self.unload()
                raise
        self._agents = registered
        return self

    def pre_hook(self, agent: Any, hooks: list[PreHook]) -> Self:
        """
        Attaches pre-execution hooks to the agent. Chained like `post_hook` / `run_options`.
        :param agent: The native framework agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        :return: This module, for chaining.
        :raises ValueError: If the agent is not loaded in this module.
        """
        self._wrapped(agent).pre_hooks.extend(hooks)
        return self

    def post_hook(self, agent: Any, hooks: list[PostHook]) -> Self:
        """
        Attaches post-execution hooks to the agent. Chained like `pre_hook` / `run_options`.
        :param agent: The native framework agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        :return: This module, for chaining.
        :raises ValueError: If the agent is not loaded in this module.
        """
        self._wrapped(agent).post_hooks.extend(hooks)
        return self

    def run_options(self, agent: Any, factory: RunOptionsFactory | None = None, /, **options: Any) -> Self:
        """
        Declares framework-native run options for one loaded agent, merged into every native run call the
        adapter makes for it (keyword arguments of the framework's own run API, such as OpenAI's `hooks`,
        `run_config` and `max_turns`). Repeated calls merge, the later call winning per key. Chained like
        `pre_hook` / `post_hook`.

        An optional factory, given positionally before the keywords, computes options per run: it is called as
        `factory(agent, session, requests)` on every run (sync or async) and its result is merged over the static
        keywords for that run. One factory per agent, a later call replacing the earlier one; keywords keep merging.
        The parameter is positional-only, so a keyword named `factory` is an ordinary run option.
        :param agent: The native framework agent the options are for.
        :param factory: A callable computing run options per run, or None to declare static options only.
        :param options: The framework-native keyword arguments to declare.
        :return: This module, for chaining.
        :raises TypeError: If the factory is not callable; nothing is stored.
        :raises ValueError: If the agent is not loaded in this module, or an option names a key the adapter reserves;
            nothing is stored.
        """
        wrapped = self._wrapped(agent)
        if factory is not None and not callable(factory):
            raise TypeError(f"Run options factory for agent '{wrapped.name}' must be callable, got {type(factory).__name__}")
        wrapped.validate_run_options(options)
        if factory is not None:
            wrapped.run_options_factory = factory
        wrapped.run_options.update(options)
        return self

    def _wrapped(self, agent: Any) -> Agent:
        """
        Returns the Agent Kernel agent wrapping a native framework agent loaded in this module.
        :param agent: The native framework agent.
        :return: The wrapped agent.
        :raises ValueError: If the agent is not loaded in this module.
        """
        name = self._native_agent_name(agent)
        wrapped = self.get_agent(name)
        if wrapped is None:
            raise ValueError(f"Agent '{name}' is not loaded in this module")
        return wrapped

    def _native_agent_name(self, agent: Any) -> str:
        """
        Returns the Agent Kernel agent name a native framework agent was registered under.
        The default is the native agent's `name`; adapters whose rule differs override it (CrewAI names agents
        by `role`, smolagents falls back to a fixed name).
        :param agent: The native framework agent.
        :return: The registered agent name.
        """
        return agent.name
