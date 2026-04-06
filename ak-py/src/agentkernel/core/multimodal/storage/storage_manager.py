"""
Attachment storage manager for multimodal memory.
"""

import logging
import time
import uuid

from ...config import AKConfig
from .base import (
    DEFAULT_MAX_ATTACHMENTS,
    AttachmentData,
    AttachmentStore,
)

_log = logging.getLogger("ak.core.multimodal.storage")


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

        if storage_type == "session_cache":
            from .session_cache import SessionNonVolatileCacheAttachmentStore

            return SessionNonVolatileCacheAttachmentStore(session_id)

        elif storage_type == "redis":
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

        elif storage_type == "dynamodb":
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

        else:
            # Default: in_memory
            from .in_memory import InMemoryAttachmentStore

            return InMemoryAttachmentStore(session_id)

    def save_attachment(
        self,
        data: str,
        attachment_type: str,
        name: str,
        mime_type: str,
        description: str = "",
        max_attachments: int = DEFAULT_MAX_ATTACHMENTS,
    ) -> str:
        """
        Save an attachment using the configured storage driver.

        :param data: Base64 encoded attachment data.
        :param attachment_type: "image" or "file".
        :param name: Filename.
        :param mime_type: MIME type of the attachment.
        :param description: Optional description from LLM.
        :param max_attachments: Maximum number of attachments to keep.
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
                    )
                )
                _log.debug(f"Loaded attachment: {attachment_id}")
            else:
                _log.warning(f"Attachment not found: {attachment_id}")

        return result
