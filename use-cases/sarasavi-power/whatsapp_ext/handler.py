"""WhatsApp handler subclass: voice notes now, call-webhook routing in v2 voice.

Agent Kernel's ``AgentWhatsAppRequestHandler`` hard-rejects audio messages and
silently drops non-``messages`` webhook fields. This subclass keeps every stock
behavior (verification, signatures, text/image/document paths) via ``super()``
and adds:

* inbound voice notes -> the audio blob rides to Gemini as an inline part
  (the ADK runner already forwards ``AgentRequestFile`` blobs untouched);
* the reply is sent as text (hooks apply) AND as a synthesized voice note.
"""

from __future__ import annotations

import asyncio
import os
import traceback
from contextvars import ContextVar

from agentkernel.core import AgentService, Runtime
from agentkernel.core.model import AgentRequestFile, AgentRequestImage, AgentRequestText
from agentkernel.whatsapp import AgentWhatsAppRequestHandler
from fastapi import HTTPException, Request

from whatsapp_ext import interactive
from whatsapp_ext import media as media_ext

VOICE_CALLS_ENABLED = os.environ.get("SARASAVI_VOICE_ENABLED", "true").strip().lower() in ("1", "true", "yes")

# Sent before the language preference is known, so it covers all three languages.
_MEDIA_ACK = "⏳ One moment... / මොහොතක්... / ஒரு நிமிடம்..."

# Set once per caller: the language chooser is a first-contact question only.
_LANGUAGE_PROMPTED_KEY = "language_prompted"

# Which of the WABA's numbers this webhook arrived on. One Meta app can host
# several numbers (e.g. a test number that may receive calls plus a real number
# open to the public) and they all deliver to this single URL, so replies must go
# out from whichever number the user actually contacted — not a fixed one.
_active_phone_number_id: ContextVar[str | None] = ContextVar("active_phone_number_id", default=None)

# The stored profile language (LanguagePreferenceHook) still steers replies; this
# note only tells the model an audio part is present and how to treat it.
_VOICE_NOTE_INSTRUCTION = (
    "[Voice note] The user sent a voice message, attached as audio. Listen to it, "
    "treat its spoken content as the user's request, and reply in the language "
    "spoken in the audio (English, Sinhala, or Tamil)."
)

# Bill photos are the fastest accurate path to a real reading: a CEB/LECO bill
# prints the units, so reading them beats asking the user to type numbers off a
# page. Gemini reads the image directly — the model must still route the value
# through record_bill_reading so the deterministic engine owns every calculation.
_BILL_PHOTO_INSTRUCTION = (
    "[Photo] The user sent a photograph, attached as an image. If it is a CEB or LECO "
    "electricity bill, or a meter display, read it carefully and extract: the units "
    "consumed in kWh, the number of billing days (or the from/to dates), and the total "
    "amount if shown. Then call record_bill_reading with the units and billing days you "
    "read, and tell the user exactly which numbers you took from the photo so they can "
    "correct you. On a Sri Lankan CEB bill the consumption is usually labelled "
    "'Units', 'kWh', or 'ඒකක'. If the bill instead shows three consumption figures marked "
    "(O), (D) and (P), it is a Domestic Time-of-Use bill: read all three and use the "
    "time-of-use calculation rather than the block one. If any number is blurred or you are unsure, say which "
    "one and ask the user to type just that value. Never guess a number. If the photo "
    "is not a bill or meter, say briefly what you see and steer back to electricity."
)


def _is_bare_greeting(message: dict) -> bool:
    """True when a text message opens the conversation without asking anything.

    Media is never a greeting: a voice note or a bill photo is the whole request.
    For text, a question mark or any digit means there is something to answer, and
    a long message is a real one whatever it contains.
    """
    if message.get("type") != "text":
        return False
    body = ((message.get("text") or {}).get("body") or "").strip()
    if not body or len(body) > 30:
        return False
    return "?" not in body and not any(ch.isdigit() for ch in body)


