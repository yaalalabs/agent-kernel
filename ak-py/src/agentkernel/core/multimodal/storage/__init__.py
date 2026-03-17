"""
Storage sub-package for multimodal attachments.

Provides pluggable storage backends (in_memory, session_cache, redis, dynamodb)
and the ``AttachmentStorageManager`` high-level API.
"""

from .base import AttachmentData, AttachmentStore
from .in_memory import InMemoryAttachmentStore
from .storage_manager import AttachmentStorageManager
