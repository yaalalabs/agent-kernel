"""Shared DynamoDB connection driver."""

import time
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key as DDBKey

from .base import BaseDriver


class DynamoDBDriver(BaseDriver):
    """
    DynamoDB connection driver parameterized by table and key schema.

    Owns the connection lifecycle (lazy boto3 resource + Table + ``.load()``
    existence check, with retry) and a generic item-dict surface; value
    handling and data layout stay in the consuming stores. ``table`` is a
    public part of the driver contract for consumers whose data operations
    exceed the generic surface.
    """

    def __init__(
        self,
        table_name: str,
        partition_key: str,
        sort_key: Optional[str] = None,
        region: Optional[str] = None,
        ttl: int = 0,
    ):
        """
        Initialize the driver. Constructor arguments are trusted; config reading and
        validation happen in the stores.

        :param table_name: DynamoDB table name.
        :param partition_key: Name of the table's partition key attribute.
        :param sort_key: Name of the table's sort key attribute, if any.
        :param region: AWS region name; defaults to the boto3 environment default.
        :param ttl: TTL in seconds; when > 0, :meth:`put` attaches an ``expiry_time``
            attribute (UNIX epoch seconds).
        """
        super().__init__("ak.core.util.driver.dynamodb")
        self._table_name = table_name
        self._partition_key = partition_key
        self._sort_key = sort_key
        self._region = region
        self._ttl = int(ttl) if ttl else 0
        self._table = None

    @property
    def table(self):
        """
        Returns the boto3 DynamoDB Table resource, connecting lazily if needed.

        :return: The DynamoDB Table resource for the configured table name.
        """
        if self._table is None:
            with self._lock:
                if self._table is None:
                    self._connect()
        return self._table

    def _connect(self) -> None:
        """Connects to DynamoDB and resolves the configured table, with retries."""

        def connect():
            self._log.debug("Connecting to DynamoDB resource")
            resource = boto3.resource("dynamodb", region_name=self._region)
            table = resource.Table(self._table_name)
            # lightweight call to ensure table exists/accessible
            table.load()
            self._log.debug("Connected to DynamoDB table %s", self._table_name)
            return table

        self._table = self._connect_with_retries(connect, Exception)

    def _item_key(self, pk_value: Any, sk_value: Any = None) -> dict:
        """Composes the primary-key dict from partition and (optional) sort key values."""
        key = {self._partition_key: pk_value}
        if self._sort_key is not None:
            key[self._sort_key] = sk_value
        return key

    def put(self, item: dict) -> None:
        """
        Put a single item. When TTL is configured (> 0), attaches an ``expiry_time``
        attribute (UNIX epoch seconds) to a copy of the item — the caller's dict is
        never mutated.

        :param item: The complete item dict, including key attributes.
        """
        try:
            if self._ttl > 0:
                item = dict(item)
                item["expiry_time"] = int(time.time()) + self._ttl
            self.table.put_item(Item=item)
        except Exception as e:
            self._log.error("Failed to put item into table %s: %s", self._table_name, e)
            raise

    def get(self, pk_value: Any, sk_value: Any = None) -> Optional[dict]:
        """
        Get a single item by key.

        :param pk_value: Partition key value.
        :param sk_value: Sort key value (required when the table has a sort key).
        :return: The raw item dict, or None if the item does not exist. Value
            attribute extraction stays in the stores.
        """
        try:
            resp = self.table.get_item(Key=self._item_key(pk_value, sk_value))
            return resp.get("Item")
        except Exception as e:
            self._log.error("Failed to get item from table %s: %s", self._table_name, e)
            raise

    def delete(self, pk_value: Any, sk_value: Any = None) -> None:
        """
        Delete a single item by key.

        :param pk_value: Partition key value.
        :param sk_value: Sort key value (required when the table has a sort key).
        """
        try:
            self.table.delete_item(Key=self._item_key(pk_value, sk_value))
        except Exception as e:
            self._log.error("Failed to delete item from table %s: %s", self._table_name, e)
            raise

    def query_sort_keys(self, pk_value: Any) -> list[str]:
        """
        Query for all sort key values under a given partition key, following
        ``LastEvaluatedKey`` pagination.

        :param pk_value: Partition key value.
        :return: A list of sort key values stored under the partition key.
        """
        if self._sort_key is None:
            raise ValueError("query_sort_keys requires a sort_key")
        keys: list[str] = []
        try:
            kwargs = {"KeyConditionExpression": DDBKey(self._partition_key).eq(pk_value)}
            resp = self.table.query(**kwargs)
            items = resp.get("Items", [])
            keys.extend([it.get(self._sort_key) for it in items if self._sort_key in it])
            # pagination
            while "LastEvaluatedKey" in resp:
                resp = self.table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
                items = resp.get("Items", [])
                keys.extend([it.get(self._sort_key) for it in items if self._sort_key in it])
        except Exception as e:
            self._log.error("Failed to query keys for %s=%s: %s", self._partition_key, pk_value, e)
            raise
        return keys

    def clear_all(self) -> None:
        """
        Scan the entire table and delete all items.

        Intended for development/test parity with Redis clear by prefix. Use with
        extreme caution in shared environments.
        """
        try:
            names = {"#pk": self._partition_key}
            if self._sort_key is not None:
                names["#sk"] = self._sort_key
            projection = ",".join(names.keys())
            with self.table.batch_writer() as batch:
                resp = self.table.scan(ProjectionExpression=projection, ExpressionAttributeNames=names)
                while True:
                    for it in resp.get("Items", []):
                        batch.delete_item(Key={attr: it[attr] for attr in names.values()})
                    if "LastEvaluatedKey" not in resp:
                        break
                    resp = self.table.scan(
                        ProjectionExpression=projection,
                        ExpressionAttributeNames=names,
                        ExclusiveStartKey=resp["LastEvaluatedKey"],
                    )
        except Exception as e:
            self._log.error("Failed to clear DynamoDB table %s: %s", self._table_name, e)
            raise
