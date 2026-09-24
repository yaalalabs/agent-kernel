"""SecretCache — the TTL'd process cache between the environment and the provider."""

import time
from threading import Lock
from typing import Optional

from ..core.util.factory import AKConfigError


class SecretCache:
    """TTL'd key -> value store holding provider hits only.

    Keyed by the same environment-variable-style key the caller passed, so a cache entry, a provider
    lookup and an environment variable all name one thing. Nothing here transforms the key.

    Owns the cache write lock: held only while writing, evicting or clearing entries. Reads take no
    lock — each entry is one immutable (value, expires_at) tuple swapped in by a single dict
    assignment, so a reader sees either the old entry or the new one, never a torn one.
    """

    def __init__(self, ttl: int) -> None:
        """:raises AKConfigError: If ttl is negative."""
        if ttl < 0:
            raise AKConfigError(f"secret.cache_ttl must be >= 0 (0 disables caching), got {ttl}")
        self._ttl = ttl
        self._entries: dict[str, tuple[str, float]] = {}  # key -> (value, expires_at monotonic)
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, key: str) -> Optional[str]:
        """Return the cached value, or None when absent or expired. Lock-free read; an expired entry
        is evicted under the write lock."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() < expires_at:
            return value
        with self._lock:
            # Evict only the expired tuple this read saw, never a fresh one a concurrent set stored.
            if self._entries.get(key) is entry:
                del self._entries[key]
        return None

    def set(self, key: str, value: str) -> None:
        """Store a provider hit under the write lock. A no-op when caching is disabled (ttl == 0)."""
        if not self.enabled:
            return
        entry = (value, time.monotonic() + self._ttl)
        with self._lock:
            self._entries[key] = entry

    def invalidate(self, key: str) -> None:
        """Drop one entry under the write lock. Never raises for an unknown key."""
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        """Drop every entry under the write lock."""
        with self._lock:
            self._entries.clear()
