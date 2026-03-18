"""
Multimodal module for Agent Kernel.

This module provides:
- Pluggable storage backends for saving/retrieving attachments
- PreHook for processing current images and injecting descriptions
- Tools for LLM to access image data (framework-agnostic)
"""

from .factory import MultimodalPreHookFactory
from .tools import AnalyzeAttachmentsTool
