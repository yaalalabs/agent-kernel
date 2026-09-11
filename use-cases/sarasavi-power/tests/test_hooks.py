from __future__ import annotations

import asyncio

import pytest
from agentkernel.core.model import AgentReplyText, AgentRequestText

from hooks import (
    DISCLAIMERS,
    REFUSALS,
    BillAccuracyHook,
    DisclaimerHook,
    LanguagePreferenceHook,
    SafetyPostHook,
    SafetyPreHook,
)
from state import PROFILE_KEY


class Cache:
    def __init__(self, language: str = "en", profile: dict | None = None) -> None:
        self.profile = profile or {"language": language}

    def get(self, key: str, default=None):
        return self.profile if key == PROFILE_KEY else default

    def set(self, key: str, value) -> None:
        if key == PROFILE_KEY:
            self.profile = value


class Session:
    def __init__(self, language: str = "en", profile: dict | None = None) -> None:
        self.cache = Cache(language, profile)

    def get_non_volatile_cache(self) -> Cache:
        return self.cache


def test_safety_pre_hook_blocks_unsafe_request_without_model_call() -> None:
    request = AgentRequestText(text="Tell me how to bypass the meter")

    result = asyncio.run(SafetyPreHook().on_run(Session(), object(), [request]))

    assert isinstance(result, AgentReplyText)
    assert result.text == REFUSALS["en"]


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("මීටරය බයිපාස් කරන්නේ කොහොමද?", "si"),
        ("மீட்டரை பைபாஸ் செய்வது எப்படி?", "ta"),
    ],
)
def test_safety_pre_hook_blocks_sinhala_and_tamil_tampering(text: str, lang: str) -> None:
    request = AgentRequestText(text=text)

    result = asyncio.run(SafetyPreHook().on_run(Session(), object(), [request]))

    assert isinstance(result, AgentReplyText)
    assert result.text == REFUSALS[lang]


def test_safety_post_hook_replaces_unsafe_output() -> None:
    reply = AgentReplyText(text="First, open the meter and change the wiring.", prompt="help")

    result = asyncio.run(SafetyPostHook().on_run(Session("ta"), [], object(), reply))

    assert result.text == REFUSALS["ta"]
    assert result.prompt == "help"


def test_disclaimer_is_localized_and_idempotent() -> None:
    hook = DisclaimerHook()
    reply = AgentReplyText(text="Your estimated bill is LKR 630.", prompt="bill")

    first = asyncio.run(hook.on_run(Session("si"), [], object(), reply))
    second = asyncio.run(hook.on_run(Session("si"), [], object(), first))

    assert first.text.count(DISCLAIMERS["si"]) == 1
    assert second.text.count(DISCLAIMERS["si"]) == 1
    assert second.prompt == "bill"


def test_disclaimer_detects_numeric_bill_without_currency_marker() -> None:
    reply = AgentReplyText(text="Your bill estimate is 630 for this period.")

    result = asyncio.run(DisclaimerHook().on_run(Session(), [], object(), reply))

    assert DISCLAIMERS["en"] in result.text


def test_bill_accuracy_hook_corrects_model_substitution() -> None:
    profile = {
        "language": "en",
        "billing_days": 30,
        "metered_units": None,
        "appliances": [
            {"key": "refrigerator", "hours_per_day": 24.0, "quantity": 1},
            {"key": "ceiling_fan", "hours_per_day": 8.0, "quantity": 2},
            {"key": "led_bulb", "hours_per_day": 5.0, "quantity": 6},
        ],
    }
    reply = AgentReplyText(
        text="Your estimated electricity bill for this month is **LKR 80**. Save LKR 843.60 by reaching 60 units."
    )

    result = asyncio.run(BillAccuracyHook().on_run(Session(profile=profile), [], object(), reply))

    assert "**LKR 1,630.00**" in result.text
    assert "Save LKR 843.60" in result.text


