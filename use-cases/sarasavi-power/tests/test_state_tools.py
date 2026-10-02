from __future__ import annotations

import json

import pytest

import state
import tool


def decode(payload: str) -> dict:
    return json.loads(payload)


def test_profile_writes_require_explicit_consent(memory_cache) -> None:
    denied = decode(tool.set_household(name="Nimali"))

    assert denied["ok"] is False
    assert "consent" in denied["error"]
    assert state.load_profile()["consent"] is False


def test_billing_period_drives_consumption_and_bill(memory_cache) -> None:
    assert decode(tool.set_storage_consent(True))["ok"] is True
    updated = decode(
        tool.set_household(
            name="Sivakumar",
            billing_cycle="bimonthly",
            language="ta",
        )
    )
    assert updated["profile"]["billing_days"] == 60
    assert decode(tool.add_appliance("refrigerator", 24))["ok"] is True

    usage = decode(tool.estimate_consumption())
    bill = decode(tool.compute_current_bill())

    assert usage["billing_days"] == 60
    assert usage["total_kwh"] == 75.6
    assert bill["units_source"] == "estimated"
    assert bill["total"] == 650.4


def test_metered_baseline_is_used_for_change_simulation(memory_cache) -> None:
    decode(tool.set_storage_consent(True))
    decode(tool.set_household(billing_cycle="monthly"))
    decode(tool.add_appliance("refrigerator", 24))
    reading = decode(tool.record_bill_reading(181, billing_days=30))

    assert reading["ok"] is True
    assert decode(tool.compute_current_bill())["total"] == 8450.0

    simulation = decode(tool.simulate_change("refrigerator", 12))

    assert simulation["baseline_source"] == "metered"
    assert simulation["before_units"] == 181.0
    assert simulation["after_units"] == 162.1
    assert simulation["bill_savings"] == pytest.approx(2817.6)


def test_export_delete_and_consent_revocation_erase_profile(memory_cache) -> None:
    decode(tool.set_storage_consent(True))
    decode(tool.set_household(name="Kalana", language="en"))

    exported = decode(tool.export_household_data())
    assert exported["profile"]["name"] == "Kalana"

    deleted = decode(tool.delete_household_data())
    assert deleted == {"ok": True, "deleted": True}
    assert state.load_profile()["consent"] is False

    decode(tool.set_storage_consent(True))
    decode(tool.set_household(name="Temporary"))
    revoked = decode(tool.set_storage_consent(False))
    assert revoked["data_erased"] is True
    assert state.load_profile()["name"] is None
    assert state.load_profile()["consent"] is False


def test_tool_validation_returns_structured_errors(memory_cache) -> None:
    decode(tool.set_storage_consent(True))

    assert decode(tool.set_language("xx"))["ok"] is False
    assert decode(tool.add_appliance("refrigerator", 4, quantity=0))["ok"] is False
    assert decode(tool.add_appliance("unknown", 4))["ok"] is False
    assert decode(tool.record_bill_reading(float("nan")))["ok"] is False
    assert decode(tool.record_bill_reading(20, billing_days=367))["ok"] is False


def test_friendly_appliance_names_are_resolved(memory_cache) -> None:
    decode(tool.set_storage_consent(True))

    added = decode(tool.add_appliance("air conditioner", 5))

    assert added["ok"] is True
    assert added["added"] == "air_conditioner"


def test_savings_exposes_current_bill_at_top_level(memory_cache) -> None:
    decode(tool.set_storage_consent(True))
    decode(tool.add_appliance("refrigerator", 24))
    decode(tool.add_appliance("ceiling_fan", 8, quantity=2))
    decode(tool.add_appliance("led_bulb", 5, quantity=6))

    savings = decode(tool.find_savings())

    assert savings["units"] == 79.5
    assert savings["current_bill"]["total"] == 1630.0
    assert savings["current_bill"]["slab"] == "C"


def test_savings_closes_with_a_followable_action_plan(memory_cache) -> None:
    """The recommendation agent is told to append this verbatim; it must exist
    and actually reflect this household's own boundary win, not a generic line."""
    decode(tool.set_storage_consent(True))
    decode(tool.add_appliance("refrigerator", 24))
    decode(tool.add_appliance("ceiling_fan", 8, quantity=2))
    decode(tool.add_appliance("led_bulb", 5, quantity=6))

    savings = decode(tool.find_savings())
    plan = savings["plan"]
    boundary = savings["top_boundary_opportunity"]

    assert plan.startswith("Your action plan:")
    assert f"{boundary['savings']:,.2f}" in plan
    assert "Refrigerator" in plan  # the household's own top appliance, not a placeholder


def test_appliance_can_be_removed_and_meter_reading_cleared(memory_cache) -> None:
    decode(tool.set_storage_consent(True))
    decode(tool.add_appliance("fridge", 24))
    decode(tool.record_bill_reading(61))

    removed = decode(tool.remove_appliance("refrigerator"))
    cleared = decode(tool.clear_bill_reading())

    assert removed["ok"] is True
    assert removed["removed"] is True
    assert removed["appliances"] == []
    assert cleared == {"ok": True, "metered_units": None}
    assert decode(tool.compute_current_bill())["ok"] is False


@pytest.mark.parametrize(
    ("language", "appliance_label", "tip_fragment"),
    [
        ("si", "ශීතකරණය", "ශීතකරණ"),
        ("ta", "குளிர்சாதனப் பெட்டி", "குளிர்சாதனப் பெட்டி"),
    ],
)
def test_tools_localize_appliances_breakdown_and_tips(
    memory_cache, language: str, appliance_label: str, tip_fragment: str
) -> None:
    decode(tool.set_storage_consent(True))
    decode(tool.set_language(language))
    decode(tool.add_appliance(appliance_label, 24))

    listed = decode(tool.list_appliances())
    usage = decode(tool.estimate_consumption())
    savings = decode(tool.find_savings())
    tips = decode(tool.match_saving_tips(appliance_label))

    refrigerator = next(item for item in listed["appliances"] if item["key"] == "refrigerator")
    assert listed["language"] == language
    assert refrigerator["name"] == appliance_label
    assert usage["breakdown"][0]["name"] == appliance_label
    assert savings["language"] == language
    assert any(tip_fragment in tip for tip in tips["tips"])
