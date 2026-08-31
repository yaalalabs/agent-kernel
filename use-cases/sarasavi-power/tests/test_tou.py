"""Domestic Time-of-Use tariff, pinned to a real CEB bill.

Anchored to an actual D-TOU bill (reading date 2026-08-13) rather than to the
rate table alone: reproducing a printed bill to the cent is the only check that
proves the rates, the fixed charge and the levy formula are all right together.

  Consumption: 275(O), 540(D), 173(P)
  Charge:      Rs. 55,293.00
  SSC Levy:    Rs.  1,417.77
  Monthly Bill:Rs. 56,710.77
"""

from __future__ import annotations

import json

import pytest

import tool
from engine import compute_tou_bill, sscl_levy

REAL_BILL = {"off_peak": 275, "day": 540, "peak": 173}


def test_reproduces_the_printed_charge_exactly() -> None:
    assert compute_tou_bill(**REAL_BILL)["charge"] == 55293.00


def test_reproduces_the_printed_levy_and_total_exactly() -> None:
    result = compute_tou_bill(**REAL_BILL)

    assert result["sscl_levy"] == 1417.77
    assert result["total"] == 56710.77


def test_levy_is_two_and_a_half_percent_of_the_total_not_the_charge() -> None:
    """The bill proves the base: 1417.77 / 56710.77 is exactly 0.025."""
    result = compute_tou_bill(**REAL_BILL)

    assert round(result["sscl_levy"] / result["total"], 6) == 0.025
    # The naive reading (2.5% of the charge) would understate it.
    assert result["sscl_levy"] != round(result["charge"] * 0.025, 2)


def test_period_rates_match_the_may_2026_annex() -> None:
    rates = {b["period"]: b["rate"] for b in compute_tou_bill(**REAL_BILL)["breakdown"]}

    assert rates == {"off_peak": 33.0, "day": 47.0, "peak": 106.0}


def test_breakdown_leads_with_the_costliest_period() -> None:
    result = compute_tou_bill(**REAL_BILL)

    # Day dominates here despite peak costing 3x more per unit, which is exactly
    # the insight a TOU household needs.
    assert result["most_expensive_period"] == "day"
    assert result["breakdown"][0]["cost"] >= result["breakdown"][-1]["cost"]


def test_units_are_the_sum_of_the_three_periods() -> None:
    assert compute_tou_bill(**REAL_BILL)["units"] == 988


def test_zero_consumption_still_owes_the_fixed_charge_plus_levy() -> None:
    result = compute_tou_bill(0, 0, 0)

    assert result["charge"] == 2500.0
    assert result["total"] == round(2500.0 + sscl_levy(2500.0), 2)


def test_longer_meter_period_prorates_the_fixed_charge() -> None:
    monthly = compute_tou_bill(10, 10, 10)
    bimonthly = compute_tou_bill(10, 10, 10, billing_days=60)

    assert bimonthly["fixed_charge"] == round(monthly["fixed_charge"] * 2, 2)


@pytest.mark.parametrize("bad", [(-1, 0, 0), (0, float("nan"), 0), (0, 0, float("inf"))])
def test_invalid_readings_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        compute_tou_bill(*bad)


def test_tool_wrapper_returns_the_same_verified_total() -> None:
    payload = json.loads(tool.compute_time_of_use_bill(275, 540, 173))

    assert payload["ok"] is True
    assert payload["total"] == 56710.77
