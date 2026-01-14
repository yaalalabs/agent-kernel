"""
Multimodal tools for LLM to access images/files.

This module provides:
1. describe_image_briefly() - PreHook uses this to get short descriptions
2. get_image - Function-decorated tool that LLM can call

The get_image tool uses AuxiliaryCache to access session data,
making it framework-agnostic (works with OpenAI SDK, ADK, etc.)
"""

import logging
from typing import TYPE_CHECKING

from agents import function_tool

from .storage import ATTACHMENT_KEY_PREFIX

if TYPE_CHECKING:
    from ..base import Session

_log = logging.getLogger("ak.multimodal.tools")


@function_tool
def get_attachments(attachment_ids: list[str]) -> list[dict]:
    """
    Get actual file/image data for the specified attachment IDs.

    Use this when you need to analyze files or images in detail.
    You must provide attachment IDs from the available list.

    :param attachment_ids: List of attachment IDs to retrieve (e.g., ['abc123', 'def456'])
    :return: List of attachment data dictionaries with id, type, data (base64), mime_type
    """
    if not attachment_ids:
        return []

    try:
        from ..runtime import AuxiliaryCache

        # Use AuxiliaryCache to access session's non-volatile cache
        nv_cache = AuxiliaryCache.get_non_volatile_cache()

        result = []
        for att_id in attachment_ids:
            attachment = nv_cache.get(f"{ATTACHMENT_KEY_PREFIX}{att_id}")
            if attachment:
                result.append(
                    {
                        "id": attachment["id"],
                        "type": attachment["type"],
                        "name": attachment["name"],
                        "mime_type": attachment["mime_type"],
                        "data": attachment["data"],  # Base64 encoded
                    }
                )
                _log.debug(f"Retrieved attachment: {att_id}")
            else:
                _log.warning(f"Attachment not found: {att_id}")

        return result

    except Exception as e:
        _log.error(f"Error retrieving images: {e}")
        return [{"error": str(e)}]


async def describe_attachment_briefly(
    data: str,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Get a brief description of the attachment using a vision LLM.

    Called by PreHook to generate descriptions for new attachments.

    :param data: Base64 encoded attachment data
    :param mime_type: MIME type of the attachment
    :return: Brief description of the attachment
    """
    if not data:
        return "No data"

    try:
        # Lazy import to avoid circular dependencies
        import os

        from openai import AsyncOpenAI

        from ..config import AKConfig

        # Try to get API key from config or env
        api_key = os.getenv("OPENAI_API_KEY")
        config = AKConfig.get()
        if hasattr(config, "openai") and config.openai.api_key:
            api_key = config.openai.api_key

        if not api_key:
            return "Attachment (Description unavailable: Missing API Key)"

        client = AsyncOpenAI(api_key=api_key)

        if mime_type.startswith("image/"):
            # Use Vision model for images
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in one short sentence (max 20 words). Be specific."},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{data}"},
                            },
                        ],
                    }
                ],
                max_tokens=50,
            )
            description = response.choices[0].message.content.strip()
            _log.debug(f"Generated attachment description: {description}")
            return description
        else:
            # For non-images (PDFs, docs), we can't easily "see" them via Vision API directly
            # without conversion. Return generic description for now.
            return f"File ({mime_type})"

    except Exception as e:
        _log.error(f"Error describing attachment: {e}")
        return "Attachment (description failed)"
