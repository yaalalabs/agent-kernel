"""
Multimodal PreHook for attachment processing.

This module provides a PreHook that:
1. Detects images/files in the CURRENT request
2. Calls LLM to generate brief descriptions
3. Saves attachments to configurable storage
4. Injects attachment descriptions into the request text
"""

import logging
from typing import Optional

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
from .source import AttachmentSource, ExtractedAttachment
from .storage import AttachmentStorageManager

# (attachment_id, description) as injected into the request text.
_AttachmentDescription = tuple[str, str]


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

        One pass decides, for each request, both what to describe and whether the request itself
        travels on to the agent — so every branch below ends in an explicit `continue` or an append.

        Three attachment shapes reach here:
          - `AgentRequestAttachmentRef` (thread mode): the bytes were saved by `ChatService` before
            the run and only the id travels in-band, so it is described from storage and never saved
            again. The ref is always stripped — a dangling one must not reach the agent.
          - `AgentRequestImage` / `AgentRequestFile` carrying base64 (thread-off): described, saved,
            and stripped, because the bytes now live in storage.
          - The same two carrying something that is *not* base64 — a URL, or a `data:` URI without
            the marker: **kept**, because this hook cannot use those bytes and the adapter can.
            Declining to describe one *and* stripping it would be worse than the corruption this all
            replaced — the model would never see the attachment at all.

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

        manager = AttachmentStorageManager(session_id=session.id)
        filtered_requests: list[AgentRequest] = []
        descriptions: list[_AttachmentDescription] = []
        last_text_idx = -1

        for req in requests:
            if isinstance(req, AgentRequestAttachmentRef):
                described = await self._describe_stored(req, manager, config)
                if described is not None:
                    descriptions.append(described)
                continue  # a ref never travels on: resolved, its id is injected; unresolved, it is dangling

            if isinstance(req, (AgentRequestImage, AgentRequestFile)):
                extracted = AttachmentSource.extract(req)
                if extracted is None:
                    continue  # no bytes at all, so there is nothing to forward either
                if not extracted.is_base64:
                    self._log.debug(f"Attachment '{extracted.name}' carries no base64 bytes; passing it to the agent undescribed")
                    filtered_requests.append(req)  # the same object, not a copy — the adapter resolves it
                    continue
                descriptions.append(await self._store(extracted, manager, config))
                continue  # the bytes are in storage now, so the raw request must not travel on

            if isinstance(req, AgentRequestText):
                last_text_idx = len(filtered_requests)
            filtered_requests.append(req)

        if not descriptions:
            return filtered_requests

        # Build description text for attachment metadata and inject it.
        desc_text = "\n\n[Attached Images/Files:]\n" + "".join(f"- {att_id}: {desc}\n" for att_id, desc in descriptions)

        if last_text_idx >= 0:
            last_text_req = filtered_requests[last_text_idx]
            filtered_requests[last_text_idx] = AgentRequestText(prompt=f"{last_text_req.prompt}{desc_text}")
        else:
            # No text at all (attachments only) — description becomes the query
            filtered_requests.append(AgentRequestText(prompt=desc_text.strip()))

        return filtered_requests

    async def _describe_stored(
        self,
        req: AgentRequestAttachmentRef,
        manager: AttachmentStorageManager,
        config: _MultimodalConfig,
    ) -> Optional[_AttachmentDescription]:
        """
        Describe an attachment that is already in storage, referenced only by its id.

        This is the thread-mode path: `ChatService` saved the bytes before the run and only the id
        travels in-band, so the bytes are loaded and described but never saved again.

        :param req: The reference request.
        :param manager: The storage manager for this session.
        :param config: Multimodal configuration.
        :return: (attachment_id, description), or None when the id is not in storage.
        """
        stored = manager.get_attachment_data([req.attachment_id])
        if not stored:
            self._log.warning(f"Attachment {req.attachment_id} not found in storage; skipping")
            return None
        attachment = stored[0]
        return req.attachment_id, await self._described(attachment.data, attachment.mime_type, config)

    async def _store(
        self,
        extracted: ExtractedAttachment,
        manager: AttachmentStorageManager,
        config: _MultimodalConfig,
    ) -> _AttachmentDescription:
        """
        Describe an attachment's raw bytes and save them, returning the id storage assigned.

        This is the thread-off path, where the bytes travel on the request itself.

        :param extracted: The attachment pulled off the request, already source-resolved.
        :param manager: The storage manager for this session.
        :param config: Multimodal configuration.
        :return: (attachment_id, description).
        """
        description = await self._described(extracted.data, extracted.mime_type, config)
        attachment_id = manager.save_attachment(
            data=extracted.data,
            attachment_type=extracted.att_type,
            name=extracted.name,
            mime_type=extracted.mime_type,
            description=description,
            max_attachments=config.max_attachments,
        )
        self._log.info(f"Saved {extracted.att_type} {attachment_id}: {extracted.name}")
        return attachment_id, description

    async def _described(self, data: str, mime_type: str, config: _MultimodalConfig) -> str:
        """
        Describe one attachment and clamp the result to the configured length.

        Truncation lives here rather than in `_describe_attachment_briefly` because both storage paths
        need it and that method is what tests replace — folding it in would change what a mock stands
        in for.

        :param data: Base64 encoded attachment data.
        :param mime_type: MIME type of the attachment.
        :param config: Multimodal configuration.
        :return: The description, no longer than `description_max_length`.
        """
        description = await self._describe_attachment_briefly(data=data, mime_type=mime_type)
        return description[: config.description_max_length]

    def name(self) -> str:
        return "MultimodalPreHook"
