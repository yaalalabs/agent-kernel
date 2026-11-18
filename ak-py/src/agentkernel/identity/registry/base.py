"""The shared body of the registries that keep their descriptors in a store other processes read."""

from abc import abstractmethod
from datetime import datetime, timezone

from ...core.base import Agent
from ...core.model import AgentDescriptor
from ...core.registry import AgentRegistry


class StoreBackedAgentRegistry(AgentRegistry):
    """
    StoreBackedAgentRegistry is the base class for registries that persist descriptors in a shared store.

    Only the descriptor leaves the process. The agents stay in a dict of this process, so `get` and `agents`
    answer for the agents hosted here, while `descriptor` and `descriptors` read the store and therefore know
    every agent any process registered. The store holds one record per agent id: two processes hosting the same
    agent write the same record, and a deregistration by either removes it until the other registers again.

    A backend implements the four store operations: `_put`, `_remove`, `descriptor` and `descriptors`.
    """

    def __init__(self) -> None:
        """
        Initializes a registry that hosts no agent yet.
        """
        self._agents: dict[str, Agent] = {}

    def register(self, descriptor: AgentDescriptor, agent: Agent) -> None:
        self._ensure_free(self._agents.get(descriptor.id), descriptor.id, agent)
        # Stored before the agent is hosted: a store that cannot be reached leaves the agent unregistered.
        self._put(descriptor.model_copy(update={"updated_at": datetime.now(timezone.utc).isoformat()}))
        self._agents[descriptor.id] = agent

    def deregister(self, id: str) -> None:
        self._agents.pop(id, None)
        self._remove(id)

    def get(self, id: str) -> Agent | None:
        return self._agents.get(id)

    def agents(self) -> dict[str, Agent]:
        return self._agents

    @abstractmethod
    def _put(self, descriptor: AgentDescriptor) -> None:
        """
        Writes a descriptor to the store, replacing the record under its id.
        :param descriptor: The descriptor to store, already stamped with `updated_at`.
        """
        raise NotImplementedError

    @abstractmethod
    def _remove(self, id: str) -> None:
        """
        Removes the record under an id from the store. An id the store does not hold is ignored.
        :param id: The agent id.
        """
        raise NotImplementedError