class SarasaviWhatsAppHandler(AgentWhatsAppRequestHandler):
    """Stock Agent Kernel WhatsApp handler + Sarasavi voice extensions."""

    def __init__(self):
        super().__init__()
        self._call_manager = None  # built lazily on the first `calls` event

    # Base-class code (send, media upload, calls API) reads self._phone_number_id;
    # routing it through the context variable makes every outbound path follow the
    # inbound number automatically, with the configured number as the fallback.
    @property
    def _phone_number_id(self) -> str:
        return _active_phone_number_id.get() or self._configured_phone_number_id

    @_phone_number_id.setter
    def _phone_number_id(self, value: str) -> None:
        self._configured_phone_number_id = value

    async def _handle_webhook(self, request: Request):
        """Route `calls` webhook events (which the base class drops) before
        delegating messages/statuses to the stock handler.

        Meta delivers every subscribed field to this one URL. Call signaling is
        latency-sensitive (the SDP answer has a deadline), so call events are
        dispatched as background tasks first; the base class then re-verifies and
        processes messages exactly as before.
        """
        if VOICE_CALLS_ENABLED:
            if self._app_secret:  # same check the base performs; do not act on unsigned payloads
                signature = request.headers.get("x-hub-signature-256", "")
                if not self._verify_signature(await request.body(), signature):
                    self._log.warning("Invalid request signature")
                    raise HTTPException(status_code=403, detail="Invalid signature")
            try:
                body = await request.json()
                if body.get("object") == "whatsapp_business_account":
                    for entry in body.get("entry", []):
                        for change in entry.get("changes", []):
                            self._bind_inbound_number(change.get("value", {}))
                            for call in change.get("value", {}).get("calls", []) or []:
                                self._log.info(
                                    "Call webhook received: event=%s id=%s from=%s sdp_bytes=%s",
                                    call.get("event"),
                                    call.get("id"),
                                    call.get("from"),
                                    len((call.get("session") or {}).get("sdp", "")),
                                )
                                manager = self._get_call_manager()
                                if manager is None:
                                    self._log.error("No call manager available; dropping call event")
                                    continue
                                task = asyncio.create_task(manager.handle_call_event(call))
                                task.add_done_callback(self._log_call_task_result)
            except HTTPException:
                raise
            except Exception:
                self._log.exception("Error routing call events")
        else:
            # Calls disabled, but replies must still leave from the inbound number.
            try:
                body = await request.json()
                for entry in body.get("entry", []):
                    for change in entry.get("changes", []):
                        self._bind_inbound_number(change.get("value", {}))
            except Exception:
                self._log.exception("Could not read the inbound phone number id")
        return await super()._handle_webhook(request)

    def _bind_inbound_number(self, value: dict) -> None:
        """Pin this request's replies to the number the user contacted.

        asyncio.create_task copies the current context, so call tasks spawned
        below inherit this binding too.
        """
        inbound = (value.get("metadata") or {}).get("phone_number_id")
        if inbound and inbound != _active_phone_number_id.get():
            _active_phone_number_id.set(inbound)
            if inbound != self._configured_phone_number_id:
                self._log.info("Serving a secondary WABA number: %s", inbound)

    def _log_call_task_result(self, task) -> None:
        """Surface exceptions from the detached call task instead of losing them."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self._log.error("Call handling task failed", exc_info=exc)

    def _get_call_manager(self):
        """Build the CallManager once; None when the voice stack cannot load."""
        if self._call_manager is not None:
            return self._call_manager
        try:
            from voice import summary as voice_summary
            from voice.bridge import RTCBridge
            from voice.call_manager import CallManager, CallSession
            from voice.calls_api import WhatsAppCallsAPI
            from voice.live_agent import LIVE_MODEL, VoiceToolExecutor, build_live_config

            calls_api = WhatsAppCallsAPI(self._base_url, self._phone_number_id, self._access_token)

            def live_connect():
                from google import genai

                return genai.Client().aio.live.connect(model=LIVE_MODEL, config=build_live_config())

            async def on_done(call_session):
                executor = call_session._executor
                await voice_summary.store_call_summary(executor, call_session.transcript, call_session.tools_used)
                brief = await voice_summary.brief_topic(call_session.transcript)
                recap = voice_summary.recap_text(
                    call_session.transcript,
                    call_session.tools_used,
                    started_at=call_session.started_at,
                    duration_seconds=call_session.duration_seconds,
                    brief=brief,
                )
                if recap:
                    await self._send_message(call_session.from_number, recap)

            def session_factory(call_id, from_number, offer_sdp):
                return CallSession(
                    call_id,
                    from_number,
                    offer_sdp,
                    calls_api=calls_api,
                    bridge=RTCBridge(),
                    live_connect=live_connect,
                    executor=VoiceToolExecutor(from_number),
                    on_done=on_done,
                )

            async def send_text(to_number, text):
                await self._send_message(to_number, text)

            self._call_manager = CallManager(calls_api, session_factory, send_text=send_text)
        except Exception:
            self._log.exception("Voice call stack unavailable; call events will be ignored")
            self._call_manager = None
        return self._call_manager

    async def _handle_message(self, message: dict, value: dict):
        message_type = message.get("type")
        if await self._maybe_prompt_language(message):
            return
        if message_type == "audio":
            await self._handle_audio_message(message, value)
            return
        if message_type == "image":
            await self._handle_image_message(message, value)
            return
        await super()._handle_message(message, value)

    async def _maybe_prompt_language(self, message: dict) -> bool:
        """On first contact, offer the language buttons instead of answering.

        Script detection cannot see romanized Sinhala/Tamil ("mata bill eka
        danaganna one"), which is what most people actually type, so those users
        would silently get an English assistant. Asking once, up front, removes
        the guess. Returns True when this message was consumed by the prompt.
        """
        from_number = message.get("from")
        if not from_number:
            return False

        try:
            runtime = Runtime.current()
            session = runtime.sessions().load(from_number)
            cache = session.get_non_volatile_cache()

            # A tapped button settles it; record and let the agent answer normally.
            chosen = interactive.language_from_reply(message)
            if chosen:
                cache.set(_LANGUAGE_PROMPTED_KEY, chosen)
                runtime.sessions().store(session)
                return False

            if cache.get(_LANGUAGE_PROMPTED_KEY, None) is not None:
                return False

            # Only greet-and-ask when the message carries nothing to answer.
            # Consuming a real question to ask a housekeeping one loses the very
            # thing the user came to say, and their language is usually evident
            # from the question anyway.
            if not _is_bare_greeting(message):
                cache.set(_LANGUAGE_PROMPTED_KEY, "skipped")
                runtime.sessions().store(session)
                return False

            sent = await interactive.send_language_prompt(
                self._base_url, self._phone_number_id, self._access_token, from_number
            )
            if not sent:
                # Never strand the user behind a failed prompt: mark it done and
                # let the normal (script-detecting) flow answer this message.
                cache.set(_LANGUAGE_PROMPTED_KEY, "skipped")
                runtime.sessions().store(session)
                return False

            cache.set(_LANGUAGE_PROMPTED_KEY, "asked")
            runtime.sessions().store(session)
            return True
        except Exception:
            self._log.exception("Language prompt failed; continuing with normal handling")
            return False

    async def _handle_image_message(self, message: dict, value: dict):
        """Bill/meter photo -> Gemini reads it -> record_bill_reading.

        The stock path forwards images with a bare "[Image received]" caption,
        which gives the model no reason to extract a reading. Sending an explicit
        instruction alongside the image turns a photo into a real bill reading.
        """
        message_id = message.get("id")
        from_number = message.get("from")
        if not from_number or not message_id:
            self._log.warning("Image message missing required fields (from/id)")
            return

        image_info = message.get("image", {})
        media_id = image_info.get("id")
        if not media_id:
            self._log.warning("Image message %s carries no media id", message_id)
            return

        media_size, media_mime_type = await self._get_media_info(media_id)
        if media_size is None:
            await self._send_message(
                from_number, "Sorry, I could not retrieve that photo. Please try again.", message_id
            )
            return
        if media_size > self._max_file_size:
            await self._send_message(
                from_number,
                "Sorry, that photo is too large. Please send a smaller one, or type the units from your bill.",
                message_id,
            )
            return

        image_data = await self._download_media(media_id)
        if image_data is None:
            await self._send_message(
                from_number, "Sorry, I could not download that photo. Please try again.", message_id
            )
            return

        # A caption is the user's own request about the photo; keep it.
        caption = (image_info.get("caption") or "").strip()
        instruction = _BILL_PHOTO_INSTRUCTION
        if caption:
            instruction = f"{instruction}\n\nUser's caption: {caption}"
        requests = [
            AgentRequestText(text=instruction),
            AgentRequestImage(
                image_data=image_data,
                name=f"bill_photo_{message_id}.jpg",
                mime_type=media_mime_type or image_info.get("mime_type") or "image/jpeg",
            ),
        ]
        await self._run_and_reply(from_number, message_id, requests, "photo")

    async def _handle_audio_message(self, message: dict, value: dict):
        """Mirror the stock document path, but for voice notes, and answer in kind."""
        message_id = message.get("id")
        from_number = message.get("from")
        if not from_number or not message_id:
            self._log.warning("Audio message missing required fields (from/id)")
            return

        audio_info = message.get("audio", {})
        media_id = audio_info.get("id")
        if not media_id:
            self._log.warning("Audio message %s carries no media id", message_id)
            return

        media_size, media_mime_type = await self._get_media_info(media_id)
        if media_size is None:
            await self._send_message(
                from_number, "Sorry, I could not retrieve your voice note. Please try again.", message_id
            )
            return
        if media_size > self._max_file_size:
            await self._send_message(
                from_number,
                "Sorry, that voice note is too large. Please send a shorter one or type your question.",
                message_id,
            )
            return

        audio_data = await self._download_media(media_id)
        if audio_data is None:
            await self._send_message(
                from_number, "Sorry, I could not download your voice note. Please try again.", message_id
            )
            return

        requests = [
            AgentRequestText(text=_VOICE_NOTE_INSTRUCTION),
            AgentRequestFile(
                file_data=audio_data,
                name=f"voice_note_{message_id}.ogg",
                mime_type=media_mime_type or audio_info.get("mime_type") or "audio/ogg",
            ),
        ]

        await self._run_and_reply(from_number, message_id, requests, "voice note", voice_reply=True)

    async def _run_and_reply(
        self,
        from_number: str,
        message_id: str,
        requests: list,
        kind: str,
        *,
        voice_reply: bool = False,
    ) -> None:
        """Run the agent over a multimodal request and deliver the reply.

        Shared by the voice-note and photo paths so both get the same
        acknowledgement, hook pipeline and error handling. ``voice_reply`` adds a
        spoken copy — right when the user spoke to us, noise otherwise.
        """
        service = AgentService()
        try:
            # Only the slow paths acknowledge. Transcribing a voice note or reading
            # a bill photo takes several seconds, so silence would look broken;
            # a plain text answer is fast enough that an ack is just extra noise.
            await self._send_message(from_number, _MEDIA_ACK, message_id)

            service.select(session_id=from_number, name=self._whatsapp_agent)
            if not service.agent:
                await self._send_message(
                    from_number, "Sorry, no agent is available to handle your request.", message_id
                )
                return

            result = await service.run_multi(requests=requests)
            response_text = str(result)
            await self._send_message(from_number, response_text, message_id)
            if voice_reply:
                await self._send_voice_reply(from_number, response_text)
        except Exception as e:
            self._log.error(f"Error handling {kind}: {e}\n{traceback.format_exc()}")
            await self._send_message(from_number, f"Sorry, there was an error processing your {kind}.", message_id)

    async def _send_voice_reply(self, to_number: str, text: str) -> None:
        """Best-effort spoken version of the reply; the text message is canonical."""
        try:
            ogg = await asyncio.to_thread(media_ext.render_voice_reply, text)
            if not ogg:
                return
            media_id = await media_ext.upload_media(
                self._base_url, self._phone_number_id, self._access_token, ogg, "audio/ogg"
            )
            if media_id:
                await media_ext.send_audio(
                    self._base_url, self._phone_number_id, self._access_token, to_number, media_id
                )
        except Exception:
            self._log.exception("Voice reply failed; text reply was already delivered")
