from .base import Agent
from .runtime import Runtime, MemoryType


class Module:
    """
    Module is the base class for all agent modules.
    
    An agent module is a Python module containing a set of agents built using a supported agent
    framework. Agent Kernel provides an implementation of the Module class for each supported agent
    framework, allowing the agents to be registered and managed in a framework agnostic manner.
    """

    def __init__(self, agents: list[Agent], memory_type: MemoryType = MemoryType.IN_MEMORY):
        """
        Initializes a Module instance.
        :param agents: List of agents in the module.
        :param memory_type: Memory type for the module.
        """
        self._agents = agents
        for agent in agents:
            Runtime.instance(memory_type).register(agent)

    @property
    def agents(self) -> list[Agent]:
        """
        Returns the list of agents in the module.
        """
        return self._agents
