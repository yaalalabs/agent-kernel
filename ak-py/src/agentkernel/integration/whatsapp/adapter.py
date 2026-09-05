"""WhatsApp Cloud API inbound/outbound adapter pair (spec #524 §9)."""

import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import Request

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import ATTACHMENTS_DISABLED_ERROR, SESSION_CACHE_ERROR, InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter
from ..adapter.meta import answer_challenge, verify_signature

NAME = "whatsapp"
WEBHOOK_PATH = "/whatsapp/webhook"


class _WhatsAppClient:
    """The Cloud API calls both halves make."""

    _log = logging.getLogger("ak.integration.whatsapp")

    def __init__(self):
        config = AKConfig.get().whatsapp
        self._access_token = config.access_token
        self._phone_number_id = config.phone_number_id
        self._verify_token = config.verify_token
        self._app_secret = config.app_secret
        self._base_url = f"https://graph.facebook.com/{config.api_version or 'v24.0'}"
        if not all([self._access_token, self._phone_number_id, self._verify_token]):
            self._log.error("WhatsApp configuration is incomplete. Please set access_token, phone_number_id, and verify_token.")
            raise ValueError("Incomplete WhatsApp configuration.")

    @property
    def app_secret(self) -> str:
        return self._app_secret

    @property
    def verify_token(self) -> str:
        return self._verify_token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

    async def send_message(self, to_number: str, chunks: List[str], reply_to_message_id: Optional[str] = None) -> None:
        """Send a (possibly split) message, replying to the original on the first chunk only."""
        url = f"{self._base_url}/{self._phone_number_id}/messages"
        async with httpx.AsyncClient() as client:
            for index, chunk in enumerate(chunks):
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": chunk},
                }
                if index == 0 and reply_to_message_id:
                    payload["context"] = {"message_id": reply_to_message_id}
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                self._log.debug(f"Message sent successfully: {response.json()}")

    async def media_info(self, media_id: str) -> Tuple[Optional[int], Optional[str]]:
        """Get a media file's size and MIME type, so an oversized file is refused before download."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/{media_id}", headers={"Authorization": f"Bearer {self._access_token}"})
                response.raise_for_status()
                info = response.json()
            file_size = info.get("file_size")
            if file_size is None:
                self._log.error(f"No file size found for media ID {media_id}")
                return None, None
            return int(file_size), info.get("mime_type")
        except Exception as e:
            self._log.error(f"Error getting media info {media_id}: {e}")
            return None, None

    async def download_media(self, media_id: str) -> Optional[str]:
        """Download a media file and return it base64-encoded."""
        try:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/{media_id}", headers=headers)
                response.raise_for_status()
                media_url = response.json().get("url")
                if not media_url:
                    self._log.error(f"No URL found for media ID {media_id}")
                    return None
                media = await client.get(media_url, headers=headers)
                media.raise_for_status()
            return base64.b64encode(media.content).decode("utf-8")
        except Exception as e:
            self._log.error(f"Error downloading media {media_id}: {e}")
            return None


class WhatsAppInboundAdapter(InboundAdapter):
    """WhatsApp webhook events -> normalized requests."""

    name = NAME
    webhook_path = WEBHOOK_PATH
    challenge_path = WEBHOOK_PATH

    _log = logging.getLogger("ak.integration.whatsapp")

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.whatsapp.agent or None
        self._max_file_size = config.api.max_file_size
        self._client = _WhatsAppClient()

    async def verify(self, raw: Request) -> None:
        await verify_signature(raw, self._client.app_secret)

    async def challenge(self, raw: Request) -> Any:
        return await answer_challenge(raw, self._client.verify_token)

    async def parse(self, raw: Request) -> InboundParseResult:
        """Normalize every message in the delivery; one webhook can carry several."""
        body = await raw.json()
        self._log.debug(f"Received WhatsApp webhook: {body}")
        if body.get("object") != "whatsapp_business_account":
            return InboundParseResult()

        requests: List[InboundRequest] = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status in value.get("statuses", []):
                    self._log.debug(f"Message status update: {status}")
                for message in value.get("messages", []):
                    parsed = await self._to_request(message)
                    if parsed is not None:
                        requests.append(parsed)
        return InboundParseResult(requests=requests)

    async def _to_request(self, message: dict) -> Optional[InboundRequest]:
        """Normalize one WhatsApp message, or None when it carries nothing runnable."""
        message_id = message.get("id")
        from_number = message.get("from")
        message_type = message.get("type")
        if not from_number or not message_id:
            self._log.warning("Message missing required fields (from/id)")
            return None

        self._log.debug(f"Processing message {message_id} from {from_number} of type {message_type}")

        requests: List[AgentRequest] = []
        text: Optional[str] = None

        if message_type == "text":
            text = message.get("text", {}).get("body")
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title")
        elif message_type in ("image", "document"):
            text = await self._add_media(message, message_type, message_id, from_number, requests)
            if text is None:
                return None
        elif message_type in ("video", "audio"):
            await self._say(from_number, "Sorry, audio and video messages are not supported yet.", message_id)
            return None

        if not text:
            self._log.warning(f"Unsupported message type: {message_type}")
            return None

        requests.insert(0, AgentRequestText(prompt=text))
        requests, _ = offload_attachments(
            from_number,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )

        return InboundRequest(
            # The sender's number is the conversation: WhatsApp has no thread of its own.
            session_id=from_number,
            request_id=message_id,
            requests=requests,
            prompt=text,
            agent=self._agent,
            user_id=from_number,
            reply_context={"to": from_number, "reply_to_message_id": message_id},
        )

    async def _add_media(self, message: dict, message_type: str, message_id: str, from_number: str, requests: List[AgentRequest]) -> Optional[str]:
        """Download an image or document onto ``requests``.

        :return: The caption to use as the prompt, or None when the media could not be taken.
        """
        info = message.get(message_type, {})
        caption = info.get("caption", "")
        filename = info.get("filename", "document")
        label = "[Image received]" if message_type == "image" else f"[Document received: {filename}]"
        media_id = info.get("id")
        if not media_id:
            return caption or label

        noun = "image" if message_type == "image" else f"document '{filename}'"
        media_size, media_mime_type = await self._client.media_info(media_id)
        if media_size is None:
            await self._say(from_number, f"Sorry, I could not retrieve the {noun} information. Please try again.", message_id)
            return None
        if media_size > self._max_file_size:
            await self._say(
                from_number,
                f"Sorry, the {noun} file size ({media_size / (1024 * 1024):.2f} MB) exceeds the maximum allowed size of "
                f"{self._max_file_size / (1024 * 1024):.2f} MB.",
                message_id,
            )
            return None

        data = await self._client.download_media(media_id)
        if data is None:
            await self._say(from_number, f"Sorry, I could not download the {noun}. Please try again.", message_id)
            return None

        if message_type == "image":
            requests.append(
                AgentRequestImage(
                    image_data=data, name=f"whatsapp_image_{message_id}", mime_type=media_mime_type or info.get("mime_type", "image/jpeg")
                )
            )
        else:
            requests.append(AgentRequestFile(file_data=data, name=filename, mime_type=media_mime_type or info.get("mime_type")))
        self._log.info(f"{noun} downloaded and added to request")
        return caption or label

    async def _say(self, to_number: str, text: str, reply_to_message_id: Optional[str]) -> None:
        """Tell the sender why their message is not being run."""
        try:
            await self._client.send_message(to_number, [text], reply_to_message_id)
        except Exception as e:
            self._log.error(f"Could not send a WhatsApp message: {e}")


class WhatsAppOutboundAdapter(OutboundAdapter):
    """Agent replies -> WhatsApp messages."""

    name = NAME
    MESSAGE_LIMIT = 4096

    _log = logging.getLogger("ak.integration.whatsapp")

    def __init__(self):
        self._acknowledgement = AKConfig.get().whatsapp.agent_acknowledgement or None
        self._client = _WhatsAppClient()

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        if self._acknowledgement:
            try:
                await self._client.send_message(reply_context["to"], [self._acknowledgement], reply_context.get("reply_to_message_id"))
            except Exception as e:
                self._log.warning(f"Could not send the WhatsApp acknowledgement: {e}")
        return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        await self._client.send_message(reply_context["to"], self.split_reply(str(reply)), reply_context.get("reply_to_message_id"))

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        try:
            await self._client.send_message(reply_context["to"], [message], reply_context.get("reply_to_message_id"))
        except Exception as e:
            self._log.error(f"Could not deliver the WhatsApp error message: {e}")
