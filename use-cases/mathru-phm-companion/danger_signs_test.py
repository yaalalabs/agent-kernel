"""Tests for the severity decision. Every row of the fail-toward-escalation table."""

import pytest

import danger_signs

POPULATED_TABLE = {
    "status": "sourced",
    "signs": [
        {
            "id": "red_sign",
            "severity": "red",
            "keywords": ["heavy bleeding", "le gelima"],
            "action": "RED ACTION STRING",
        },
        {
            "id": "amber_sign",
            "severity": "amber",
            "keywords": ["mild swelling"],
            "action": "AMBER ACTION STRING",
        },
    ],
}


@pytest.fixture
def populated(monkeypatch):
    """Swap in a populated table, so placeholder status does not mask the matching logic."""
    monkeypatch.setattr(danger_signs, "load_table", lambda: POPULATED_TABLE)


# --- the shipped table is a placeholder, and must escalate everything -------------------


def test_placeholder_table_forces_red_and_escalates():
    # The real data file ships as a placeholder. An unpopulated table cannot rule anything
    # out, so it must never be allowed to reassure.
    decision = danger_signs.screen("I have a headache")
    assert decision["severity"] == danger_signs.RED
    assert decision["escalate"] is True
    assert decision["table_status"] == "placeholder"


def test_placeholder_table_still_reports_green_for_no_symptom():
    # The empty-text check runs before the table is consulted at all.
    assert danger_signs.screen("")["severity"] == danger_signs.GREEN


def test_shipped_table_contains_no_green_entries():
    # `green` is a system-level state, never a table value.
    severities = {sign.get("severity") for sign in danger_signs.load_table()["signs"]}
    assert severities <= set(danger_signs.TABLE_SEVERITIES)
    assert danger_signs.GREEN not in severities


# --- exceptions fail toward escalation --------------------------------------------------


def test_exception_during_matching_forces_red_and_escalates(monkeypatch):
    def boom():
        raise RuntimeError("table unreadable")

    monkeypatch.setattr(danger_signs, "load_table", boom)

    decision = danger_signs.screen("I have a headache")
    assert decision["severity"] == danger_signs.RED
    assert decision["escalate"] is True
    assert "RuntimeError" in decision["reason"]


def test_screen_never_raises(monkeypatch):
    monkeypatch.setattr(danger_signs, "load_table", lambda: {"status": "sourced", "signs": [{"bad": object()}]})
    assert danger_signs.screen("something")["severity"] in {danger_signs.RED, danger_signs.AMBER}


@pytest.mark.parametrize("status", ["sourcedd", "Sourced", "reviewed", "", None, True])
def test_only_the_exact_sourced_status_is_trusted(monkeypatch, status):
    # A typo must fail toward escalation. Treating "anything but placeholder" as populated
    # would let one character silently switch the table from escalating to trusting.
    monkeypatch.setattr(
        danger_signs,
        "load_table",
        lambda: {"status": status, "signs": [{"id": "amber_sign", "severity": "amber", "keywords": ["swelling"]}]},
    )
    decision = danger_signs.screen("I have swelling")
    assert decision["severity"] == danger_signs.RED
    assert decision["escalate"] is True


# --- matching against a populated table -------------------------------------------------


def test_red_keyword_matches_and_escalates(populated):
    decision = danger_signs.screen("I have heavy bleeding since morning")
    assert decision["severity"] == danger_signs.RED
    assert decision["escalate"] is True
    assert decision["matched_signs"] == ["red_sign"]
    assert decision["action"] == "RED ACTION STRING"


def test_matching_is_case_insensitive(populated):
    assert danger_signs.screen("HEAVY BLEEDING")["severity"] == danger_signs.RED


def test_transliterated_keyword_matches(populated):
    assert danger_signs.screen("mata le gelima thiyenawa")["severity"] == danger_signs.RED


def test_amber_keyword_matches_without_escalating(populated):
    decision = danger_signs.screen("I have mild swelling in my feet")
    assert decision["severity"] == danger_signs.AMBER
    assert decision["escalate"] is False
    assert decision["matched_signs"] == ["amber_sign"]


def test_red_wins_when_both_match(populated):
    decision = danger_signs.screen("mild swelling and heavy bleeding")
    assert decision["severity"] == danger_signs.RED
    assert decision["escalate"] is True


def test_keyword_matching_respects_word_boundaries(populated):
    # "dose" must not match inside "doses"? No - the risk here is a keyword matching inside
    # an unrelated longer word. "mild swelling" should not match "mild swellings"' prefix
    # in a way that changes severity, but a substring hit on a different word must not fire.
    assert danger_signs.screen("bleedingheart flower")["matched_signs"] == []


# --- symptom reported but nothing matched -----------------------------------------------


def test_unmatched_symptom_is_amber_never_green(populated):
    decision = danger_signs.screen("my elbow feels strange")
    assert decision["severity"] == danger_signs.AMBER
    assert decision["escalate"] is False
    assert decision["matched_signs"] == []


def test_unmatched_action_does_not_reassure(populated):
    action = danger_signs.screen("my elbow feels strange")["action"]
    assert "PHM" in action
    assert "hospital" in action


# --- green requires no symptom at all ---------------------------------------------------


@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_green_only_when_no_symptom_reported(populated, empty):
    decision = danger_signs.screen(empty)
    assert decision["severity"] == danger_signs.GREEN
    assert decision["escalate"] is False


def test_any_non_empty_text_is_never_green(populated):
    assert danger_signs.screen("x")["severity"] != danger_signs.GREEN


# --- action strings feed the hook allowlist ---------------------------------------------


def test_action_strings_returns_table_actions(populated):
    assert set(danger_signs.action_strings()) == {"RED ACTION STRING", "AMBER ACTION STRING"}


def test_action_strings_returns_empty_list_when_table_unreadable(monkeypatch):
    def boom():
        raise OSError("gone")

    monkeypatch.setattr(danger_signs, "load_table", boom)
    assert danger_signs.action_strings() == []
