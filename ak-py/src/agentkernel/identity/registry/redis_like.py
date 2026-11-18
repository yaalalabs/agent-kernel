"""Redis-like implementation of the AgentRegistry interface.

Layout (keys under the configured prefix):
  - Descriptor:  {prefix}agent:{id}   -> AgentDescriptor JSON document
  - All index:   {prefix}index:all    -> set of agent ids

A descriptor is one document, so every write is a full SET of that document, and the index set
exists only to list the descriptors without scanning the keyspace. TTL defaults to 0 for the
registry: nothing registers an agent again until its process restarts, so a descriptor that expired
would drop a running agent from every listing. When one is configured it is refreshed on every write.
"""

import logging

from ...core.model import AgentDescriptor
from ...core.util.driver.redis_like import _RedisLikeDriver
from .base import StoreBackedAgentRegistry

_ALL_INDEX = "index:all"


class _RedisLikeAgentRegistry(StoreBackedAgentRegistry):
    """Shared agent registry body for the Redis-protocol backends.

    Concrete subclasses (``RedisAgentRegistry``, ``ValkeyAgentRegistry``) implement only ``__init__``,
    where they build the driver of their client library and hand it here. Mirrors
    ``_RedisLikeScheduleStore``, whose subclasses supply their driver the same way.
    """

    def __init__(self, driver: _RedisLikeDriver, log: logging.Logger):
        """
        Initializes the registry over a driver.
        :param driver: The connection driver, built with the registry's prefix and TTL.
        :param log: The backend's logger.
        """
        super().__init__()
        self._driver = driver
        self._log = log

    def _agent_key(self, id: str) -> str:
        return self._driver.key(f"agent:{id}")

    def _index_key(self) -> str:
        return self._driver.key(_ALL_INDEX)

    def descriptor(self, id: str) -> AgentDescriptor | None:
        payload = self._driver.get(self._agent_key(id))
        if payload is None:
            return None
        return AgentDescriptor.model_validate_json(payload)

    def descriptors(self) -> list[AgentDescriptor]:
        found: list[AgentDescriptor] = []
        for id in self._driver.smembers(self._index_key()):
            descriptor = self.descriptor(id)
            # A member without a document is a descriptor whose TTL elapsed ahead of the index set.
            if descriptor is not None:
                found.append(descriptor)
        return found

    def _put(self, descriptor: AgentDescriptor) -> None:
        """Write a descriptor document and (re)register it in the index set.

        The membership is re-added on every write, not just on the first: under a configured TTL the
        index set can expire while a descriptor is still live, and a descriptor missing from the
        index would vanish from every listing.

        :param descriptor: The full descriptor to write.
        """
        self._log.debug(f"Storing the descriptor of agent '{descriptor.id}'")
        agent_key = self._agent_key(descriptor.id)
        index_key = self._index_key()
        self._driver.set(agent_key, descriptor.model_dump_json())
        self._driver.sadd(index_key, descriptor.id)
        if self._driver.ttl > 0:
            self._driver.expire(index_key)

    def _remove(self, id: str) -> None:
        self._log.debug(f"Removing the descriptor of agent '{id}'")
        self._driver.delete(self._agent_key(id))
        self._driver.srem(self._index_key(), id)
