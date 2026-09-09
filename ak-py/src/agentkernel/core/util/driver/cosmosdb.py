"""Shared Azure Cosmos DB (Table API) connection driver. Requires the ``azure`` extra."""

import time
from typing import Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient

from .base import BaseDriver


class CosmosDBDriver(BaseDriver):
    """
    Cosmos DB Table API connection driver.

    Owns the connection lifecycle (lazy client with a ``__health_check__`` probe,
    with retry) and a generic PartitionKey/RowKey entity surface with manual TTL
    handling (Cosmos DB Table API TTL works differently than DynamoDB).
    ``table_client`` is a public part of the driver contract for consumers whose
    data operations exceed the generic surface.
    """

    def __init__(self, connection_string: str, table_name: str, ttl: int = 0):
        """
        Initialize the driver. Constructor arguments are trusted; config reading and
        validation happen in the stores.

        :param connection_string: Cosmos DB connection string.
        :param table_name: Cosmos DB table name.
        :param ttl: TTL in seconds for manual TTL management (0 disables).
        """
        super().__init__("ak.core.util.driver.cosmosdb")
        self._connection_string = connection_string
        self._table_name = table_name
        self._ttl = int(ttl) if ttl else 0
        self._table_service_client = None
        self._table_client = None

    @property
    def table_client(self):
        """
        Returns the Azure Table client, connecting lazily if needed.

        :return: The Table client for the configured table name.
        """
        if self._table_client is None:
            with self._lock:
                if self._table_client is None:
                    self._connect()
        return self._table_client

    def _connect(self) -> None:
        """Connects to the Cosmos DB Table API and gets the table client, with retries."""

        def connect():
            self._log.debug("Connecting to Cosmos DB Table API")
            service_client = TableServiceClient.from_connection_string(conn_str=self._connection_string)
            table_client = service_client.get_table_client(table_name=self._table_name)
            # Lightweight call to ensure table exists/accessible
            try:
                table_client.get_entity(partition_key="__health_check__", row_key="__health_check__")
            except ResourceNotFoundError:
                # Expected - just checking if table is accessible
                pass
            self._log.debug("Connected to Cosmos DB Table %s", self._table_name)
            return service_client, table_client

        self._table_service_client, self._table_client = self._connect_with_retries(connect, Exception)

    def put(self, session_id: str, key: str, value: bytes) -> None:
        """
        Put a single entity for the given partition and row key.

        When TTL is configured (> 0), attaches ``CreatedAt``/``ExpiresIn`` properties
        used for manual TTL management.

        :param session_id: The partition key value.
        :param key: The row key value.
        :param value: The serialized value as bytes.
        """
        try:
            entity = {
                "PartitionKey": session_id,
                "RowKey": key,
                "value": value,
            }

            if self._ttl and self._ttl > 0:
                # Store creation timestamp for manual TTL handling if needed
                entity["CreatedAt"] = int(time.time())
                entity["ExpiresIn"] = int(self._ttl)

            self.table_client.upsert_entity(entity=entity)
            self._log.debug("Successfully put entity session_id=%s key=%s", session_id, key)
        except Exception as e:
            self._log.error("Failed to put entity session_id=%s key=%s: %s", session_id, key, e)
            raise

    def get(self, session_id: str, key: str) -> Optional[bytes]:
        """
        Get a single entity's raw bytes for the given partition and row key.

        :param session_id: The partition key value.
        :param key: The row key value.
        :return: The stored bytes value, or None if the entity does not exist.
        """
        try:
            entity = self.table_client.get_entity(partition_key=session_id, row_key=key)

            # Check TTL if configured
            if self._ttl and self._ttl > 0:
                created_at = entity.get("CreatedAt")
                if created_at and (int(time.time()) - created_at) > self._ttl:
                    self._log.debug("Entity expired: session_id=%s key=%s", session_id, key)
                    # Delete expired entity
                    try:
                        self.table_client.delete_entity(partition_key=session_id, row_key=key)
                    except Exception as delete_err:
                        self._log.warning("Failed to delete expired entity: %s", delete_err)
                    return None

            value = entity.get("value")
            if value is None:
                return None

            # Handle bytes
            if isinstance(value, bytes):
                return value

            self._log.debug("Successfully retrieved entity session_id=%s key=%s", session_id, key)
            return value

        except ResourceNotFoundError:
            self._log.debug("Entity not found: session_id=%s key=%s", session_id, key)
            return None
        except Exception as e:
            self._log.error("Failed to get entity session_id=%s key=%s: %s", session_id, key, e)
            raise

    def query_sort_keys(self, session_id: str) -> list[str]:
        """
        Query for all row keys associated with a given partition key.

        :param session_id: The partition key value.
        :return: A list of row keys stored under the partition key.
        """
        keys: list[str] = []
        try:
            # Query all entities with the given PartitionKey
            filter_query = f"PartitionKey eq '{session_id}'"
            entities = self.table_client.query_entities(query_filter=filter_query)

            for entity in entities:
                row_key = entity.get("RowKey")
                if row_key:
                    # Check TTL if configured
                    if self._ttl and self._ttl > 0:
                        created_at = entity.get("CreatedAt")
                        if created_at and (int(time.time()) - created_at) > self._ttl:
                            # Skip expired entities
                            self._log.debug("Skipping expired entity: %s", row_key)
                            # Optionally delete expired entity
                            try:
                                self.table_client.delete_entity(partition_key=session_id, row_key=row_key)
                            except Exception as delete_err:
                                self._log.warning("Failed to delete expired entity: %s", delete_err)
                            continue

                    keys.append(row_key)

            self._log.debug("Found %d keys for session_id=%s", len(keys), session_id)

        except Exception as e:
            self._log.error("Failed to query keys for session_id=%s: %s", session_id, e)
            raise

        return keys

    def delete(self, session_id: str, key: str) -> None:
        """
        Delete a single entity.

        :param session_id: The partition key value.
        :param key: The row key value.
        """
        try:
            self.table_client.delete_entity(partition_key=session_id, row_key=key)
            self._log.debug("Deleted entity session_id=%s key=%s", session_id, key)
        except ResourceNotFoundError:
            self._log.debug("Entity not found for deletion: session_id=%s key=%s", session_id, key)
        except Exception as e:
            self._log.error("Failed to delete entity session_id=%s key=%s: %s", session_id, key, e)
            raise

    def clear_all(self) -> None:
        """
        Scan the entire table and delete all entities.

        Intended for development/test parity with Redis clear by prefix. Use with
        extreme caution in shared environments.
        """
        try:
            # Query all entities
            entities = self.table_client.list_entities()

            delete_count = 0
            for entity in entities:
                partition_key = entity.get("PartitionKey")
                row_key = entity.get("RowKey")

                if partition_key and row_key:
                    try:
                        self.table_client.delete_entity(partition_key=partition_key, row_key=row_key)
                        delete_count += 1
                    except Exception as delete_err:
                        self._log.warning("Failed to delete entity %s/%s: %s", partition_key, row_key, delete_err)

            self._log.info("Cleared %d entities from table %s", delete_count, self._table_name)

        except Exception as e:
            self._log.error("Failed to clear Cosmos DB table %s: %s", self._table_name, e)
            raise
