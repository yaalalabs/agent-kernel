"""
Multimodal tools for LLM to access images/files.

This module provides:
1. describe_attachment_briefly() - PreHook uses this to get short descriptions
2. get_attachments - Function-decorated tool that LLM can call

The get_attachments tool uses AuxiliaryCache to access session data,
making it framework-agnostic (works with OpenAI SDK, ADK, etc.)
"""

import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)


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
        from .storage import get_attachment_data

        # Use AuxiliaryCache to access session's non-volatile cache
        nv_cache = AuxiliaryCache.get_non_volatile_cache()

        # Call storage facade with direct cache (session is None in this context)
        attachments = get_attachment_data(session=None, cache=nv_cache, attachment_ids=attachment_ids)

        result = []
        for att in attachments:
            result.append(
                {
                    "id": att.id,
                    "type": att.type,
                    "name": att.name,
                    "mime_type": att.mime_type,
                    "data": att.data,  # Base64 encoded
                }
            )
            _log.debug(f"Retrieved attachment: {att.id}")

        return result

    except Exception as e:
        _log.error(f"Error retrieving images: {e}")
        return [{"error": str(e)}]


async def describe_attachment_briefly(
    data: str,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Get a brief description of the attachment using a vision LLM via LiteLLM.

    Called by PreHook to generate descriptions for new attachments.

    :param data: Base64 encoded attachment data
    :param mime_type: MIME type of the attachment
    :return: Brief description of the attachment
    """
    if not data:
        return "No data"

    try:

        import os

        import litellm

        from ..config import AKConfig

        # Try to get API key from config or env
        api_key = os.getenv("OPENAI_API_KEY")
        config = AKConfig.get()
        if hasattr(config, "openai") and config.openai.api_key:
            api_key = config.openai.api_key

        if not api_key:
            return "Attachment (Description unavailable: Missing API Key)"

        if mime_type.startswith("image/"):
            # Use Vision model for images via LiteLLM
            response = await litellm.acompletion(
                model="gpt-4o",
                api_key=api_key,
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
            # For non-images (PDFs, docs), return directive description to force tool usage
            return f"File ({mime_type}) - Content not currently visible. Use get_attachments to analyze."

    except ImportError:
        _log.error("LiteLLM not installed. Cannot describe attachment.")
        return "Attachment (LiteLLM missing)"
    except Exception as e:
        _log.error(f"Error describing attachment: {e}")
        return "Attachment (description failed)"
