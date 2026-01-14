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
def get_image(image_ids: list[str]) -> list[dict]:
    """
    Get actual image/file data for the specified attachment IDs.
    
    Use this when you need to analyze images in detail to answer the user's question.
    You must provide image IDs from the available attachments list.
    
    :param image_ids: List of attachment IDs to retrieve (e.g., ['abc123', 'def456'])
    :return: List of attachment data dictionaries with id, type, data (base64), mime_type
    """
    if not image_ids:
        return []
    
    try:
        from ..runtime import AuxiliaryCache
        # Use AuxiliaryCache to access session's non-volatile cache
        nv_cache = AuxiliaryCache.get_non_volatile_cache()
        
        result = []
        for img_id in image_ids:
            attachment = nv_cache.get(f"{ATTACHMENT_KEY_PREFIX}{img_id}")
            if attachment:
                result.append({
                    "id": attachment["id"],
                    "type": attachment["type"],
                    "name": attachment["name"],
                    "mime_type": attachment["mime_type"],
                    "data": attachment["data"],  # Base64 encoded
                })
                _log.debug(f"Retrieved attachment: {img_id}")
            else:
                _log.warning(f"Attachment not found: {img_id}")
        
        return result
        
    except Exception as e:
        _log.error(f"Error retrieving images: {e}")
        return [{"error": str(e)}]


async def describe_image_briefly(
    image_data: str,
    mime_type: str,
    llm_client=None,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Get a brief description of an image using a vision LLM.
    
    Called by PreHook to generate descriptions for new images.
    
    :param image_data: Base64 encoded image data
    :param mime_type: MIME type of the image
    :param llm_client: Optional OpenAI client
    :param model: Vision-capable model to use
    :return: Brief description of the image
    """
    if not image_data:
        return "No image data"
    
    if llm_client is None:
        try:
            from openai import OpenAI
            llm_client = OpenAI()
        except Exception as e:
            _log.error(f"Failed to create OpenAI client: {e}")
            return "Image (could not generate description)"
    
    try:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Describe this image in one short sentence (max 20 words). Be specific."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}"
                        }
                    }
                ]
            }
        ]
        
        response = llm_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=50,
        )
        
        description = response.choices[0].message.content.strip()
        _log.debug(f"Generated image description: {description}")
        return description
        
    except Exception as e:
        _log.error(f"Error describing image: {e}")
        return "Image (error generating description)"
