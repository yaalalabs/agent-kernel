"""
Multimodal PreHook for simplified approach.

This module provides PreHook implementation that:
1. Detects images in CURRENT request only
2. Calls LLM to get brief descriptions
3. Saves images to configurable storage
4. Injects ONLY current image descriptions into request
"""

import logging
from typing import TYPE_CHECKING

from ..config import AKConfig
from ..hooks import PreHook
from ..model import (
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from .storage import save_attachment
from .tools import describe_attachment_briefly

if TYPE_CHECKING:
    from ..base import Agent, Session


class NoOpPreHook(PreHook):
    """No-op pre-hook when multimodal is disabled."""

    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest]:
        return requests

    def name(self) -> str:
        return "NoOpMultimodalPreHook"


class MultimodalPreHook(PreHook):
    """
    Pre-hook that processes CURRENT images and injects descriptions.

    This hook:
    1. Detects new images in CURRENT request only
    2. Calls LLM to generate brief descriptions
    3. Saves images to storage (session/DynamoDB/Redis based on config)
    4. Injects ONLY current image descriptions into request

    Note: Conversation memory handles history - no need to inject previous images.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.hooks.multimodal_pre")

    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest]:
        """
        Process current images and inject descriptions.

        :param session: The current session
        :param agent: The agent instance
        :param requests: List of current agent requests
        :return: Modified requests with current image descriptions
        """
        config = getattr(AKConfig.get(), "multimodal", None)
        if not config or not config.enabled:
            return requests

        if not session:
            return requests

        # Process ONLY current images: describe and save them
        current_descriptions = await self._process_current_attachments(session, requests, config)

        if not current_descriptions:
            return requests

        # Build description text for current attachments only
        desc_text = "[Current Images/Files]\n"
        for att_id, desc in current_descriptions:
            desc_text += f"- {att_id}: {desc}\n"

        desc_text += "\nIf you need to examine any file or image in detail, " "use the get_attachments tool with the attachment ID."

        # Merge Strategy:
        # Combine description with user text to ensure OpenAI runner sees a single text request.
        # This is critical because OpenAIRunner disables conversation history for multi-part messages.

        final_requests = []
        user_text_req = None

        for req in requests:
            if isinstance(req, AgentRequestText):
                user_text_req = req
            elif not isinstance(req, (AgentRequestImage, AgentRequestFile)):
                # Keep other request types (like AgentRequestAny)
                final_requests.append(req)

        if user_text_req:
            # Merge description with user text
            merged_text = f"{desc_text}\n{user_text_req.text}"
            new_text_req = AgentRequestText(text=merged_text)
            # Preserve injected flag if needed, usually False for user text
            final_requests.append(new_text_req)
        else:
            # No user text (just image), so description becomes the text
            final_requests.append(context_request)

        return final_requests

    async def _process_current_attachments(self, session: "Session", requests: list[AgentRequest], config) -> list[tuple[str, str]]:
        """
        Process current attachments: generate descriptions and save to storage.
        Returns list of (attachment_id, description) tuples.
        """
        descriptions = []

        for req in requests:
            # Skip injected context requests
            if getattr(req, "_injected", False):
                continue

            if isinstance(req, AgentRequestImage):
                if req.image_data:
                    # Call LLM to get brief description
                    description = await describe_attachment_briefly(
                        data=req.image_data,
                        mime_type=req.mime_type or "image/jpeg",
                    )

                    # Save image to storage
                    attachment_id = save_attachment(
                        session=session,
                        data=req.image_data,
                        attachment_type="image",
                        name=getattr(req, "name", "image"),
                        mime_type=req.mime_type or "image/jpeg",
                        description=description,
                        max_attachments=config.max_attachments,
                    )

                    descriptions.append((attachment_id, description))
                    self._log.info(f"Saved image {attachment_id}: {description[:50]}...")

            elif isinstance(req, AgentRequestFile):
                if req.file_data:
                    # For files, use filename as description
                    description = await describe_attachment_briefly(
                        data=req.file_data,
                        mime_type=req.mime_type or "application/octet-stream",
                    )
                    attachment_id = save_attachment(
                        session=session,
                        data=req.file_data,
                        attachment_type="file",
                        name=getattr(req, "name", "file"),
                        mime_type=req.mime_type or "application/octet-stream",
                        description=description,
                        max_attachments=config.max_attachments,
                    )

                    descriptions.append((attachment_id, description))
                    self._log.info(f"Saved file {attachment_id}: {req.name}")

        return descriptions

    def name(self) -> str:
        return "MultimodalPreHook"


class MultimodalPreHookFactory:
    """Factory to get the appropriate multimodal pre-hook based on config."""

    @staticmethod
    def get() -> PreHook:
        config = getattr(AKConfig.get(), "multimodal", None)
        if config and config.enabled:
            return MultimodalPreHook()
        else:
            return NoOpPreHook()
