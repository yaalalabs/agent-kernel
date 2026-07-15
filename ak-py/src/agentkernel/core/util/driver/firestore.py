"""Shared Google Firestore connection driver. Requires the ``gcp`` extra."""

import datetime
import logging
import threading
from typing import Optional

from .base import connect_with_retries

# Fields that are not data keys and must be excluded when reading back keys
_RESERVED_FIELDS = {"expiry_time"}


class FirestoreDriver:
    """
    Firestore connection driver.

    Owns the connection lifecycle (lazy client, with retry) and a per-document
    field surface: one document per ID, with each key stored as a field (bytes)
    on that document. ``collection`` is a public part of the driver contract for
    consumers whose data operations exceed the generic surface (e.g.
    subcollections).
    """

    def __init__(
        self,
        collection_name: str,
        project_id: Optional[str] = None,
        database_id: Optional[str] = None,
        ttl: int = 0,
    ):
        """
        Initialize the driver. Constructor arguments are trusted; config reading and
        validation happen in the stores.

        :param collection_name: Firestore collection name.
        :param project_id: GCP project ID; if None, inferred from Application Default
            Credentials.
        :param database_id: Firestore database ID; if None, the '(default)' database.
        :param ttl: TTL in seconds; when > 0, :meth:`put` sets an ``expiry_time``
            datetime field a Firestore TTL policy can use (0 disables).
        """
        self._collection_name = collection_name
        self._project_id = project_id
        self._database_id = database_id
        self._ttl = int(ttl) if ttl else 0
        self._client = None
        self._lock = threading.Lock()
        self._log = logging.getLogger("ak.core.util.driver.firestore")

    @property
    def collection(self):
        """
        Returns the Firestore CollectionReference, connecting lazily if needed.

        :return: The Firestore CollectionReference for the configured collection.
        """
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._connect()
        return self._client.collection(self._collection_name)

    def _connect(self) -> None:
        """Connects to Firestore, with retries."""

        def connect():
            from google.cloud import firestore

            kwargs: dict = {}
            if self._project_id:
                kwargs["project"] = self._project_id
            if self._database_id is not None:
                kwargs["database"] = self._database_id
            client = firestore.Client(**kwargs)
            self._log.debug("Connected to Firestore collection %s", self._collection_name)
            return client

        self._client = connect_with_retries(connect, Exception, self._log)

    def put(self, session_id: str, key: str, value: bytes) -> None:
        """
        Write a single key/value pair into the document using merge so other keys
        on the same document are not overwritten.

        When TTL is configured (> 0), sets an ``expiry_time`` datetime field that
        a Firestore TTL policy can use to auto-delete expired documents.

        :param session_id: The document ID.
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
        Read a single field value from the document.

        :param session_id: The document ID.
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
        Return all data-key field names stored on the document, excluding reserved
        metadata fields such as ``expiry_time``.

        :param session_id: The document ID.
        :return: List of key names stored on the document.
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
