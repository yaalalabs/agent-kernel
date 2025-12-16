import logging
import time
import traceback
from typing import Any, Optional

import redis

from ..base import Session
from ..config import AKConfig
from .base import SessionCache, SessionStore
from .serde import BinarySerde


class RedisDriver:
    """
    RedisUtil provides Redis connection and helper methods for namespaced key/value operations.
    """

    _redis_client = None

    def __init__(self):
        self._log = logging.getLogger("ak.core.session.redis.util")
        self._url = AKConfig.get().session.redis.url
        self._prefix = AKConfig.get().session.redis.prefix
        self._ttl = int(AKConfig.get().session.redis.ttl)

    @property
    def client(self):
        """
        Returns the Redis client instance.
        """
        if self._redis_client is None:
            self._connect()
        else:
            try:
                self._redis_client.ping()
                self._log.debug("Redis client is alive")
            except redis.RedisError:
                self._log.warning("Redis client is not alive, reconnecting")
                self._connect()
            except Exception as e:
                self._log.error(f"Unexpected error while pinging Redis client: {e}")
                self._log.error(traceback.format_exc())
        return self._redis_client

    @property
    def ttl(self):
        """
        Returns the configured TTL for Redis keys.
        """
        return self._ttl

    def _connect(self):
        """
        Connects to Redis using the configured URL or host/port.
        """
        retries = 3
        for attempt in range(retries):
            try:
                self._log.debug(f"Connecting to Redis using URL {self._url}")
                client = redis.from_url(self._url, decode_responses=False, socket_connect_timeout=5)
                client.ping()
                self._redis_client = client
            except redis.RedisError as e:
                self._log.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    break
                time.sleep(2)

    def key(self, session_id: str) -> str:
        """
        Generates a Redis key for the given session ID using a configured prefix.
        :param session_id: The session ID to generate a key for.
        :return: The generated key.
        """
        return f"{self._prefix}{session_id}"

    def hset(self, key: str, field: str, value: Any) -> None:
        """
        Sets a field in the Redis hash associated with the given key.
        :param key: The key to set the field for.
        :param field: The field to set.
        :param value: The value to set for the field.
        """
        self._log.debug(f"HSET {key} field={field}")
        self.client.hset(name=key, key=field, value=value)

    def hget(self, key: str, field: str) -> Optional[bytes]:
        """
        Retrieves a field from the Redis hash associated with the given key.
        :param key: The key to retrieve the field for.
        :param field: The field to retrieve.
        :return: The value of the field, or None if the field does not exist.
        """
        self._log.debug(f"HGET {key} field={field}")
        return self.client.hget(name=key, key=field)

    def expire(self, key: str) -> None:
        """
        Sets the TTL for the Redis hash associated with the given key.
        :param key: The key to set the TTL for.
        """
        self._log.debug(f"EXPIRE {key} {self._ttl}")
        self.client.expire(name=key, time=self._ttl)

    def hkeys(self, key: str) -> list[str]:
        """
        Retrieves all keys in the Redis hash associated with the given key.
        :param key: The key to retrieve the keys for.
        :return: A list of keys in the hash.
        """
        self._log.debug(f"HKEYS {key}")
        raw = self.client.hkeys(name=key)
        return [k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k for k in raw]

    def exists(self, key: str) -> bool:
        """
        Checks if a Redis key exists.
        :param key: The key to check.
        :return: True if the key exists, False otherwise.
        """
        try:
            return bool(self.client.exists(key))
        except redis.RedisError:
            return False

    def clear_prefix(self) -> None:
        """
        Clears all keys matching the configured prefix pattern.
        """
        pattern = f"{self._prefix}*"
        keys = list(self.client.scan_iter(match=pattern, count=1000))
        if keys:
            self.client.delete(*keys)


class RedisSessionStore(SessionStore):
    """
    RedisSessionStore class provides a redis-based implementation of the SessionStore interface.
    """

    def __init__(self, cache: SessionCache = None):
        """
        Initializes a RedisSessionStore instance.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.redis")
        self._serde = BinarySerde()
        self._driver = RedisDriver()
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        self._log.debug(f"Loading redis session with ID {session_id}")
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
        for key in session.get_all_keys():
            if key == Session.VOLATILE_CACHE_KEY:  # Do not store volatile cache
                continue
            value = session.get(key)
            self._driver.hset(self._driver.key(session.id), key, self._serde.dumps(value))
        if self._driver.ttl:
            self._driver.expire(self._driver.key(session.id))
        if self._cache:
            self._cache.set(session)
