"""
ConversationThreadManager — service façade for Conversation Thread Support.

Owns thread lifecycle (create/load/append/history) and, when multimodal is
enabled, saving attachment bytes into the existing AttachmentStore before the
agent runs. A single shared instance is used by ChatService and ThreadRouter.
"""

import base64
import logging
import sys
from threading import RLock
from typing import List, Optional

from ..config import AKConfig
from ..model import AgentRequest, AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage
from .model import MessagePage, Thread, ThreadAttachment, ThreadMessage, ThreadPage
from .naming import ThreadNamingStrategy
from .store import ThreadStore, ThreadStoreBuilder

# Pagination defaults and cap for message/thread listings.
DEFAULT_MESSAGE_PAGE_SIZE = 50
DEFAULT_THREAD_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _encode_cursor(offset: Optional[int]) -> Optional[str]:
    """Encode a numeric page offset into an opaque cursor token, or None."""
    if offset is None:
        return None
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: Optional[str]) -> int:
    """Decode an opaque cursor token back into a numeric offset (0 when absent).

    :raises ValueError: If the cursor is present but malformed.
    """
    if not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        raise ValueError("Invalid pagination cursor")
    if offset < 0:
        raise ValueError("Invalid pagination cursor")
    return offset


def _clamp_limit(limit: Optional[int], default: int) -> int:
    """Clamp a requested page size into [1, MAX_PAGE_SIZE], defaulting when absent."""
    if not limit or limit < 1:
        return default
    return min(limit, MAX_PAGE_SIZE)


