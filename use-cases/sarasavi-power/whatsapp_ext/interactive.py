"""Outbound WhatsApp interactive (button) messages.

Agent Kernel reads inbound button replies but can only *send* plain text, so the
language chooser is built here.

Why a chooser at all, when the assistant already detects Sinhala and Tamil from
their script: most Sri Lankans type romanized Sinhala ("mata bill eka danaganna
one", "kohomada"), which is pure Latin text and therefore indistinguishable from
English by script. Those users would silently get an English assistant. One tap
settles it before the first real question.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("sarasavi.whatsapp.interactive")

# WhatsApp caps reply-button titles at 20 characters and allows at most three.
LANGUAGE_BUTTONS = [
    ("lang_en", "English"),
    ("lang_si", "සිංහල"),
    ("lang_ta", "தமிழ்"),
]

LANGUAGE_PROMPT = (
    "🌐 Please choose your preferred language.\n\n"
    "කරුණාකර ඔබට කැමති භාෂාව තෝරන්න.\n"
    "தயவுசெய்து உங்கள் விருப்ப மொழியைத் தேர்ந்தெடுக்கவும்."
)

# Maps a tapped button back to a language code. The assistant also receives the
# button title as text, but resolving it here keeps the mapping deterministic.
BUTTON_LANGUAGES = {"lang_en": "en", "lang_si": "si", "lang_ta": "ta"}


async def send_buttons(
    base_url: str,
    phone_number_id: str,
    access_token: str,
    to_number: str,
    body: str,
    buttons: list[tuple[str, str]],
) -> bool:
    """Send an interactive reply-button message. False on any failure.

    Callers must treat False as "fall back to plain text" — never as fatal.
    """
    url = f"{base_url}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": [{"type": "reply", "reply": {"id": bid, "title": title}} for bid, title in buttons]},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                logger.error("interactive send failed: HTTP %s %s", response.status_code, response.text[:400])
                return False
            return True
    except httpx.HTTPError:
        logger.exception("interactive send failed")
        return False


async def send_language_prompt(base_url: str, phone_number_id: str, access_token: str, to_number: str) -> bool:
    """Ask the user to pick a language, once, before the first real answer."""
    return await send_buttons(base_url, phone_number_id, access_token, to_number, LANGUAGE_PROMPT, LANGUAGE_BUTTONS)


def language_from_reply(message: dict) -> str | None:
    """Resolve a tapped language button to 'en' | 'si' | 'ta', else None."""
    interactive = message.get("interactive") or {}
    if interactive.get("type") != "button_reply":
        return None
    button_id = (interactive.get("button_reply") or {}).get("id", "")
    return BUTTON_LANGUAGES.get(button_id)
