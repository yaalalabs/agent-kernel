"""Deterministic CEB/LECO domestic electricity tariff engine.

Framework-agnostic pure Python — NO ``agentkernel`` imports. This module is the
correctness bedrock of Sarasavi Power: every rupee shown to a user is computed
here, never by an LLM. The Agent Kernel tool wrappers (``tool.py``) call into
this module and never re-implement any of it.

Tariff model: *retroactive slab*. Total monthly consumption selects exactly one
slab; that slab's fixed charge plus its full rate ladder price the WHOLE month.
Crossing a slab boundary re-prices every unit (it is not marginal pricing), so a
small cut across a boundary can cut the bill disproportionately. The 60-unit
boundary is a particularly visible example for low-usage households.

Numbers live in ``data/tariff_ceb_domestic.json`` (dated and swappable, with
source URLs and verification metadata). This module owns the *logic*; the JSON
owns the *values*.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, replace
from typing import Optional

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "tariff_ceb_domestic.json")


@dataclass(frozen=True)
class Slab:
    id: str
    min_units: int
    max_units: Optional[int]  # None => unbounded top slab
    fixed: float
    ladder: list[tuple[Optional[int], float]]  # [(upper_bound|None, rate_per_kwh), ...]


@dataclass(frozen=True)
class TariffTable:
    category: str
    effective_date: str
    currency: str
    status: str
    fas_rate_per_kwh: float
    reference_billing_days: int
    fixed_charge_prorated: bool
    slabs: list[Slab]
    # Optional Domestic Time-of-Use rates, and the Social Security Contribution
    # Levy every licensee adds. Both default to absent so an older dated table
    # still loads.
    time_of_use: dict | None = None
    sscl_rate_of_total: float = 0.0

    def cycles(self) -> list[str]:
        """Return the friendly billing-cycle names accepted by the public API."""
        return ["monthly", "bimonthly"]


def load_tariff(path: str = _DATA_PATH) -> TariffTable:
    """Load the dated PUCSL tariff table.

    The JSON stores the official 30-day ceilings. They are prorated at calculation
    time because PUCSL bills by the actual number of days between meter readings.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    meta = raw["meta"]
    monthly_cfg = raw["cycles"]["monthly"]
    monthly = [_slab_from_json(s) for s in monthly_cfg["slabs"]]

    return TariffTable(
        category=meta["category"],
        effective_date=meta["effective_date"],
        currency=meta["currency"],
        status=meta["status"],
        fas_rate_per_kwh=float(meta.get("fas_rate_per_kwh", 0.0)),
        reference_billing_days=int(meta.get("reference_billing_days", 30)),
        fixed_charge_prorated=bool(meta.get("fixed_charge_prorated", False)),
        slabs=monthly,
        time_of_use=raw.get("time_of_use"),
        sscl_rate_of_total=float(meta.get("sscl_rate_of_total", 0.0)),
    )


def _slab_from_json(s: dict) -> Slab:
    ladder = [(None if u is None else int(u), float(r)) for u, r in s["ladder"]]
    return Slab(
        id=s["id"],
        min_units=int(s["min"]),
        max_units=None if s["max"] is None else int(s["max"]),
        fixed=float(s["fixed"]),
        ladder=ladder,
    )


def _scale_slab(s: Slab, billing_days: int, reference_days: int) -> Slab:
    """Prorate one slab's unit ceilings exactly as the PUCSL calculator does."""

    def scale(upper: Optional[int]) -> Optional[int]:
        if upper is None:
            return None
        return math.floor(upper * billing_days / reference_days)

    return Slab(
        id=s.id,
        min_units=s.min_units,  # recomputed by _renumber_mins after ceilings scale
        max_units=scale(s.max_units),
        fixed=s.fixed,
        ladder=[(scale(upper), rate) for upper, rate in s.ladder],
    )


def _scaled_slabs(table: TariffTable, billing_days: int) -> list[Slab]:
    return _renumber_mins([_scale_slab(slab, billing_days, table.reference_billing_days) for slab in table.slabs])


def _renumber_mins(slabs: list[Slab]) -> list[Slab]:
    """Recompute display ``min_units`` so they stay contiguous with scaled maxima."""
    out: list[Slab] = []
    prev_max = -1
    for s in slabs:
        out.append(replace(s, min_units=prev_max + 1))
        prev_max = s.max_units if s.max_units is not None else prev_max
    return out


def _resolve_billing_days(cycle: str, billing_days: Optional[int]) -> int:
    if billing_days is None:
        try:
            billing_days = {"monthly": 30, "bimonthly": 60}[cycle]
        except KeyError as exc:
            raise ValueError("cycle must be 'monthly' or 'bimonthly'") from exc
    if isinstance(billing_days, bool) or not isinstance(billing_days, int):
        raise ValueError("billing_days must be a whole number")
    if not 1 <= billing_days <= 366:
        raise ValueError("billing_days must be between 1 and 366")
    return billing_days


