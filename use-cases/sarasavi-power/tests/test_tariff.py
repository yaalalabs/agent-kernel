from __future__ import annotations

import pytest

from engine import boundary_opportunities, compute_bill, simulate_reduction


@pytest.mark.parametrize(
    ("units", "slab", "total"),
    [
        (0, "A", 80.0),
        (30, "A", 230.0),
        (60, "B", 630.0),
        (61, "C", 1260.0),
        (90, "C", 1840.0),
        (91, "D", 2468.0),
        (120, "D", 3280.0),
        (180, "E", 6420.0),
        (181, "F", 8450.0),
        (250, "F", 15350.0),
    ],
)
def test_official_30_day_tariff_anchors(units: float, slab: str, total: float) -> None:
    result = compute_bill(units)

    assert result["slab"] == slab
    assert result["total"] == total
    assert result["billing_days"] == 30
    assert result["effective_date"] == "2026-05-11"
    assert result["unverified"] is False


def test_sixty_day_boundaries_double_without_doubling_fixed_charge() -> None:
    at_boundary = compute_bill(120, billing_days=60)
    above_boundary = compute_bill(121, billing_days=60)

    assert at_boundary["slab"] == "B"
    assert at_boundary["fixed_charge"] == 210.0
    assert at_boundary["total"] == 1050.0
    assert above_boundary["slab"] == "C"
    assert above_boundary["total"] == 2100.0


def test_arbitrary_billing_days_follow_official_floor_proration() -> None:
    assert compute_bill(62, billing_days=31)["total"] == 644.0
    assert compute_bill(63, billing_days=31)["total"] == 1288.0


def test_sixty_day_180_equivalent_cliff() -> None:
    """The retroactive re-pricing cliff at the 180-unit equivalent on a 60-day cycle."""
    at_boundary = compute_bill(360, billing_days=60)
    above_boundary = compute_bill(361, billing_days=60)

    assert at_boundary["slab"] == "E"
    assert at_boundary["total"] == 11340.0
    assert above_boundary["slab"] == "F"
    assert above_boundary["total"] == 14300.0


def test_boundary_optimizer_finds_181_unit_cliff() -> None:
    best = boundary_opportunities(181)[0]

    assert best["target_units"] == 180.0
    assert best["units_to_cut"] == 1.0
    assert best["savings"] == 2030.0


def test_boundary_optimizer_finds_one_unit_cliff() -> None:
    best = boundary_opportunities(61)[0]

    assert best["target_units"] == 60.0
    assert best["units_to_cut"] == 1.0
    assert best["savings"] == 630.0


def test_simulation_uses_requested_billing_period() -> None:
    result = simulate_reduction(121, 1, billing_days=60)

    assert result["billing_days"] == 60
    assert result["crossed_slab"] is True
    assert result["bill_savings"] == 1050.0


@pytest.mark.parametrize("days", [0, 367, True, 30.5])
def test_invalid_billing_days_are_rejected(days) -> None:
    with pytest.raises(ValueError):
        compute_bill(60, billing_days=days)


@pytest.mark.parametrize("units", [-1, float("inf"), float("nan")])
def test_invalid_units_are_rejected(units: float) -> None:
    with pytest.raises(ValueError):
        compute_bill(units)
