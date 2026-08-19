"""
Client-library-agnostic implementation shared by the Redis and Valkey drivers.

This module must not import ``redis`` or ``valkey``: concrete subclasses supply
the client library via ``_from_url``, ``_error_class``, and ``_backend_name``.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Optional

from .base import BaseDriver


class _RedisLikeDriver(BaseDriver):
    """
    Shared connection lifecycle and generic command surface for Redis-compatible
    backends (the ``valkey`` client is a fork of ``redis-py`` with an identical API).

    The driver owns lazy connect (3 attempts, 2-second delay), a ping health-check
    with automatic reconnect on every ``client`` access, and TTL plumbing. Key
    schemas and serialization stay in the consuming stores. ``client`` is a public
    part of the driver contract for consumers whose data operations exceed the
    generic surface.
    """

    # subclasses set these
    _backend_name: str = "RedisLike"
    _error_class: type[BaseException] = Exception

    def __init__(self, url: str, prefix: str = "", ttl: int = 0, decode_responses: bool = False):
        """
        Initialize the driver. Constructor arguments are trusted; config reading and
        validation happen in the stores.

        :param url: Connection URL.
        :param prefix: Key prefix applied by :meth:`key` and prefix-scoped scans.
        :param ttl: TTL in seconds applied by :meth:`set` and :meth:`expire` (0 disables).
        :param decode_responses: Whether the client decodes responses to strings.
        """
        super().__init__(f"ak.core.util.driver.{self._backend_name.lower()}")
        self._url = url
        self._prefix = prefix
        self._ttl = int(ttl)
        self._decode_responses = decode_responses
        self._client = None

    @abstractmethod
    def _from_url(self, url: str, **kwargs):
        """Create a client from a URL using the concrete backend's library."""

    @property
    def client(self):
        """
        Returns the client instance, connecting lazily on first use.

        An established client is pinged on every access and reconnected if the ping
        fails with the backend's error class; a ping failure outside that scope
        propagates to the caller.
        """
        client = self._client
        if client is None:
            self._ensure_connected(expected=None)
        else:
            try:
                client.ping()
                self._log.debug("%s client is alive", self._backend_name)
            except self._error_class:
                self._log.warning("%s client is not alive, reconnecting", self._backend_name)
                self._ensure_connected(expected=client)
        return self._client

    @property
    def ttl(self) -> int:
        """Returns the configured TTL in seconds (0 = disabled)."""
        return self._ttl

    def _ensure_connected(self, expected) -> None:
        """
        Connect while holding the lock, re-verifying that ``self._client`` is still
        ``expected`` (``None`` on first use; the exact object whose ping failed on
        reconnect). If another thread already replaced it, skip — concurrent first
        use or concurrent failed pings produce exactly one connect.
        """
        with self._lock:
            if self._client is not expected:
                return
            self._connect()

    def _connect(self) -> None:
        """Connects using the configured URL, with retries on the backend's error class."""

        def connect():
            self._log.debug("Connecting to %s using URL %s", self._backend_name, self._url)
            client = self._from_url(self._url, decode_responses=self._decode_responses, socket_connect_timeout=5)
            client.ping()
            return client

        self._client = self._connect_with_retries(connect, self._error_class)

    def key(self, suffix: str) -> str:
        """
        Composes a full key from the configured prefix and the given suffix.

        :param suffix: The key suffix (the store's key schema).
        :return: ``f"{prefix}{suffix}"``.
        """
        return f"{self._prefix}{suffix}"

    # ------------------------------------------------------------------ strings
    def set(self, key: str, value: Any, nx: bool = False) -> bool:
        """
        SET a key, applying ``ex=ttl`` atomically when a TTL is configured.

        :param key: The key to set.
        :param value: The value to store.
        :param nx: When True, only set if the key does not exist (conditional create).
        :return: Whether the SET was applied.
        """
        self._log.debug(f"SET {key} nx={nx}")
        kwargs: dict = {}
        if self._ttl > 0:
            kwargs["ex"] = self._ttl
        if nx:
            kwargs["nx"] = True
        return bool(self.client.set(key, value, **kwargs))

    def get(self, key: str) -> Any:
        """
        GET a key's value (raw bytes unless ``decode_responses`` is set).

        :param key: The key to read.
        :return: The stored value, or None if the key does not exist.
        """
        self._log.debug(f"GET {key}")
        return self.client.get(key)

    def incr(self, key: str) -> int:
        """
        INCR a counter key, applying the configured TTL on the first increment.

        The TTL is applied when the counter is created (result == 1) so the whole counter
        expires a fixed time after it started, rather than being extended by every increment.

        :param key: The counter key.
        :return: The counter's new value.
        """
        self._log.debug(f"INCR {key}")
        value = int(self.client.incr(key))
        if value == 1:
            self.expire(key)
        return value

    def delete(self, *keys: str) -> None:
        """
        DEL one or more keys.

        :param keys: The keys to delete.
        """
        self._log.debug(f"DEL {keys}")
        self.client.delete(*keys)

    def exists(self, key: str) -> bool:
        """
        Checks whether a key exists. Errors propagate to the caller.

        :param key: The key to check.
        :return: True if the key exists, False otherwise.
        """
        return bool(self.client.exists(key))

    # ------------------------------------------------------------------- hashes
    def hset(self, key: str, field: str, value: Any) -> None:
        """
        Sets a field in the hash stored at the given key.

        :param key: The hash key.
        :param field: The field to set.
        :param value: The value to set for the field.
        """
        self._log.debug(f"HSET {key} field={field}")
        self.client.hset(name=key, key=field, value=value)

    def hget(self, key: str, field: str) -> Optional[bytes]:
        """
        Retrieves a field from the hash stored at the given key.

        :param key: The hash key.
        :param field: The field to retrieve.
        :return: The value of the field, or None if the field does not exist.
        """
        self._log.debug(f"HGET {key} field={field}")
        return self.client.hget(name=key, key=field)

    def hkeys(self, key: str) -> list[str]:
        """
        Retrieves all field names in the hash stored at the given key.

        :param key: The hash key.
        :return: A list of field names, decoded to strings.
        """
        self._log.debug(f"HKEYS {key}")
        raw = self.client.hkeys(name=key)
        return [k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k for k in raw]

    # -------------------------------------------------------------------- lists
    def rpush(self, key: str, value: Any) -> None:
        """
        Appends a value to the list stored at the given key.

        :param key: The list key.
        :param value: The value to append.
        """
        self._log.debug(f"RPUSH {key}")
        self.client.rpush(key, value)

    def lpop(self, key: str) -> Optional[str]:
        """
        Removes and returns the first element of the list, decoded to a string.

        :param key: The list key.
        :return: The popped element, or None if the list is empty.
        """
        self._log.debug(f"LPOP {key}")
        item = self.client.lpop(key)
        if item is None:
            return None
        return item.decode() if isinstance(item, (bytes, bytearray)) else item

    def llen(self, key: str) -> int:
        """
        Returns the length of the list stored at the given key.

        :param key: The list key.
        :return: The number of elements in the list.
        """
        return self.client.llen(key)

    def lrem(self, key: str, count: int, value: Any) -> None:
        """
        Removes occurrences of a value from the list stored at the given key.

        :param key: The list key.
        :param count: The number of occurrences to remove (0 = all).
        :param value: The value to remove.
        """
        self._log.debug(f"LREM {key} count={count}")
        self.client.lrem(key, count, value)

    def lrange(self, key: str, start: int, end: int) -> list:
        """
        Returns a range of elements from the list stored at the given key, raw
        (consumers decode/deserialize themselves).

        :param key: The list key.
        :param start: Zero-based start index.
        :param end: Zero-based end index (inclusive).
        :return: The list elements in the range.
        """
        self._log.debug(f"LRANGE {key} {start} {end}")
        return self.client.lrange(key, start, end)

    # --------------------------------------------------------------------- sets
    def sadd(self, key: str, member: Any) -> None:
        """
        Adds a member to the set stored at the given key.

        :param key: The set key.
        :param member: The member to add.
        """
        self._log.debug(f"SADD {key}")
        self.client.sadd(key, member)

    def srem(self, key: str, member: Any) -> None:
        """
        Removes a member from the set stored at the given key. Removing an absent
        member is not an error.

        :param key: The set key.
        :param member: The member to remove.
        """
        self._log.debug(f"SREM {key}")
        self.client.srem(key, member)

    def smembers(self, key: str) -> set[str]:
        """
        Returns all members of the set stored at the given key, decoded to strings.

        :param key: The set key.
        :return: The set members.
        """
        self._log.debug(f"SMEMBERS {key}")
        return {m.decode() if isinstance(m, (bytes, bytearray)) else m for m in self.client.smembers(key)}

    # ------------------------------------------------------------ key iteration
    def scan_keys(self, match_suffix: str) -> list[str]:
        """
        Scans for keys matching the configured prefix plus the given suffix pattern.

        :param match_suffix: Pattern appended to the prefix (e.g. ``"*:meta"``).
        :return: Matching key names, decoded to strings.
        """
        pattern = f"{self._prefix}{match_suffix}"
        self._log.debug(f"SCAN match={pattern}")
        return [k.decode() if isinstance(k, (bytes, bytearray)) else k for k in self.client.scan_iter(match=pattern)]

    # -------------------------------------------------------------- maintenance
    def expire(self, key: str) -> None:
        """
        Applies the configured TTL to the given key. No-op when ``ttl <= 0`` — a
        raw ``EXPIRE key 0`` would delete the key.

        :param key: The key to set the TTL for.
        """
        if self._ttl > 0:
            self._log.debug(f"EXPIRE {key} {self._ttl}")
            self.client.expire(name=key, time=self._ttl)

    def clear_prefix(self) -> None:
        """Deletes all keys matching the configured prefix pattern."""
        pattern = f"{self._prefix}*"
        keys = list(self.client.scan_iter(match=pattern, count=1000))
        if keys:
            self.client.delete(*keys)