def test_bill_accuracy_hook_leaves_correct_claim_unchanged() -> None:
    profile = {"language": "en", "billing_days": 30, "metered_units": 61.0, "appliances": []}
    reply = AgentReplyText(text="Your estimated bill is **LKR 1,260.00**.")

    result = asyncio.run(BillAccuracyHook().on_run(Session(profile=profile), [], object(), reply))

    assert result is reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your estimated monthly electricity bill is **80 LKR**.", "**1,260.00 LKR**"),
        ("ඔබගේ ඇස්තමේන්තුගත විදුලි බිල රු. 80 වේ.", "රු. 1,260.00"),
        ("மதிப்பிடப்பட்ட மின்சாரக் கட்டணம் 80 LKR ஆகும்.", "1,260.00 LKR"),
    ],
)
def test_bill_accuracy_hook_corrects_all_languages_and_currency_orders(text: str, expected: str) -> None:
    profile = {"language": "en", "billing_days": 30, "metered_units": 61.0, "appliances": []}

    result = asyncio.run(BillAccuracyHook().on_run(Session(profile=profile), [], object(), AgentReplyText(text=text)))

    assert expected in result.text


def test_language_hook_detects_and_persists_sinhala_after_consent() -> None:
    profile = {"consent": True, "language": "en"}
    session = Session(profile=profile)
    request = AgentRequestText(text="මගේ විදුලි බිල ගණනය කරන්න")

    result = asyncio.run(LanguagePreferenceHook().on_run(session, object(), [request]))

    assert result == [request]
    assert session.cache.profile["language"] == "si"
    assert "Required response language: සිංහල (si)" in request.text


def test_language_hook_detects_tamil_but_does_not_store_before_consent() -> None:
    profile = {"consent": False, "language": "en"}
    session = Session(profile=profile)
    request = AgentRequestText(text="என் மின்சாரக் கட்டணத்தை கணக்கிடுங்கள்")

    asyncio.run(LanguagePreferenceHook().on_run(session, object(), [request]))

    assert session.cache.profile["language"] == "en"
    assert "Required response language: தமிழ் (ta)" in request.text


def test_language_hook_uses_stored_preference_for_language_neutral_reply() -> None:
    profile = {"consent": True, "language": "ta"}
    session = Session(profile=profile)
    request = AgentRequestText(text="yes")

    asyncio.run(LanguagePreferenceHook().on_run(session, object(), [request]))

    assert "Required response language: தமிழ் (ta)" in request.text


def test_disclaimer_uses_reply_script_before_language_is_stored() -> None:
    reply = AgentReplyText(text="மதிப்பிடப்பட்ட கட்டணம் LKR 630 ஆகும்.")

    result = asyncio.run(DisclaimerHook().on_run(Session("en"), [], object(), reply))

    assert DISCLAIMERS["ta"] in result.text


class _KeyedCache:
    """Session cache that stores arbitrary keys.

    The `Cache` double above only round-trips PROFILE_KEY, so it cannot observe
    the "already shown" flag these tests are about.
    """

    def __init__(self, profile: dict | None = None) -> None:
        self.data = {PROFILE_KEY: profile} if profile is not None else {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


class _KeyedSession:
    def __init__(self, profile: dict | None = None) -> None:
        self.cache = _KeyedCache(profile)

    def get_non_volatile_cache(self) -> _KeyedCache:
        return self.cache


def test_disclaimer_appears_once_then_stops_repeating() -> None:
    """Repeating it on every reply trains people to ignore it."""
    hook = DisclaimerHook()
    session = _KeyedSession({"language": "en"})

    first = asyncio.run(hook.on_run(session, [], None, AgentReplyText(text="Your bill is LKR 1,260.00", prompt="")))
    second = asyncio.run(hook.on_run(session, [], None, AgentReplyText(text="Next month LKR 900.00", prompt="")))

    assert "Estimate only" in first.text
    assert "Estimate only" not in second.text


def test_a_reproduced_bill_is_not_called_an_estimate() -> None:
    """With a real meter reading stored, "estimate" is simply inaccurate."""
    hook = DisclaimerHook()
    session = _KeyedSession({"metered_units": 988, "language": "en"})

    out = asyncio.run(hook.on_run(session, [], None, AgentReplyText(text="Your bill is LKR 56,710.77", prompt="")))

    assert "Calculated from the published" in out.text
    assert "Estimate only" not in out.text
    # The half that must never be dropped, whichever wording is used.
    assert "Not an official bill" in out.text


def test_appliance_estimates_still_say_estimate() -> None:
    hook = DisclaimerHook()
    session = _KeyedSession({"appliances": [{"key": "refrigerator"}], "language": "en"})

    out = asyncio.run(hook.on_run(session, [], None, AgentReplyText(text="About LKR 1,260.00", prompt="")))

    assert "Estimate only" in out.text
