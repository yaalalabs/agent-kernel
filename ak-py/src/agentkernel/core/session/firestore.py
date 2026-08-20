import logging
from typing import Optional

from ..base import Session
from ..config import AKConfig
from ..util.driver.firestore import FirestoreDriver
from ..util.factory import AKConfigError
from .base import SessionCache, SessionStore, WSConnectionStore
from .serde import BinarySerde


class FirestoreSessionStore(SessionStore):
    """
    Firestore-backed implementation of SessionStore.

    Document schema (one document per session):
      - Document ID : session_id
      - Fields      : {key: bytes, ...}  (one field per session key)
      - Optional    : expiry_time (datetime) for Firestore TTL auto-deletion

    To enable automatic TTL deletion, configure a TTL policy on the Firestore
    collection pointing to the ``expiry_time`` field in the GCP Console or via
    ``gcloud firestore fields ttls update``.
    """

    def __init__(self, cache: Optional[SessionCache] = None) -> None:
        """
        Initialize the Firestore-backed SessionStore.

        :param cache: An optional SessionCache instance for in-memory caching of sessions.
        """
        self._log = logging.getLogger("ak.core.session.firestore")
        self._serde = BinarySerde()
        cfg = AKConfig.get().session.firestore
        if cfg is None or not cfg.collection_name:
            raise ValueError("AKConfig.session.firestore.collection_name must be set to use FirestoreSessionStore")
        self._driver = FirestoreDriver(
            collection_name=cfg.collection_name,
            project_id=cfg.project_id,
            database_id=cfg.database_id,
            ttl=cfg.ttl,
        )
        self._cache = cache

    def load(self, session_id: str, strict: bool = False) -> Session:
        """
        Load a session by its unique identifier.

        Reads all keys from the Firestore document and reconstructs a Session
        by deserializing each field via BinarySerde.

        :param session_id: Unique identifier for the session.
        :param strict: If True, raises a KeyError if the session is not found.
        :return: The populated Session, or a new Session if not found and strict is False.
        """
        self._log.debug("Loading Firestore session with ID %s", session_id)
        if self._cache:
            session = self._cache.get(session_id)
            if session:
                self._log.debug("Session %s found in cache", session_id)
                return session

        keys = self._driver.get_all_keys(session_id)
        if not keys:
            if strict:
                raise KeyError(f"Session {session_id} not found")
            self._log.warning("Session %s not found, creating new session", session_id)
            return self.new(session_id)

        session = Session(session_id)
        for k in keys:
            payload = self._driver.get(session_id, k)
            if payload is None:
                continue
            session.set(k, self._serde.loads(payload))
        if self._cache:
            self._cache.set(session)
        return session

    def new(self, session_id: str) -> Session:
        """
        Initialize a new, empty Session instance.

        :param session_id: Unique identifier for the session.
        :return: A new Session instance for the provided identifier.
        """
        self._log.debug("Creating new session with ID %s", session_id)
        session = Session(session_id)
        if self._cache:
            self._cache.set(session)
        return session

    def store(self, session: Session) -> None:
        """
        Persist all session key/value pairs as fields on the Firestore document.

        :param session: The session to persist.
        """
        for key, value in session.get_all(volatile=False):
            payload = self._serde.dumps(value)
            self._driver.put(session.id, key, payload)
        if self._cache:
            self._cache.set(session)

    def clear(self) -> None:
        """
        Delete all documents from the configured Firestore collection.

        This is a destructive operation intended for development/testing only.
        """
        self._driver.delete_all()
        if self._cache:
            self._cache.clear()

    def get_connection_store(self) -> "WSConnectionStore":
        """
        A WebSocket connection store is not yet provided on Firestore (spec #495 §9).

        Firestore can absolutely hold one (AWS's own WebSocket mode keeps connections in
        DynamoDB): implementing it here, over this store's driver, is how to add it. Until then,
        configure ``session.type`` as ``redis``, ``valkey`` or ``dynamodb``, or ``in_memory`` for a
        single-process deployment.

        :raises AKConfigError: Always.
        """
        raise AKConfigError(
            "session.type 'firestore' does not yet provide a WebSocket connection store: "
            "use redis, valkey or dynamodb sessions, or in_memory for single-process deployments"
        )
