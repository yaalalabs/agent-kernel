"""WhatsApp markup normalization.

WhatsApp is not Markdown: emphasis is *single* asterisks and there are no
headings or links. Models emit Markdown regardless, so these pin the deterministic
rewrite that keeps stray `**` and `###` out of the chat.
"""

from __future__ import annotations

import pytest

from hooks import to_whatsapp_markup

BULLET = "•"


def test_double_asterisk_bold_becomes_whatsapp_bold() -> None:
    assert to_whatsapp_markup("**Your bill:** LKR 1,260.00") == "*Your bill:* LKR 1,260.00"


def test_existing_whatsapp_bold_is_left_alone() -> None:
    """Already-correct markup must survive untouched."""
    assert to_whatsapp_markup("*Your bill:* LKR 1,260.00") == "*Your bill:* LKR 1,260.00"


def test_headings_become_bold_lines() -> None:
    assert to_whatsapp_markup("### Summary\nSome text") == "*Summary*\nSome text"
    assert to_whatsapp_markup("# Big\ntext") == "*Big*\ntext"


def test_markdown_bullets_become_real_bullets() -> None:
    assert to_whatsapp_markup("- fridge\n- fan") == f"{BULLET} fridge\n{BULLET} fan"
    assert to_whatsapp_markup("* fridge") == f"{BULLET} fridge"


def test_nested_bullet_indentation_is_preserved() -> None:
    assert to_whatsapp_markup("- a\n  - b") == f"{BULLET} a\n  {BULLET} b"


def test_links_are_flattened_since_whatsapp_has_none() -> None:
    assert (
        to_whatsapp_markup("See [PUCSL](https://pucsl.gov.lk) for rates")
        == "See PUCSL (https://pucsl.gov.lk) for rates"
    )


def test_underscore_italics_are_collapsed() -> None:
    assert to_whatsapp_markup("__estimate__") == "_estimate_"


def test_long_blank_runs_are_collapsed() -> None:
    assert to_whatsapp_markup("a\n\n\n\nb") == "a\n\nb"


def test_money_and_units_are_never_altered() -> None:
    """Formatting must not touch a number the engine produced."""
    text = "Your estimated bill is LKR 1,260.00 for 61.0 kWh (30 days)."

    assert to_whatsapp_markup(text) == text


def test_sinhala_and_tamil_text_survives() -> None:
    si = "**බිල:** රු. 1,260.00"
    assert to_whatsapp_markup(si) == "*බිල:* රු. 1,260.00"
    ta = "- மின் கட்டணம்"
    assert to_whatsapp_markup(ta) == f"{BULLET} மின் கட்டணம்"


@pytest.mark.parametrize("value", ["", None])
def test_empty_input_is_returned_unchanged(value) -> None:
    assert to_whatsapp_markup(value) == value


def test_conversion_is_idempotent() -> None:
    once = to_whatsapp_markup("### Bill\n**Total:** LKR 900.00\n- fridge")

    assert to_whatsapp_markup(once) == once


def test_refusal_offers_alternatives_in_every_language() -> None:
    """A refusal must never be a dead end — it redirects to what we can do."""
    from hooks import REFUSALS

    for lang, text in REFUSALS.items():
        assert BULLET in text, f"{lang} refusal offers no alternatives"
        assert text.count(BULLET) >= 2, f"{lang} refusal offers too few alternatives"


def test_refusal_points_at_a_real_authority_not_just_a_no() -> None:
    from hooks import REFUSALS

    for lang, text in REFUSALS.items():
        assert "1987" in text, f"{lang} refusal omits the CEB fault line"


def test_agents_never_claim_to_be_the_utility() -> None:
    """Impersonating CEB/LECO would be dishonest and would risk the number."""
    import agent

    for a in agent.AGENTS:
        assert "never state or imply that you are ceb" in a.instruction.lower()


def test_em_dashes_are_replaced_with_ordinary_punctuation() -> None:
    """The model reaches for em dashes constantly; replies must not carry them."""
    assert to_whatsapp_markup("Estimate only — not an official bill") == "Estimate only, not an official bill"
    assert to_whatsapp_markup("units – the main driver") == "units, the main driver"


def test_numeric_ranges_keep_a_hyphen_not_a_comma() -> None:
    """'5–10 units' must not become '5, 10 units'."""
    assert to_whatsapp_markup("Use 5–10 units less") == "Use 5-10 units less"


def test_no_user_facing_constant_contains_a_dash() -> None:
    from hooks import DISCLAIMERS, REFUSALS
    from whatsapp_ext.handler import _MEDIA_ACK
    from whatsapp_ext.interactive import LANGUAGE_PROMPT

    strings = list(DISCLAIMERS.values()) + list(REFUSALS.values()) + [_MEDIA_ACK, LANGUAGE_PROMPT]
    for text in strings:
        assert "—" not in text and "–" not in text, f"dash left in: {text[:60]}"


def test_ordinary_hyphens_are_untouched() -> None:
    """Dates and hyphenated words must survive."""
    assert to_whatsapp_markup("Reading date 2026-08-13") == "Reading date 2026-08-13"
