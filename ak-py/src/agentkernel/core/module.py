import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Self

from pydantic import ValidationError

from ..core.hooks import PostHook, PreHook
from .base import Agent, RunOptionsFactory
from .model import AgentDescriptor
from .runtime import Runtime


class Module(ABC):
    """
    Module is the base class for all agent modules.

    An agent module is a Python module containing a set of agents built using a supported agent
    framework. Agent Kernel provides an implementation of the Module class for each supported agent
    framework, allowing the agents to be registered and managed in a framework-agnostic manner.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger("ak.core.module")

    _REPORTED_DESCRIPTOR_FIELDS: ClassVar[frozenset[str]] = frozenset({"tools", "runner", "supports_streaming", "updated_at"})
    """
    The `AgentDescriptor` fields that state a fact about the agent: the tools its adapter reads from the native
    agent, its runner and whether that runner streams, and when the registry stored the record. `describe`
    refuses them: they are reported, not declared.
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
    def _wrap(self, agent: Any, agents: list[Any]) -> Agent:
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
                self._roll_back()
                raise
        self._agents = registered
        return self

    def _roll_back(self) -> None:
        """
        Deregisters the agents a failed load had registered, one by one.

        A failure here is logged and never raised: the error that failed the load is the one the caller needs,
        and over a shared registry the outage that caused it usually fails the cleanup too. Every agent is
        attempted whatever happened to the one before it. Those that could not be removed stay in the module,
        still registered, so `unload()` finishes the cleanup once the registry answers again.
        """
        remaining = []
        for agent in self._agents:
            try:
                Runtime.current().deregister(agent)
            except Exception as e:
                remaining.append(agent)
                self._log.error(
                    f"Agent '{agent.name}' is still registered after a failed load: it could not be deregistered ({e}). "
                    "Call unload() on this module once the registry is reachable, or restart the process."
                )
        self._agents = remaining

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

    def run_options(self, agent: Any, *factory: RunOptionsFactory, **options: Any) -> Self:
        """
        Declares framework-native run options for one loaded agent, merged into every native run call the
        adapter makes for it (keyword arguments of the framework's own run API, such as OpenAI's `hooks`,
        `run_config` and `max_turns`). Repeated calls merge, the later call winning per key. Chained like
        `pre_hook` / `post_hook`.

        An optional factory, given as the one positional argument after the agent, computes options per run: it
        is called as `factory(agent, session, requests)` on every run (sync or async) and its result is merged over
        the static keywords for that run. One factory per agent, a later call replacing the earlier one; keywords
        keep merging. The factory is accepted only positionally (the agent keeps its keyword form, as with
        `pre_hook` / `post_hook`), so a keyword named `factory` is an ordinary run option.
        :param agent: The native framework agent the options are for.
        :param factory: At most one callable computing run options per run; omit it to declare static options only.
        :param options: The framework-native keyword arguments to declare.
        :return: This module, for chaining.
        :raises TypeError: If more than one positional argument follows the agent, or the factory is not callable;
            nothing is stored.
        :raises ValueError: If the agent is not loaded in this module, or an option names a key the adapter reserves;
            nothing is stored.
        """
        wrapped = self._wrapped(agent)
        if len(factory) > 1:
            raise TypeError(f"Module.run_options() takes at most one factory for agent '{wrapped.name}', got {len(factory)}")
        run_options_factory = factory[0] if factory else None
        if run_options_factory is not None and not callable(run_options_factory):
            raise TypeError(f"Run options factory for agent '{wrapped.name}' must be callable, got {type(run_options_factory).__name__}")
        wrapped.validate_run_options(options)
        if run_options_factory is not None:
            wrapped.run_options_factory = run_options_factory
        wrapped.run_options.update(options)
        return self

    def describe(self, agent: Any, **fields: Any) -> Self:
        """
        Declares catalog metadata for one loaded agent: the `AgentDescriptor` fields only the application knows,
        such as `description`, `version`, `owner`, `tags`, `visibility` and `surfaces`. The fields are set over the
        descriptor the adapter built from the native agent, and the registry is updated with the result. Repeated
        calls merge, the later call winning per field (a list is replaced, not extended). Chained like `pre_hook` /
        `post_hook` / `run_options`.

        The `id` is the key the agent is registered under and cannot be described. Neither can what the agent's
        adapter, its runner and the registry report (`tools`, `runner`, `supports_streaming`, `updated_at`): a
        surface decides from them whether the agent can be served and an authorization policy names tools by
        them, so a descriptor claiming a runner streams when it does not would open a stream that can only fail,
        and a declared tool list would name tools the agent cannot call. `name` and `skills` stay declarable.
        :param agent: The native framework agent the metadata is for.
        :param fields: The `AgentDescriptor` fields to set.
        :return: This module, for chaining.
        :raises ValueError: If the agent is not loaded in this module or not registered in the current runtime, a
            field is not one `AgentDescriptor` declares, `id` or a reported field is named, or a value is not
            valid for its field; nothing is stored.
        """
        wrapped = self._wrapped(agent)
        unknown = sorted(set(fields) - set(AgentDescriptor.model_fields))
        if unknown:
            raise ValueError(f"Unknown descriptor field(s) for agent '{wrapped.name}': {', '.join(unknown)}")
        if "id" in fields:
            raise ValueError(f"The descriptor id of agent '{wrapped.name}' is the key it is registered under and cannot be described")
        reported = sorted(set(fields) & self._REPORTED_DESCRIPTOR_FIELDS)
        if reported:
            raise ValueError(
                f"Descriptor field(s) {', '.join(reported)} of agent '{wrapped.name}' are what its adapter, its runner and "
                "the registry report and cannot be described"
            )
        # Validated as a whole, not copied with the update applied: the descriptor is read by other processes
        # once a shared registry stores it, so a value its model refuses must fail here.
        try:
            described = AgentDescriptor.model_validate({**wrapped.descriptor.model_dump(), **fields})
        except ValidationError as e:
            details = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in e.errors())
            raise ValueError(f"Invalid descriptor for agent '{wrapped.name}': {details}") from e
        runtime = Runtime.current()
        if runtime.registry.get(described.id) is not wrapped:
            raise ValueError(f"Agent '{wrapped.name}' is not registered in the current runtime")
        # The registry first, the agent after: a run that starts while a store is still writing must not act as
        # described here (its identity, say) before any reader can see it, and a registration that raises leaves
        # the agent as it was. After an error the store holds the old record or the new one (a write can be
        # applied and still report failure); the agent keeps the old one, and describing it again settles both.
        declared = wrapped.descriptor
        runtime.registry.register(described, wrapped)
        if wrapped.descriptor is declared:
            # No overlay names the agent, so the registry set nothing over it.
            wrapped._set_descriptor(described)
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