def select_slab(units: float, slabs: list[Slab]) -> Slab:
    """Return the single slab a total-consumption figure falls into.

    Selection keys off the UPPER boundary only (slabs are ordered ascending): the
    slab is the first whose ``max_units`` is unbounded or >= ``units``. Keying off
    ``min_units`` would open gaps when boundaries are rescaled (e.g. bimonthly),
    so ``min_units`` is display metadata only.
    """
    if units < 0:
        raise ValueError("units must be >= 0")
    for slab in slabs:
        if slab.max_units is None or units <= slab.max_units:
            return slab
    return slabs[-1]  # unbounded top slab


def _energy_charge(units: float, ladder: list[tuple[Optional[int], float]]) -> float:
    """Charge each ladder segment (prev, upper] at its rate, up to ``units``."""
    total = 0.0
    prev = 0.0
    for upper, rate in ladder:
        seg_upper = units if upper is None else min(units, float(upper))
        if seg_upper > prev:
            total += (seg_upper - prev) * rate
            prev = seg_upper
        if upper is not None and units <= upper:
            break
    return total


def compute_bill(
    units: float,
    cycle: str = "monthly",
    table: Optional[TariffTable] = None,
    *,
    billing_days: Optional[int] = None,
) -> dict:
    """Compute a PUCSL domestic bill for the meter-reading period.

    ``cycle`` remains as a friendly compatibility input. Supplying
    ``billing_days`` enables the official calculator's exact day-based proration.
    """
    table = table or load_tariff()
    days = _resolve_billing_days(cycle, billing_days)
    if not math.isfinite(units) or units < 0:
        raise ValueError("units must be a finite number >= 0")

    slabs = _scaled_slabs(table, days)
    slab = select_slab(units, slabs)
    energy = _energy_charge(units, slab.ladder)
    fas = units * table.fas_rate_per_kwh
    total = slab.fixed + energy + fas

    return {
        "units": round(units, 3),
        "cycle": "monthly" if days == 30 else "bimonthly" if days == 60 else "custom",
        "billing_days": days,
        "slab": slab.id,
        "fixed_charge": round(slab.fixed, 2),
        "energy_charge": round(energy, 2),
        "fas_charge": round(fas, 2),
        "total": round(total, 2),
        "currency": table.currency,
        "effective_date": table.effective_date,
        "unverified": not table.status.upper().startswith("VERIFIED"),
    }


def boundary_opportunities(
    units: float,
    cycle: str = "monthly",
    table: Optional[TariffTable] = None,
    *,
    billing_days: Optional[int] = None,
) -> list[dict]:
    """Find lower slab boundaries below current usage and the savings of reaching them.

    This is the product's signature lever: because pricing is retroactive, dropping
    just below a boundary can cut the whole bill. Returns opportunities sorted by
    savings-per-unit-cut (most efficient first).
    """
    table = table or load_tariff()
    days = _resolve_billing_days(cycle, billing_days)
    slabs = _scaled_slabs(table, days)
    current = compute_bill(units, cycle, table, billing_days=days)
    current_slab = select_slab(units, slabs)

    opportunities: list[dict] = []
    for slab in slabs:
        # A boundary target is the top of a slab strictly below the current one.
        if slab.max_units is None or slab.max_units >= units:
            continue
        if slab.id == current_slab.id:
            continue
        target_units = float(slab.max_units)
        target_bill = compute_bill(target_units, cycle, table, billing_days=days)
        units_to_cut = round(units - target_units, 2)
        savings = round(current["total"] - target_bill["total"], 2)
        if units_to_cut <= 0 or savings <= 0:
            continue
        opportunities.append(
            {
                "target_units": target_units,
                "units_to_cut": units_to_cut,
                "from_slab": current_slab.id,
                "to_slab": slab.id,
                "current_bill": current["total"],
                "new_bill": target_bill["total"],
                "savings": savings,
                "savings_per_unit_cut": round(savings / units_to_cut, 2),
                "currency": table.currency,
                "billing_days": days,
            }
        )

    opportunities.sort(key=lambda o: o["savings_per_unit_cut"], reverse=True)
    return opportunities


