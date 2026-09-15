"""Contract tests: every tool returns parseable JSON with stable top-level keys.

The voice bridge and the text agents both quote these payloads verbatim, so key
renames are breaking changes. Keep this suite keyless and network-free.
"""

from __future__ import annotations

import json

import pytest

import tool


def _consented_household(billing_days: int = 30) -> None:
    tool.set_storage_consent(True)
    tool.set_household(billing_cycle="monthly", billing_days=billing_days)
    tool.add_appliance("refrigerator", 24)
    tool.add_appliance("ceiling_fan", 8, quantity=2)


@pytest.mark.parametrize(
    ("call", "expected_keys"),
    [
        (lambda: tool.set_storage_consent(True), {"ok", "consent", "data_erased"}),
        (lambda: tool.set_household(billing_cycle="monthly"), {"ok", "profile"}),
        (lambda: tool.list_appliances(), {"language", "appliances"}),
        (lambda: tool.add_appliance("refrigerator", 24), {"ok", "added", "appliances"}),
        (lambda: tool.remove_appliance("refrigerator"), {"ok", "removed", "appliance", "appliances"}),
        (lambda: tool.set_language("si"), {"ok", "language"}),
        (lambda: tool.record_bill_reading(61), {"ok", "metered_units", "billing_days"}),
        (lambda: tool.clear_bill_reading(), {"ok", "metered_units"}),
        (lambda: tool.get_household_profile(), {"profile"}),
        (lambda: tool.export_household_data(), {"ok", "profile"}),
        (lambda: tool.delete_household_data(), {"ok", "deleted"}),
    ],
)
def test_intake_tools_return_stable_json_keys(memory_cache, call, expected_keys) -> None:
    tool.set_storage_consent(True)

    payload = json.loads(call())

    assert expected_keys <= set(payload)


def test_analysis_and_recommendation_tools_return_stable_json_keys(memory_cache) -> None:
    _consented_household()

    consumption = json.loads(tool.estimate_consumption())
    bill = json.loads(tool.compute_current_bill())
    savings = json.loads(tool.find_savings())
    simulation = json.loads(tool.simulate_change("ceiling_fan", 4))
    tips = json.loads(tool.match_saving_tips("fan"))

    assert {"ok", "billing_days", "total_kwh", "breakdown"} <= set(consumption)
    assert {"ok", "units_source", "slab", "total", "billing_days"} <= set(bill)
    assert {
        "ok",
        "units",
        "units_source",
        "current_bill",
        "confidence",
        "top_boundary_opportunity",
        "high_impact_appliances",
        "tips",
    } <= set(savings)
    assert {"ok", "appliance", "estimated_before_kwh", "estimated_after_kwh"} <= set(simulation)
    assert {"query", "language", "tips"} <= set(tips)


@pytest.mark.parametrize(
    "call",
    [
        lambda: tool.set_household(billing_cycle="weekly"),
        lambda: tool.add_appliance("refrigerator", 24.5),
        lambda: tool.add_appliance("refrigerator", -1),
        lambda: tool.add_appliance("hovercraft", 1),
        lambda: tool.record_bill_reading(-5),
        lambda: tool.record_bill_reading(61, billing_days=367),
        lambda: tool.simulate_change("air_conditioner", 3),
    ],
)
def test_invalid_inputs_return_structured_errors(memory_cache, call) -> None:
    tool.set_storage_consent(True)

    payload = json.loads(call())

    assert payload["ok"] is False
    assert payload["error"]


def test_boundary_values_are_accepted(memory_cache) -> None:
    tool.set_storage_consent(True)

    assert json.loads(tool.add_appliance("led_bulb", 0))["ok"] is True
    assert json.loads(tool.add_appliance("ceiling_fan", 24))["ok"] is True
    assert json.loads(tool.record_bill_reading(0))["ok"] is True
    assert json.loads(tool.record_bill_reading(61, billing_days=366))["ok"] is True


def test_spoken_language_aliases_resolve(memory_cache) -> None:
    tool.set_storage_consent(True)

    assert json.loads(tool.add_appliance("ෆෑන් එක", 8))["added"] == "ceiling_fan"
    assert json.loads(tool.add_appliance("ஃப்ரிட்ஜ்", 24))["added"] == "refrigerator"
    assert json.loads(tool.add_appliance("aircon", 5))["added"] == "air_conditioner"
    assert json.loads(tool.add_appliance("වතුර මෝටරය", 1))["added"] == "water_pump"
