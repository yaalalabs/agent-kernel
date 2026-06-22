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

import litellm

from ...core.base import Agent, Session
from ..config import AKConfig, _MultimodalConfig
from ..hooks import PreHook
from ..model import (
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
)
from .storage import AttachmentStorageManager

if TYPE_CHECKING:
    pass


class MultimodalPreHook(PreHook):
    """
    Pre-hook that processes CURRENT attachments and injects descriptions.

    Flow:
    1. Detects new images/files in the current request
    2. For each: call LLM → generate description → save to storage
    3. Remove raw binary data from requests
    4. Append attachment metadata (IDs + descriptions) to the user's text
    5. Re-inject all session attachments on every turn so follow-up requests
       expose the real IDs from storage. Framework conversation memory may
       summarize prior turns and not preserve exact attachment UUIDs; storage
       is the source of truth for IDs usable by analyze_attachments.
    """

    def __init__(self):
        self._log = logging.getLogger("ak.hooks.multimodal_pre")

    async def _describe_attachment_briefly(
        self,
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
                self._log.debug(f"Generated attachment description: {description}")
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
            self._log.error("LiteLLM not installed. Install with: pip install litellm")
            return "Attachment (LiteLLM missing)"
        except Exception as e:
            self._log.error(f"Error describing attachment: {e}")
            return "Attachment (description failed)"

    async def on_run(self, session: Session, agent: Agent, requests: list[AgentRequest]) -> list[AgentRequest]:
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

        manager = AttachmentStorageManager(session_id=session.id)

        # Describe and save any new attachments in the current request
        await self._process_attachments(requests, config, manager)

        # Re-inject all stored session attachments on every turn. Framework
        # memory may not preserve exact attachment UUIDs across turns.
        descriptions = manager.list_attachment_summaries()
        if not descriptions:
            return requests

        return self._inject_attachment_metadata(requests, descriptions)

    @staticmethod
    def _inject_attachment_metadata(
        requests: list[AgentRequest],
        descriptions: list[tuple[str, str]],
    ) -> list[AgentRequest]:
        """
        Inject attachment IDs and descriptions into the last text request.

        :param requests: Current agent requests.
        :param descriptions: Attachment IDs and descriptions for the session.
        :return: Requests with attachment metadata appended to the prompt text.
        """
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
            # Drop images (their data is stored and described)
            if isinstance(req, AgentRequestImage):
                continue
            # Drop files as well after persisting; rely on injected IDs + analyze_attachments
            if isinstance(req, AgentRequestFile):
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
        requests: list[AgentRequest],
        config: _MultimodalConfig,
        manager: AttachmentStorageManager,
    ) -> None:
        """
        Describe and save each attachment in the current request.

        :param requests: List of current agent requests.
        :param config: Multimodal configuration.
        :param manager: Attachment storage manager for the session.
        """
        for req in requests:
            data, att_type, name, mime_type = self._extract_attachment(req)
            if data is None:
                continue

            # Generate brief description via LLM
            description = await self._describe_attachment_briefly(data=data, mime_type=mime_type)

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

            self._log.info(f"Saved {att_type} {attachment_id}: {name}")

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
