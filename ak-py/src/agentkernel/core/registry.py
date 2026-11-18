"""
The agent registry: where a Runtime keeps its agents and the descriptor of each.

An agent has two faces. The `Agent` object runs it and exists only in the process that loaded it;
the `AgentDescriptor` is its catalog entry, plain data another process can read. A registry holds
both under the descriptor's id, and is the one place the surfaces and the authorizer ask which
agents exist.

The contract, the in-memory backend and the factory live in `core/` because a Runtime needs a
registry whether or not one is configured. The backends that keep descriptors in a shared store
live under `identity/registry/`, and the factory imports them only when the configuration selects one.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .base import Agent
from .config import AKConfig
from .model import AgentDescriptor
from .util.factory import AKConfigError, require_extra, resolve_dotted
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

    @staticmethod
    def _ensure_free(held: Agent | None, id: str, agent: Agent) -> None:
        """
        Refuses a registration under an id another agent of this process holds. The same agent again is not a
        duplicate, and neither is an agent another process hosts under the id.
        :param held: The agent this process hosts under the id, or None.
        :param id: The id being registered.
        :param agent: The agent being registered.
        :raises AgentRegistrationError: If a different agent holds the id.
        """
        if held is not None and held is not agent:
            raise AgentRegistrationError(f"Agent with name '{id}' is already registered.")

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
        self._ensure_free(self._agents.get(descriptor.id), descriptor.id, agent)
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


class _OverlaidAgentRegistry(AgentRegistry):
    """
    Applies the `registry.agents.<id>` overlay to each agent as it registers, over any backend.

    The overlay is the last descriptor source: its fields replace the ones the adapter built and
    `Module.describe` declared. The resulting descriptor is the one the backend stores and the one the
    agent carries from then on, so the process that hosts an agent holds a single record of it. Every
    other operation is the backend's own.
    """

    def __init__(self, backend: AgentRegistry, overlay: dict[str, dict[str, Any]]):
        """
        Initializes the registry over a backend.
        :param backend: The registry that keeps the agents and descriptors.
        :param overlay: The descriptor fields to set, by agent id.
        """
        self._backend = backend
        self._overlay = overlay

    def register(self, descriptor: AgentDescriptor, agent: Agent) -> None:
        fields = self._overlay.get(descriptor.id)
        if not fields:
            self._backend.register(descriptor, agent)
            return
        # Validated as a whole: the fields come from configuration and reach other processes through the store.
        overlaid = AgentDescriptor.model_validate({**descriptor.model_dump(), **fields})
        self._backend.register(overlaid, agent)
        # Only once it is registered: a refused registration leaves the agent as it was declared.
        agent._set_descriptor(overlaid)

    def deregister(self, id: str) -> None:
        self._backend.deregister(id)

    def get(self, id: str) -> Agent | None:
        return self._backend.get(id)

    def descriptor(self, id: str) -> AgentDescriptor | None:
        return self._backend.descriptor(id)

    def agents(self) -> dict[str, Agent]:
        return self._backend.agents()

    def descriptors(self) -> list[AgentDescriptor]:
        return self._backend.descriptors()

    def clear(self) -> None:
        self._backend.clear()

    def list(self, cursor: str | None = None, limit: int | None = None, tags: list[str] | None = None) -> AgentDescriptorPage:
        return self._backend.list(cursor=cursor, limit=limit, tags=tags)


_BUILTIN_REGISTRIES = ["in_memory", "redis", "valkey", "dynamodb"]


class AgentRegistryFactory:
    """
    AgentRegistryFactory builds the registry a Runtime keeps its agents in, from the `registry` configuration.
    """

    @staticmethod
    def build() -> AgentRegistry:
        """
        Builds a registry for one Runtime. Each call returns a registry of its own, so two Runtimes never
        share the agents they host.

        ``registry.type`` is a built-in short name (in_memory, redis, valkey, dynamodb) or a dotted path to a
        user-supplied ``AgentRegistry`` subclass (bring-your-own), built with no arguments. With no ``registry``
        block the registry is in-memory. When ``registry.agents`` sets any field, the registry applies that
        overlay as agents register.
        :return: The registry.
        :raises AKConfigError: If the type is unknown, or a store type has no connection block.
        :raises ImportError: If a store type's client library is not installed, naming the extra that ships it.
        """
        # A configuration object from before the block existed simply has no registry: the in-memory default.
        config = getattr(AKConfig.get(), "registry", None)
        if config is None:
            return InMemoryAgentRegistry()
        backend = AgentRegistryFactory._backend(config)
        overlay = {id: fields for id, entry in config.agents.items() if (fields := entry.model_dump(exclude_none=True))}
        return _OverlaidAgentRegistry(backend, overlay) if overlay else backend

    @staticmethod
    def _backend(config: Any) -> AgentRegistry:
        """
        Builds the backend the ``registry`` block selects, handing it its connection settings.
        :param config: The ``registry`` configuration block.
        :return: The backend, not yet connected.
        """
        key = config.type.lower()
        if key == "in_memory":
            return InMemoryAgentRegistry()
        if key == "redis":
            settings = AgentRegistryFactory._settings(config, "redis")
            with require_extra("redis", "registry.type: redis"):
                from ..identity.registry.redis import RedisAgentRegistry

            return RedisAgentRegistry(url=settings.url, prefix=settings.prefix, ttl=settings.ttl)
        if key == "valkey":
            settings = AgentRegistryFactory._settings(config, "valkey")
            with require_extra("valkey", "registry.type: valkey"):
                from ..identity.registry.valkey import ValkeyAgentRegistry

            return ValkeyAgentRegistry(url=settings.url, prefix=settings.prefix, ttl=settings.ttl)
        if key == "dynamodb":
            settings = AgentRegistryFactory._settings(config, "dynamodb")
            with require_extra("aws", "registry.type: dynamodb"):
                from ..identity.registry.dynamodb import DynamoDBAgentRegistry

            return DynamoDBAgentRegistry(table_name=settings.table_name, ttl=settings.ttl)
        if "." not in config.type:
            raise AKConfigError(
                f"unknown registry type '{config.type}'; expected one of {_BUILTIN_REGISTRIES} or a dotted path to an AgentRegistry subclass"
            )
        return resolve_dotted(config.type, base=AgentRegistry)()

    @staticmethod
    def _settings(config: Any, backend: str) -> Any:
        """
        Returns the connection block of a store type.
        :param config: The ``registry`` configuration block.
        :param backend: The store type, which is also the name of its block.
        :return: The block.
        :raises AKConfigError: If the block is absent.
        """
        settings = getattr(config, backend)
        if settings is None:
            raise AKConfigError(f"registry.{backend} must be set when registry.type is '{backend}'")
        return settings
