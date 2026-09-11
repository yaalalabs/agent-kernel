"""A real question must never be swallowed by the language chooser.

A user asked "Rupiyal 3400 ka bilak enne normally kochchara units walatada?" and
the prompt consumed it: the buttons went out, the question was discarded, and
after choosing a language they were asked about appliances instead. The chooser
is housekeeping and must never cost the user the thing they came to say.
"""

from __future__ import annotations

import json

import pytest

import tool
from whatsapp_ext.handler import _is_bare_greeting


def _text(body: str) -> dict:
    return {"type": "text", "text": {"body": body}}


@pytest.mark.parametrize("body", ["Hi", "hello", "ayubowan", "හෙලෝ", "Hey there"])
def test_openers_may_be_greeted_with_the_chooser(body: str) -> None:
    assert _is_bare_greeting(_text(body)) is True


@pytest.mark.parametrize(
    "body",
    [
        "Rupiyal 3400 ka bilak enne normally kochchara units walatada ?",  # the real one
        "27 units kiyada?",
        "how much is 150 units",
        "මගේ බිල අඩු කරගන්නේ කොහොමද?",
    ],
)
def test_real_questions_are_never_swallowed(body: str) -> None:
    assert _is_bare_greeting(_text(body)) is False


@pytest.mark.parametrize("kind", ["audio", "image", "document", "interactive"])
def test_media_is_never_treated_as_a_greeting(kind: str) -> None:
    """A voice note or bill photo IS the request."""
    assert _is_bare_greeting({"type": kind}) is False


def test_empty_body_is_not_a_greeting() -> None:
    assert _is_bare_greeting(_text("   ")) is False


def test_reverse_lookup_answers_the_question_that_was_lost() -> None:
    result = json.loads(tool.estimate_units_for_bill(3400))

    assert result["ok"] is True
    assert result["units"] == 120.0
    assert result["slab"] == "D"


def test_reverse_lookup_is_honest_about_the_gap_between_blocks() -> None:
    """A stepped tariff cannot land on every amount; say so rather than pretend."""
    result = json.loads(tool.estimate_units_for_bill(3400))

    assert result["bill_at_those_units"] == 3280.00
    assert result["difference"] == -120.00


@pytest.mark.parametrize("amount,units", [(215, 27.0), (1260, 61.0), (80, 0.0)])
def test_reverse_lookup_round_trips_exact_bills(amount, units) -> None:
    assert json.loads(tool.estimate_units_for_bill(amount))["units"] == units


@pytest.mark.parametrize("bad", [-1, float("nan")])
def test_invalid_amounts_are_rejected(bad) -> None:
    assert json.loads(tool.estimate_units_for_bill(bad))["ok"] is False
