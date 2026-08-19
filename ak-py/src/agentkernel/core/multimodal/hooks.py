"""
Multimodal PreHook for attachment processing.

This module provides a PreHook that:
1. Detects images/files in the CURRENT request
2. Calls LLM to generate brief descriptions
3. Saves attachments to configurable storage
4. Injects attachment descriptions into the request text
"""

import logging
from dataclasses import dataclass
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


# (attachment_id, description) as injected into the request text.
_AttachmentDescription = tuple[str, str]


@dataclass(frozen=True)
class _ExtractedAttachment:
    """
    One attachment's data pulled off a request, with its source form resolved.

    `consumable` is False for a remote reference (`http://`, `https://`, `s3://`), which this hook
    neither describes nor stores: fetching it would put network I/O and SSRF exposure inside a
    system pre-hook that runs on every request. Such a request must survive into the filtered list
    so the adapter still receives the attachment and resolves it itself.
    """

    data: str
    att_type: str
    name: str
    mime_type: str
    consumable: bool


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
        descriptions, consumed_ids = await self._process_attachments(session, requests, config)

        # Build filtered request list, stripping the attachment requests this hook consumed:
        #  - Raw image/file: their data is saved to storage
        #  - AgentRequestAttachmentRef: the id is resolved and injected (or dropped if unresolved)
        # so a dangling reference is never passed to the agent. A raw image/file the hook declined is
        # kept instead, so the adapter still receives it.
        filtered_requests: list[AgentRequest] = []
        last_text_idx = -1
        for req in requests:
            if isinstance(req, AgentRequestAttachmentRef):
                continue
            if isinstance(req, (AgentRequestImage, AgentRequestFile)) and id(req) in consumed_ids:
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
            filtered_requests[last_text_idx] = AgentRequestText(prompt=f"{last_text_req.prompt}{desc_text}")
        else:
            # No text at all (attachments only) — description becomes the query
            filtered_requests.append(AgentRequestText(prompt=desc_text.strip()))

        return filtered_requests

    async def _process_attachments(
        self,
        session: "Session",
        requests: list[AgentRequest],
        config: _MultimodalConfig,
    ) -> tuple[list[_AttachmentDescription], set[int]]:
        """
        Describe each attachment in the current request.

        Two request shapes are handled:
          - AgentRequestAttachmentRef (thread mode): the bytes were already saved
            by ChatService and only the id travels in-band. Load the bytes from the
            AttachmentStore by id, describe them, and reference the same id — no save.
          - AgentRequestImage / AgentRequestFile (thread-off): raw bytes travel on
            the request; describe and save them here exactly as before.

        The second return value identifies the image/file requests this hook took ownership of, so
        the caller knows which to strip. Identity is by `id(req)` rather than by value because these models are
        unhashable and two equal attachments must still be tracked separately. A request is consumed
        when its bytes were stored, and also when it carries no data at all — nothing can be
        forwarded either way. A request the hook declined is not consumed; see `_ExtractedAttachment`.

        :param session: The current session.
        :param requests: List of current agent requests.
        :param config: Multimodal configuration.
        :return: (descriptions to inject, set of consumed id(req) values).
        """
        descriptions: list[_AttachmentDescription] = []
        consumed: set[int] = set()
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

            if not isinstance(req, (AgentRequestImage, AgentRequestFile)):
                continue

            extracted = self._extract_attachment(req)
            if extracted is None:
                consumed.add(id(req))  # an attachment request with no bytes — nothing to forward
                continue
            if not extracted.consumable:
                self._log.debug(f"Attachment '{extracted.name}' is a remote reference; passing it to the agent undescribed")
                continue
            consumed.add(id(req))

            # Generate brief description via LLM
            description = await self._describe_attachment_briefly(data=extracted.data, mime_type=extracted.mime_type)

            # Truncate to configured max length
            if len(description) > config.description_max_length:
                description = description[: config.description_max_length]

            # Thread-off: save the raw bytes here.
            attachment_id = manager.save_attachment(
                data=extracted.data,
                attachment_type=extracted.att_type,
                name=extracted.name,
                mime_type=extracted.mime_type,
                description=description,
                max_attachments=config.max_attachments,
            )
            self._log.info(f"Saved {extracted.att_type} {attachment_id}: {extracted.name}")
            descriptions.append((attachment_id, description))

        return descriptions, consumed

    @staticmethod
    def _extract_attachment(req: AgentRequest) -> Optional[_ExtractedAttachment]:
        """
        Extract attachment data from a request if it is an image or file, and classify its source.

        :param req: An agent request.
        :return: The extracted attachment, or None if the request carries no attachment data.
        """
        if isinstance(req, AgentRequestImage) and req.image_data:
            data, mime_type, consumable = MultimodalPreHook._resolve_source(req.image_data, req.mime_type, "image/jpeg")
            return _ExtractedAttachment(data, "image", req.name, mime_type, consumable)
        if isinstance(req, AgentRequestFile) and req.file_data:
            data, mime_type, consumable = MultimodalPreHook._resolve_source(req.file_data, req.mime_type, "application/octet-stream")
            return _ExtractedAttachment(data, "file", req.name, mime_type, consumable)
        return None

    @staticmethod
    def _resolve_source(source: str, declared_mime: Optional[str], default_mime: str) -> tuple[str, str, bool]:
        """
        Resolve one attachment source string into its bytes, its mime type, and whether it is usable.

        - `http://`, `https://`, `s3://`: a remote reference, returned unchanged and not consumable.
        - `data:<mime>;base64,<payload>`: split into the payload plus the mime type the URI itself
          declares. The URI wins over `declared_mime` and over `default_mime`, neither of which is
          consulted unless the URI omits its own — this is what stops a PNG being stored as JPEG.
        - Anything else is treated as bare base64, keeping `declared_mime` or `default_mime`.

        A `data:` URI that is not base64-encoded is passed through rather than decoded, since its
        bytes are not what this hook would store. Per RFC 2397 the marker is the final parameter of
        the header, so a header that merely contains the text `;base64` does not qualify.

        Scheme and header matching is case-insensitive, since URI schemes (RFC 3986 §3.1), media
        types and parameter names all are. Only the leading bytes and the short header are folded —
        an attachment payload can be megabytes of base64, and lowercasing it would copy the lot.

        :param source: The raw source string from the request.
        :param declared_mime: The request's own mime_type, if it set one.
        :param default_mime: Fallback when neither the source nor the request declares one.
        :return: (data, mime_type, consumable).
        """
        scheme = source[:8].lower()  # 8 == len("https://"), the longest prefix matched below

        if scheme.startswith(("http://", "https://", "s3://")):
            return source, declared_mime or default_mime, False

        if scheme.startswith("data:"):
            header, _, payload = source.partition(",")
            if not payload or not header.lower().endswith(";base64"):
                return source, declared_mime or default_mime, False
            uri_mime = header[len("data:") :].split(";", 1)[0].lower()
            return payload, uri_mime or declared_mime or default_mime, True

        return source, declared_mime or default_mime, True

    def name(self) -> str:
        return "MultimodalPreHook"
