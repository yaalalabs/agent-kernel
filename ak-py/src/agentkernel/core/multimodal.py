"""
Multimodal memory hooks for 2-step LLM approach.

This module provides PreHook and PostHook implementations for:
1. PreHook: Injects previous attachment list into the request
2. PostHook: Saves current attachments with description from LLM response

The 2-step LLM logic (check if attachments needed, then re-run with data)
is handled in runtime.py.
"""

import logging
from typing import TYPE_CHECKING

from .attachment import (
    AttachmentMetadata,
    extract_description_from_response,
    format_attachment_list_for_prompt,
    get_attachment_list,
    save_attachment,
    update_attachment_description,
)
from .config import AKConfig
from .hooks import PostHook, PreHook
from .model import (
    AgentReply,
    AgentReplyText,
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)

if TYPE_CHECKING:
    from .base import Agent, Session


class MultimodalPreHook(PreHook):
    """
    Pre-hook that injects previous attachment list into the request.

    This hook:
    1. Gets list of previous attachments from session
    2. Formats them as text with IDs and descriptions
    3. Adds instruction for LLM to request specific IDs if needed
    4. Injects this text into the request

    The IDs in the response are parsed in runtime.py to decide
    whether to make a second LLM call with actual attachment data.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.hooks.multimodal_pre")

    async def on_run(self, session: "Session", agent: "Agent", requests: list[AgentRequest]) -> list[AgentRequest]:
        """
        Inject previous attachment metadata into the request.

        :param session: The current session
        :param agent: The agent instance
        :param requests: List of current agent requests
        :return: Modified requests with attachment list prepended
        """
        config = AKConfig.get().multimodal
        if not config.enabled:
            return requests

        if not session:
            return requests

        # Get previous attachments
        attachments = get_attachment_list(session)
        if not attachments:
            self._log.debug("No previous attachments in session")
            return requests

        # Format attachment list for LLM
        context_text = format_attachment_list_for_prompt(attachments)

        # Create context request and inject it
        context_request = AgentRequestText(text=context_text)

        # Mark as injected so we don't save it as part of conversation
        context_request._injected = True

        self._log.info(f"Injected {len(attachments)} previous attachment(s) metadata into request")

        # Prepend context to requests
        return [context_request] + list(requests)

    def name(self) -> str:
        return "MultimodalPreHook"


class MultimodalPostHook(PostHook):
    """
    Post-hook that saves current attachments with description from LLM response.

    This hook:
    1. Finds any images/files in the original requests
    2. Extracts a description from the LLM response
    3. Saves attachments to session with the description

    Note: This hook should only be called after the FINAL LLM response,
    not after the first "check if attachments needed" response.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.hooks.multimodal_post")

    async def on_run(
        self,
        session: "Session",
        requests: list[AgentRequest],
        agent: "Agent",
        agent_reply: AgentReply,
    ) -> AgentReply:
        """
        Save current attachments with description from LLM response.

        :param session: The current session
        :param requests: The original requests (may contain images/files)
        :param agent: The agent instance
        :param agent_reply: The LLM response
        :return: The agent_reply unchanged
        """
        config = AKConfig.get().multimodal
        if not config.enabled:
            return agent_reply

        if not session:
            return agent_reply

        # Extract description from LLM response
        reply_text = getattr(agent_reply, "text", "")
        description = extract_description_from_response(reply_text, max_length=config.description_max_length)

        # Find and save current attachments
        saved_count = 0
        for req in requests:
            # Skip injected context requests
            if getattr(req, "_injected", False):
                continue

            if isinstance(req, AgentRequestImage):
                if req.image_data:
                    attachment_id = save_attachment(
                        session=session,
                        data=req.image_data,
                        attachment_type="image",
                        name=getattr(req, "name", "image"),
                        mime_type=req.mime_type or "image/jpeg",
                        description=description,
                        max_attachments=config.max_attachments,
                    )
                    self._log.info(f"Saved current image: {attachment_id}")
                    saved_count += 1

            elif isinstance(req, AgentRequestFile):
                if req.file_data:
                    attachment_id = save_attachment(
                        session=session,
                        data=req.file_data,
                        attachment_type="file",
                        name=req.name,
                        mime_type=req.mime_type or "application/octet-stream",
                        description=description,
                        max_attachments=config.max_attachments,
                    )
                    self._log.info(f"Saved current file: {attachment_id}")
                    saved_count += 1

        if saved_count > 0:
            self._log.info(f"Saved {saved_count} attachment(s) with description: {description[:50]}...")

        return agent_reply

    def name(self) -> str:
        return "MultimodalPostHook"
