"""Voice-note handler tests: request composition and graceful degradation.

Keyless: WhatsApp and Gemini are faked; only the handler's own logic runs.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from agentkernel.core.model import AgentRequestFile, AgentRequestText

from whatsapp_ext import media as media_ext
from whatsapp_ext.handler import _VOICE_NOTE_INSTRUCTION, SarasaviWhatsAppHandler


def _handler() -> SarasaviWhatsAppHandler:
    instance = SarasaviWhatsAppHandler.__new__(SarasaviWhatsAppHandler)
    import logging

    instance._log = logging.getLogger("test.whatsapp")
    instance._whatsapp_agent = "orchestrator"
    instance._whatsapp_agent_acknowledgement = None
    instance._access_token = "token"
    instance._phone_number_id = "12345"
    instance._base_url = "https://graph.facebook.com/v24.0"
    instance._max_file_size = 10 * 1024 * 1024
    return instance


_AUDIO_MESSAGE = {
    "id": "wamid.audio1",
    "from": "94771234567",
    "type": "audio",
    "audio": {"id": "media-1", "mime_type": "audio/ogg; codecs=opus", "voice": True},
}


def test_audio_message_builds_text_plus_audio_requests() -> None:
    handler = _handler()
    handler._get_media_info = AsyncMock(return_value=(2048, "audio/ogg"))
    handler._download_media = AsyncMock(return_value="ZmFrZS1vZ2c=")
    handler._send_message = AsyncMock()
    handler._send_voice_reply = AsyncMock()

    captured: dict = {}

    class FakeService:
        agent = object()

        def select(self, session_id, name):
            captured["session_id"] = session_id
            captured["agent"] = name

        async def run_multi(self, requests):
            captured["requests"] = requests
            return "Your estimated bill is LKR 630."

    with patch("whatsapp_ext.handler.AgentService", FakeService):
        asyncio.run(handler._handle_audio_message(_AUDIO_MESSAGE, {}))

    requests = captured["requests"]
    assert captured["session_id"] == "94771234567"
    assert isinstance(requests[0], AgentRequestText)
    assert requests[0].text == _VOICE_NOTE_INSTRUCTION
    assert isinstance(requests[1], AgentRequestFile)
    assert requests[1].file_data == "ZmFrZS1vZ2c="
    assert requests[1].mime_type == "audio/ogg"
    handler._send_message.assert_awaited()  # text reply is canonical
    handler._send_voice_reply.assert_awaited_once()


def test_oversized_voice_note_is_rejected_politely() -> None:
    handler = _handler()
    handler._get_media_info = AsyncMock(return_value=(50 * 1024 * 1024, "audio/ogg"))
    handler._download_media = AsyncMock()
    handler._send_message = AsyncMock()

    asyncio.run(handler._handle_audio_message(_AUDIO_MESSAGE, {}))

    handler._download_media.assert_not_awaited()
    text = handler._send_message.await_args.args[1]
    assert "too large" in text


def test_non_audio_messages_delegate_to_stock_handler() -> None:
    handler = _handler()
    with patch.object(SarasaviWhatsAppHandler.__mro__[1], "_handle_message", new=AsyncMock()) as base:
        asyncio.run(handler._handle_message({"type": "text", "id": "1", "from": "2"}, {}))
    base.assert_awaited_once()


def test_voice_reply_failure_never_raises() -> None:
    handler = _handler()
    with patch.object(media_ext, "render_voice_reply", side_effect=RuntimeError("tts down")):
        asyncio.run(handler._send_voice_reply("94771234567", "hello"))


def test_pcm_to_ogg_opus_produces_ogg_container() -> None:
    # 200ms of silence at 24kHz mono PCM16.
    pcm = b"\x00\x00" * 4800

    ogg = media_ext.pcm_to_ogg_opus(pcm)

    assert ogg is not None
    assert ogg[:4] == b"OggS"


def test_strip_for_speech_removes_markdown_and_caps_length() -> None:
    text = "**Bill**: _LKR 630_ " + "x" * 2000

    cleaned = media_ext._strip_for_speech(text)

    assert "**" not in cleaned and "_" not in cleaned
    assert len(cleaned) <= 900
