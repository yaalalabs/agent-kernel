"""The Redis/Valkey-family WebSocket connection store (spec #495 §9).

Client-library-agnostic, like the driver layer's ``redis_like``: the Redis and Valkey session
stores construct :class:`RedisLikeWSConnectionStore` with their own shared driver, and every
database operation is encapsulated here.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .base import WSConnectionStore


class RedisLikeWSConnectionStore(WSConnectionStore):
    """:class:`WSConnectionStore` over a shared Redis/Valkey driver (``core/util/driver/``).

    Constructed by the Redis and Valkey session stores with their own driver; all database
    operations are encapsulated here. Layout: one hash per user (``user:{user_id}``, field
    ``connection_id`` -> endpoint), so concurrent connects of the same user on different
    gateway pods never lose entries (field-atomic writes), plus one plain key per connection
    (``conn:{connection_id}`` -> ``{"user_id", "endpoint"}``) for reverse lookups.
    """

    _log = logging.getLogger("ak.core.session.ws_connection_store")

    def __init__(self, driver: Any):
        """:param driver: a ``_RedisLikeDriver`` carrying this store's key prefix and TTL."""
        self._driver = driver

    @staticmethod
    def _user_key(user_id: str) -> str:
        return f"user:{user_id}"

    @staticmethod
    def _connection_key(connection_id: str) -> str:
        return f"conn:{connection_id}"

    def add_connection(self, user_id: str, connection_id: str, endpoint: str) -> None:
        user_key = self._driver.key(self._user_key(user_id))
        self._driver.hset(user_key, connection_id, endpoint)
        self._driver.expire(user_key)  # HSET has no ex argument; refresh the hash's TTL explicitly
        self._driver.set(self._driver.key(self._connection_key(connection_id)), json.dumps({"user_id": user_id, "endpoint": endpoint}))

    def get_connections(self, user_id: str) -> List[str]:
        return list(self.get_endpoints(user_id))

    def get_endpoints(self, user_id: str) -> Dict[str, str]:
        return self._driver.hgetall(self._driver.key(self._user_key(user_id)))

    def get_endpoint(self, connection_id: str) -> Optional[str]:
        record = self._record(connection_id)
        return record["endpoint"] if record else None

    def get_user_id(self, connection_id: str) -> Optional[str]:
        record = self._record(connection_id)
        return record["user_id"] if record else None

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        self._driver.hdel(self._driver.key(self._user_key(user_id)), connection_id)
        self._driver.delete(self._driver.key(self._connection_key(connection_id)))

    def _record(self, connection_id: str) -> Optional[dict]:
        raw = self._driver.get(self._driver.key(self._connection_key(connection_id)))
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self._log.warning(f"Dropping unreadable connection record: connection_id={connection_id}")
            self._driver.delete(self._driver.key(self._connection_key(connection_id)))
            return None
