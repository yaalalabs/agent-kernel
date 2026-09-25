from __future__ import annotations

import pytest

from localization import (
    LANGUAGE_EXAMPLE_PROMPTS,
    appliance_key_from_name,
    appliance_name,
    build_savings_plan,
    detect_language,
    normalize_language,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please use English", "en"),
        ("සිංහලෙන් පිළිතුරු දෙන්න", "si"),
        ("எனக்கு தமிழில் பதில் சொல்லுங்கள்", "ta"),
        ("Switch to Sinhala", "si"),
        ("Tamil please", "ta"),
        ("What is my bill?", None),
    ],
)
def test_language_detection(text: str, expected: str | None) -> None:
    assert detect_language(text) == expected


@pytest.mark.parametrize(
    ("language", "name"),
    [("en", "Refrigerator"), ("si", "ශීතකරණය"), ("ta", "குளிர்சாதனப் பெட்டி")],
)
def test_appliance_names_round_trip(language: str, name: str) -> None:
    assert appliance_name("refrigerator", language) == name
    assert appliance_key_from_name(name) == "refrigerator"


def test_unknown_language_falls_back_to_english() -> None:
    assert normalize_language("xx") == "en"


def test_committed_example_prompts_are_detectable() -> None:
    assert detect_language(LANGUAGE_EXAMPLE_PROMPTS["si"]) == "si"
    assert detect_language(LANGUAGE_EXAMPLE_PROMPTS["ta"]) == "ta"


_BOUNDARY = {"units_to_cut": 1.0, "target_units": 60.0, "savings": 630.0}
_APPLIANCES = [
    {"key": "refrigerator", "share_pct": 55.0},
    {"key": "air_conditioner", "share_pct": 30.0},
]


@pytest.mark.parametrize("language", ["en", "si", "ta"])
def test_plan_numbers_every_step_starting_at_one(language: str) -> None:
    plan = build_savings_plan(language, _BOUNDARY, _APPLIANCES)

    lines = plan.splitlines()
    numbered = lines[1:]  # line 0 is the heading
    assert [line.split(".")[0] for line in numbered] == [str(n) for n in range(1, len(numbered) + 1)]
    assert len(numbered) == 4  # boundary + 2 appliances + recheck


def test_plan_currency_is_worded_never_lkr_in_sinhala_or_tamil() -> None:
    si_plan = build_savings_plan("si", _BOUNDARY, [])
    ta_plan = build_savings_plan("ta", _BOUNDARY, [])

    assert "රුපියල්" in si_plan and "LKR" not in si_plan
    assert "ரூபாய்" in ta_plan and "LKR" not in ta_plan
    assert "LKR" in build_savings_plan("en", _BOUNDARY, [])


def test_plan_degrades_to_appliances_only_without_a_boundary_win() -> None:
    plan = build_savings_plan("en", None, _APPLIANCES)

    assert "Refrigerator" in plan
    assert "Air Conditioner" in plan or "air_conditioner" not in plan  # localized name, not the raw key
    assert plan.count("\n") == 3  # heading + 2 appliance steps + recheck, no boundary step


def test_plan_falls_back_to_a_general_tip_for_a_metered_only_household() -> None:
    """No appliance breakdown at all (bill/meter reading only) and already on the
    cheapest slab (no boundary win) must still produce a followable plan."""
    plan = build_savings_plan("en", None, [])

    lines = plan.splitlines()
    assert len(lines) == 3  # heading + one general tip + recheck
    assert "Your action plan:" in lines[0]
    assert "meter reading" in lines[-1]


def test_plan_appliance_step_cites_the_actual_saving_tip() -> None:
    plan = build_savings_plan("en", None, [{"key": "refrigerator", "share_pct": 55.0}])

    assert "fridge" in plan.lower() or "compressor" in plan.lower() or "seal" in plan.lower()
