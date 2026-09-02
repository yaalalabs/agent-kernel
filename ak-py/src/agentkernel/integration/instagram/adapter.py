"""Instagram Business inbound/outbound adapter pair (spec #524 §9).

Same Meta webhook and Send API contract as Messenger, on the Instagram Graph host: Business
Login for Instagram (without Facebook Login), a tighter message limit, and echo messages to skip.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import Request

from ...core.config import AKConfig
from ...core.model import AgentReply, AgentRequest, AgentRequestFile, AgentRequestImage, AgentRequestText
from ...core.multimodal.storage.offload import offload_attachments
from ..adapter.base import ATTACHMENTS_DISABLED_ERROR, SESSION_CACHE_ERROR, InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter
from ..adapter.meta import MetaSendAPIClient, answer_challenge, verify_signature

NAME = "instagram"
WEBHOOK_PATH = "/instagram/webhook"

_log = logging.getLogger("ak.integration.instagram")


def _client() -> MetaSendAPIClient:
    config = AKConfig.get().instagram
    if not all([config.access_token, config.verify_token]):
        _log.error("Instagram configuration is incomplete. Please set access_token and verify_token.")
        raise ValueError("Incomplete Instagram configuration.")
    return MetaSendAPIClient(
        base_url=f"https://graph.instagram.com/{config.api_version or 'v21.0'}",
        access_token=config.access_token,
        log=_log,
    )


class InstagramInboundAdapter(InboundAdapter):
    """Instagram webhook events -> normalized requests."""

    name = NAME
    webhook_path = WEBHOOK_PATH
    challenge_path = WEBHOOK_PATH

    _log = _log

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.instagram.agent or None
        self._max_file_size = config.api.max_file_size
        self._app_secret = config.instagram.app_secret
        self._verify_token = config.instagram.verify_token
        self._api = _client()

    async def verify(self, raw: Request) -> None:
        await verify_signature(raw, self._app_secret)

    async def challenge(self, raw: Request) -> Any:
        return await answer_challenge(raw, self._verify_token)

    async def parse(self, raw: Request) -> InboundParseResult:
        """Normalize every messaging event in the delivery; one webhook can carry several."""
        body = await raw.json()
        self._log.debug(f"Received Instagram webhook: {body}")
        if body.get("object") != "instagram":
            return InboundParseResult()

        requests: List[InboundRequest] = []
        for entry in body.get("entry", []):
            for event in entry.get("messaging", []):
                parsed = await self._to_request(event)
                if parsed is not None:
                    requests.append(parsed)
        return InboundParseResult(requests=requests)

    async def _to_request(self, event: dict) -> Optional[InboundRequest]:
        """Normalize one messaging event: a message, or a postback treated as its title."""
        sender_id = event.get("sender", {}).get("id")
        if not sender_id:
            self._log.warning("Event missing sender id")
            return None

        if "message" in event:
            message = event["message"]
            message_id = message.get("mid")
            if not message_id:
                self._log.warning("Message missing required field (mid)")
                return None
            if message.get("is_echo"):
                # Our own outbound message, echoed back: answering it would loop.
                self._log.debug(f"Skipping echo message {message_id}")
                return None
            text = (message.get("text") or "").strip()
            attachments = message.get("attachments", [])
            if not text and not attachments:
                self._log.warning("Message has no text content or attachments")
                return None
            return await self._build(sender_id, message_id, text, attachments)

        if "postback" in event:
            postback = event["postback"]
            text = postback.get("title") or postback.get("payload")
            if not text:
                self._log.warning("Postback has no title or payload")
                return None
            # A postback carries no message id of its own; the sender plus the payload is what
            # distinguishes one button press from the next.
            return await self._build(sender_id, f"{NAME}:{sender_id}:{postback.get('payload') or text}", text, [])

        if "read" in event:
            self._log.debug(f"Message read receipt: {event['read']}")
        elif "reaction" in event:
            self._log.debug(f"Reaction received: {event['reaction']}")
        return None

    async def _build(self, sender_id: str, request_id: str, text: str, attachments: list) -> Optional[InboundRequest]:
        requests: List[AgentRequest] = []
        if text:
            requests.append(AgentRequestText(prompt=text))
        for attachment in attachments:
            await self._add_attachment(attachment, requests)

        if not requests:
            return None

        requests, _ = offload_attachments(
            sender_id,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )
        return InboundRequest(
            # Instagram has no thread of its own: the Instagram-scoped user is the conversation.
            session_id=sender_id,
            request_id=request_id,
            requests=requests,
            prompt=text,
            agent=self._agent,
            user_id=sender_id,
            reply_context={"recipient_id": sender_id},
        )

    async def _add_attachment(self, attachment: dict, requests: List[AgentRequest]) -> None:
        """Download one attachment onto ``requests``; tell the agent when it could not be read."""
        url = (attachment.get("payload") or {}).get("url")
        if not url:
            self._log.warning(f"Attachment has no URL: {attachment}")
            return
        try:
            downloaded = await self._api.download_attachment(url, self._max_file_size)
            if downloaded is None:
                return
            data, filename, mime_type = downloaded
            if attachment.get("type") == "image" or mime_type.startswith("image/"):
                requests.append(AgentRequestImage(image_data=data, name=filename, mime_type=mime_type))
            else:
                requests.append(AgentRequestFile(file_data=data, name=filename, mime_type=mime_type))
        except Exception as e:
            # Instagram, unlike Messenger, has never told the agent about a failed attachment.
            self._log.error(f"Error processing attachment: {e}")


class InstagramOutboundAdapter(OutboundAdapter):
    """Agent replies -> Instagram direct messages."""

    name = NAME
    MESSAGE_LIMIT = 1000

    _log = _log

    def __init__(self):
        self._api = _client()

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        """Mark the message seen and start typing, so the user sees something immediately."""
        recipient_id = reply_context["recipient_id"]
        await self._api.sender_action(recipient_id, "mark_seen")
        await self._api.sender_action(recipient_id, "typing_on")
        return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        recipient_id = reply_context["recipient_id"]
        await self._api.sender_action(recipient_id, "typing_off")
        await self._api.send_message(recipient_id, self.split_reply(str(reply)))

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        recipient_id = reply_context["recipient_id"]
        await self._api.sender_action(recipient_id, "typing_off")
        try:
            await self._api.send_message(recipient_id, [message])
        except Exception as e:
            self._log.error(f"Could not deliver the Instagram error message: {e}")
