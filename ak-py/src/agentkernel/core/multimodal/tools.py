"""
Multimodal tools for LLM to access images/files.

"""

import logging

from .storage import AttachmentStorageManager
from ..config import AKConfig
from ..model import SystemTool
from ..tool import ToolContext

_log = logging.getLogger(__name__)


def _analyze_attachments(attachment_ids: list[str], prompt: str) -> str:
    """
    Analyze attachments (images/files) using LLM and return ONLY the analysis response.

    :param attachment_ids: List of attachment IDs to analyze
    :param prompt: The question/prompt for analyzing the attachments
    :return: Only the LLM analysis response text
    """
    if not attachment_ids:
        return "No attachments provided"

    try:
        ctx = ToolContext.get()
        session = ctx.session

        attachments = AttachmentStorageManager(session_id=session.id).get_attachment_data(attachment_ids=attachment_ids)

        if not attachments:
            return "No attachments found for the given in this session"

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


class AnalyzeAttachmentsTool(SystemTool):
    name = "analyze_attachments"
    description = (
        "User has attached files/images. Their IDs and descriptions are listed in the user's message.\n"
        "Available tool:\n"
        "- analyze_attachments(attachment_ids, prompt): Analyze attachments using litellm.\n"
        "  Returns only analysis text (no raw data), perfect for saving clean conversation history.\n"
        "Use this tool when asked about attached images or files.\n"
        "IMPORTANT: The descriptions above are brief summaries. If the user asks for SPECIFIC DETAILS "
        "(numbers, quotes, tables) found in the files, you MUST use the `analyze_attachments` tool to "
        "inspect the file content again. Do not guess based on the summary."
    )
    func = _analyze_attachments
