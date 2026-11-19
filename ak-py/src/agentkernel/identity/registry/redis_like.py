"""Redis-like implementation of the AgentRegistry interface.

Layout (keys under the configured prefix):
  - Descriptor:  {prefix}agent:{id}   -> AgentDescriptor JSON document
  - All index:   {prefix}index:all    -> set of agent ids

A descriptor is one document, so every write is a full SET of that document, and the index set
exists only to list the descriptors without scanning the keyspace. The two keys change together,
in one MULTI/EXEC transaction per write and per removal, so no interruption and no interleaving
with another process leaves a document that is not listed or a listing entry without its document.
Nothing expires: the registry takes no TTL (see `StoreBackedAgentRegistry`).
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
        :param driver: The connection driver, built with the registry's prefix and no TTL.
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
            # A member without a document: the document was deleted from the store on its own.
            if descriptor is not None:
                found.append(descriptor)
        return found

    def is_empty(self) -> bool:
        """Whether no agent is listed, read from the index set alone, without fetching a document."""
        return not self._driver.smembers(self._index_key())

    def _put(self, descriptor: AgentDescriptor) -> None:
        """Write a descriptor document and its index membership, together.

        One transaction, the driver's `rpush_with_expiry` shape: issued as two commands, a failure between
        them would leave a document other processes resolve by id and never list.

        :param descriptor: The full descriptor to write.
        """
        self._log.debug(f"Storing the descriptor of agent '{descriptor.id}'")
        transaction = self._driver.client.pipeline()
        transaction.set(self._agent_key(descriptor.id), descriptor.model_dump_json())
        transaction.sadd(self._index_key(), descriptor.id)
        transaction.execute()

    def _remove(self, id: str) -> None:
        """Delete a descriptor document and its index membership, together.

        One transaction, so a registration by another process lands wholly before or wholly after it: issued
        as two commands, a registration between them would lose its index membership and keep its document.

        :param id: The agent id.
        """
        self._log.debug(f"Removing the descriptor of agent '{id}'")
        transaction = self._driver.client.pipeline()
        transaction.delete(self._agent_key(id))
        transaction.srem(self._index_key(), id)
        transaction.execute()
