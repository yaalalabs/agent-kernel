"""Language chooser: button payload shape and reply resolution.

The chooser exists because script detection cannot see romanized Sinhala/Tamil —
the way most Sri Lankans actually type — so those users would silently be served
an English assistant.
"""

from __future__ import annotations

import pytest

from localization import detect_language
from whatsapp_ext.interactive import (
    BUTTON_LANGUAGES,
    LANGUAGE_BUTTONS,
    LANGUAGE_PROMPT,
    language_from_reply,
)


@pytest.mark.parametrize("text", ["mata bill eka danaganna one", "kohomada", "ayubowan"])
def test_romanized_sinhala_is_invisible_to_script_detection(text: str) -> None:
    """The gap the chooser exists to close — pinned so it is not forgotten."""
    assert detect_language(text) is None


def test_prompt_is_written_in_all_three_languages() -> None:
    assert "choose your preferred language" in LANGUAGE_PROMPT.lower()
    assert "භාෂාව" in LANGUAGE_PROMPT  # Sinhala
    assert "மொழி" in LANGUAGE_PROMPT  # Tamil


def test_button_titles_respect_whatsapp_limits() -> None:
    """WhatsApp allows at most three reply buttons, titles capped at 20 chars."""
    assert len(LANGUAGE_BUTTONS) <= 3
    for _, title in LANGUAGE_BUTTONS:
        assert 0 < len(title) <= 20


def test_buttons_are_labelled_in_their_own_script() -> None:
    titles = {title for _, title in LANGUAGE_BUTTONS}

    assert "English" in titles
    assert "සිංහල" in titles
    assert "தமிழ்" in titles


def test_every_button_maps_to_a_supported_language_code() -> None:
    ids = {bid for bid, _ in LANGUAGE_BUTTONS}

    assert ids == set(BUTTON_LANGUAGES)
    assert set(BUTTON_LANGUAGES.values()) == {"en", "si", "ta"}


@pytest.mark.parametrize("button_id,expected", [("lang_en", "en"), ("lang_si", "si"), ("lang_ta", "ta")])
def test_tapped_button_resolves_to_its_language(button_id: str, expected: str) -> None:
    message = {"interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}}}

    assert language_from_reply(message) == expected


def test_non_button_messages_resolve_to_nothing() -> None:
    assert language_from_reply({"type": "text", "text": {"body": "hi"}}) is None
    assert language_from_reply({}) is None
    assert language_from_reply({"interactive": {"type": "list_reply"}}) is None


def test_unknown_button_id_is_not_treated_as_a_language() -> None:
    message = {"interactive": {"type": "button_reply", "button_reply": {"id": "something_else"}}}

    assert language_from_reply(message) is None
