import datetime
import logging
import time
from typing import Optional

from ..base import Session
from ..config import AKConfig
from .base import SessionCache, SessionStore
from .serde import BinarySerde

# Fields that are not session keys and must be excluded when reading back keys
_RESERVED_FIELDS = {"expiry_time"}


class FirestoreDriver:
    """
    FirestoreDriver provides connection management and helpers for a simple
    per-document layout: one Firestore document per session_id, with each
    session key stored as a field (bytes) on that document.
    """

    _client = None

    def __init__(self) -> None:
        self._log = logging.getLogger("ak.core.session.firestore.driver")
        cfg = AKConfig.get().session.firestore
        if cfg is None or not cfg.collection_name:
            raise ValueError("AKConfig.session.firestore.collection_name must be set to use FirestoreSessionStore")
        self._collection_name = cfg.collection_name
        self._project_id = cfg.project_id
        self._ttl = cfg.ttl

    @property
    def collection(self):
        """
        Returns the Firestore CollectionReference, connecting lazily if needed.

        :return: The Firestore CollectionReference for the configured collection.
        """
        if self._client is None:
            self._connect()
        return self._client.collection(self._collection_name)

    def _connect(self) -> None:
        """
        Establish a connection to Firestore.

        Retries a few times with a small delay between attempts. Raises the last
        encountered exception if all attempts fail.
        """
        retries = 3
        delay = 2
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                from google.cloud import firestore

                kwargs: dict = {}
                if self._project_id:
                    kwargs["project"] = self._project_id
                self._client = firestore.Client(**kwargs)
                self._log.debug("Connected to Firestore collection %s", self._collection_name)
                return
            except Exception as e:
                last_err = e
                self._log.warning("Firestore connection attempt %s failed: %s", attempt + 1, e)
                if attempt < retries - 1:
                    time.sleep(delay)
        if last_err:
            raise last_err

    def put(self, session_id: str, key: str, value: bytes) -> None:
        """
        Write a single key/value pair into the session document using merge so
        other keys on the same document are not overwritten.

        When TTL is configured (> 0), sets an ``expiry_time`` datetime field that
        a Firestore TTL policy can use to auto-delete expired sessions.

        :param session_id: The session identifier (document ID).
        :param key: The field name within the document.
        :param value: The serialized value as bytes.
        """
        try:
            data: dict = {key: value}
            if self._ttl and self._ttl > 0:
                data["expiry_time"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self._ttl)
            self.collection.document(session_id).set(data, merge=True)
        except Exception as e:
            self._log.error("Failed to put item session_id=%s key=%s: %s", session_id, key, e)
            raise

    def get(self, session_id: str, key: str) -> Optional[bytes]:
        """
        Read a single field value from the session document.

        :param session_id: The session identifier (document ID).
        :param key: The field name to read.
        :return: The stored bytes value, or None if the document or field does not exist.
        """
        try:
            doc = self.collection.document(session_id).get()
            if not doc.exists:
                return None
            val = doc.to_dict().get(key)
            return bytes(val) if val is not None else None
        except Exception as e:
            self._log.error("Failed to get item session_id=%s key=%s: %s", session_id, key, e)
            raise

    def get_all_keys(self, session_id: str) -> list[str]:
        """
        Return all session-key field names stored on the document, excluding
        reserved metadata fields such as ``expiry_time``.

        :param session_id: The session identifier (document ID).
        :return: List of key names stored under the session.
        """
        try:
            doc = self.collection.document(session_id).get()
            if not doc.exists:
                return []
            return [k for k in doc.to_dict().keys() if k not in _RESERVED_FIELDS]
        except Exception as e:
            self._log.error("Failed to get keys for session_id=%s: %s", session_id, e)
            raise

    def delete_all(self) -> None:
        """
        Delete all documents in the collection.

        Intended for development/test parity with other backends' ``clear()``.
        Use with caution in shared environments.
        """
        try:
            batch_size = 500
            while True:
                docs = list(self.collection.limit(batch_size).stream())
                if not docs:
                    break
                for doc in docs:
                    doc.reference.delete()
        except Exception as e:
            self._log.error("Failed to clear Firestore collection %s: %s", self._collection_name, e)
            raise


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
        self._driver = FirestoreDriver()
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
