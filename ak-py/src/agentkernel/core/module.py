from abc import ABC, abstractmethod
from typing import Any, List

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
        :param agents: List of agents in the module.
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
            Runtime.instance().deregister(agent)
        self._agents.clear()

    @abstractmethod
    def _wrap(self, agent: Any, agents: List[Any]) -> Agent:
        """
        Wraps an agent in a framework-specific wrapper.
        :param agent: The agent to wrap.
        :return: The wrapped agent.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, agents: list[Any]):
        """
        Loads and registers all agents to the runtime by replacing the current agents.
        :param agents: List of agents to load.
        """
        self.unload()
        registered = []
        for agent in agents:
            try:
                wrapped = self._wrap(agent, agents)
                Runtime.instance().register(wrapped)
                registered.append(wrapped)
            except:
                self._agents = registered
                self.unload()
                raise
        self._agents = registered
