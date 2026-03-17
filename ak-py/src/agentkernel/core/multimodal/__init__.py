"""
Multimodal module for Agent Kernel.

This module provides:
- Pluggable storage backends for saving/retrieving attachments
- PreHook for processing current images and injecting descriptions
- Tools for LLM to access image data (framework-agnostic)
"""

# Register the tool instruction with the base Agent
from ..base import Agent
from .hooks import MultimodalPreHook, MultimodalPreHookFactory, NoOpPreHook
from .storage import (
    AttachmentData,
    AttachmentStorageManager,
    AttachmentStore,
)
from .tools import (
    analyze_attachments,
    describe_attachment_briefly,
)

_analyze_attachments_instruction = (
    "User has attached files/images. Their IDs and descriptions are listed in the user's message.\n"
    "Available tool:\n"
    "- analyze_attachments(attachment_ids, prompt): Analyze attachments using litellm.\n"
    "  Returns only analysis text (no raw data), perfect for saving clean conversation history.\n"
    "Use this tool when asked about attached images or files.\n"
    "IMPORTANT: The descriptions above are brief summaries. If the user asks for SPECIFIC DETAILS "
    "(numbers, quotes, tables) found in the files, you MUST use the `analyze_attachments` tool to "
    "inspect the file content again. Do not guess based on the summary."
)

Agent.register_system_tool_instruction("analyze_attachments", _analyze_attachments_instruction)
