from __future__ import annotations

import pytest

from localization import (
    LANGUAGE_EXAMPLE_PROMPTS,
    appliance_key_from_name,
    appliance_name,
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
