import logging
import os
import pickle
import time
import traceback
from typing import Any, Optional

import redis

from .base import SessionStore
from ..base import Session


class RedisDriver:
    """
    RedisUtil provides Redis connection and helper methods for namespaced key/value operations.
    """
    _redis_client = None

    def __init__(
            self,
            ssl: bool = False,
            url: str | None = None,
            host: str | None = None,
            port: int | None = None,
            prefix: str | None = None,
            ttl_seconds: int | None = None,
    ):
        self._log = logging.getLogger("ak.core.sessions.redis.util")
        self._prefix = prefix
        self._url = url or os.getenv("AK_REDIS_URL")
        self._host = host or os.getenv("AK_REDIS_HOST", "localhost")
        self._port = int(port or os.getenv("AK_REDIS_PORT", "6379"))
        self._ssl = ssl or (os.getenv("AK_REDIS_SSL", "false").lower() == "true")
        self._prefix = prefix or os.getenv("AK_REDIS_PREFIX", "ak:sessions:")
        self._ttl = ttl_seconds or int(os.getenv("AK_SESSION_TTL_SECONDS", "604800"))

    @property
    def client(self):
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
        return self._ttl

    def _connect(self):
        retries = 3
        for attempt in range(retries):
            try:
                if self._url:
                    self._log.debug(f"Connecting to Redis using URL {self._url}")
                    client = redis.from_url(self._url, ssl=self._ssl)
                else:
                    self._log.debug(f"Connecting to Redis at {self._host}:{self._port}")
                    client = redis.Redis(
                        host=self._host,
                        port=self._port,
                        ssl=self._ssl,
                        decode_responses=False,
                        socket_connect_timeout=5
                    )
                client.ping()
                self._redis_client = client
            except redis.RedisError as e:
                self._log.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == 3:
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
        self._log.debug(f"HSET {key} field={field}")
        self.client.hset(name=key, key=field, value=value)

    def hget(self, key: str, field: str) -> Optional[bytes]:
        self._log.debug(f"HGET {key} field={field}")
        return self.client.hget(name=key, key=field)

    def expire(self, key: str) -> None:
        self._log.debug(f"EXPIRE {key} {self._ttl}")
        self.client.expire(name=key, time=self._ttl)

    def exists(self, key: str) -> bool:
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

    def __init__(
            self,
            driver: RedisDriver
    ):
        """
        Initializes a RedisSessionStore instance.
        :param driver: Redis Driver instance
        """
        self._log = logging.getLogger("ak.core.sessions.redis")
        self._serde = RedisSessionSerde()
        self._driver = driver

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        key = self._driver.key(session_id)
        if not self._driver.exists(key):
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning(f"Session {session_id} not found, creating new session")
            return self.new(session_id)
        # Return Redis-backed session
        return RedisSession(session_id, self._driver)

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
        return RedisSession(session_id, self._driver)

    def clear(self) -> None:
        """
        Clears all stored sessions for this store's prefix.
        """
        self._driver.clear_prefix()

    def store(self, session: Session) -> None:
        pass


class RedisSessionSerde:
    """
    RedisSessionSerde provides serialization and deserialization of Session objects for Redis
    storage using a JSON representation.
    """
    _log = logging.getLogger("ak.core.sessions.redisserde")

    # Binary headers to distinguish formats

    @classmethod
    def dumps(cls, obj: Any) -> bytes:
        """
        Serialize a value to JSON, falling back to repr for non-serializable objects.
        :param obj: The value to serialize.
        :return: The serialized value as a JSON string.
        """
        cls._log.debug(f"dumped: {obj}")
        return pickle.dumps(obj)

    @classmethod
    def loads(cls, payload: bytes) -> Any:
        """
        Deserialize a JSON string/bytes back into a Python object; returns None if missing.
        :param payload: The JSON string or bytes to deserialize.
        :return: The deserialized value.
        """
        cls._log.debug(f"loads: {type(payload)}")
        if payload is None:
            return None
        loaded = pickle.loads(payload)
        cls._log.debug(f"loaded: {loaded}")
        return loaded


class RedisSession(Session):
    """
    Redis-backed Session that persists each field as a Redis hash field.

    Uses a RedisUtil helper for namespaced access. Values are JSON-serialized and
    deserialized using RedisSessionSerde.
    """

    def __init__(self, id: str, driver: "RedisDriver"):
        super().__init__(id)
        self._log = logging.getLogger("ak.core.sessions.redissession")
        self._driver = driver
        self._key = self._driver.key(id)

    def get(self, key: str) -> Any:
        raw = self._driver.hget(self._key, key)
        return RedisSessionSerde.loads(raw)

    def set(self, key: str, value: Any) -> Any:
        payload = RedisSessionSerde.dumps(value)
        self._driver.hset(self._key, key, payload)
        if self._driver.ttl:
            self._driver.expire(self._key)
        return value
