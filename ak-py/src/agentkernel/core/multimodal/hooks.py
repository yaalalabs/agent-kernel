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
    AgentRequestAttachmentRef,
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

    Conversation memory handles history — no need to re-inject previous attachments.
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

        # Nothing to do when there are no attachment-bearing requests to process.
        if not any(isinstance(req, (AgentRequestImage, AgentRequestFile, AgentRequestAttachmentRef)) for req in requests):
            return requests

        # Describe all current attachments (saving raw ones; resolving refs by id).
        descriptions = await self._process_attachments(session, requests, config)

        # Build filtered request list, always stripping attachment requests:
        #  - Raw image/file: their data is saved to storage
        #  - AgentRequestAttachmentRef: the id is resolved and injected (or dropped if unresolved)
        # so a dangling reference is never passed to the agent.
        filtered_requests = []
        last_text_idx = -1
        for req in requests:
            if isinstance(req, (AgentRequestImage, AgentRequestFile, AgentRequestAttachmentRef)):
                continue
            if isinstance(req, AgentRequestText):
                last_text_idx = len(filtered_requests)
            filtered_requests.append(req)

        if not descriptions:
            return filtered_requests

        # Build description text for attachment metadata and inject it.
        desc_text = "\n\n[Attached Images/Files:]\n"
        for att_id, desc in descriptions:
            desc_text += f"- {att_id}: {desc}\n"

        if last_text_idx >= 0:
            last_text_req = filtered_requests[last_text_idx]
            filtered_requests[last_text_idx] = AgentRequestText(text=f"{last_text_req.text}{desc_text}")
        else:
            # No text at all (attachments only) — description becomes the query
            filtered_requests.append(AgentRequestText(text=desc_text.strip()))

        return filtered_requests

    async def _process_attachments(
        self,
        session: "Session",
        requests: list[AgentRequest],
        config: _MultimodalConfig,
    ) -> list[tuple[str, str]]:
        """
        Describe each attachment in the current request.

        Two request shapes are handled:
          - AgentRequestAttachmentRef (thread mode): the bytes were already saved
            by ChatService and only the id travels in-band. Load the bytes from the
            AttachmentStore by id, describe them, and reference the same id — no save.
          - AgentRequestImage / AgentRequestFile (thread-off): raw bytes travel on
            the request; describe and save them here exactly as before.

        :param session: The current session.
        :param requests: List of current agent requests.
        :param config: Multimodal configuration.
        :return: List of (attachment_id, description) tuples.
        """
        descriptions: list[tuple[str, str]] = []
        manager = AttachmentStorageManager(session_id=session.id)

        for req in requests:
            if isinstance(req, AgentRequestAttachmentRef):
                # Thread mode: resolve the already-stored attachment by id.
                stored = manager.get_attachment_data([req.attachment_id])
                if not stored:
                    self._log.warning(f"Attachment {req.attachment_id} not found in storage; skipping")
                    continue
                attachment = stored[0]
                description = await self._describe_attachment_briefly(data=attachment.data, mime_type=attachment.mime_type)
                if len(description) > config.description_max_length:
                    description = description[: config.description_max_length]
                descriptions.append((req.attachment_id, description))
                continue

            data, att_type, name, mime_type = self._extract_attachment(req)
            if data is None:
                continue

            # Generate brief description via LLM
            description = await self._describe_attachment_briefly(data=data, mime_type=mime_type)

            # Truncate to configured max length
            if len(description) > config.description_max_length:
                description = description[: config.description_max_length]

            # Thread-off: save the raw bytes here.
            attachment_id = manager.save_attachment(
                data=data,
                attachment_type=att_type,
                name=name,
                mime_type=mime_type,
                description=description,
                max_attachments=config.max_attachments,
            )
            self._log.info(f"Saved {att_type} {attachment_id}: {name}")
            descriptions.append((attachment_id, description))

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
