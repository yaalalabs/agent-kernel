import threading
from typing import Dict, Optional

from .base import StatefulEdgeAdapter


class StatefulEdgeRegistry:
    """A runtime registry for active, stateful edge connections (spec #524).

    Unlike the IntegrationAdapterFactory which constructs stateless webhook adapters on demand,
    stateful edges (like LiveKit or Twilio) are constructed and managed by a GatewayRunner.
    The runner registers the live connection here so that the Response Handler can route
    replies back to the same long-lived connection.
    """

    _cache: Dict[str, StatefulEdgeAdapter] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, adapter: StatefulEdgeAdapter, session_id: Optional[str] = None) -> None:
        """Register a live stateful edge adapter instance.

        :param adapter: The adapter instance.
        :param session_id: Optional session id to register a unique stateful connection.
        """
        # We index by session_id if provided; otherwise fallback to the integration name.
        # In a real deployed environment, session_id is always present for stateful connections.
        key = session_id if session_id else adapter.name
        with cls._lock:
            cls._cache[key] = adapter

    @classmethod
    def unregister(cls, session_id: str) -> None:
        """Remove a live stateful edge adapter instance from the cache.

        Called when a stateful connection disconnects, preventing memory leaks.
        """
        with cls._lock:
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
