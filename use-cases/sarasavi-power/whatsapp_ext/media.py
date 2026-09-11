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
import re

import httpx

import speech

logger = logging.getLogger("sarasavi.whatsapp.media")

# WhatsApp renders `audio/ogg; codecs=opus` uploads as voice notes (mic bubble).
_VOICE_MIME = "audio/ogg"

# Gemini TTS. Any prebuilt voice name works; Leda/Aoede sound natural in Sinhala.
TTS_MODEL = os.environ.get("SARASAVI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("SARASAVI_TTS_VOICE", "Leda")

# Keep spoken replies short: synthesize at most this many characters.
_MAX_TTS_CHARS = 900

# The reply text is written to be read (LKR 345.00, 61 kWh); localization.py's
# format strings emit these tokens the same way in every language. Read aloud
# verbatim, a TTS engine spells "LKR" letter by letter (එල් කේ ආර්) and reads
# the decimal point as "point"/"දශම" -- both sound broken, and "345.58" as
# "three forty five point five eight" hides that .58 means cents. Detect the
# reply's script and rewrite every amount as words (speech.py owns the
# wording): රුපියල්/ரூபாய்/rupees first, cents become සත and are dropped when
# zero, and in a Sinhala reply the remaining digits themselves become Sinhala
# words so the TTS voice cannot wander into an English reading of "2,500".
_SINHALA_SCRIPT = re.compile(r"[඀-෿]")
_TAMIL_SCRIPT = re.compile(r"[஀-௿]")
# Currency on either side of the number, in any written form the text agents
# use: "LKR 345.58", "1,260.00 LKR", "රුපියල් 1,260.00", "රු. 630", "ரூபாய் 80".
_AMOUNT = r"\d+(?:,\d{3})*(?:\.\d{1,2})?"
_CURRENCY_TOKEN = r"(?:LKR|Rs\.?|රුපියල්|රු\.?|ரூபாய்|ரூ\.?)"
_CURRENCY_AMOUNT = re.compile(
    _CURRENCY_TOKEN + r"\s*(?P<after>" + _AMOUNT + r")"
    r"|(?P<before>" + _AMOUNT + r")\s*" + _CURRENCY_TOKEN
)
_ZERO_DECIMAL = re.compile(r"(\d)\.00\b")  # leftover non-currency "61.00 kWh" -> "61 kWh"
# "<n> kWh" -> the unit word leads for Sinhala/Tamil, the way a quantity is
# actually said there (කිලෝ වොට් 520, like රුපියල් leads a rupee amount), not
# the English number-then-unit order the text reply writes literally. English
# keeps its own natural order ("520 units").
_UNIT_AMOUNT = re.compile(r"(?:(?P<num>[\d,]+(?:\.\d+)?)\s*)?\bkWh\b")
# Digits still left in a Sinhala reply after the passes above (unit counts,
# day counts, plain "2500" the model wrote without a currency token).
_BARE_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

_UNIT_WORD = {"si": "කිලෝ වොට්", "ta": "கிலோவாட்", "en": "units"}


def _script(text: str) -> str:
    if _SINHALA_SCRIPT.search(text):
        return "si"
    if _TAMIL_SCRIPT.search(text):
        return "ta"
    return "en"


def _speak_bare_sinhala(match: re.Match) -> str:
    """Word one leftover digit run: "2500" -> "දෙදහස් පන්සීය", "61.5" -> "හැට එක දශම පහ".

    A non-zero decimal tail is read digit by digit after දශම, the normal Sinhala
    reading for a measurement; a zero tail is not said at all. Runs too long to
    word (reference numbers) are left as digits.
    """
    token = match.group(0)
    whole_text, _, frac = token.partition(".")
    try:
        words = speech.number_to_sinhala_words(int(whole_text.replace(",", "")))
    except ValueError:
        return token
    frac = frac.rstrip("0")
    if frac:
        words += " දශම " + speech.sinhala_digits(frac)
    return words


def _normalize_for_speech(text: str) -> str:
    """Rewrite written currency/unit shorthand into what TTS should say aloud."""
    lang = _script(text)

    def _speak_amount(match: re.Match) -> str:
        token = match.group("after") or match.group("before")
        whole_text, _, cents_text = token.partition(".")
        whole = int(whole_text.replace(",", "") or 0)
        cents = int(cents_text.ljust(2, "0")) if cents_text else 0
        return speech.spoken_rupees(whole + cents / 100, lang)

    def _speak_unit(match: re.Match) -> str:
        num, unit_word = match.group("num"), _UNIT_WORD[lang]
        if not num:
            return unit_word
        return f"{num} {unit_word}" if lang == "en" else f"{unit_word} {num}"

    text = _CURRENCY_AMOUNT.sub(_speak_amount, text)  # "LKR 345.58" -> "රුපියල් ... සත ..."
    text = _ZERO_DECIMAL.sub(r"\1", text)  # any other "N.00" left (e.g. kWh figures)
    text = _UNIT_AMOUNT.sub(_speak_unit, text)  # "520 kWh" -> "කිලෝ වොට් 520" (si/ta), "520 units" (en)
    if lang == "si":
        text = _BARE_NUMBER.sub(_speak_bare_sinhala, text)  # "ඒකක 61" -> "ඒකක හැට එක"
    return text


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
    """Drop markdown decorations, normalize currency/units, and cap the length."""
    cleaned = text.replace("**", "").replace("*", "").replace("_", "").replace("#", "")
    cleaned = _normalize_for_speech(cleaned)
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
