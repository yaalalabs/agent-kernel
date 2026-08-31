"""The post-call recap is a service record, not a transcript."""

from __future__ import annotations

import datetime

from voice.summary import recap_text

STARTED = datetime.datetime(2026, 8, 30, 6, 51, tzinfo=datetime.timezone.utc)
CONVERSATION = [
    "agent: Sarasavi Power, how can",
    "agent:  I help?",
    "caller: I want to lower",
    "caller:  my electricity bill",
]


def test_no_recap_when_the_caller_never_spoke() -> None:
    """Picking up and hanging up must not produce a summary of half a greeting."""
    assert recap_text(["agent: Sarasavi Power, how can", "agent:  I help?"]) is None


def test_recap_reports_time_and_duration_in_sri_lanka_time() -> None:
    out = recap_text(CONVERSATION, ["find_savings"], started_at=STARTED, duration_seconds=95)

    assert "2026-08-30 12:21 (Sri Lanka)" in out  # 06:51 UTC = 12:21 +5:30
    assert "1m 35s" in out


def test_recap_states_what_was_discussed_not_the_whole_transcript() -> None:
    out = recap_text(CONVERSATION, ["find_savings"], started_at=STARTED, duration_seconds=30)

    assert "I want to lower my electricity bill" in out
    # The assistant's own words are not read back to the caller.
    assert "Sarasavi Power, how can" not in out


def test_recap_lists_actions_taken_without_repeats() -> None:
    out = recap_text(
        CONVERSATION,
        ["set_storage_consent", "add_appliance", "add_appliance", "find_savings"],
        started_at=STARTED,
        duration_seconds=60,
    )

    assert out.count("Appliance usage recorded") == 1
    assert "Consent recorded" in out
    assert "Savings options identified" in out


def test_resolved_call_is_marked_answered_and_carries_the_disclaimer() -> None:
    out = recap_text(CONVERSATION, ["compute_current_bill"], started_at=STARTED, duration_seconds=60)

    assert "Answered on the call" in out
    assert "Estimate only" in out


def test_unresolved_call_says_so_and_offers_the_next_step() -> None:
    out = recap_text(CONVERSATION, ["set_storage_consent"], started_at=STARTED, duration_seconds=20)

    assert "estimate not yet requested" in out
    assert "Send a message here" in out
    # No figures were quoted, so no bill disclaimer belongs on it.
    assert "Estimate only" not in out


def test_recap_uses_whatsapp_markup_and_no_dashes() -> None:
    out = recap_text(CONVERSATION, ["find_savings"], started_at=STARTED, duration_seconds=60)

    assert "**" not in out
    assert "—" not in out and "–" not in out


def test_voice_opens_in_sinhala_then_follows_the_caller() -> None:
    """The opening line is sent before anyone has spoken, so it cannot be detected;
    Sinhala is the right default for these callers."""
    from voice.live_agent import _SYSTEM_PROMPT

    assert "open in SINHALA" in _SYSTEM_PROMPT
    assert "ආයුබෝවන්" in _SYSTEM_PROMPT
    # It must still follow the caller after that first line.
    assert "switch the moment they switch" in _SYSTEM_PROMPT


def test_brief_replaces_the_clipped_transcript_when_available() -> None:
    """The written summary is what the caller reads, not their own raw speech."""
    out = recap_text(
        CONVERSATION,
        ["find_savings"],
        started_at=STARTED,
        duration_seconds=60,
        brief="Caller asked how to reduce a 27 unit monthly bill.",
    )

    assert "*Discussed:* Caller asked how to reduce a 27 unit monthly bill." in out
    assert "I want to lower my electricity bill" not in out


def test_recap_falls_back_to_the_transcript_when_no_brief() -> None:
    """A failed summarisation must not cost the whole record."""
    out = recap_text(CONVERSATION, ["find_savings"], started_at=STARTED, duration_seconds=60)

    assert "I want to lower my electricity bill" in out
