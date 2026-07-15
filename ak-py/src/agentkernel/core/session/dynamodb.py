import logging

from boto3.dynamodb.types import Binary

from ..base import Session
from ..config import AKConfig
from ..util.driver.dynamodb import DynamoDBDriver
from .base import SessionCache, SessionStore
from .serde import BinarySerde


class DynamoDBSessionStore(SessionStore):
    """
    DynamoDB-backed implementation of SessionStore.
    Table schema uses:
      - session_id: partition key (string)
      - key: sort key (string)
      - value: binary attribute (serialized using BinarySerde)
    """

    def __init__(self, cache: SessionCache = None):
        """
        Initialize the DynamoDB-backed SessionStore.

        Prepares the serializer and a DynamoDB driver that encapsulates access
        to the configured table.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.dynamodb")
        self._serde = BinarySerde()
        cfg = AKConfig.get().session.dynamodb
        if cfg is None or not cfg.table_name:
            raise ValueError("AKConfig.session.dynamodb.table_name must be set to use DynamoDBSessionStore")
        self._driver = DynamoDBDriver(table_name=cfg.table_name, partition_key="session_id", sort_key="key", ttl=cfg.ttl)
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Load a session by its unique identifier.

        Reads all keys for the session from DynamoDB and reconstructs a Session
        by deserializing each value via BinarySerde.

        :param session_id: Unique identifier for the session.
        :param strict: If True, raises a KeyError if the session is not found.
        :return: The populated Session, or a new Session if not found and strict is False.
        """
        self._log.debug(f"Loading dynamodb session with ID {session_id}")
        if self._cache:
            session = self._cache.get(session_id)
            if session:
                self._log.debug(f"Session {session_id} found in cache")
                return session
        keys = self._driver.query_sort_keys(session_id)
        if not keys:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning("Session %s not found, creating new session", session_id)
            return self.new(session_id)

        session = Session(session_id)
        for k in keys:
            item = self._driver.get(session_id, k)
            payload = self._unwrap(item)
            if payload is None:
                continue
            session.set(k, self._serde.loads(payload))
        if self._cache:
            self._cache.set(session)
        return session

    @staticmethod
    def _unwrap(item) -> bytes:
        """Extract the raw bytes payload from an item's value attribute, unwrapping
        boto3 Binary objects."""
        if not item:
            return None
        val = item.get("value")
        # boto3 Binary objects expose .value or are bytes-like
        if hasattr(val, "value"):
            return val.value
        return val

    def new(self, session_id: str) -> Session:
        """
        Initialize a new, empty Session instance

        :param session_id: Unique identifier for the session.
        :return: A new Session instance for the provided identifier.
        """
        self._log.debug("Creating new session with ID %s", session_id)
        session = Session(session_id)
        if self._cache:
            self._cache.set(session)
        return session

    def store(self, session: Session) -> None:
        """
        Persist all session key/value pairs as individual DynamoDB items.
        :param session: The session to persist.
        """
        for key, value in session.get_all(volatile=False):
            payload = self._serde.dumps(value)
            self._driver.put({"session_id": session.id, "key": key, "value": Binary(payload)})
        if self._cache:
            self._cache.set(session)

    def clear(self) -> None:
        """
        Clear all items from the configured DynamoDB table.

        This is a destructive operation intended for development/testing only.
        """
        self._driver.clear_all()
        if self._cache:
            self._cache.clear()
