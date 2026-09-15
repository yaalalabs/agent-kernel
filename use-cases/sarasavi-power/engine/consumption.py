"""Deterministic appliance-consumption estimator.

Framework-agnostic pure Python — NO ``agentkernel`` imports. This is the single,
canonical consumption model (the plan deliberately forbids competing definitions):
one thermostatic *duty-cycle* + *standby* formula, used by every tool wrapper.

kWh per appliance per month =
    quantity * ( watts * duty_cycle * active_hours
                 + standby_watts * standby_hours )   * days / 1000

where ``standby_hours`` applies only to ``always_plugged`` devices, for the part
of the day they are not in active use.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, replace
from typing import Optional

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "appliances.json")


@dataclass(frozen=True)
class Appliance:
    key: str
    name: str
    watts: float
    duty_cycle: float
    always_plugged: bool
    standby_watts: float
    category: str


def load_appliances(path: str = _DATA_PATH) -> dict[str, Appliance]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, Appliance] = {}
    for a in raw["appliances"]:
        out[a["key"]] = Appliance(
            key=a["key"],
            name=a["name"],
            watts=float(a["watts"]),
            duty_cycle=float(a["duty_cycle"]),
            always_plugged=bool(a["always_plugged"]),
            standby_watts=float(a.get("standby_watts", 0.0)),
            category=a["category"],
        )
    return out


def appliance_kwh(appliance: Appliance, hours_per_day: float, quantity: int = 1, days: int = 30) -> float:
    """Monthly kWh for one appliance line-item. The ONE consumption formula."""
    if not math.isfinite(hours_per_day) or hours_per_day < 0 or hours_per_day > 24:
        raise ValueError("hours_per_day must be within [0, 24]")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise ValueError("quantity must be a whole number >= 0")
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a whole number > 0")

    active_wh = appliance.watts * appliance.duty_cycle * hours_per_day
    if appliance.always_plugged:
        standby_hours = max(0.0, 24.0 - hours_per_day)
        standby_wh = appliance.standby_watts * standby_hours
    else:
        standby_wh = 0.0

    daily_wh = quantity * (active_wh + standby_wh)
    return daily_wh * days / 1000.0


def estimate_total(usages: list[dict], catalog: Optional[dict[str, Appliance]] = None) -> dict:
    """Aggregate a household's monthly kWh from a list of appliance usages.

    Each usage: {"key": str, "hours_per_day": float, "quantity": int?, "days": int?,
    "watts_override": float?}. ``watts_override`` replaces the catalog's typical
    rating with a value read off the household's own appliance (e.g. its nameplate),
    which is more accurate than the generic default.
    Returns total kWh plus a per-appliance breakdown sorted by impact (highest first)
    so the analysis agent can name the high-impact areas.
    """
    catalog = catalog or load_appliances()
    breakdown: list[dict] = []
    total = 0.0

    for u in usages:
        key = u["key"]
        if key not in catalog:
            raise KeyError(f"unknown appliance {key!r}")
        appliance = catalog[key]
        watts_override = u.get("watts_override")
        if watts_override is not None:
            appliance = replace(appliance, watts=float(watts_override))
        quantity = u.get("quantity", 1)
        days = u.get("days", 30)
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError("quantity must be a whole number")
        if isinstance(days, bool) or not isinstance(days, int):
            raise ValueError("days must be a whole number")
        hours = float(u["hours_per_day"])
        kwh = appliance_kwh(appliance, hours, quantity, days)
        total += kwh
        breakdown.append(
            {
                "key": key,
                "name": appliance.name,
                "quantity": quantity,
                "hours_per_day": hours,
                "days": days,
                "kwh": round(kwh, 2),
                "watts": appliance.watts,
                "watts_is_custom": watts_override is not None,
            }
        )

    breakdown.sort(key=lambda b: b["kwh"], reverse=True)
    for b in breakdown:
        b["share_pct"] = round(100.0 * b["kwh"] / total, 1) if total > 0 else 0.0

    return {"total_kwh": round(total, 2), "breakdown": breakdown}
