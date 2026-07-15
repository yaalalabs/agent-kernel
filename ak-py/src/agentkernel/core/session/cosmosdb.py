import logging

from ..base import Session
from ..config import AKConfig
from ..util.driver.cosmosdb import CosmosDBDriver
from .base import SessionCache, SessionStore
from .serde import BinarySerde


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
        cfg = AKConfig.get().session.cosmosdb
        if cfg is None or not cfg.connection_string:
            raise ValueError("AKConfig.session.cosmosdb.connection_string must be set to use CosmosDBSessionStore")
        if not cfg.table_name:
            raise ValueError("AKConfig.session.cosmosdb.table_name must be set to use CosmosDBSessionStore")
        self._driver = CosmosDBDriver(connection_string=cfg.connection_string, table_name=cfg.table_name, ttl=cfg.ttl)
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
        keys = self._driver.query_sort_keys(session_id)

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
        self._driver.clear_all()

        # Clear cache
        if self._cache:
            self._cache.clear()
