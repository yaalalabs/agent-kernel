import threading
import time
from typing import Dict, Optional

from .base import StatefulEdgeAdapter


class StatefulEdgeRegistry:
    """A runtime registry for active, stateful edge connections (spec #524).

    Unlike the IntegrationAdapterFactory which constructs stateless webhook adapters on demand,
    stateful edges (like LiveKit or Twilio) are constructed and managed by a GatewayRunner.
    The runner registers the live connection here so that the Response Handler can route
    replies back to the same long-lived connection.
    """

    ENDED_TTL_SECONDS: float = 60.0
    """How long an unregistered session counts as recently ended."""

    _cache: Dict[str, StatefulEdgeAdapter] = {}
    _ended: Dict[str, float] = {}
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
            cls._ended.pop(key, None)

    @classmethod
    def unregister(cls, session_id: str, adapter: Optional[StatefulEdgeAdapter] = None) -> None:
        """Remove a live stateful edge adapter instance from the cache.

        Called when a stateful connection disconnects, preventing memory leaks. The session is recorded
        as recently ended (see :meth:`recently_ended`).

        :param session_id: The session id the edge was registered under.
        :param adapter: When given, the entry is removed only if it is this adapter, so a stopped edge
            cannot remove a newer one registered under the same id.
        """
        with cls._lock:
            current = cls._cache.get(session_id)
            if adapter is not None and current is not adapter:
                return
            cls._cache.pop(session_id, None)
            now = time.time()
            cls._prune_ended(now)
            cls._ended[session_id] = now

    @classmethod
    def recently_ended(cls, session_id: str) -> bool:
        """True for :attr:`ENDED_TTL_SECONDS` after the session's edge was unregistered."""
        with cls._lock:
            cls._prune_ended(time.time())
            return session_id in cls._ended

    @classmethod
    def _prune_ended(cls, now: float) -> None:
        """Drop expired marks; the caller holds the lock."""
        for key in [key for key, at in cls._ended.items() if now - at >= cls.ENDED_TTL_SECONDS]:
            del cls._ended[key]

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
            cls._ended.clear()
