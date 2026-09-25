"""Shared startup validation for local entrypoints.

Validation lives here so every channel fails with a short, actionable message
instead of a provider traceback. Importing an entrypoint remains safe; checks
only run when that entrypoint is executed.
"""

from __future__ import annotations

import os

# Keep in sync with agent.MODEL; duplicated here so startup validation never has to
# import agent.py (which would build the agents before the config is checked).
_DEFAULT_MODEL = "gemini-2.5-flash"

_PLACEHOLDER_FRAGMENTS = (
    "your-",
    "choose-any",
    "replace-me",
    "changeme",
    "example",
)


def _is_missing_or_placeholder(value: str | None) -> bool:
    cleaned = (value or "").strip().lower()
    return not cleaned or any(fragment in cleaned for fragment in _PLACEHOLDER_FRAGMENTS)


def _use_vertex_ai() -> bool:
    """True when ADK should authenticate through Vertex AI instead of an API key."""
    return os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")


def require_gemini_config() -> str:
    """Fail fast with a human-readable message before Agent Kernel starts.

    Google ADK reads GOOGLE_API_KEY; google-genai also accepts GEMINI_API_KEY, so
    either is enough. Vertex AI mode uses Google Cloud credentials and needs neither.
    """
    if _use_vertex_ai():
        return os.environ.get("SARASAVI_MODEL", _DEFAULT_MODEL)

    key = os.environ.get("GOOGLE_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if _is_missing_or_placeholder(key):
        raise SystemExit(
            "GOOGLE_API_KEY is missing or still a placeholder. "
            "Get a Gemini key at https://aistudio.google.com/apikey and set it in .env "
            "before starting Sarasavi Power."
        )
    return os.environ.get("SARASAVI_MODEL", _DEFAULT_MODEL)


def require_whatsapp_config() -> None:
    """Require the four Meta values used by Agent Kernel's WhatsApp handler."""
    required = (
        "AK_WHATSAPP__VERIFY_TOKEN",
        "AK_WHATSAPP__ACCESS_TOKEN",
        "AK_WHATSAPP__PHONE_NUMBER_ID",
        "AK_WHATSAPP__APP_SECRET",
    )
    missing = [name for name in required if _is_missing_or_placeholder(os.environ.get(name))]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            "Meta WhatsApp configuration is incomplete. Set these values in .env: "
            f"{joined}. Until then, use offline_demo.py, demo.py, or rest.py."
        )
