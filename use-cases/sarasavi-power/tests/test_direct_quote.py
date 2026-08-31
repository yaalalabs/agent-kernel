"""Answering a bare pricing question, with nothing stored.

"How much is 27 units?" is the commonest first question a stranger asks, and it
must be answerable without consent, a profile, or an onboarding detour.
"""

from __future__ import annotations

import json

import pytest

import state
import tool


@pytest.fixture(autouse=True)
def _blank_session(memory_cache):
    """Every test here runs as a first-time user with an empty session."""
    assert state.load_profile().get("appliances") == []


def test_answers_with_no_profile_and_no_consent() -> None:
    result = json.loads(tool.estimate_bill_for_units(27))

    assert result["ok"] is True
    assert result["slab"] == "A"
    assert result["total"] == 215.00


def test_the_same_question_through_the_stateful_tool_still_refuses() -> None:
    """Contrast: the profile-based tool cannot answer a stranger, which is why
    the stateless one exists."""
    assert json.loads(tool.compute_current_bill())["ok"] is False


@pytest.mark.parametrize(
    "units,slab,total",
    [(0, "A", 80.00), (27, "A", 215.00), (60, "B", 630.00), (61, "C", 1260.00), (120, "D", 3280.00)],
)
def test_known_anchors(units, slab, total) -> None:
    result = json.loads(tool.estimate_bill_for_units(units))

    assert result["slab"] == slab
    assert result["total"] == total


def test_reports_the_boundary_that_would_reprice_the_period() -> None:
    """61 units is one unit into a costlier block; that is the useful part."""
    result = json.loads(tool.estimate_bill_for_units(61))

    assert result["nearest_boundary"] is not None
    assert result["nearest_boundary"]["target_units"] == 60


def test_billing_days_are_honoured() -> None:
    monthly = json.loads(tool.estimate_bill_for_units(120))
    bimonthly = json.loads(tool.estimate_bill_for_units(120, billing_days=60))

    # 120 units over 60 days is a much lighter user than 120 over 30.
    assert bimonthly["total"] < monthly["total"]


def test_answering_never_writes_to_the_session(memory_cache) -> None:
    """A quick quote must not quietly create a stored profile."""
    tool.estimate_bill_for_units(27)

    assert memory_cache.data == {}


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_units_are_rejected(bad) -> None:
    assert json.loads(tool.estimate_bill_for_units(bad))["ok"] is False


def test_invalid_billing_days_are_rejected() -> None:
    assert json.loads(tool.estimate_bill_for_units(50, billing_days=400))["ok"] is False
