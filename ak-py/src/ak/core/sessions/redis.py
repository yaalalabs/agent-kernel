import json
import logging
import os
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

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist
        in storage.
        """
        key = self._util.key(session_id)
        raw = self._util.get(key)
        if raw is not None:
            try:
                return self._serde.deserialize(raw)
            except Exception as ex:
                self._log.error(f"Failed to deserialize session {session_id}: {ex}")
                if strict:
                    self._log.error(traceback.format_exc())
                    raise
        if strict:
            raise KeyError(f"Session {session_id} not found")
        self._log.warning(f"Session {session_id} not found, creating new session")
        session = Session(session_id)
        self.store(session)
        return session

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

    def new(self, session_id: str) -> Session:
        """
        Initialize a session for a given session id.
        :param session_id: Unique identifier for the session.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        self._log.debug(f"Creating new session with ID {session_id} ")
        session = Session(session_id)
        self.store(session)
        return session

    def store(self, session: Session) -> None:
        """
        Stores a session or updates it if it already exists in the storage.
        :param session: The session to store.
        """
        key = self._util.key(session.id)
        payload = self._serde.serialize(session)
        self._util.set(key, payload, ex=self._ttl)

    def clear(self) -> None:
        """
        Clears all stored sessions for this store's prefix.
        """
        self._util.clear_prefix()


class RedisSessionSerde:
    """
    RedisSessionSerde provides serialization and deserialization of Session objects for Redis
    storage using a JSON representation.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.core.sessions.redis.serde")

    @staticmethod
    def serialize(session: Session) -> str:
        """
        Serialize a Session to a JSON string.
        Non-JSON-serializable values in session data are converted to strings via repr().
        """

        def safe(obj: Any) -> Any:
            try:
                json.dumps(obj)
                return obj
            except Exception:
                return repr(obj)

        data = {
            "id": session.id,
            "data": {k: safe(v) for k, v in getattr(session, "_data", {}).items()},
        }
        return json.dumps(data)

    @staticmethod
    def deserialize(payload: Any) -> Session:
        """
        Deserialize a JSON string or bytes back into a Session instance.
        """
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        obj = json.loads(payload)
        s = Session(obj["id"])
        for k, v in obj.get("data", {}).items():
            s.set(k, v)
        return s


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
                    client = redis.from_url(self._url, ssl=self._ssl)
                else:
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
        return f"{self._prefix}{session_id}"

    def get(self, key: str) -> Optional[bytes]:
        return self.client.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        self.client.set(name=key, value=value, ex=ex)

    def delete(self, key: str) -> None:
        self.client.delete(key)

    def clear_prefix(self) -> None:
        pattern = f"{self._prefix}*"
        # Use scan_iter to avoid blocking
        keys = list(self.client.scan_iter(match=pattern, count=1000))
        if keys:
            self.client.delete(*keys)
