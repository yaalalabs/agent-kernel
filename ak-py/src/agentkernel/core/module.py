from abc import ABC, abstractmethod
from typing import Any, List

from ..core.hooks import PostHook, PreHook
from .base import Agent
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

    @abstractmethod
    def pre_hook(self, agent: Any, hooks: list[PreHook]) -> "Module":
        """
        Attaches pre-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of pre-execution hooks to attach.
        """
        raise NotImplementedError

    @abstractmethod
    def post_hook(self, agent: Any, hooks: list[PostHook]) -> "Module":
        """
        Attaches post-execution hooks to the agent.
        :param agent: The agent to attach hooks to.
        :param hooks: List of post-execution hooks to attach.
        """
        raise NotImplementedError
