"""Telegram Bot API inbound/outbound adapter pair (spec #524 §9).

The adapter parses the whole update object rather than just its ``message``, so Telegram's
``update_id`` — the id it retries with — becomes the deduplication key. A press on a pause button
is the one exception: see :meth:`TelegramInboundAdapter._decision`.
"""

import base64
import logging
import mimetypes
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException, Request

from ...core.config import AKConfig
from ...core.model import (
    AgentPausedReplyAny,
    AgentReply,
    AgentRequest,
    AgentRequestFile,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from ...core.multimodal.storage import AttachmentStorageManager
from ..adapter.base import ATTACHMENTS_DISABLED_ERROR, SESSION_CACHE_ERROR, InboundAdapter, InboundParseResult, InboundRequest, OutboundAdapter
from ..adapter.routes import BUILTIN_WEBHOOK_ROUTES

NAME = "telegram"
HTTP_TIMEOUT = 30.0

CALLBACK_PREFIX = "akhitl:"
"""What marks an inline-keyboard press as a decision on a paused run.

Specific rather than short: an application may already ship its own inline keyboards, and a
two-letter prefix would turn its presses into decisions.
"""
CALLBACK_LIMIT = 64
"""Telegram's ``callback_data`` budget, in bytes — a multibyte character costs more than one."""
VERB_CODES = {"approved": "a", "denied": "d", "cancelled": "c"}
"""A wire format: a code is never reused for another verb, because a message outlives a deploy."""
VERBS_BY_CODE = {code: verb for verb, code in VERB_CODES.items()}
BUTTON_LABELS = {"approved": "✓ Approve", "denied": "✗ Deny", "cancelled": "⊘ Cancel"}

_log = logging.getLogger("ak.integration.telegram")

START_MESSAGE = "👋 Hello! I'm an AI assistant powered by Agent Kernel. How can I help you today?"
HELP_MESSAGE = "Send me any message and I'll respond using AI. Available commands:\n/start - Start conversation\n/help - Show this help"


class _TelegramClient:
    """The Bot API calls both halves make."""

    def __init__(self):
        config = AKConfig.get().telegram
        self._bot_token = config.bot_token
        if not self._bot_token:
            _log.error("Telegram bot token is not configured. Please set bot_token.")
            raise ValueError("Incomplete Telegram configuration.")
        self._base_url = f"https://api.telegram.org/{config.api_version or 'bot'}{self._bot_token}"
        self._webhook_secret = config.webhook_secret

    @property
    def webhook_secret(self) -> str:
        return self._webhook_secret

    async def send_message(self, chat_id: str, chunks: List[str], reply_markup: Optional[dict] = None) -> None:
        """Send each chunk as its own message, in order.

        ``reply_markup`` rides on the last chunk alone, so a keyboard sits under the end of a split
        reply instead of repeating under every piece of it.
        """
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for index, chunk in enumerate(chunks):
                payload: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
                if reply_markup and index == len(chunks) - 1:
                    payload["reply_markup"] = reply_markup
                response = await client.post(f"{self._base_url}/sendMessage", json=payload)
                response.raise_for_status()
                _log.debug(f"Message sent successfully: {response.json()}")

    async def chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Send a typing indicator. Never raises: it is a courtesy."""
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(f"{self._base_url}/sendChatAction", json={"chat_id": chat_id, "action": action})
                response.raise_for_status()
        except Exception as e:
            _log.warning(f"Failed to send chat action: {e}")

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None:
        """Clear the loading state on an inline keyboard press. Never raises."""
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(f"{self._base_url}/answerCallbackQuery", json=payload)
                response.raise_for_status()
        except Exception as e:
            _log.warning(f"Failed to answer callback query: {e}")

    async def file_info(self, file_id: str) -> Optional[dict]:
        """Resolve a file id to its path and declared size."""
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(f"{self._base_url}/getFile", json={"file_id": file_id})
                response.raise_for_status()
                result = response.json()
            if result.get("ok"):
                return result.get("result")
            _log.error(f"Failed to get file info: {result}")
        except Exception as e:
            _log.error(f"Error getting file info: {e}")
        return None

    async def download(self, file_path: str) -> Optional[bytes]:
        """Download a file from Telegram's file host."""
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(f"https://api.telegram.org/file/bot{self._bot_token}/{file_path}")
                response.raise_for_status()
                return response.content
        except Exception as e:
            _log.error(f"Error downloading file from Telegram: {e}")
            return None


class TelegramInboundAdapter(InboundAdapter):
    """Telegram updates -> normalized requests."""

    name = NAME
    webhook_path = BUILTIN_WEBHOOK_ROUTES[NAME].webhook_path

    _log = _log

    def __init__(self):
        config = AKConfig.get()
        self._agent = config.telegram.agent or None
        self._max_file_size = config.api.max_file_size
        self._client = _TelegramClient()

    def success_response(self) -> Any:
        """Telegram expects its own acknowledgement shape."""
        return {"ok": True}

    def missing_verification_settings(self) -> List[str]:
        """Without a webhook secret the secret-token header is never checked (``verify``)."""
        return [] if self._client.webhook_secret else ["telegram.webhook_secret"]

    async def verify(self, raw: Request) -> None:
        """Check the secret token Telegram was configured to send, when one is set."""
        if not self._client.webhook_secret:
            return
        if raw.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != self._client.webhook_secret:
            self._log.warning("Invalid webhook secret token on foreground route request.")
            raise HTTPException(status_code=403, detail="Invalid secret token")

    async def parse(self, raw: Request) -> InboundParseResult:
        """Normalize one update: a message, an edited message, or a callback query."""
        update = await raw.json()
        self._log.debug(f"Received Telegram update: {update}")
        # The whole update, not update["message"]: update_id is the id Telegram retries with.
        update_id = update.get("update_id")

        if "message" in update:
            request = await self._from_message(update["message"], update_id)
        elif "edited_message" in update:
            # An edit is treated as a new message, as it always has been.
            request = await self._from_message(update["edited_message"], update_id)
        elif "callback_query" in update:
            request = await self._from_callback_query(update["callback_query"], update_id)
        else:
            self._log.debug(f"Unhandled update type: {list(update.keys())}")
            request = None

        return InboundParseResult(requests=[request] if request is not None else [])

    async def _from_message(self, message: dict, update_id: Any) -> Optional[InboundRequest]:
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        if not chat_id or not message_id:
            self._log.warning("Message missing required fields (chat_id/message_id)")
            return None

        # A media message carries its text in `caption` instead of `text`.
        text = (message.get("text") or message.get("caption") or "").strip()
        if not text and "document" not in message and "photo" not in message:
            self._log.warning("Message has no text, files, or images")
            return None

        self._log.debug(f"Processing message {message_id} from chat {chat_id}")

        if text.startswith("/") and text in ("/start", "/help"):
            # Answered here rather than by the agent, as before: no run is needed.
            await self._client.send_message(str(chat_id), [START_MESSAGE if text == "/start" else HELP_MESSAGE])
            return None

        sender_id = (message.get("from") or {}).get("id")
        return await self._build(chat_id, update_id, text, message, str(sender_id) if sender_id is not None else None)

    async def _from_callback_query(self, callback_query: dict, update_id: Any) -> Optional[InboundRequest]:
        """An inline keyboard press: a decision when the data is ours, otherwise the message text."""
        chat_id = (callback_query.get("message") or {}).get("chat", {}).get("id")
        data = callback_query.get("data")
        self._log.debug(f"Processing callback query {callback_query.get('id')}: {data}")
        await self._client.answer_callback_query(callback_query.get("id"), "Processing...")
        if not chat_id or not data:
            return None
        sender_id = (callback_query.get("from") or {}).get("id")
        sender = str(sender_id) if sender_id is not None else None
        if data.startswith(CALLBACK_PREFIX):
            return self._decision(callback_query, chat_id, data, sender)
        return await self._build(chat_id, update_id, data, None, sender)

    def _decision(self, callback_query: dict, chat_id: Any, data: str, sender: Optional[str]) -> Optional[InboundRequest]:
        """A press on a pause button, as the decision it carries.

        The request id is composed from the press rather than taken from ``update_id``, which
        Telegram mints per update: on that id a second click on the same button would be a new
        request, reach a pause already answered, and earn the user an error for pressing twice.

        :param callback_query: The press, carrying the message it was attached to.
        :param chat_id: The conversation, which is the session.
        :param data: The callback data, already known to carry this adapter's prefix.
        :param sender: Who pressed, so a pre-hook can decide whether they may.
        :return: The decision as a request, or None when the data does not parse.
        """
        parsed = self._parse_callback_data(data)
        if parsed is None:
            return None
        interruption_id, status = parsed
        message_id = (callback_query.get("message") or {}).get("message_id")
        session_id = str(chat_id)
        return InboundRequest(
            session_id=session_id,
            request_id=f"{NAME}:{session_id}:{message_id}:{interruption_id}:{status}",
            requests=[AgentResumeRequestAny(decisions=[ResumeDecision(id=interruption_id, status=status)])],
            agent=self._agent,
            user_id=sender,
            reply_context={"chat_id": session_id},
        )

    @staticmethod
    def _parse_callback_data(data: str) -> Optional[tuple[str, str]]:
        """Read ``akhitl:<verb code>:<interruption id>`` back into the pair it encodes.

        :param data: The callback data carrying this adapter's prefix.
        :return: The interruption id and the decision's status, or None when either is missing.
        """
        code, _, interruption_id = data[len(CALLBACK_PREFIX) :].partition(":")
        status = VERBS_BY_CODE.get(code)
        if not status or not interruption_id:
            _log.warning(f"Ignoring a press whose callback data does not parse: {data}")
            return None
        return interruption_id, status

    async def _build(self, chat_id: Any, update_id: Any, text: str, message: Optional[dict], sender_id: Optional[str]) -> Optional[InboundRequest]:
        session_id = str(chat_id)
        requests: List[AgentRequest] = []
        if text:
            requests.append(AgentRequestText(prompt=text))
        if message:
            failed = await self._process_files(message, requests)
            if failed:
                self._log.warning(f"Failed to process files: {failed}")

        if not requests:
            self._log.warning("No valid content found in message")
            await self._client.send_message(session_id, ["Sorry, your message appears to be empty."])
            return None

        requests, _ = AttachmentStorageManager.offload(
            session_id,
            requests,
            attachments_disabled_error=ATTACHMENTS_DISABLED_ERROR,
            session_cache_error=SESSION_CACHE_ERROR,
        )
        return InboundRequest(
            # The chat is the conversation.
            session_id=session_id,
            request_id=str(update_id),
            requests=requests,
            prompt=text,
            agent=self._agent,
            user_id=sender_id,
            reply_context={"chat_id": session_id},
        )

    async def _process_files(self, message: dict, requests: List[AgentRequest]) -> List[str]:
        """Download the message's photo and document, if any.

        :return: Names of the attachments that could not be taken.
        """
        failed: List[str] = []
        photos = message.get("photo") or []
        if photos:
            # Telegram sends every rendition; the last is the largest.
            await self._add_file(photos[-1].get("file_id"), "photo", None, requests, failed, as_image=True)
        if "document" in message:
            document = message.get("document", {})
            await self._add_file(
                document.get("file_id"),
                document.get("file_name", "document"),
                document.get("mime_type", "application/octet-stream"),
                requests,
                failed,
                as_image=False,
            )
        return failed

    async def _add_file(
        self,
        file_id: Optional[str],
        label: str,
        mime_type: Optional[str],
        requests: List[AgentRequest],
        failed: List[str],
        as_image: bool,
    ) -> None:
        """Resolve, size-check and download one attachment onto ``requests``."""
        try:
            info = await self._client.file_info(file_id) if file_id else None
            if not info:
                self._log.warning(f"Failed to get file info for {label}")
                failed.append(label)
                return

            file_path = info.get("file_path")
            declared_size = info.get("file_size")
            # Skip before downloading only on a known positive size over the limit; Telegram
            # omits the size for some files, and an unknown size is checked after download.
            if isinstance(declared_size, int) and declared_size > 0 and declared_size > self._max_file_size:
                self._log.warning(f"'{label}' is too large to process ({declared_size} bytes > {self._max_file_size} bytes). Skipping.")
                failed.append(label)
                return
            if not file_path:
                self._log.warning(f"File path is missing from file info for {label}")
                failed.append(label)
                return

            content = await self._client.download(file_path)
            if content is None:
                self._log.warning(f"Failed to download {label}")
                failed.append(label)
                return
            if len(content) > self._max_file_size:
                self._log.warning(f"Downloaded '{label}' is too large ({len(content)} bytes > {self._max_file_size} bytes). Skipping.")
                failed.append(label)
                return

            encoded = base64.b64encode(content).decode("utf-8")
            if as_image:
                name = file_path.rsplit("/", 1)[-1]
                guessed, _ = mimetypes.guess_type(file_path)
                requests.append(AgentRequestImage(image_data=encoded, name=name, mime_type=guessed or "image/jpeg"))
            else:
                requests.append(AgentRequestFile(file_data=encoded, name=label, mime_type=mime_type))
            self._log.debug(f"Added {label} to request (size: {len(content)} bytes)")
        except Exception as e:
            self._log.error(f"Error processing {label}: {e}")
            failed.append(label)


class TelegramOutboundAdapter(OutboundAdapter):
    """Agent replies -> Telegram messages."""

    name = NAME
    MESSAGE_LIMIT = 4096
    UNPRESSABLE_NOTICE = "These cannot be answered from Telegram, because their ids exceed the button size limit: {ids}"

    _log = _log

    def __init__(self):
        self._client = _TelegramClient()

    async def acknowledge(self, reply_context: Dict[str, str]) -> Dict[str, str]:
        await self._client.chat_action(reply_context["chat_id"], "typing")
        return {}

    async def deliver(self, reply: AgentReply, reply_context: Dict[str, str]) -> None:
        await self._client.send_message(reply_context["chat_id"], self.split_reply(str(reply)))

    async def deliver_paused(self, reply: AgentPausedReplyAny, reply_context: Dict[str, str]) -> None:
        """Send the pause with an inline keyboard, so it can be answered by pressing."""
        rows, unpressable = self._rows(reply)
        text = self.format_pause(reply)
        if unpressable:
            text = f"{text}\n\n{self.UNPRESSABLE_NOTICE.format(ids=', '.join(unpressable))}"
        markup = {"inline_keyboard": rows} if rows else None
        await self._client.send_message(reply_context["chat_id"], self.split_reply(text), reply_markup=markup)

    def _rows(self, reply: AgentPausedReplyAny) -> tuple[list, List[str]]:
        """One row of buttons per interruption, in the verbs this adapter offers.

        An interruption whose callback data will not fit Telegram's budget gets no row — the ids
        are the framework's own, so their length is not Agent Kernel's to bound — and is named
        back to the caller. Saying so in the message matters: the pause text shows an
        interruption's id only when the framework named nothing else, so two gated calls to the
        same tool read alike and a reader could not tell which one has no buttons.

        :param reply: The paused reply to draw.
        :return: The keyboard rows, and the ids of the interruptions that could not get one.
        """
        rows, unpressable = [], []
        for interruption in reply.interruptions:
            row = [
                {"text": BUTTON_LABELS[verb], "callback_data": f"{CALLBACK_PREFIX}{VERB_CODES[verb]}:{interruption.id}"} for verb in self.DECISIONS
            ]
            oversized = [button for button in row if len(button["callback_data"].encode()) > CALLBACK_LIMIT]
            if oversized:
                self._log.warning(
                    f"Interruption '{interruption.id}' needs {len(oversized[0]['callback_data'].encode())} bytes of callback_data, "
                    f"over Telegram's {CALLBACK_LIMIT}; rendering it without buttons"
                )
                unpressable.append(interruption.id)
                continue
            rows.append(row)
        return rows, unpressable

    async def deliver_error(self, message: str, reply_context: Dict[str, str]) -> None:
        try:
            await self._client.send_message(reply_context["chat_id"], [message])
        except Exception as e:
            self._log.error(f"Could not deliver the Telegram error message: {e}")