def simulate_reduction(
    current_units: float,
    kwh_saved: float,
    cycle: str = "monthly",
    table: Optional[TariffTable] = None,
    *,
    billing_days: Optional[int] = None,
) -> dict:
    """Bill impact of shaving ``kwh_saved`` off current consumption (ROI of an action)."""
    table = table or load_tariff()
    days = _resolve_billing_days(cycle, billing_days)
    if not math.isfinite(current_units) or current_units < 0:
        raise ValueError("current_units must be a finite number >= 0")
    if not math.isfinite(kwh_saved):
        raise ValueError("kwh_saved must be finite")
    new_units = max(0.0, current_units - kwh_saved)
    before = compute_bill(current_units, cycle, table, billing_days=days)
    after = compute_bill(new_units, cycle, table, billing_days=days)
    return {
        "kwh_saved": round(kwh_saved, 3),
        "billing_days": days,
        "before_units": before["units"],
        "after_units": after["units"],
        "before_total": before["total"],
        "after_total": after["total"],
        "bill_savings": round(before["total"] - after["total"], 2),
        "crossed_slab": before["slab"] != after["slab"],
        "from_slab": before["slab"],
        "to_slab": after["slab"],
        "currency": table.currency,
    }


# --- Domestic Time-of-Use ------------------------------------------------------


# The Social Security Contribution Levy is 2.5% of the FINAL bill, not of the
# energy charge, so it is charged as charge x rate/(1 - rate). Verified to the
# cent against a real CEB bill: 55,293.00 charge -> 1,417.77 levy.
def sscl_levy(charge: float, table: Optional[TariffTable] = None) -> float:
    """The SSC Levy that a licensee adds on top of ``charge``."""
    rate = (table or load_tariff()).sscl_rate_of_total
    if not rate:
        return 0.0
    return round(charge * rate / (1.0 - rate), 2)


def compute_tou_bill(
    off_peak: float,
    day: float,
    peak: float,
    table: Optional[TariffTable] = None,
    *,
    billing_days: Optional[int] = None,
) -> dict:
    """Compute a Domestic Time-of-Use bill from the three metered period readings.

    D-TOU is a separate optional domestic tariff: three separately metered periods
    at flat rates, with no consumption blocks and no retroactive slab boundaries.
    Advice for these households is therefore about SHIFTING load between periods,
    not about staying under a boundary.
    """
    table = table or load_tariff()
    tou = table.time_of_use
    if not tou:
        raise ValueError("this tariff table carries no time-of-use rates")

    readings = {"off_peak": off_peak, "day": day, "peak": peak}
    for name, value in readings.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} units must be a finite number >= 0")

    days = _resolve_billing_days("monthly", billing_days)
    # The fixed charge is a monthly charge; a longer meter-reading period is
    # billed pro rata, matching how the block tariff's fixed charge behaves.
    fixed = round(tou["fixed_charge"] * days / 30.0, 2) if days != 30 else tou["fixed_charge"]

    breakdown = []
    energy = 0.0
    for name, units in readings.items():
        period = tou["periods"][name]
        cost = units * period["rate"]
        energy += cost
        breakdown.append(
            {
                "period": name,
                "window": period["window"],
                "units": round(units, 3),
                "rate": period["rate"],
                "cost": round(cost, 2),
            }
        )

    charge = round(fixed + energy, 2)
    levy = sscl_levy(charge, table)
    breakdown.sort(key=lambda item: item["cost"], reverse=True)
    total_units = round(off_peak + day + peak, 3)
    return {
        "tariff": "domestic_time_of_use",
        "units": total_units,
        "billing_days": days,
        "fixed_charge": fixed,
        "energy_charge": round(energy, 2),
        "charge": charge,
        "sscl_levy": levy,
        "total": round(charge + levy, 2),
        "breakdown": breakdown,
        "most_expensive_period": breakdown[0]["period"] if breakdown else None,
        "currency": table.currency,
    }


def units_for_bill(
    amount: float,
    table: Optional[TariffTable] = None,
    *,
    billing_days: Optional[int] = None,
) -> dict:
    """Invert the tariff: roughly how many units produce a bill of ``amount``.

    "My bill is about 3,400 rupees, how many units is that?" is a question people
    ask constantly, and it cannot be answered by the forward calculation. The bill
    rises monotonically with units, so a bisection inverts it safely. Fixed charges
    make the curve step, so an amount can fall in a gap between two blocks: the
    closest achievable bill is returned along with its own exact total, and the
    caller can see the difference.
    """
    table = table or load_tariff()
    days = _resolve_billing_days("monthly", billing_days)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("amount must be a finite number >= 0")

    low, high = 0.0, 64.0
    # Grow the bracket until the bill exceeds the target (guarded, not unbounded).
    while compute_bill(high, table=table, billing_days=days)["total"] < amount and high < 1_000_000:
        high *= 2

    for _ in range(60):
        mid = (low + high) / 2
        if compute_bill(mid, table=table, billing_days=days)["total"] < amount:
            low = mid
        else:
            high = mid

    units = round(high, 1)
    bill = compute_bill(units, table=table, billing_days=days)
    return {
        "asked_amount": round(float(amount), 2),
        "units": units,
        "billing_days": days,
        "slab": bill["slab"],
        "bill_at_those_units": bill["total"],
        "difference": round(bill["total"] - amount, 2),
        "currency": table.currency,
    }
