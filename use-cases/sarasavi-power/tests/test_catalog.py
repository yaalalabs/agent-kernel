"""Appliance catalog coverage, aliasing, and data sanity.

A resolution miss is user-visible: the assistant tells the household its appliance
is unsupported and (before this) quoted the internal key back at them.
"""

from __future__ import annotations

import pytest

from engine import load_appliances
from localization import APPLIANCE_ALIASES, APPLIANCE_NAMES
from tool import _friendly_catalog, _resolve_appliance_key

CATALOG = load_appliances()


def test_catalog_covers_a_realistic_sri_lankan_household() -> None:
    """The v1 catalog of 16 missed common appliances such as table fans."""
    assert len(CATALOG) >= 45

    for key in (
        "table_fan",
        "electric_kettle",
        "set_top_box",
        "storage_water_heater",
        "induction_cooker",
        "cctv_system",
        "power_inverter",
        "chest_freezer",
    ):
        assert key in CATALOG, f"missing common appliance: {key}"


@pytest.mark.parametrize("language", ["en", "si", "ta"])
def test_every_appliance_is_named_in_every_language(language: str) -> None:
    missing = set(CATALOG) - set(APPLIANCE_NAMES[language])

    assert not missing, f"{language} names missing for: {sorted(missing)}"


@pytest.mark.parametrize("language", ["si", "ta"])
def test_every_localized_name_resolves_back_to_its_appliance(language: str) -> None:
    """A user typing the Sinhala/Tamil name must be understood."""
    for key, name in APPLIANCE_NAMES[language].items():
        assert _resolve_appliance_key(name, CATALOG) == key, f"{language} '{name}' did not resolve"


def test_every_alias_points_at_a_real_appliance() -> None:
    unknown = {alias: key for alias, key in APPLIANCE_ALIASES.items() if key not in CATALOG}

    assert not unknown, f"aliases point at missing keys: {unknown}"


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("table fan", "table_fan"),  # the case that failed in production
        ("desktop pc", "desktop_computer"),  # ditto
        ("Table Fan", "table_fan"),
        ("stand fan", "table_fan"),
        ("pedestal fan", "table_fan"),
        ("fridge", "refrigerator"),
        ("ac", "air_conditioner"),
        ("PEO TV", "set_top_box"),
        ("geyser", "storage_water_heater"),
        ("kettle", "electric_kettle"),
        ("water motor", "water_pump"),
        ("mixie", "blender"),
        ("ups", "power_inverter"),
        ("cctv", "cctv_system"),
        ("pankawa", "ceiling_fan"),  # romanized Sinhala
        ("isthrikkaya", "iron"),
        ("rupavahiniya", "tv_led"),
    ],
)
def test_colloquial_names_resolve(spoken: str, expected: str) -> None:
    assert _resolve_appliance_key(spoken, CATALOG) == expected


@pytest.mark.parametrize("plural,expected", [("fans", "ceiling_fan"), ("led bulbs", "led_bulb"), ("laptops", "laptop")])
def test_plurals_resolve(plural: str, expected: str) -> None:
    assert _resolve_appliance_key(plural, CATALOG) == expected


def test_genuinely_unknown_input_still_returns_none() -> None:
    """Aliasing must not become a catch-all that silently mislabels appliances."""
    assert _resolve_appliance_key("nonsense_thing", CATALOG) is None
    assert _resolve_appliance_key("", CATALOG) is None


def test_error_replies_offer_display_names_not_internal_keys() -> None:
    """The production bug: the model quoted 'table_fan' and 'desktop_pc' at the user."""
    names = _friendly_catalog(CATALOG)

    assert len(names) == len(CATALOG)
    assert not any("_" in name for name in names), "an internal key leaked into the user-facing list"
    assert "Table or stand fan" in names


@pytest.mark.parametrize("key,item", sorted(CATALOG.items()))
def test_power_figures_are_physically_sane(key: str, item) -> None:
    assert 1 <= item.watts <= 4000, f"{key} draws an implausible {item.watts} W"
    assert 0 < item.duty_cycle <= 1.0, f"{key} has an invalid duty cycle"
    assert 0 <= item.standby_watts <= item.watts, f"{key} standby exceeds rated draw"
    if item.standby_watts:
        assert item.always_plugged, f"{key} has standby draw but is not always plugged"
