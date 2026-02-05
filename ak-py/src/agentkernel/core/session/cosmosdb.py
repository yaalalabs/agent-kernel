import logging
import time
from typing import Optional

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient

from ..base import Session
from ..config import AKConfig
from .base import SessionCache, SessionStore
from .serde import BinarySerde


class CosmosDBDriver:
    """
    CosmosDBDriver provides connection management and helpers for Azure Cosmos DB Table API.
    Uses a simple three-attribute item layout: PartitionKey (session_id), RowKey (key), and value (Binary).
    """

    _table_service_client = None
    _table_client = None

    def __init__(self):
        self._log = logging.getLogger("ak.core.session.cosmosdb.driver")
        cfg = AKConfig.get().session.cosmosdb
        if cfg is None or not cfg.connection_string:
            raise ValueError("AKConfig.session.cosmosdb.connection_string must be set to use CosmosDBSessionStore")
        if not cfg.table_name:
            raise ValueError("AKConfig.session.cosmosdb.table_name must be set to use CosmosDBSessionStore")

        self._connection_string = cfg.connection_string
        self._table_name = cfg.table_name
        self._ttl = cfg.ttl

    @property
    def table_client(self):
        """
        Returns the Azure Table client, connecting lazily if needed.

        :return: The Table client for the configured table name.
        """
        if self._table_client is None:
            self._connect()
        return self._table_client

    def _connect(self):
        """
        Establish a connection to Cosmos DB Table API and get the table client.

        Retries a few times with a small delay between attempts. Raises the last
        encountered exception if all attempts fail.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None

        for attempt in range(retries):
            try:
                self._log.debug("Connecting to Cosmos DB Table API")
                self._table_service_client = TableServiceClient.from_connection_string(conn_str=self._connection_string)
                self._table_client = self._table_service_client.get_table_client(table_name=self._table_name)
                # Lightweight call to ensure table exists/accessible
                try:
                    self._table_client.get_entity(partition_key="__health_check__", row_key="__health_check__")
                except ResourceNotFoundError:
                    # Expected - just checking if table is accessible
                    pass

                self._log.debug("Connected to Cosmos DB Table %s", self._table_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning("Cosmos DB connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)

        if last_err:
            raise last_err

    def put(self, session_id: str, key: str, value: bytes) -> None:
        """
        Put a single entity for the given session and key.

        When TTL is configured (> 0), attaches a Timestamp property that can be used
        for manual TTL management (Cosmos DB Table API TTL works differently than DynamoDB).

        :param session_id: The session identifier (partition key).
        :param key: The item key within the session (row key).
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
        Get a single entity's raw bytes for the given session and key.

        :param session_id: The session identifier (partition key).
        :param key: The item key within the session (row key).
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

    def query_keys(self, session_id: str) -> list[str]:
        """
        Query for all row keys associated with a given session partition key.

        :param session_id: The session identifier (partition key).
        :return: A list of keys (row keys) stored under the session.
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

    def delete_entity(self, session_id: str, key: str) -> None:
        """
        Delete a single entity.

        :param session_id: The session identifier (partition key).
        :param key: The item key within the session (row key).
        """
        try:
            self.table_client.delete_entity(partition_key=session_id, row_key=key)
            self._log.debug("Deleted entity session_id=%s key=%s", session_id, key)
        except ResourceNotFoundError:
            self._log.debug("Entity not found for deletion: session_id=%s key=%s", session_id, key)
        except Exception as e:
            self._log.error("Failed to delete entity session_id=%s key=%s: %s", session_id, key, e)
            raise

    def scan_and_clear_all(self) -> None:
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


class CosmosDBSessionStore(SessionStore):
    """
    Cosmos DB Table API-backed implementation of SessionStore.
    Table schema uses:
      - PartitionKey: session_id (string)
      - RowKey: key (string)
      - value: binary attribute (serialized using BinarySerde)
      - CreatedAt: optional timestamp for TTL management (UNIX epoch seconds)
      - ExpiresIn: optional TTL value in seconds

    Note: Property names 'Timestamp' and 'TTL' are reserved in Cosmos DB Table API.
    """

    def __init__(self, cache: SessionCache = None):
        """
        Initialize the Cosmos DB-backed SessionStore.

        Prepares the serializer and a Cosmos DB driver that encapsulates access
        to the configured table.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.cosmosdb")
        self._serde = BinarySerde()
        self._driver = CosmosDBDriver()
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Load a session by its unique identifier.

        Reads all keys for the session from Cosmos DB and reconstructs a Session
        by deserializing each value via BinarySerde.

        :param session_id: Unique identifier for the session.
        :param strict: If True, raises a KeyError if the session is not found.
        :return: The populated Session, or a new Session if not found and strict is False.
        """
        self._log.debug(f"Loading Cosmos DB session with ID {session_id}")

        # Check cache first
        if self._cache:
            session = self._cache.get(session_id)
            if session:
                self._log.debug(f"Session {session_id} found in cache")
                return session

        # Query all keys for this session
        keys = self._driver.query_keys(session_id)

        if not keys:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning("Session %s not found, creating new session", session_id)
            return self.new(session_id)

        # Reconstruct session from stored data
        session = Session(session_id)
        for k in keys:
            payload = self._driver.get(session_id, k)
            if payload is None:
                continue
            session.set(k, self._serde.loads(payload))

        # Update cache
        if self._cache:
            self._cache.set(session)

        return session

    def new(self, session_id: str) -> Session:
        """
        Initialize a new, empty Session instance.

        :param session_id: Unique identifier for the session.
        :return: A new Session instance for the provided identifier.
        """
        self._log.debug("Creating new session with ID %s", session_id)
        session = Session(session_id)

        # Update cache
        if self._cache:
            self._cache.set(session)

        return session

    def store(self, session: Session) -> None:
        """
        Persist all session key/value pairs as individual Cosmos DB entities.

        :param session: The session to persist.
        """
        for key, value in session.get_all(volatile=False):
            payload = self._serde.dumps(value)
            self._driver.put(session.id, key, payload)

        # Update cache
        if self._cache:
            self._cache.set(session)

    def clear(self) -> None:
        """
        Clear all entities from the configured Cosmos DB table.

        This is a destructive operation intended for development/testing only.
        """
        self._driver.scan_and_clear_all()

        # Clear cache
        if self._cache:
            self._cache.clear()
