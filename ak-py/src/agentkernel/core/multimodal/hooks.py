"""
Multimodal PreHook for attachment processing.

This module provides a PreHook that:
1. Detects images/files in the CURRENT request
2. Calls LLM to generate brief descriptions
3. Saves attachments to configurable storage
4. Injects attachment descriptions into the request text
"""

import logging
from typing import TYPE_CHECKING, Optional

from ..config import AKConfig, _MultimodalConfig
from ..hooks import PreHook
from ..model import (
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from .storage import AttachmentStorageManager
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
    Pre-hook that processes CURRENT attachments and injects descriptions.

    Flow:
    1. Detects new images/files in the current request
    2. For each: call LLM → generate description → save to storage
    3. Remove raw binary data from requests
    4. Append attachment metadata (IDs + descriptions) to the user's text

    Conversation memory handles history — no need to re-inject previous attachments.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.hooks.multimodal_pre")

    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest]:
        """
        Process current attachments and inject descriptions into requests.

        :param session: The current session.
        :param agent: The agent instance.
        :param requests: List of current agent requests.
        :return: Modified requests with attachment descriptions injected.
        """
        config = getattr(AKConfig.get(), "multimodal", None)
        if not session or not config or not config.enabled:
            return requests

        # Describe and save all current attachments
        descriptions = await self._process_attachments(session, requests, config)
        if not descriptions:
            return requests

        # Build description text for attachment metadata
        desc_text = "\n\n[Attached Images/Files:]\n"
        for att_id, desc in descriptions:
            desc_text += f"- {att_id}: {desc}\n"

        # Build filtered request list:
        #  - Drop raw image/file requests (data is saved to storage)
        #  - Keep all text and other request types
        #  - Append attachment metadata to the LAST text request
        filtered_requests = []
        last_text_idx = -1

        for req in requests:
            if isinstance(req, (AgentRequestImage, AgentRequestFile)):
                continue
            if isinstance(req, AgentRequestText):
                last_text_idx = len(filtered_requests)
            filtered_requests.append(req)

        if last_text_idx >= 0:
            last_text_req = filtered_requests[last_text_idx]
            filtered_requests[last_text_idx] = AgentRequestText(text=f"{last_text_req.text}{desc_text}")
        else:
            # No text at all (image/file only) — description becomes the query
            filtered_requests.append(AgentRequestText(text=desc_text.strip()))

        return filtered_requests

    async def _process_attachments(
        self,
        session: "Session",
        requests: list[AgentRequest],
        config: _MultimodalConfig,
    ) -> list[tuple[str, str]]:
        """
        Describe and save each attachment in the current request.

        :param session: The current session.
        :param requests: List of current agent requests.
        :param config: Multimodal configuration.
        :return: List of (attachment_id, description) tuples.
        """
        descriptions: list[tuple[str, str]] = []
        manager = AttachmentStorageManager(session_id=session.id)

        for req in requests:
            data, att_type, name, mime_type = self._extract_attachment(req)
            if data is None:
                continue

            # Generate brief description via LLM
            description = await describe_attachment_briefly(data=data, mime_type=mime_type)

            # Truncate to configured max length
            if len(description) > config.description_max_length:
                description = description[: config.description_max_length]

            # Save to storage
            attachment_id = manager.save_attachment(
                data=data,
                attachment_type=att_type,
                name=name,
                mime_type=mime_type,
                description=description,
                max_attachments=config.max_attachments,
            )

            descriptions.append((attachment_id, description))
            self._log.info(f"Saved {att_type} {attachment_id}: {name}")

        return descriptions

    @staticmethod
    def _extract_attachment(req: AgentRequest) -> tuple[Optional[str], str, str, str]:
        """
        Extract attachment data from a request if it is an image or file.

        :param req: An agent request.
        :return: (data, type, name, mime_type) or (None, ...) if not an attachment.
        """
        if isinstance(req, AgentRequestImage) and req.image_data:
            return (
                req.image_data,
                "image",
                getattr(req, "name", "image"),
                req.mime_type or "image/jpeg",
            )
        if isinstance(req, AgentRequestFile) and req.file_data:
            return (
                req.file_data,
                "file",
                getattr(req, "name", "file"),
                req.mime_type or "application/octet-stream",
            )
        return None, "", "", ""

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
            return NoOpPreHook()
        except Exception:
            logging.getLogger("ak.hooks.multimodal_pre").exception("Failed to initialize MultimodalPreHook; falling back to NoOpPreHook.")
            return NoOpPreHook()
