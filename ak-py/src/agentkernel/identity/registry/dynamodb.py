"""DynamoDB-backed agent registry. Requires the ``aws`` extra.

Expected table schema:
    Partition Key: ``agent_id`` (S)
    Sort Key:      none
    TTL attribute: ``expiry_time`` (N), Unix epoch seconds (optional, disabled by default)

Item layout (one item per agent):
    agent_id    -> the partition key
    data        -> the AgentDescriptor as JSON
    updated_at  -> ISO-8601 timestamp of the write, denormalized beside the document

A listing scans the table rather than using an index: the registry is a low-cardinality resource
(one item per agent, no per-request growth), the schedule store's precedent.
"""

import logging

from ...core.model import AgentDescriptor
from ...core.util.driver.dynamodb import DynamoDBDriver
from .base import StoreBackedAgentRegistry


class DynamoDBAgentRegistry(StoreBackedAgentRegistry):
    """DynamoDB-backed implementation of the AgentRegistry interface."""

    def __init__(self, table_name: str, ttl: int = 0):
        """
        Initializes the registry. Nothing connects until the first read or write.
        :param table_name: The DynamoDB table, with a partition key named `agent_id` and no sort key.
        :param ttl: The item TTL in seconds; 0, the default, keeps descriptors until they are deregistered.
        """
        super().__init__()
        self._log = logging.getLogger("ak.identity.registry.dynamodb")
        self._driver = DynamoDBDriver(table_name=table_name, partition_key="agent_id", ttl=int(ttl))

    def descriptor(self, id: str) -> AgentDescriptor | None:
        item = self._driver.get(id)
        if not item:
            return None
        return AgentDescriptor.model_validate_json(item["data"])

    def descriptors(self) -> list[AgentDescriptor]:
        items: list[dict] = []
        resp = self._driver.table.scan()
        while True:
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            resp = self._driver.table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        return [AgentDescriptor.model_validate_json(item["data"]) for item in items]

    def _put(self, descriptor: AgentDescriptor) -> None:
        self._log.debug(f"Storing the descriptor of agent '{descriptor.id}'")
        self._driver.put({"agent_id": descriptor.id, "data": descriptor.model_dump_json(), "updated_at": descriptor.updated_at})

    def _remove(self, id: str) -> None:
        self._log.debug(f"Removing the descriptor of agent '{id}'")
        self._driver.delete(id)
