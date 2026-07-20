import logging

from ..base import Session
from ..config import AKConfig
from ..util.driver.valkey import ValkeyDriver
from .base import SessionCache, SessionStore
from .serde import BinarySerde


class ValkeySessionStore(SessionStore):
    """
    ValkeySessionStore class provides a valkey-based implementation of the SessionStore interface.
    """

    def __init__(self, cache: SessionCache = None):
        """
        Initializes a ValkeySessionStore instance.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.valkey")
        self._serde = BinarySerde()
        cfg = AKConfig.get().session.valkey
        if cfg is None:
            raise ValueError("session.valkey config block is required when session.type is 'valkey'")
        self._driver = ValkeyDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        self._log.debug(f"Loading valkey session with ID {session_id}")
        if self._cache:
            session = self._cache.get(session_id)
            if session:
                self._log.debug(f"Session {session_id} found in cache")
                return session
        key = self._driver.key(session_id)
        if self._driver.exists(key):
            session = Session(session_id)
            for field in self._driver.hkeys(key):
                if field == "__init__":
                    continue
                value = self._driver.hget(key, field)
                session.set(field, self._serde.loads(value))
            if self._cache:
                self._cache.set(session)
            return session
        else:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning(f"Session {session_id} not found, creating new session")
            return self.new(session_id)

    def new(self, session_id: str) -> Session:
        """
        Initialize a session for a given session id.
        :param session_id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        self._log.debug(f"Creating new session with ID {session_id} ")
        key = self._driver.key(session_id)
        # Create a minimal hash so the key exists and TTL can apply
        self._driver.hset(key, "__init__", self._serde.dumps(True))
        if self._driver.ttl:
            self._driver.expire(key)
        session = Session(session_id)
        if self._cache:
            self._cache.set(session)
        return session

    def clear(self) -> None:
        """
        Clears all stored sessions for this store's prefix.
        """
        self._driver.clear_prefix()
        if self._cache:
            self._cache.clear()

    def store(self, session: Session) -> None:
        """
        Stores a session or updates it if it already exists in the storage.
        :param session: The session to store.
        """
        for key, value in session.get_all(volatile=False):
            self._driver.hset(self._driver.key(session.id), key, self._serde.dumps(value))
        if self._driver.ttl:
            self._driver.expire(self._driver.key(session.id))
        if self._cache:
            self._cache.set(session)
