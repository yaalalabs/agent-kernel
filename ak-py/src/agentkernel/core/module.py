from abc import ABC, abstractmethod

from .base import Agent
from .runtime import Runtime


class Module(ABC):
    """
    Module is the base class for all agent modules.

    An agent module is a Python module containing a set of agents built using a supported agent
    framework. Agent Kernel provides an implementation of the Module class for each supported agent
    framework, allowing the agents to be registered and managed in a framework-agnostic manner.
    """

    def __init__(self, agents: list[Agent]):
        """
        Initializes a Module instance.
        :param agents: List of agents in the module.
        """
        self._agents = agents
        self._load(agents)

    @property
    def agents(self) -> list[Agent]:
        """
        Returns the list of agents in the module.
        """
        return self._agents

    @abstractmethod
    def add(self, agent: Agent):
        """
        Adds an agent to the module.
        :param agent: The agent to add.
        """
        self._agents.append(agent)

    def unload(self):
        """
        Unloads and deregisters all agents in the module
        """
        for agent in self._agents:
            Runtime.instance().deregister(agent)
        self._agents.clear()

    def _load(self, agents: list[Agent]):
        """
        Loads and registers all agents to the runtime.
        :param agents: List of agents to load.
        """
        self._agents = agents
        for agent in agents:
            Runtime.instance().register(agent)

    @abstractmethod
    def reload(self, agents: list[Agent]):
        """
        Reloads and replaces all agents in the module with the specified agents.
        :param agents: List of agents to replace the current agents.
        """
        self.unload()
        self._load(agents)
