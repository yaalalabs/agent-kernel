import logging
import threading
from typing import Dict, List, Optional

from ..base import Session
from .base import SessionStore, WSConnectionStore


class InMemoryWSConnectionStore(WSConnectionStore):
    """Process-local connection store: single-process topologies only.

    State is class-level (like the in-memory transport's queues) so every component asking for
    the connection store sees the same connections, however many SessionStore instances were
    built along the way. No TTL: connections die with the process, and disconnect/stale-push
    cleanup handles the rest.
    """

    _lock = threading.Lock()
    _endpoints: Dict[str, Dict[str, str]] = {}  # user_id -> {connection_id: endpoint}
    _users: Dict[str, str] = {}  # connection_id -> user_id

    @property
    def shared(self) -> bool:
        return False

    def add_connection(self, user_id: str, connection_id: str, endpoint: str) -> None:
        with self._lock:
            self._endpoints.setdefault(user_id, {})[connection_id] = endpoint
            self._users[connection_id] = user_id

    def get_connections(self, user_id: str) -> List[str]:
        with self._lock:
            return list(self._endpoints.get(user_id, {}))

    def get_endpoints(self, user_id: str) -> Dict[str, str]:
        with self._lock:
            return dict(self._endpoints.get(user_id, {}))

    def get_endpoint(self, connection_id: str) -> Optional[str]:
        with self._lock:
            user_id = self._users.get(connection_id)
            if user_id is None:
                return None
            return self._endpoints.get(user_id, {}).get(connection_id)

    def get_user_id(self, connection_id: str) -> Optional[str]:
        with self._lock:
            return self._users.get(connection_id)

    def delete_connection(self, user_id: str, connection_id: str) -> None:
        with self._lock:
            connections = self._endpoints.get(user_id)
            if connections is not None:
                connections.pop(connection_id, None)
                if not connections:
                    del self._endpoints[user_id]
            self._users.pop(connection_id, None)

    @classmethod
    def reset(cls) -> None:
        """Drop every connection mapping (tests)."""
        with cls._lock:
            cls._endpoints.clear()
            cls._users.clear()


class InMemorySessionStore(SessionStore):
    """
    InMemorySessionStore class provides an in-memory implementation of the SessionStore interface.
    """

    def __init__(self):
        """
        Initializes an InMemorySessionStore instance.
        """
        self._sessions = {}
        self._log = logging.getLogger("ak.core.session.inmemory")

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Loads a session by its unique identifier.
        :param session_id: Unique identifier for the session.
        :param strict: If True, raises an exception if the session is not found.
        :return: The session associated with the identifier, or a new session if it does not exist.
        """
        self._log.debug(f"Loading in-memory session with ID {session_id}")
        session = self._sessions.get(session_id)
        if session is None:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            else:
                self._log.warning(f"Session {session_id} not found, creating new session")
                session = self.new(session_id)
        return session

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
        self._log.debug(f"Storing session with ID {session.id}")
        self._sessions[session.id] = session

    def clear(self) -> None:
        """
        Clears all stored sessions.
        """
        self._log.debug("Clearing all stored sessions")
        self._sessions.clear()

    def get_connection_store(self) -> WSConnectionStore:
        """
        The process-local WebSocket connection store (single-process topologies only; consumers
        that need cross-process visibility check ``WSConnectionStore.shared`` and fail fast).
        """
        return InMemoryWSConnectionStore()
