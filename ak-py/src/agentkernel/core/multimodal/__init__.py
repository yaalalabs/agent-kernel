"""
Multimodal module for Agent Kernel.

This module provides:
- Storage functions for saving/retrieving attachments
- PreHook for processing current images and injecting descriptions
- Tools for LLM to access image data (framework-agnostic)
"""

from .hooks import MultimodalPreHook, MultimodalPreHookFactory, NoOpPreHook
from .storage import (
    AttachmentData,
    AttachmentStorageDriver,
    CacheStorageDriver,
    get_attachment_data,
    save_attachment,
)
from .tools import (
    analyis_attachments,
    describe_attachment_briefly,
)
