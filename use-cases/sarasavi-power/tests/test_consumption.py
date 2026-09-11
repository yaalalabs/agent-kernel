from __future__ import annotations

import pytest

from engine import appliance_kwh, estimate_total, load_appliances


def test_known_appliance_anchors() -> None:
    catalog = load_appliances()

    assert appliance_kwh(catalog["refrigerator"], 24, days=30) == pytest.approx(37.8)
    assert appliance_kwh(catalog["air_conditioner"], 5, days=30) == pytest.approx(99.0)
    assert appliance_kwh(catalog["iron"], 0.5, days=30) == pytest.approx(9.0)


def test_period_days_scale_consumption_and_preserve_impact_order() -> None:
    result = estimate_total(
        [
            {"key": "refrigerator", "hours_per_day": 24, "days": 60},
            {"key": "air_conditioner", "hours_per_day": 5, "days": 60},
        ]
    )

    assert result["total_kwh"] == 273.6
    assert result["breakdown"][0]["key"] == "air_conditioner"
    assert result["breakdown"][0]["kwh"] == 198.0


@pytest.mark.parametrize("hours", [-1, 25, float("nan"), float("inf")])
def test_invalid_hours_are_rejected(hours: float) -> None:
    refrigerator = load_appliances()["refrigerator"]

    with pytest.raises(ValueError):
        appliance_kwh(refrigerator, hours)


@pytest.mark.parametrize(("quantity", "days"), [(True, 30), (1.5, 30), (1, False), (1, 0)])
def test_invalid_quantity_or_days_are_rejected(quantity, days) -> None:
    refrigerator = load_appliances()["refrigerator"]

    with pytest.raises(ValueError):
        appliance_kwh(refrigerator, 24, quantity=quantity, days=days)
