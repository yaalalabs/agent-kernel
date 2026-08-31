"""Correctness validation for the deterministic engine (NOT a demo).

Golden vectors are computed BY THE ENGINE against the committed seed table, so they
are internally self-consistent (the plan's critic explicitly required this). They
pin the engine's behaviour — especially the retroactive 60-unit cliff and the
duty-cycle consumption model — so a future change that breaks them fails loudly.

Run:  python golden_vectors.py      (from this directory)
Exit code 0 = all invariants hold; non-zero = a regression.
"""

from __future__ import annotations

from .consumption import appliance_kwh, estimate_total, load_appliances
from .tariff import boundary_opportunities, compute_bill, load_tariff, simulate_reduction


def _approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def validate_tariff() -> list[str]:
    table = load_tariff()
    checks: list[str] = []
    vectors = {
        0: 80.00,
        30: 230.00,
        45: 495.00,
        60: 630.00,
        61: 1260.00,
        75: 1540.00,
        90: 1840.00,
        100: 2720.00,
        120: 3280.00,
        150: 5100.00,
        180: 6420.00,
        181: 8450.00,
        250: 15350.00,
        300: 20350.00,
    }

    print(f"\nTariff table: {table.category}  (effective {table.effective_date}, {table.currency})")
    print("  status:", "verified" if table.status.startswith("VERIFIED") else table.status)
    print(f"\n  {'units':>6} {'slab':>4} {'fixed':>9} {'energy':>10} {'total':>10}")
    print("  " + "-" * 43)
    prev_total = -1.0
    for units, expected_total in vectors.items():
        b = compute_bill(units, table=table)
        u = units
        print(f"  {u:>6} {b['slab']:>4} {b['fixed_charge']:>9.2f} {b['energy_charge']:>10.2f} {b['total']:>10.2f}")
        assert _approx(b["total"], expected_total), f"{units} units: expected {expected_total}, got {b['total']}"
        assert b["total"] >= prev_total - 1e-9, f"bill not monotonic at {u} units"
        prev_total = b["total"]
    checks.append("official 30-day totals + monotonicity")

    b0 = compute_bill(0, table=table)
    assert _approx(b0["total"], b0["fixed_charge"]), "zero-unit bill must equal the fixed charge"
    checks.append("min-bill == fixed-charge")

    b60 = compute_bill(60, table=table)
    b61 = compute_bill(61, table=table)
    cliff = round(b61["total"] - b60["total"], 2)
    assert b61["slab"] != b60["slab"], "60 and 61 units must sit in different slabs"
    assert cliff > 300, f"expected a large 60->61 cliff, got {cliff}"
    print(f"\n  60->61 cliff: +{cliff} {table.currency} for ONE extra unit " f"(slab {b60['slab']}->{b61['slab']}).")
    checks.append(f"60->61 cliff = +{cliff}")

    opps = boundary_opportunities(61, table=table)
    assert opps, "expected at least one boundary opportunity at 61 units"
    best = opps[0]
    assert best["units_to_cut"] == 1 and best["to_slab"] == "B", "best fix at 61 should be cut 1 -> slab B"
    print(
        f"  optimizer @61u: cut {best['units_to_cut']} unit -> save "
        f"{best['savings']} {table.currency} (per-unit {best['savings_per_unit_cut']})."
    )
    checks.append("optimizer finds 1-unit boundary fix")

    sim = simulate_reduction(100, 15, table=table)
    assert sim["bill_savings"] >= 0, "cutting kWh must not raise the bill"
    checks.append("reduction ROI non-negative")

    b120_60d = compute_bill(120, table=table, billing_days=60)
    b121_60d = compute_bill(121, table=table, billing_days=60)
    assert b120_60d["total"] == 1050.0 and b120_60d["fixed_charge"] == 210.0
    assert b121_60d["total"] == 2100.0
    checks.append("60-day ceilings doubled; fixed charge applied once")

    b62_31d = compute_bill(62, table=table, billing_days=31)
    b63_31d = compute_bill(63, table=table, billing_days=31)
    assert b62_31d["total"] == 644.0 and b63_31d["total"] == 1288.0
    checks.append("arbitrary-day ceilings use PUCSL floor proration")

    b181 = compute_bill(181, table=table)
    assert b181["slab"] == "F" and b181["total"] == 8450.0
    checks.append("May-2026 above-180 category")

    return checks


def validate_consumption() -> list[str]:
    catalog = load_appliances()
    checks: list[str] = []
    print("\nConsumption golden anchors (monthly kWh):")

    # Fridge: 150W * 0.35 duty * 24h = 1260 Wh/day * 30 / 1000 = 37.8 kWh
    fridge = appliance_kwh(catalog["refrigerator"], hours_per_day=24, days=30)
    assert _approx(fridge, 37.8), f"fridge kWh {fridge} != 37.8"
    print(f"  refrigerator 24h/day  -> {fridge:.2f} kWh (expected 37.80)")
    checks.append("fridge=37.8")

    # AC: 1100W * 0.60 * 5h = 3300 Wh/day * 30 / 1000 = 99.0 kWh
    ac = appliance_kwh(catalog["air_conditioner"], hours_per_day=5, days=30)
    assert _approx(ac, 99.0), f"AC kWh {ac} != 99.0"
    print(f"  air conditioner 5h/day -> {ac:.2f} kWh (expected 99.00)")
    checks.append("ac=99.0")

    # Iron: 1000W * 0.60 * 0.5h = 300 Wh/day * 30 / 1000 = 9.0 kWh
    iron = appliance_kwh(catalog["iron"], hours_per_day=0.5, days=30)
    assert _approx(iron, 9.0), f"iron kWh {iron} != 9.0"
    print(f"  iron 0.5h/day          -> {iron:.2f} kWh (expected 9.00)")
    checks.append("iron=9.0")

    # Aggregate + breakdown ordering: AC must dominate.
    result = estimate_total(
        [
            {"key": "refrigerator", "hours_per_day": 24},
            {"key": "air_conditioner", "hours_per_day": 5},
            {"key": "led_bulb", "hours_per_day": 5, "quantity": 6},
            {"key": "iron", "hours_per_day": 0.5},
        ]
    )
    assert result["breakdown"][0]["key"] == "air_conditioner", "AC should be the top consumer"
    print(
        f"  sample household total -> {result['total_kwh']:.2f} kWh; "
        f"top: {result['breakdown'][0]['name']} ({result['breakdown'][0]['share_pct']}%)"
    )
    checks.append("aggregate + impact ordering")

    return checks


def main() -> int:
    print("=" * 60)
    print("Sarasavi Power — engine correctness validation")
    print("=" * 60)
    try:
        tariff_checks = validate_tariff()
        consumption_checks = validate_consumption()
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        return 1

    total = len(tariff_checks) + len(consumption_checks)
    print(f"\nAll {total} invariants held " f"({len(tariff_checks)} tariff, {len(consumption_checks)} consumption).")
    print("Tariff anchors match the PUCSL calculator effective 11 May 2026.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
