"""Tests for the post-execution hook, in both directions.

Blocking unsafe language matters, but so does *not* blocking the safety messages. A filter
that swallowed a danger-sign action string would be worse than no filter at all.
"""

import logging

import pytest
from agentkernel.core.model import AgentReplyText

import danger_signs
import escalation
import hooks


@pytest.fixture
def hook():
    return hooks.BlockUnsafeLanguageHook()


async def run_hook(hook, text):
    reply = AgentReplyText(prompt="", response=text)
    result = await hook.on_run(session=None, requests=[], agent=None, agent_reply=reply)
    return result.response


# --- blocks diagnosis-like language -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "This looks like pre-eclampsia.",
        "You are suffering from anaemia.",
        "Your diagnosis is gestational diabetes.",
        "It could be an infection.",
        "I would diagnose this as high blood pressure.",
    ],
)
async def test_diagnosis_language_is_blocked(hook, text):
    assert await run_hook(hook, text) == hooks.DIAGNOSIS_BLOCK_RESPONSE


# --- blocks medication-like language, with a different response -------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You should take folic acid every day.",
        "Take two paracetamol tablets.",
        "The usual dose is 500 mg.",
        "Try an iron supplement.",
        "A vitamin would help.",
    ],
)
async def test_medication_language_is_blocked(hook, text):
    assert await run_hook(hook, text) == hooks.MEDICATION_BLOCK_RESPONSE


async def test_medication_block_is_not_alarming(hook):
    # "Should I take folic acid?" is a benign question. Answering it with an urgent
    # escalation message would be its own kind of harm.
    reply = await run_hook(hook, "You should take folic acid.")
    assert reply == hooks.MEDICATION_BLOCK_RESPONSE
    assert reply != hooks.DIAGNOSIS_BLOCK_RESPONSE
    assert "hospital" not in reply


async def test_diagnosis_wins_when_a_reply_trips_both(hook):
    assert await run_hook(hook, "You have anaemia, so take an iron tablet.") == hooks.DIAGNOSIS_BLOCK_RESPONSE


# --- must NOT block the safety messages -------------------------------------------------


async def test_escalation_sent_message_passes_through(hook):
    assert await run_hook(hook, escalation.ESCALATION_SENT_MESSAGE) == escalation.ESCALATION_SENT_MESSAGE


async def test_escalation_failed_message_passes_through(hook):
    assert await run_hook(hook, escalation.ESCALATION_FAILED_MESSAGE) == escalation.ESCALATION_FAILED_MESSAGE


async def test_danger_sign_action_strings_pass_through(hook, monkeypatch):
    monkeypatch.setattr(danger_signs, "action_strings", lambda: ["Go to your nearest hospital now."])
    hooks.load_blocked_language.cache_clear()
    assert await run_hook(hook, "Go to your nearest hospital now.") == "Go to your nearest hospital now."


async def test_failsafe_action_passes_through(hook):
    assert await run_hook(hook, danger_signs.FAILSAFE_ACTION) == danger_signs.FAILSAFE_ACTION


async def test_unmatched_action_passes_through(hook):
    assert await run_hook(hook, danger_signs.UNMATCHED_ACTION) == danger_signs.UNMATCHED_ACTION


async def test_ordinary_replies_pass_through(hook):
    text = "Your next visit is not available yet. Your PHM can tell you when it is due."
    assert await run_hook(hook, text) == text


# --- the allowlist is subtracted, not a blanket pass ------------------------------------


async def test_allowlisted_span_does_not_excuse_a_diagnosis_elsewhere(hook):
    # A reply that carries a legitimate action string AND names a condition must still be
    # blocked. Otherwise appending a safe sentence would launder any unsafe reply.
    text = f"{danger_signs.FAILSAFE_ACTION} You have pre-eclampsia."
    assert await run_hook(hook, text) == hooks.DIAGNOSIS_BLOCK_RESPONSE


# --- word boundaries --------------------------------------------------------------------


@pytest.mark.parametrize("text", ["The programme is amazing.", "Send me a telegram.", "Small amount of milk."])
async def test_short_terms_do_not_match_inside_longer_words(hook, text):
    # "mg" and "ml" are broad; they must not fire inside unrelated words.
    assert await run_hook(hook, text) == text


# --- every block is logged, redacted ----------------------------------------------------


async def test_blocks_are_logged_with_the_original_reply(hook, caplog):
    with caplog.at_level(logging.WARNING, logger="mathru.hooks"):
        await run_hook(hook, "You have pre-eclampsia.")

    assert any("Blocked diagnosis language" in record.message for record in caplog.records)
    assert any("pre-eclampsia" in record.message for record in caplog.records)


async def test_block_logs_redact_phone_numbers(hook, caplog):
    with caplog.at_level(logging.WARNING, logger="mathru.hooks"):
        await run_hook(hook, "Call 94771234567, you have anaemia.")

    logged = " ".join(record.message for record in caplog.records)
    assert "94771234567" not in logged
    assert "***567" in logged


# --- non-text replies are left alone ----------------------------------------------------


async def test_non_text_replies_are_returned_unchanged(hook):
    sentinel = object()
    assert await hook.on_run(session=None, requests=[], agent=None, agent_reply=sentinel) is sentinel
