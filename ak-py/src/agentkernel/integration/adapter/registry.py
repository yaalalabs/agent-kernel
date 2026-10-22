import threading
from typing import Dict, Optional

from .base import StatefulEdgeAdapter


class StatefulEdgeRegistry:
    """A runtime registry of live stateful edge connections, so the Response Handler can route replies back to them."""

    _cache: Dict[str, StatefulEdgeAdapter] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, adapter: StatefulEdgeAdapter, session_id: Optional[str] = None) -> None:
        """Register a live stateful edge adapter instance, keyed by ``session_id`` or else the adapter's name."""
        # We index by session_id if provided; otherwise fallback to the integration name.
        # In a real deployed environment, session_id is always present for stateful connections.
        key = session_id if session_id else adapter.name
        with cls._lock:
            cls._cache[key] = adapter

    @classmethod
    def unregister(cls, session_id: str, adapter: Optional[StatefulEdgeAdapter] = None) -> None:
        """Remove a live stateful edge adapter from the registry, only while it is ``adapter`` when one is given."""
        with cls._lock:
            if adapter is None or cls._cache.get(session_id) is adapter:
                cls._cache.pop(session_id, None)

    @classmethod
    def get(cls, session_id: str) -> Optional[StatefulEdgeAdapter]:
        """Retrieve a live stateful edge adapter instance by session_id."""
        with cls._lock:
            return cls._cache.get(session_id)

    @classmethod
    def reset(cls) -> None:
        """Drop the instance cache. For tests."""
        with cls._lock:
            cls._cache.clear()
