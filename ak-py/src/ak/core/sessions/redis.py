import logging
import os
import pickle
import time
import traceback
from typing import Any, Optional

import redis

from .base import SessionStore
from ..base import Session


class RedisSessionStore(SessionStore):
    """
    RedisSessionStore class provides a redis-based implementation of the SessionStore interface.
    """

    def __init__(
            self,
            ssl: bool = False,
            url: str | None = None,
            host: str | None = None,
            port: int | None = None,
            prefix: str | None = None,
            ttl_seconds: int | None = None,
    ):
        """
        Initializes a RedisSessionStore instance.
        :param ssl: Whether to use SSL for Redis connection
        :param url: Redis connection URL (takes precedence over host/port if provided)
        :param host: Redis server hostname
        :param port: Redis server port
        :param prefix: Key prefix for session storage
        :param ttl_seconds: Time-to-live in seconds for stored sessions
        """
        self._log = logging.getLogger("ak.core.sessions.redis")
        self._serde = RedisSessionSerde()
        self._util = RedisUtil(
            ssl=ssl,
            url=url,
            host=host,
            port=port,
            prefix=prefix,
        )
        self._ttl = ttl_seconds

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        key = self._util.key(session_id)
        if not self._util.exists(key):
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning(f"Session {session_id} not found, creating new session")
            return self.new(session_id)
        # Return Redis-backed session
        return RedisSession(session_id, self._util, ttl_seconds=self._ttl)

    def new(self, session_id: str) -> Session:
        """
        Initialize a session for a given session id.
        :param session_id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        self._log.debug(f"Creating new session with ID {session_id} ")
        key = self._util.key(session_id)
        # Create a minimal hash so the key exists and TTL can apply
        self._util.hset(key, "__init__", self._serde.dumps(True))
        if self._ttl:
            self._util.expire(key, self._ttl)
        return RedisSession(session_id, self._util, ttl_seconds=self._ttl)

    def clear(self) -> None:
        """
        Clears all stored sessions for this store's prefix.
        """
        self._util.clear_prefix()

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
        if not isinstance(obj, bool):
            cls._log.debug(f"dumped: {obj._items}")
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
        cls._log.debug(f"loaded: {loaded._items}")
        return loaded


class RedisSession(Session):
    """
    Redis-backed Session that persists each field as a Redis hash field.

    Uses a RedisUtil helper for namespaced access. Values are JSON-serialized and
    deserialized using RedisSessionSerde.
    """

    def __init__(self, id: str, util: "RedisUtil", ttl_seconds: Optional[int] = None):
        super().__init__(id)
        self._log = logging.getLogger("ak.core.sessions.redissession")
        self._util = util
        self._ttl = ttl_seconds
        self._key = self._util.key(id)

    def get(self, key: str) -> Any:
        raw = self._util.hget(self._key, key)
        return RedisSessionSerde.loads(raw)

    def set(self, key: str, value: Any) -> Any:
        payload = RedisSessionSerde.dumps(value)
        self._util.hset(self._key, key, payload)
        if self._ttl:
            self._util.expire(self._key, self._ttl)
        return value


class RedisUtil:
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
    ):
        self._log = logging.getLogger("ak.core.sessions.redis.util")
        self._prefix = prefix
        self._url = url or os.getenv("AK_REDIS_URL")
        self._host = host or os.getenv("AK_REDIS_HOST", "localhost")
        self._port = int(port or os.getenv("AK_REDIS_PORT", "6379"))
        self._ssl = ssl or (os.getenv("AK_REDIS_SSL", "false").lower() == "true")
        self._prefix = prefix or os.getenv("AK_REDIS_PREFIX", "ak:sessions:")

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

    def hset(self, key: str, field: str, value: str) -> None:
        self._log.debug(f"HSET {key} field={field}")
        self.client.hset(name=key, key=field, value=value)

    def hget(self, key: str, field: str) -> Optional[bytes]:
        self._log.debug(f"HGET {key} field={field}")
        return self.client.hget(name=key, key=field)

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._log.debug(f"EXPIRE {key} {ttl_seconds}")
        self.client.expire(name=key, time=ttl_seconds)

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
