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

        # Dynamic Context
        desc_text = "\n\n[Attached Images/Files:]\n"
        for att_id, desc in current_descriptions:
            desc_text += f"- {att_id}: {desc}\n"

        # Filter: Remove raw images/files from request types, but keep text
        filtered_requests_temp = []
        user_text_req = None

        for req in requests:
            if isinstance(req, AgentRequestText):
                user_text_req = req
            elif not isinstance(req, (AgentRequestImage, AgentRequestFile)):
                filtered_requests_temp.append(req)

        if user_text_req:
            # Merge description with user text
            merged_text = f"{user_text_req.text}{desc_text}"
            new_text_req = AgentRequestText(text=merged_text)
            filtered_requests_temp.append(new_text_req)
        else:
            # No user text (just image), so description becomes the text query
            filtered_requests_temp.append(AgentRequestText(text=desc_text.strip()))

        return filtered_requests_temp

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
                    # For files, call helper (returns generic desc or analysis)
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
                    self._log.info(f"Saved file {attachment_id}: {getattr(req, 'name', 'file')}")

        return descriptions

    def name(self) -> str:
        return "MultimodalPreHook"


class MultimodalPreHookFactory:
    """Factory to get the appropriate multimodal pre-hook based on config."""

    @staticmethod
    def get() -> PreHook:
        try:
            config = getattr(AKConfig.get(), "multimodal", None)
            if config and config.enabled:
                return MultimodalPreHook()
            else:
                return NoOpPreHook()
        except Exception:

            return NoOpPreHook()