class ConversationThreadManager:
    """
    Service façade owning thread lifecycle and thread-mode attachment storage.
    """

    _instance: Optional["ConversationThreadManager"] = None
    _naming_strategy: Optional[ThreadNamingStrategy] = None
    _lock: RLock = RLock()
    _log = logging.getLogger("ak.thread.manager")

    def __init__(self, store: ThreadStore, naming_strategy: Optional[ThreadNamingStrategy] = None):
        """
        Initializes a ConversationThreadManager instance.
        :param store: The ThreadStore backend to persist threads in.
        :param naming_strategy: Strategy that names auto-created threads; the
                                built-in LLM-based default when omitted.
        """
        self._store = store
        self._naming = naming_strategy or ThreadNamingStrategy()

    @classmethod
    def get(cls) -> Optional["ConversationThreadManager"]:
        """
        Return the shared ConversationThreadManager instance, or None when
        Conversation Thread Support is not configured (no 'thread' block).
        Callers use the None check as the feature-enabled check.
        :return: The shared instance, or None if the feature is disabled.
        """
        if AKConfig.get().thread is None:
            return None
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(store=ThreadStoreBuilder.build(), naming_strategy=cls._naming_strategy)
            return cls._instance

    @classmethod
    def set_naming_strategy(cls, strategy: ThreadNamingStrategy) -> None:
        """
        Register a user-supplied ThreadNamingStrategy that names auto-created
        threads instead of the built-in default. Call once at startup; also
        applied to an already-built shared instance.
        :param strategy: The strategy to use for auto-generated thread names.
        """
        with cls._lock:
            cls._naming_strategy = strategy
            if cls._instance is not None:
                cls._instance._naming = strategy

    @classmethod
    def reset(cls) -> None:
        """
        Drop the shared instance and any registered naming strategy so the next
        get() rebuilds from config. Intended for testing.
        """
        with cls._lock:
            cls._instance = None
            cls._naming_strategy = None

    def get_or_create_thread(
        self,
        session_id: str,
        user_id: str,
        group_id: Optional[str] = None,
        name: Optional[str] = None,
        first_prompt: Optional[str] = None,
    ) -> Thread:
        """
        Load the thread for a session_id, creating it on the session's first request.
        group_id is applied only at creation and ignored for existing threads. name
        applies on any request: at creation it is used verbatim, and on an existing
        thread it renames it; either way an explicitly supplied name locks the name
        against automatic naming. A blank name is ignored.
        :param session_id: Unique identifier for the thread (same as the session id).
        :param user_id: Owning user id, stored at creation.
        :param group_id: Optional group/project scope, fixed at creation.
        :param name: Optional display name; when given it sets/renames the thread
                     name and locks it, otherwise the naming strategy derives one
                     from first_prompt at creation.
        :param first_prompt: The prompt of the creating request, used by the naming strategy.
        :return: The existing (possibly renamed) or newly created thread.
        """
        name = (name or "").strip() or None
        thread = self._store.load_metadata(session_id)
        if thread is not None:
            # Skip the store write when the resent name is already in place and locked.
            if name is not None and (name != thread.name or not thread.name_locked):
                self._log.info(f"Renaming thread for session {session_id}")
                return self._store.update_name(session_id, name)
            return thread
        thread = Thread(
            session_id=session_id,
            user_id=user_id,
            group_id=group_id,
            name=name or self._naming.generate_name(first_prompt or ""),
            name_locked=name is not None,
        )
        self._log.info(f"Creating thread for session {session_id} (user {user_id})")
        return self._store.create(thread)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        attachments: Optional[List[ThreadAttachment]] = None,
    ) -> ThreadMessage:
        """
        Append a message to the thread for a session_id.
        :param session_id: Unique identifier for the thread.
        :param role: Message role — "user" or "assistant".
        :param content: Message text content.
        :param attachments: Optional attachment references for the message.
        :return: The appended message.
        """
        message = ThreadMessage(role=role, content=content, attachments=attachments or [])
        self._store.append_message(session_id, message)
        return message

    def store_attachments(self, session_id: str, requests: List[AgentRequest]) -> tuple[List[AgentRequest], List[ThreadAttachment]]:
        """
        Save the bytes of each image/file request into the existing multimodal
        AttachmentStore and return (1) a rebuilt request list in which every stored
        image/file request is replaced, in place, by an AgentRequestAttachmentRef
        carrying its assigned id (all other requests kept in order), and (2) the
        ThreadAttachment references for the saved attachments.

        Passing the id in-band on the rebuilt request list is how MultimodalPreHook
        later learns which attachment to reference — no raw bytes travel past
        storage. Requires multimodal.enabled: requests carrying attachments while
        multimodal is disabled are rejected (thread mode is text-only without it),
        and text-only requests pass through unchanged. No description is
        generated here (that stays in MultimodalPreHook). Thread attachments are
        exempt from the store's max_attachments eviction.

        :param session_id: Session identifier used for attachment isolation.
        :param requests: The incoming agent requests to scan for attachments.
        :return: A tuple of (rebuilt requests, ThreadAttachment references).
        :raises ValueError: If the requests carry attachments while multimodal is disabled.
        """
        if not AKConfig.get().multimodal.enabled:
            if any(
                (isinstance(req, AgentRequestImage) and req.image_data) or (isinstance(req, AgentRequestFile) and req.file_data) for req in requests
            ):
                raise ValueError(
                    "Attachments are not supported when thread support is enabled without multimodal support — "
                    "set multimodal.enabled: true in config.yaml to accept images and files"
                )
            return requests, []
        if AKConfig.get().multimodal.storage_type == "session_cache":
            # This runs outside the session context, so session_cache writes land in a
            # session copy that distributed session stores never persist — silent loss.
            raise ValueError(
                "multimodal.storage_type 'session_cache' is not supported when thread support is enabled — "
                "use a shared attachment store (in_memory, redis, or dynamodb) in config.yaml"
            )

        from ..multimodal.storage import AttachmentStorageManager

        manager = AttachmentStorageManager(session_id=session_id)
        rebuilt: List[AgentRequest] = []
        references: List[ThreadAttachment] = []
        for req in requests:
            if isinstance(req, AgentRequestImage) and req.image_data:
                data, att_type, name, mime_type = req.image_data, "image", req.name, req.mime_type or "image/jpeg"
            elif isinstance(req, AgentRequestFile) and req.file_data:
                data, att_type, name, mime_type = req.file_data, "file", req.name, req.mime_type or "application/octet-stream"
            else:
                rebuilt.append(req)
                continue
            attachment_id = manager.save_attachment(
                data=data,
                attachment_type=att_type,
                name=name,
                mime_type=mime_type,
                max_attachments=sys.maxsize,  # thread attachments are exempt from eviction
            )
            references.append(ThreadAttachment(attachment_id=attachment_id, name=name, mime_type=mime_type))
            rebuilt.append(AgentRequestAttachmentRef(attachment_id=attachment_id))
            self._log.debug(f"Stored thread attachment {attachment_id} ({name}) for session {session_id}")
        return rebuilt, references

    def get_thread(self, session_id: str, user_id: Optional[str] = None) -> Optional[Thread]:
        """
        Load a thread's metadata by session_id, optionally enforcing ownership.
        Messages are fetched separately and paginated via get_messages.
        :param session_id: Unique identifier for the thread.
        :param user_id: When provided (resolved by an Authoriser), the thread's
                        owner must match or a PermissionError is raised.
        :return: The thread metadata, or None if it does not exist.
        :raises PermissionError: If user_id is provided and does not own the thread.
        """
        thread = self._store.load_metadata(session_id)
        if thread is None:
            return None
        if user_id is not None and thread.user_id != user_id:
            raise PermissionError(f"Thread {session_id} is not owned by user {user_id}")
        return thread

    def get_messages(self, session_id: str, limit: Optional[int] = None, cursor: Optional[str] = None) -> MessagePage:
        """
        Return a page of a thread's messages in chronological order.
        :param session_id: Unique identifier for the thread.
        :param limit: Maximum number of messages (clamped to [1, MAX_PAGE_SIZE]).
        :param cursor: Opaque cursor from a previous page's next_cursor.
        :return: A MessagePage with the messages and the next opaque cursor.
        :raises ValueError: If the cursor is malformed.
        """
        offset = _decode_cursor(cursor)
        page_size = _clamp_limit(limit, DEFAULT_MESSAGE_PAGE_SIZE)
        messages, next_offset = self._store.get_messages(session_id, limit=page_size, offset=offset)
        return MessagePage(messages=messages, next_cursor=_encode_cursor(next_offset))

    def list_threads(
        self,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> ThreadPage:
        """
        List threads filtered by user_id and/or group_id (metadata only), paginated.
        :param user_id: Filter by owning user id.
        :param group_id: Filter by group id.
        :param limit: Maximum number of threads (clamped to [1, MAX_PAGE_SIZE]).
        :param cursor: Opaque cursor from a previous page's next_cursor.
        :return: A ThreadPage with the threads and the next opaque cursor.
        :raises ValueError: If the cursor is malformed.
        """
        offset = _decode_cursor(cursor)
        page_size = _clamp_limit(limit, DEFAULT_THREAD_PAGE_SIZE)
        threads, next_offset = self._store.list_threads(user_id=user_id, group_id=group_id, limit=page_size, offset=offset)
        return ThreadPage(threads=threads, next_cursor=_encode_cursor(next_offset))
