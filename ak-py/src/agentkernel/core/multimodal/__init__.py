"""
Multimodal memory module for Agent Kernel.

This module provides:
- Storage functions for saving/retrieving attachments
- Pre/Post hooks for the 2-step LLM attachment memory flow
"""

from .hooks import MultimodalPostHook, MultimodalPreHook
from .storage import (
    AttachmentData,
    AttachmentMetadata,
    extract_description_from_response,
    format_attachment_list_for_prompt,
    get_attachment_data,
    get_attachment_list,
    parse_requested_attachment_ids,
    save_attachment,
    update_attachment_description,
)

__all__ = [
    # Storage
    "AttachmentData",
    "AttachmentMetadata",
    "save_attachment",
    "get_attachment_list",
    "get_attachment_data",
    "update_attachment_description",
    "format_attachment_list_for_prompt",
    "parse_requested_attachment_ids",
    "extract_description_from_response",
    # Hooks
    "MultimodalPreHook",
    "MultimodalPostHook",
]
