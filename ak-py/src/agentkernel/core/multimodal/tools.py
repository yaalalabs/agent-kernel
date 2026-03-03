"""
Multimodal tools for LLM to access images/files.

"""

import logging

from ..config import AKConfig
from .storage import AttachmentStorageManager

_log = logging.getLogger(__name__)


def analyze_attachments(attachment_ids: list[str], prompt: str) -> str:
    """
    Analyze attachments (images/files) using LLM and return ONLY the analysis response.

    :param attachment_ids: List of attachment IDs to analyze
    :param prompt: The question/prompt for analyzing the attachments
    :return: Only the LLM analysis response text
    """
    if not attachment_ids:
        return "No attachments provided"

    try:
        from ..tool import ToolContext

        ctx = ToolContext.get()
        session = ctx.session

        attachments = AttachmentStorageManager(session_id=session.id).get_attachment_data(attachment_ids=attachment_ids)

        if not attachments:
            return "No attachments found for the given IDs in this session"

        config = AKConfig.get()
        model_name = config.multimodal.analysis_model

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

        import litellm

        response = litellm.completion(
            model=model_name,
            messages=[{"role": "user", "content": content}],
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        _log.exception("Error analyzing attachments")
        return "Failed to analyze attachments. Please try again later."


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
        import litellm

        config = AKConfig.get()
        model_name = config.multimodal.description_model

        if mime_type.startswith("image/"):
            # Use Vision model for images via LiteLLM
            # litellm reads API keys from environment automatically (e.g. OPENAI_API_KEY)
            response = await litellm.acompletion(
                model=model_name,
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

            return f"File ({mime_type}) - Content not currently visible. Use analyze_attachments to analyze."

    except ImportError:
        _log.error("LiteLLM not installed. Install with: pip install litellm")
        return "Attachment (LiteLLM missing)"
    except Exception as e:
        _log.error(f"Error describing attachment: {e}")
        return "Attachment (description failed)"
