"""
Firestore-backed thread store.

Layout:
  - Metadata: one document per session_id in the configured collection, holding
    data (metadata JSON), user_id, group_id, updated_at.
  - Messages: a "messages" subcollection under each thread document, one document
    per message keyed by a sortable "seq", holding data (message JSON) and seq.

Appending a message adds a new subcollection document (atomic, append-only) and
blind-updates the parent document's updated_at, so concurrent appends never lose
or rewrite messages and the parent document never grows unbounded.
"""

import datetime
import logging
import time
import uuid
from typing import List, Optional, Tuple

from ....core.config import AKConfig
from ....core.util.driver.firestore import FirestoreDriver
from ..model import Thread, ThreadMessage, _utc_now
from .base import ThreadStore, paginate

_MESSAGES_SUBCOLLECTION = "messages"


def _new_seq() -> str:
    """Return a sortable, monotonic, unique message sequence key."""
    return f"{time.time_ns():020d}{uuid.uuid4().hex[:8]}"


class FirestoreThreadStore(ThreadStore):
    """
    Firestore-backed implementation of the ThreadStore interface.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.firestore")
        cfg = AKConfig.get().thread.firestore
        if cfg is None or not cfg.collection_name:
            raise ValueError("AKConfig.thread.firestore.collection_name must be set to use FirestoreThreadStore")
        # The store owns the expiry_time TTL logic, so the driver is constructed
        # without a TTL and shares only the connection layer.
        self._driver = FirestoreDriver(collection_name=cfg.collection_name, project_id=cfg.project_id, database_id=cfg.database_id)
        self._ttl = cfg.ttl

    def create(self, thread: Thread) -> Thread:
        """
        Persist a new thread's metadata document. Creation is conditional: if a
        concurrent request already created the thread, the existing metadata is
        returned untouched.
        :param thread: The thread to persist.
        :return: The persisted (or already existing) thread.
        """
        from google.api_core.exceptions import AlreadyExists

        self._log.debug(f"Creating thread for session {thread.session_id}")
        metadata = thread.model_copy(update={"messages": []})
        doc: dict = {
            "data": metadata.model_dump_json(),
            "user_id": thread.user_id,
            "group_id": thread.group_id,
            "updated_at": metadata.updated_at.isoformat(),
        }
        if self._ttl and self._ttl > 0:
            doc["expiry_time"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self._ttl)
        try:
            self._driver.collection.document(thread.session_id).create(doc)
        except AlreadyExists:
            return self.load_metadata(thread.session_id)
        return metadata

    def update_name(self, session_id: str, name: str) -> Thread:
        """
        Set a thread's display name and mark it name_locked by rewriting the
        metadata data blob; the top-level updated_at field is untouched.
        :param session_id: Unique identifier for the thread.
        :param name: The new display name.
        :return: The updated thread metadata.
        :raises KeyError: If the thread does not exist.
        """
        from google.api_core.exceptions import NotFound

        thread = self.load_metadata(session_id)
        if thread is None:
            raise KeyError(f"Thread {session_id} not found")
        thread.name = name
        thread.name_locked = True
        try:
            self._driver.collection.document(session_id).update({"data": thread.model_copy(update={"messages": []}).model_dump_json()})
        except NotFound:
            raise KeyError(f"Thread {session_id} not found")
        return thread.model_copy(update={"messages": []})

    def load_metadata(self, session_id: str) -> Optional[Thread]:
        """
        Load a thread's metadata document by its session id.
        :param session_id: Unique identifier for the thread.
        :return: The thread metadata, or None if it does not exist.
        """
        doc = self._driver.collection.document(session_id).get()
        if not doc.exists:
            return None
        record = doc.to_dict()
        payload = record.get("data")
        if payload is None:
            return None
        thread = Thread.model_validate_json(payload)
        if record.get("updated_at"):
            thread.updated_at = datetime.datetime.fromisoformat(record["updated_at"])
        return thread

    def append_message(self, session_id: str, message: ThreadMessage) -> None:
        """
        Append a message subcollection document and blind-update updated_at.
        :param session_id: Unique identifier for the thread.
        :param message: The message to append.
        :raises KeyError: If the thread does not exist.
        """
        doc_ref = self._driver.collection.document(session_id)
        if not doc_ref.get().exists:
            raise KeyError(f"Thread {session_id} not found")
        seq = _new_seq()
        doc_ref.collection(_MESSAGES_SUBCOLLECTION).document(seq).set({"seq": seq, "data": message.model_dump_json()})
        # Blind-update updated_at and refresh the TTL so an actively-used thread's
        # metadata document does not expire mid-conversation.
        update: dict = {"updated_at": _utc_now().isoformat()}
        if self._ttl and self._ttl > 0:
            update["expiry_time"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self._ttl)
        doc_ref.update(update)

    def get_messages(self, session_id: str, limit: int, offset: int = 0) -> Tuple[List[ThreadMessage], Optional[int]]:
        """
        Return a page of a thread's messages ordered by seq.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages to return.
        :param offset: Zero-based index of the first message.
        :return: A tuple of (messages page, next_offset).
        """
        if offset < 0:
            offset = 0
        query = (
            self._driver.collection.document(session_id)
            .collection(_MESSAGES_SUBCOLLECTION)
            .order_by("seq")
            .offset(offset)
            .limit(limit + 1)  # one extra to detect a following page
        )
        docs = list(query.stream())
        messages = [ThreadMessage.model_validate_json(doc.to_dict()["data"]) for doc in docs[:limit]]
        next_offset = offset + limit if len(docs) > limit else None
        return messages, next_offset

    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Thread], Optional[int]]:
        """
        List thread metadata filtered by user_id and/or group_id, most-recently updated first.
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads to return.
        :param offset: Zero-based index of the first thread.
        :return: A tuple of (threads page, next_offset).
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self._driver.collection
        if user_id is not None:
            query = query.where(filter=FieldFilter("user_id", "==", user_id))
        if group_id is not None:
            query = query.where(filter=FieldFilter("group_id", "==", group_id))

        threads = []
        for doc in query.stream():
            record = doc.to_dict()
            payload = record.get("data")
            if payload is None:
                continue
            thread = Thread.model_validate_json(payload)
            if record.get("updated_at"):
                thread.updated_at = datetime.datetime.fromisoformat(record["updated_at"])
            threads.append(thread)
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        return paginate(threads, limit, offset)

    def clear(self) -> None:
        """
        Delete all thread documents and their message subcollections.

        This is a destructive operation intended for development/testing only.
        """
        for doc in self._driver.collection.stream():
            for msg in doc.reference.collection(_MESSAGES_SUBCOLLECTION).stream():
                msg.reference.delete()
            doc.reference.delete()
