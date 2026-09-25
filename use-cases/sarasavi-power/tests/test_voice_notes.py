"""Voice-note handler tests: request composition and graceful degradation.

Keyless: WhatsApp and Gemini are faked; only the handler's own logic runs.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from agentkernel.core.model import AgentRequestFile, AgentRequestText

from whatsapp_ext import media as media_ext
from whatsapp_ext.handler import _VOICE_NOTE_INSTRUCTION, SarasaviWhatsAppHandler, _clear_oversized_adk_session


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


_SIZE_ERROR = "An error occurred (ValidationException) ... Item size has exceeded the maximum allowed size"


def test_clear_oversized_session_is_noop_outside_dynamodb() -> None:
    """Local dev's config.yaml uses session.type: in_memory, where this size cap
    does not exist; the helper must not touch DynamoDB/boto3 in that case."""
    import logging

    assert _clear_oversized_adk_session("94770000001", logging.getLogger("test")) is False


def test_oversized_session_error_is_retried_once_after_clearing() -> None:
    handler = _handler()
    handler._get_media_info = AsyncMock(return_value=(2048, "audio/ogg"))
    handler._download_media = AsyncMock(return_value="ZmFrZS1vZ2c=")
    handler._send_message = AsyncMock()
    handler._send_voice_reply = AsyncMock()
    attempts = {"n": 0}

    class FlakyService:
        agent = object()

        def select(self, session_id, name):
            pass

        async def run_multi(self, requests):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError(_SIZE_ERROR)
            return "Your estimated bill is LKR 630."

    with (
        patch("whatsapp_ext.handler.AgentService", FlakyService),
        patch("whatsapp_ext.handler._clear_oversized_adk_session", return_value=True) as clear_mock,
    ):
        asyncio.run(handler._handle_audio_message(_AUDIO_MESSAGE, {}))

    assert attempts["n"] == 2  # first call failed, retry succeeded
    clear_mock.assert_called_once()
    sent = [call.args[1] for call in handler._send_message.await_args_list]
    assert any("Your estimated bill is LKR 630." in text for text in sent)
    assert not any("error processing" in text for text in sent)


def test_oversized_session_error_falls_back_when_clearing_fails() -> None:
    handler = _handler()
    handler._get_media_info = AsyncMock(return_value=(2048, "audio/ogg"))
    handler._download_media = AsyncMock(return_value="ZmFrZS1vZ2c=")
    handler._send_message = AsyncMock()

    class AlwaysFailsService:
        agent = object()

        def select(self, session_id, name):
            pass

        async def run_multi(self, requests):
            raise RuntimeError(_SIZE_ERROR)

    with (
        patch("whatsapp_ext.handler.AgentService", AlwaysFailsService),
        patch("whatsapp_ext.handler._clear_oversized_adk_session", return_value=False),
    ):
        asyncio.run(handler._handle_audio_message(_AUDIO_MESSAGE, {}))

    text = handler._send_message.await_args.args[1]
    assert "error processing your voice note" in text


def test_unrelated_errors_are_not_retried() -> None:
    """Only the specific DynamoDB size failure gets a retry; anything else is a
    real failure and should surface as one, not double the LLM cost guessing."""
    handler = _handler()
    handler._get_media_info = AsyncMock(return_value=(2048, "audio/ogg"))
    handler._download_media = AsyncMock(return_value="ZmFrZS1vZ2c=")
    handler._send_message = AsyncMock()
    attempts = {"n": 0}

    class BrokenService:
        agent = object()

        def select(self, session_id, name):
            pass

        async def run_multi(self, requests):
            attempts["n"] += 1
            raise RuntimeError("boom")

    with (
        patch("whatsapp_ext.handler.AgentService", BrokenService),
        patch("whatsapp_ext.handler._clear_oversized_adk_session") as clear_mock,
    ):
        asyncio.run(handler._handle_audio_message(_AUDIO_MESSAGE, {}))

    assert attempts["n"] == 1
    clear_mock.assert_not_called()


def test_strip_for_speech_removes_markdown_and_caps_length() -> None:
    text = "**Bill**: _LKR 630_ " + "x" * 2000

    cleaned = media_ext._strip_for_speech(text)

    assert "**" not in cleaned and "_" not in cleaned
    assert len(cleaned) <= 900
