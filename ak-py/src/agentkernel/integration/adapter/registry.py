import threading

from .base import StatefulEdgeAdapter


class StatefulEdgeRegistry:
    """Live stateful edges by session id, so the Response Handler routes replies back to the same connection (spec #524)."""

    _cache: dict[str, StatefulEdgeAdapter] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, adapter: StatefulEdgeAdapter, session_id: str | None = None) -> None:
        """Register a live stateful edge adapter instance.

        :param adapter: The adapter instance.
        :param session_id: Optional session id to register a unique stateful connection.
        """
        key = session_id if session_id else adapter.name
        with cls._lock:
            cls._cache[key] = adapter

    @classmethod
    def unregister(cls, session_id: str, adapter: StatefulEdgeAdapter | None = None) -> None:
        """Remove a live stateful edge adapter instance.

        :param session_id: The session id the edge was registered under.
        :param adapter: When given, removed only if it is still this adapter, so a stopped edge cannot remove a newer one.
        """
        with cls._lock:
            current = cls._cache.get(session_id)
            if adapter is not None and current is not adapter:
                return
            cls._cache.pop(session_id, None)

    @classmethod
    def get(cls, session_id: str) -> StatefulEdgeAdapter | None:
        """Retrieve a live stateful edge adapter instance by session_id."""
        with cls._lock:
            return cls._cache.get(session_id)

    @classmethod
    def reset(cls) -> None:
        """Drop the instance cache. For tests."""
        with cls._lock:
            cls._cache.clear()
