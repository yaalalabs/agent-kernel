"""
The agent registry: where a Runtime keeps its agents and the descriptor of each.

An agent has two faces. The `Agent` object runs it and exists only in the process that loaded it;
the `AgentDescriptor` is its catalog entry, plain data another process can read. A registry holds
both under the descriptor's id, and is the one place the surfaces and the authorizer ask which
agents exist.

The contract and the in-memory backend live in `core/` because a Runtime needs a registry whether
or not one is configured.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from .base import Agent
from .model import AgentDescriptor
from .util.pagination import DEFAULT_PAGE_SIZE, clamp_limit, decode_cursor, encode_cursor, paginate


class AgentRegistrationError(Exception):
    """An agent could not be registered because another agent already holds its id."""


class AgentDescriptorPage(BaseModel):
    """One page of a registry listing.

    agents: the descriptors on this page, ordered by id
    next_cursor: the cursor of the page after this one; ``None`` on the last page
    """

    agents: list[AgentDescriptor]
    next_cursor: str | None = None


class AgentRegistry(ABC):
    """
    AgentRegistry is the base class for all agent registries.

    A registry maps an agent id to the agent hosted by this process and to its descriptor. A
    backend may know descriptors of agents this process does not host (a store shared between
    processes), so the two sides are read separately: `get` and `agents` answer for this process,
    `descriptor`, `descriptors` and `list` for every agent the registry knows.
    """

    @abstractmethod
    def register(self, descriptor: AgentDescriptor, agent: Agent) -> None:
        """
        Registers an agent under its descriptor's id.

        Registering an agent that already holds the id replaces its descriptor, which is how a
        descriptor changed after loading reaches the registry.
        :param descriptor: The agent's descriptor.
        :param agent: The agent to host under the descriptor's id.
        :raises AgentRegistrationError: If a different agent already holds the id; nothing is replaced.
        """
        raise NotImplementedError

    @abstractmethod
    def deregister(self, id: str) -> None:
        """
        Removes an agent and its descriptor. An id the registry does not hold is ignored.
        :param id: The id of the agent to remove.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, id: str) -> Agent | None:
        """
        Returns the agent this process hosts under an id.
        :param id: The agent id.
        :return: The agent, or None when this process does not host it.
        """
        raise NotImplementedError

    @abstractmethod
    def descriptor(self, id: str) -> AgentDescriptor | None:
        """
        Returns the descriptor registered under an id, whichever process hosts the agent.
        :param id: The agent id.
        :return: The descriptor, or None when the registry knows no such agent.
        """
        raise NotImplementedError

    @abstractmethod
    def agents(self) -> dict[str, Agent]:
        """
        Returns the agents this process hosts, keyed by id.

        The mapping is live: a caller that keeps it sees later registrations and removals.
        :return: The hosted agents by id.
        """
        raise NotImplementedError

    @abstractmethod
    def descriptors(self) -> list[AgentDescriptor]:
        """
        Returns every descriptor the registry knows, in no particular order.
        :return: The descriptors.
        """
        raise NotImplementedError

    def clear(self) -> None:
        """
        Removes every agent this process hosts, with its descriptor.
        """
        for id in tuple(self.agents()):
            self.deregister(id)

    # Defined last: inside this class body the name `list` is this method from here on, so a
    # `list[...]` annotation on a method placed below it would not be the builtin.
    def list(self, cursor: str | None = None, limit: int | None = None, tags: list[str] | None = None) -> AgentDescriptorPage:
        """
        Returns one page of the known descriptors, ordered by id.
        :param cursor: The `next_cursor` of the page before; None for the first page.
        :param limit: The page size, clamped to the shared maximum; the shared default when omitted.
        :param tags: Keep only the agents carrying every one of these tags; None or empty keeps all.
        :return: The page and the cursor of the one after it.
        :raises ValueError: If the cursor is malformed.
        """
        offset = decode_cursor(cursor)
        wanted = set(tags or ())
        matching = sorted((descriptor for descriptor in self.descriptors() if wanted.issubset(descriptor.tags)), key=lambda descriptor: descriptor.id)
        page, next_offset = paginate(matching, clamp_limit(limit, DEFAULT_PAGE_SIZE), offset)
        return AgentDescriptorPage(agents=page, next_cursor=encode_cursor(next_offset))


class InMemoryAgentRegistry(AgentRegistry):
    """
    InMemoryAgentRegistry keeps the agents and descriptors of one Runtime in process memory.

    It knows only the agents this process hosts, so every descriptor has an agent beside it.
    """

    def __init__(self) -> None:
        """
        Initializes an empty registry.
        """
        self._agents: dict[str, Agent] = {}
        self._descriptors: dict[str, AgentDescriptor] = {}

    def register(self, descriptor: AgentDescriptor, agent: Agent) -> None:
        held = self._agents.get(descriptor.id)
        if held is not None and held is not agent:
            raise AgentRegistrationError(f"Agent with name '{descriptor.id}' is already registered.")
        self._agents[descriptor.id] = agent
        self._descriptors[descriptor.id] = descriptor

    def deregister(self, id: str) -> None:
        self._agents.pop(id, None)
        self._descriptors.pop(id, None)

    def get(self, id: str) -> Agent | None:
        return self._agents.get(id)

    def descriptor(self, id: str) -> AgentDescriptor | None:
        return self._descriptors.get(id)

    def agents(self) -> dict[str, Agent]:
        return self._agents

    def descriptors(self) -> list[AgentDescriptor]:
        return list(self._descriptors.values())


class AgentRegistryFactory:
    """
    AgentRegistryFactory builds the registry a Runtime keeps its agents in.
    """

    @staticmethod
    def build() -> AgentRegistry:
        """
        Builds a registry for one Runtime. Each call returns a registry of its own, so two
        Runtimes never share agents.
        :return: An in-memory registry.
        """
        return InMemoryAgentRegistry()
