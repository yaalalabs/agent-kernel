"""Single canonical accessor for the persistent household profile.

Every tool and every hook touches session state ONLY through this module, and
ONLY under the one key ``household_profile``. Centralising it is what prevents the
key/language drift that would otherwise silently break persistence and localisation
(the production plan's critic flagged exactly this).

Cache API is the observed Agent Kernel surface (method-style, not dict):
    cache = ToolContext.get().session.get_non_volatile_cache()
    cache.get(key, default) / cache.set(key, value)

Writes deliberately fail when no ToolContext is active. Silently claiming a profile
was saved would make a competition demo look successful while losing its state.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from agentkernel.core import ToolContext

PROFILE_KEY = "household_profile"
LAST_VOICE_CALL_KEY = "last_voice_call"
DEFAULT_LANGUAGE = "en"
VALID_CYCLES = ("monthly", "bimonthly")
VALID_LANGUAGES = ("en", "si", "ta")
_CYCLE_DAYS = {"monthly": 30, "bimonthly": 60}

_EMPTY_PROFILE: dict[str, Any] = {
    "consent": False,
    "name": None,
    "billing_cycle": "monthly",
    "billing_days": 30,
    "language": DEFAULT_LANGUAGE,
    "appliances": [],  # [{key, hours_per_day, quantity}]
    "metered_units": None,  # a real bill/meter reading anchors boundary advice
}


def _cache():
    return ToolContext.get().session.get_non_volatile_cache()


def load_profile() -> dict[str, Any]:
    """Return the current household profile (a fresh default if none stored yet)."""
    try:
        stored = _cache().get(PROFILE_KEY, None)
    except RuntimeError:
        stored = None
    if not stored:
        return copy.deepcopy(_EMPTY_PROFILE)
    # Merge onto the default so newly-added fields always exist.
    profile = copy.deepcopy(_EMPTY_PROFILE)
    profile.update(stored)
    return profile


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Persist a profile, failing loudly if no Agent Kernel session is active."""
    _cache().set(PROFILE_KEY, copy.deepcopy(profile))
    return profile


def _require_consent(profile: dict[str, Any]) -> None:
    if not profile.get("consent"):
        raise PermissionError("profile storage consent is required first")


def set_consent(consent: bool) -> dict[str, Any]:
    """Grant storage consent, or revoke it and erase the stored profile."""
    profile = load_profile() if consent else copy.deepcopy(_EMPTY_PROFILE)
    profile["consent"] = bool(consent)
    return save_profile(profile)


def delete_profile() -> bool:
    """Delete all durable household data for the current session."""
    return _cache().delete(PROFILE_KEY)


def get_language(default: str = DEFAULT_LANGUAGE) -> str:
    return load_profile().get("language") or default


def set_language(language: str) -> dict[str, Any]:
    if language not in VALID_LANGUAGES:
        raise ValueError(f"language must be one of {VALID_LANGUAGES}")
    profile = load_profile()
    _require_consent(profile)
    profile["language"] = language
    return save_profile(profile)


def set_household(
    name: Optional[str] = None,
    billing_cycle: Optional[str] = None,
    language: Optional[str] = None,
    billing_days: Optional[int] = None,
) -> dict[str, Any]:
    profile = load_profile()
    _require_consent(profile)
    if name is not None:
        cleaned_name = name.strip()
        if len(cleaned_name) > 80:
            raise ValueError("name must be 80 characters or fewer")
        profile["name"] = cleaned_name or None
    if billing_cycle is not None:
        if billing_cycle not in VALID_CYCLES:
            raise ValueError(f"billing_cycle must be one of {VALID_CYCLES}")
        profile["billing_cycle"] = billing_cycle
        if billing_days is None:
            profile["billing_days"] = _CYCLE_DAYS[billing_cycle]
    if billing_days is not None:
        if isinstance(billing_days, bool) or not isinstance(billing_days, int):
            raise ValueError("billing_days must be a whole number")
        if not 1 <= billing_days <= 366:
            raise ValueError("billing_days must be between 1 and 366")
        profile["billing_days"] = billing_days
        profile["billing_cycle"] = "monthly" if billing_days == 30 else "bimonthly" if billing_days == 60 else "custom"
    if language is not None:
        if language not in VALID_LANGUAGES:
            raise ValueError(f"language must be one of {VALID_LANGUAGES}")
        profile["language"] = language
    return save_profile(profile)


def add_appliance(key: str, hours_per_day: float, quantity: int = 1) -> dict[str, Any]:
    """Add or update an appliance line-item (keyed by appliance ``key``)."""
    profile = load_profile()
    _require_consent(profile)
    if not 0 <= hours_per_day <= 24:
        raise ValueError("hours_per_day must be between 0 and 24")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 100:
        raise ValueError("quantity must be a whole number between 1 and 100")
    entry = {"key": key, "hours_per_day": float(hours_per_day), "quantity": quantity}
    appliances = [a for a in profile["appliances"] if a["key"] != key]  # replace duplicates
    appliances.append(entry)
    profile["appliances"] = appliances
    return save_profile(profile)


def remove_appliance(key: str) -> tuple[dict[str, Any], bool]:
    """Remove one appliance line-item and report whether it existed."""
    profile = load_profile()
    _require_consent(profile)
    before = len(profile["appliances"])
    profile["appliances"] = [item for item in profile["appliances"] if item["key"] != key]
    removed = len(profile["appliances"]) != before
    return save_profile(profile), removed


def set_metered_units(units: Optional[float]) -> dict[str, Any]:
    """Store (or clear) a real metered reading — the trusted anchor for advice."""
    profile = load_profile()
    _require_consent(profile)
    if units is not None and units < 0:
        raise ValueError("units must be >= 0")
    profile["metered_units"] = None if units is None else float(units)
    return save_profile(profile)


def load_last_voice_call() -> Optional[dict[str, Any]]:
    """Return the most recent voice-call record written by the voice bridge, if any."""
    try:
        return _cache().get(LAST_VOICE_CALL_KEY, None)
    except RuntimeError:
        return None
