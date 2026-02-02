"""
Multimodal tools for LLM to access images/files.

"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import litellm

from ..config import AKConfig
from .storage import get_attachment_data

_log = logging.getLogger(__name__)

# Fallback session ID for frameworks (like ADK) that don't propagate contextvars
# to tool execution. This is set by the runner before executing the agent.
_fallback_session_id: str | None = None


def set_fallback_session_id(session_id: str | None) -> None:
    """Set the fallback session ID for tool execution."""
    global _fallback_session_id
    _fallback_session_id = session_id


def get_fallback_session_id() -> str | None:
    """Get the fallback session ID."""
    return _fallback_session_id


def analyis_attachments(attachment_ids: list[str], prompt: str, session_id: str = None) -> str:
    """
    Analyze attachments (images/files) using LLM and return ONLY the analysis response.

    :param attachment_ids: List of attachment IDs to analyze
    :param prompt: The question/prompt for analyzing the attachments
    :param session_id: Optional session ID to use. If not provided, uses contextvar lookup.
                       This parameter is injected by framework wrappers (like ADK) that can't
                       propagate contextvars to tool execution context.
    :return: Only the LLM analysis response text
    """
    if not attachment_ids:
        return "No attachments provided"

    try:
        from ..base import Session
        from ..runtime import Runtime

        # Get session and cache - use provided session_id, then contextvar, then fallback
        if session_id is None:
            session_id = Session.get_current_session_id()
        if not session_id:
            # Try the fallback for frameworks that don't propagate contextvars
            session_id = get_fallback_session_id()
        if not session_id:
            return "No session context available"
        session = Runtime.current().sessions().load(session_id)
        nv_cache = session.get_non_volatile_cache()
        attachments = get_attachment_data(session=None, cache=nv_cache, attachment_ids=attachment_ids)

        if not attachments:
            return "No attachments found"

        # Get API key
        api_key = os.getenv("OPENAI_API_KEY")
        config = AKConfig.get()
        if hasattr(config, "openai") and config.openai.api_key:
            api_key = config.openai.api_key

        if not api_key:
            return "Error: Missing OpenAI API Key"

        # Build content with all attachments and prompt
        content = [{"type": "text", "text": prompt}]

        for att in attachments:
            if att.mime_type.startswith("image/"):
                content.append({"type": "image_url", "image_url": {"url": f"data:{att.mime_type};base64,{att.data}"}})
            elif att.mime_type.startswith("application/pdf"):
                content.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": att.name or "document.pdf",
                            "file_data": f"data:application/pdf;base64,{att.data}",
                        },
                    }
                )
            else:
                content.append({"type": "text", "text": f"\n[Document: {att.name} ({att.mime_type})]\n"})

        # Use model from config
        model_name = getattr(config.multimodal, "model", "gpt-4o")
        response = litellm.completion(
            model=model_name,
            api_key=api_key,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        _log.error(f"Error analyzing attachments: {e}")
        return f"Error: {str(e)}"


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

        model_name = getattr(config.multimodal, "model", "gpt-4o")

        if mime_type.startswith("image/"):
            # Use Vision model for images via LiteLLM
            response = await litellm.acompletion(
                model=model_name,
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

        elif mime_type.startswith("application/pdf"):
            resp = await litellm.acompletion(
                model=model_name,
                api_key=api_key,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this PDF in one short sentence (max 20 words). Be specific."},
                            {
                                "type": "file",
                                "file": {
                                    "filename": "document.pdf",
                                    "file_data": f"data:application/pdf;base64,{data}",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=50,
            )
            return resp.choices[0].message.content.strip()

        else:

            return f"File ({mime_type}) - Content not currently visible. Use analyis_attachments to analyze."

    except ImportError:
        _log.error("LiteLLM not installed. Cannot describe attachment.")
        return "Attachment (LiteLLM missing)"
    except Exception as e:
        _log.error(f"Error describing attachment: {e}")
        return "Attachment (description failed)"
