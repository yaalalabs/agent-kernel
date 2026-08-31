"""Outbound WhatsApp media: upload + audio send + Gemini TTS voice replies.

Agent Kernel's handler only sends text; these helpers add the Graph API media
upload and audio-message calls, plus text-to-speech through Gemini so voice-note
users can hear the answer. All functions degrade gracefully: a TTS or upload
failure is logged and the (already sent) text reply remains the source of truth.
"""

from __future__ import annotations

import io
import logging
import os

import httpx

logger = logging.getLogger("sarasavi.whatsapp.media")

# WhatsApp renders `audio/ogg; codecs=opus` uploads as voice notes (mic bubble).
_VOICE_MIME = "audio/ogg"

# Gemini TTS. Any prebuilt voice name works; Leda/Aoede sound natural in Sinhala.
TTS_MODEL = os.environ.get("SARASAVI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("SARASAVI_TTS_VOICE", "Leda")

# Keep spoken replies short: synthesize at most this many characters.
_MAX_TTS_CHARS = 900


async def upload_media(
    base_url: str, phone_number_id: str, access_token: str, data: bytes, mime_type: str
) -> str | None:
    """Upload media to WhatsApp; returns the media id or None on failure."""
    url = f"{base_url}/{phone_number_id}/media"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": ("voice_reply.ogg", data, mime_type)},
            )
            response.raise_for_status()
            return response.json().get("id")
    except Exception:
        logger.exception("WhatsApp media upload failed")
        return None


async def send_audio(base_url: str, phone_number_id: str, access_token: str, to_number: str, media_id: str) -> bool:
    """Send a previously uploaded audio media id as a voice message."""
    url = f"{base_url}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "audio",
        "audio": {"id": media_id},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            return True
    except Exception:
        logger.exception("WhatsApp audio send failed")
        return False


def _strip_for_speech(text: str) -> str:
    """Drop markdown decorations that read badly aloud and cap the length."""
    cleaned = text.replace("**", "").replace("*", "").replace("_", "").replace("#", "")
    return cleaned[:_MAX_TTS_CHARS]


def synthesize_speech(text: str) -> bytes | None:
    """Text -> 24kHz PCM16 via Gemini TTS; returns raw PCM bytes or None."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=_strip_for_speech(text),
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                    )
                ),
            ),
        )
        part = response.candidates[0].content.parts[0]
        return part.inline_data.data
    except Exception:
        logger.exception("Gemini TTS synthesis failed")
        return None


def pcm_to_ogg_opus(pcm: bytes, sample_rate: int = 24000) -> bytes | None:
    """Encode mono PCM16 to an OGG/Opus container (what WhatsApp voice notes use)."""
    try:
        import av

        buffer = io.BytesIO()
        with av.open(buffer, mode="w", format="ogg") as container:
            stream = container.add_stream("libopus", rate=48000)
            stream.layout = "mono"
            frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
            frame.planes[0].update(pcm)
            frame.sample_rate = sample_rate
            frame.pts = 0
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        return buffer.getvalue()
    except Exception:
        logger.exception("OGG/Opus encoding failed")
        return None


def render_voice_reply(text: str) -> bytes | None:
    """Full text -> OGG/Opus pipeline; None when any stage fails."""
    pcm = synthesize_speech(text)
    if not pcm:
        return None
    return pcm_to_ogg_opus(pcm)
