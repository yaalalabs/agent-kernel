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
    AttachmentMetadata,
    get_attachment_data,
    save_attachment,
)
from .tools import (
    describe_attachment_briefly,
    get_attachments,
)

__all__ = [
    # Storage
    "AttachmentData",
    "AttachmentMetadata",
    "save_attachment",
    "get_attachment_data",
    # Hooks
    "MultimodalPreHook",
    "MultimodalPreHookFactory",
    "NoOpPreHook",
    # Tools
    "describe_attachment_briefly",
    "get_attachments",  # function_tool decorated - use in agent's tools=[]
]
