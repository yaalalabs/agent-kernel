"""
Attachment storage manager for multimodal memory.
"""

import logging
import sys
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ...config import AKConfig
from ...model import AgentRequest, AgentRequestAttachmentRef, AgentRequestFile, AgentRequestImage
from ...util.factory import AKConfigError, require_extra, resolve_dotted
from ..source import AttachmentSource
from .base import (
    DEFAULT_MAX_ATTACHMENTS,
    AttachmentData,
    AttachmentStore,
)

_log = logging.getLogger("ak.multimodal.storage")

_BUILTIN_ATTACHMENT_STORES = ["session_cache", "in_memory", "redis", "dynamodb"]


@dataclass
class StoredAttachment:
    """One attachment that was moved into the AttachmentStore."""

    attachment_id: str
    name: str
    mime_type: str


class AttachmentStorageManager:
    """
    High-level API for attachment storage.
    """

    def __init__(self, session_id: str):
        """
        Initialize the manager for a specific session.
        :param session_id: Session identifier for isolation.
        """
        self._session_id = session_id
        self._driver = self._build_driver(session_id)

    @staticmethod
    def _build_driver(session_id: str) -> AttachmentStore:
        """
        Factory method to create the appropriate storage driver based on config.
        Uses lazy imports to avoid loading unnecessary dependencies.

        :param session_id: Session identifier for isolation.
        :return: An AttachmentStore instance.
        """
        config = AKConfig.get().multimodal
        storage_type = config.storage_type
        key = storage_type.lower()

        if key == "session_cache":
            from .session_cache import SessionNonVolatileCacheAttachmentStore

            return SessionNonVolatileCacheAttachmentStore(session_id)

        if key == "in_memory":
            from .in_memory import InMemoryAttachmentStore

            return InMemoryAttachmentStore(session_id)

        if key == "redis":
            with require_extra("redis", "multimodal.storage_type: redis"):
                from .redis import RedisAttachmentStore

            redis_config = config.redis
            if redis_config is None:
                raise ValueError(
                    "Multimodal storage_type is 'redis' but no 'redis' configuration "
                    "is provided under 'multimodal'. Please set AK_MULTIMODAL__REDIS__URL etc."
                )
            return RedisAttachmentStore(
                session_id=session_id,
                url=redis_config.url,
                ttl=redis_config.ttl,
                prefix=redis_config.prefix,
            )

        if key == "dynamodb":
            with require_extra("aws", "multimodal.storage_type: dynamodb"):
                from .dynamodb import DynamoDBAttachmentStore

            dynamodb_config = config.dynamodb
            if dynamodb_config is None:
                raise ValueError(
                    "Multimodal storage_type is 'dynamodb' but no 'dynamodb' configuration "
                    "is provided under 'multimodal'. Please set AK_MULTIMODAL__DYNAMODB__TABLE_NAME etc."
                )
            return DynamoDBAttachmentStore(
                session_id=session_id,
                table_name=dynamodb_config.table_name,
                ttl=dynamodb_config.ttl,
            )

        # Bring-your-own: a dotted path to an AttachmentStore subclass (session-scoped).
        if "." not in storage_type:
            raise AKConfigError(
                f"unknown multimodal storage_type '{storage_type}'; expected one of {_BUILTIN_ATTACHMENT_STORES} or a dotted path to an AttachmentStore subclass"
            )
        return resolve_dotted(storage_type, base=AttachmentStore)(session_id)

    @classmethod
    def store_is_shared(cls) -> bool:
        """Whether the configured store can be read by a process other than the one that wrote it.

        Resolves the driver class without constructing it, so a caller can check the topology at
        mount time without opening a connection. The answer comes from the driver's own ``shared``
        attribute rather than a list here, so a bring-your-own store answers for itself.

        :return: True when the configured store is backed by an external service.
        :raises AKConfigError: If ``multimodal.storage_type`` names no known store.
        """
        storage_type = AKConfig.get().multimodal.storage_type
        key = storage_type.lower()
        if key == "session_cache":
            from .session_cache import SessionNonVolatileCacheAttachmentStore as store
        elif key == "in_memory":
            from .in_memory import InMemoryAttachmentStore as store
        elif key == "redis":
            with require_extra("redis", "multimodal.storage_type: redis"):
                from .redis import RedisAttachmentStore as store
        elif key == "dynamodb":
            with require_extra("aws", "multimodal.storage_type: dynamodb"):
                from .dynamodb import DynamoDBAttachmentStore as store
        elif "." in storage_type:
            store = resolve_dotted(storage_type, base=AttachmentStore)
        else:
            raise AKConfigError(
                f"unknown multimodal storage_type '{storage_type}'; expected one of {_BUILTIN_ATTACHMENT_STORES} or a dotted path to an AttachmentStore subclass"
            )
        return store.shared

    @staticmethod
    def has_attachments(requests: List[AgentRequest]) -> bool:
        """Whether any request in the list carries attachment bytes.

        :param requests: The request list to scan.
        :return: True when at least one image or file request carries data.
        """
        return any(
            (isinstance(req, AgentRequestImage) and req.image_data) or (isinstance(req, AgentRequestFile) and req.file_data) for req in requests
        )

    @classmethod
    def offload(
        cls,
        session_id: str,
        requests: List[AgentRequest],
        *,
        attachments_disabled_error: str,
        session_cache_error: str,
    ) -> Tuple[List[AgentRequest], List[StoredAttachment]]:
        """Save each image/file request's bytes and replace it, in place, with a reference.

        Two surfaces need this same rewrite before an agent request leaves the process it was
        built in: conversation threads (the bytes must not be re-sent on every turn) and messaging
        integrations (the bytes must not ride the queue, whose brokers cap a message far below
        ``api.max_file_size``). ``MultimodalPreHook`` resolves the references later; no raw bytes
        travel past storage.

        Requests that carry no attachment bytes pass through unchanged and keep their order, and a
        list with no attachments at all is returned as-is.

        ``AttachmentSource`` decides what each attachment's record holds and whether its request
        survives: base64 data is stored as bytes and its request replaced by a reference, while a
        remote reference (``http://``, ``https://``, ``s3://``, or a non-base64 ``data:`` URI) is
        stored as a url and its request travels on untouched for the adapter to resolve.
        Attachments saved here are exempt from ``max_attachments`` eviction: they are part of a
        request that has not run yet, so evicting one would lose the user's input.

        The two rejections are caller-worded because the remedy differs per surface, and both are
        configuration errors rather than runtime failures:

        - multimodal disabled: there is nowhere to put the bytes.
        - ``storage_type: session_cache``: it writes into a session copy that the process which
          later reads the attachment never sees, so the bytes are silently lost.

        Both are raised only when the list actually carries attachment bytes: a storage setting
        must not reject a plain text message that never touches the store.

        :param session_id: Session identifier the attachments are isolated under.
        :param requests: The request list to scan.
        :param attachments_disabled_error: Message raised when attachments are present while
            ``multimodal.enabled`` is false.
        :param session_cache_error: Message raised when attachments are present while
            ``multimodal.storage_type`` is ``session_cache``.
        :return: (rebuilt request list, references to the saved attachments).
        :raises ValueError: If attachments are present but cannot be stored (see above).
        """
        if not cls.has_attachments(requests):
            # Nothing here reaches the store, so neither guard applies and there is nothing to rebuild.
            return requests, []
        config = AKConfig.get().multimodal
        if not config.enabled:
            raise ValueError(attachments_disabled_error)
        if config.storage_type == "session_cache":
            raise ValueError(session_cache_error)

        manager = cls(session_id=session_id)
        rebuilt: List[AgentRequest] = []
        stored: List[StoredAttachment] = []
        for req in requests:
            extracted = AttachmentSource.extract(req)
            if extracted is None:
                rebuilt.append(req)
                continue
            is_reference = not extracted.is_base64
            attachment_id = manager.save_attachment(
                data="" if is_reference else extracted.data,
                attachment_type=extracted.att_type,
                name=extracted.name,
                mime_type=extracted.mime_type,
                max_attachments=sys.maxsize,
                url=extracted.data if is_reference else None,
            )
            stored.append(StoredAttachment(attachment_id=attachment_id, name=extracted.name, mime_type=extracted.mime_type))
            # A remote reference must not become an AgentRequestAttachmentRef: MultimodalPreHook
            # strips every ref before the agent runs, so the attachment would reach the agent as
            # nothing at all. It travels on untouched and the adapter resolves it.
            rebuilt.append(req if is_reference else AgentRequestAttachmentRef(attachment_id=attachment_id))
            _log.debug(f"Stored attachment {attachment_id} ({extracted.name}) for session {session_id}")
        return rebuilt, stored

    def save_attachment(
        self,
        data: str,
        attachment_type: str,
        name: str,
        mime_type: str,
        description: str = "",
        max_attachments: int = DEFAULT_MAX_ATTACHMENTS,
        url: Optional[str] = None,
    ) -> str:
        """
        Save an attachment using the configured storage driver.

        :param data: Base64 encoded attachment data; empty when url is given.
        :param attachment_type: "image" or "file".
        :param name: Filename.
        :param mime_type: MIME type of the attachment.
        :param description: Optional description from LLM.
        :param max_attachments: Maximum number of attachments to keep.
        :param url: Address of a remote attachment whose bytes are not held here.
        :return: The generated attachment ID.
        """
        attachment_id = str(uuid.uuid4())
        timestamp = time.time()

        attachment = {
            "id": attachment_id,
            "type": attachment_type,
            "data": data,
            "name": name,
            "mime_type": mime_type,
            "description": description,
            "timestamp": timestamp,
            "url": url,
        }

        self._driver.save(attachment, max_attachments)
        _log.info(f"Saved {attachment_type}: {attachment_id} ({name})")
        return attachment_id

    def get_attachment_data(
        self,
        attachment_ids: list[str],
    ) -> list[AttachmentData]:
        """
        Load actual attachment data for specific IDs using the storage driver.

        :param attachment_ids: List of attachment IDs to load.
        :return: List of AttachmentData objects.
        """
        if not attachment_ids:
            return []

        result = []
        for attachment_id in attachment_ids:
            attachment = self._driver.get(attachment_id)
            if attachment:
                result.append(
                    AttachmentData(
                        id=attachment["id"],
                        type=attachment["type"],
                        data=attachment["data"],
                        name=attachment["name"],
                        mime_type=attachment["mime_type"],
                        description=attachment.get("description", ""),
                        timestamp=attachment["timestamp"],
                        url=attachment.get("url"),
                    )
                )
                _log.debug(f"Loaded attachment: {attachment_id}")
            else:
                _log.warning(f"Attachment not found: {attachment_id}")

        return result
