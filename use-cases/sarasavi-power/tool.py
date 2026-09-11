"""Agent Kernel tool wrappers for Sarasavi Power.

These are THIN adapters: they parse intent, read/write state via ``state.py``, call
the deterministic ``engine`` for every number, and return ``json.dumps(...)`` strings
(the Agent Kernel tool convention). They never re-implement engine math.

Tools are plain typed functions with docstrings — the docstring + type hints become
the tool schema the model sees (via ``GoogleADKToolBuilder.bind`` in ``agent.py``).
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import state
from engine import (
    boundary_opportunities,
    compute_bill,
    compute_tou_bill,
    estimate_total,
    load_appliances,
    simulate_reduction,
    units_for_bill,
)
from localization import (
    APPLIANCE_ALIASES,
    appliance_key_from_name,
    appliance_name,
    localize_breakdown,
    matching_tips,
    normalize_language,
    tips_for,
)


def _billing_days(profile: dict) -> int:
    return int(profile.get("billing_days") or 30)


def _language(profile: dict) -> str:
    return normalize_language(profile.get("language"))


def _period_usages(profile: dict) -> list[dict]:
    """Apply the profile's meter-reading period to every appliance line."""
    days = _billing_days(profile)
    return [{**usage, "days": days} for usage in profile.get("appliances", [])]


def _resolve_units(profile: dict) -> tuple[float, str]:
    """Return (units, source): a real metered reading if present, else an estimate."""
    metered = profile.get("metered_units")
    if metered is not None:
        return float(metered), "metered"
    est = estimate_total(_period_usages(profile))
    return est["total_kwh"], "estimated"


# --- Intake tools -----------------------------------------------------------------


def set_storage_consent(consent: bool) -> str:
    """Grant or revoke consent to store the household profile in Agent Kernel
    session memory. Revoking consent immediately erases all stored profile data."""
    profile = state.set_consent(consent)
    return json.dumps({"ok": True, "consent": profile["consent"], "data_erased": not consent})


def set_household(
    name: str = "",
    billing_cycle: str = "",
    language: str = "",
    billing_days: int = 0,
) -> str:
    """Create or update the household's basics: display name, billing cycle
    ('monthly' or 'bimonthly' for 60-day rural cycles), and preferred language
    ('en', 'si' for Sinhala, 'ta' for Tamil). Exact billing days may be supplied;
    use 0 when unknown so the selected cycle's 30/60-day default is used."""
    try:
        profile = state.set_household(
            name=name or None,
            billing_cycle=billing_cycle or None,
            language=language or None,
            billing_days=billing_days or None,
        )
    except (PermissionError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "profile": profile})


def _friendly_catalog(catalog: dict) -> list[str]:
    """Display names for an error reply, in the household's language.

    Never return raw catalog keys: the model quotes them verbatim, so the user
    ends up reading "'table_fan' is not in my list", which looks broken.
    """
    language = _language(state.load_profile())
    return [appliance_name(key, language, item.name) for key, item in sorted(catalog.items())]


def _resolve_appliance_key(appliance: str, catalog: dict) -> str | None:
    """Map whatever the user said to a catalog key.

    Tries, in order: the exact key, the shared alias table (English, romanized
    Sinhala and common brand/colloquial names), a localized display name, and
    finally a plural/singular retry. Users type "table fan" and "desktop pc", not
    "ceiling_fan" and "desktop_computer", so a miss here surfaces as the assistant
    telling them their appliance is unsupported.
    """
    raw = (appliance or "").strip()
    if not raw:
        return None
    key = raw.lower().replace(" ", "_").replace("-", "_")
    if key in catalog:
        return key
    if key in APPLIANCE_ALIASES:
        return APPLIANCE_ALIASES[key]

    resolved = appliance_key_from_name(raw)
    if resolved:
        return resolved

    # "fans" -> "fan", "led bulbs" -> "led bulb"
    if key.endswith("s"):
        singular = key[:-1]
        if singular in catalog:
            return singular
        if singular in APPLIANCE_ALIASES:
            return APPLIANCE_ALIASES[singular]
        resolved = appliance_key_from_name(raw[:-1])
        if resolved:
            return resolved
    return None


def add_appliance(appliance: str, hours_per_day: float, quantity: int = 1) -> str:
    """Record how much an appliance is used. 'appliance' must be a known key (call
    list_appliances to see them); 'hours_per_day' is average daily active hours."""
    catalog = load_appliances()
    resolved = _resolve_appliance_key(appliance, catalog)
    if resolved is None:
        return json.dumps(
            {"ok": False, "error": f"unknown appliance '{appliance}'", "known": _friendly_catalog(catalog)},
            ensure_ascii=False,
        )
    appliance = resolved
    if not math.isfinite(hours_per_day) or not 0 <= hours_per_day <= 24:
        return json.dumps({"ok": False, "error": "hours_per_day must be between 0 and 24"})
    try:
        profile = state.add_appliance(appliance, hours_per_day, quantity)
    except (PermissionError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "added": appliance, "appliances": profile["appliances"]})


def remove_appliance(appliance: str) -> str:
    """Remove a previously recorded appliance from the household profile."""
    catalog = load_appliances()
    resolved = _resolve_appliance_key(appliance, catalog)
    if resolved is None:
        return json.dumps(
            {"ok": False, "error": f"unknown appliance '{appliance}'", "known": _friendly_catalog(catalog)},
            ensure_ascii=False,
        )
    try:
        profile, removed = state.remove_appliance(resolved)
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps(
        {
            "ok": True,
            "removed": removed,
            "appliance": resolved,
            "appliances": profile["appliances"],
        }
    )


def list_appliances() -> str:
    """List the appliance keys and friendly names the assistant understands."""
    catalog = load_appliances()
    language = _language(state.load_profile())
    return json.dumps(
        {
            "language": language,
            "appliances": [
                {
                    "key": key,
                    "name": appliance_name(key, language, appliance.name),
                    "english_name": appliance.name,
                }
                for key, appliance in sorted(catalog.items())
            ],
        },
        ensure_ascii=False,
    )


def set_language(language: str) -> str:
    """Set the user's preferred language: 'en', 'si' (Sinhala) or 'ta' (Tamil)."""
    try:
        profile = state.set_language(language)
    except (PermissionError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "language": profile["language"]})


def record_bill_reading(units: float, billing_days: int = 0) -> str:
    """Record the exact units (kWh) from the user's paper bill or meter. This is the
    trusted anchor — once set, bills and boundary advice use it instead of estimates.
    Supply the exact number of billing days when printed on the bill; 0 keeps the
    household's current billing period."""
    if not math.isfinite(units) or units < 0:
        return json.dumps({"ok": False, "error": "units must be >= 0"})
    if isinstance(billing_days, bool) or not isinstance(billing_days, int):
        return json.dumps({"ok": False, "error": "billing_days must be a whole number"})
    if billing_days and not 1 <= billing_days <= 366:
        return json.dumps({"ok": False, "error": "billing_days must be between 1 and 366"})
    try:
        if billing_days:
            state.set_household(billing_days=billing_days)
        profile = state.set_metered_units(units)
    except (PermissionError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps(
        {
            "ok": True,
            "metered_units": float(units),
            "billing_days": profile["billing_days"],
        }
    )


def clear_bill_reading() -> str:
    """Forget the stored meter/bill reading and return to appliance estimates."""
    try:
        profile = state.set_metered_units(None)
    except (PermissionError, ValueError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "metered_units": profile["metered_units"]})


def get_household_profile() -> str:
    """Return everything currently known about the household (basics + appliances),
    including a summary of the most recent WhatsApp voice call if one happened."""
    return json.dumps({"profile": state.load_profile(), "last_voice_call": state.load_last_voice_call()})


def export_household_data() -> str:
    """Return all household data currently stored in this Agent Kernel session."""
    return json.dumps({"ok": True, "profile": state.load_profile()})


def delete_household_data() -> str:
    """Permanently delete the household profile stored in this session."""
    deleted = state.delete_profile()
    return json.dumps({"ok": True, "deleted": deleted})


# --- Analysis tools ---------------------------------------------------------------


def estimate_consumption() -> str:
    """Estimate the household's monthly kWh from its recorded appliances, with a
    per-appliance breakdown sorted by impact (the biggest consumers first)."""
    profile = state.load_profile()
    if not profile.get("appliances"):
        return json.dumps({"ok": False, "error": "no appliances recorded yet"})
    result = localize_breakdown(estimate_total(_period_usages(profile)), _language(profile))
    return json.dumps({"ok": True, "billing_days": _billing_days(profile), **result}, ensure_ascii=False)


def compute_current_bill() -> str:
    """Compute the current estimated bill (LKR) using the CEB/LECO domestic tariff.
    Uses the metered reading if one was recorded, otherwise the appliance estimate."""
    profile = state.load_profile()
    units, source = _resolve_units(profile)
    if source == "estimated" and units == 0:
        return json.dumps({"ok": False, "error": "no appliances or meter reading yet"})
    bill = compute_bill(units, billing_days=_billing_days(profile))
    return json.dumps({"ok": True, "units_source": source, **bill})


def compute_time_of_use_bill(off_peak_units: float, day_units: float, peak_units: float, billing_days: int = 0) -> str:
    """Compute a Domestic Time-of-Use (TOU) bill from the three metered readings.
    A Sri Lankan TOU bill prints consumption as three figures marked (O) off-peak,
    (D) day and (P) peak. Use THIS instead of compute_current_bill whenever the
    user's bill shows those three periods. Supply exact billing days when printed,
    otherwise 0. Returns the charge, the 2.5% SSC levy, the payable total, and
    which period costs the most."""
    try:
        result = compute_tou_bill(off_peak_units, day_units, peak_units, billing_days=billing_days or None)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, **result}, ensure_ascii=False)


def estimate_bill_for_units(units: float, billing_days: int = 0) -> str:
    """Compute the bill for ANY number of units, without needing a stored profile.

    Use this the moment someone asks a direct question such as "how much is 27
    units?", "what would 150 units cost?" or "what if I used 200 units?". It stores
    nothing, needs no consent, and works for a first-time user. Supply exact billing
    days when known, otherwise 0 for a standard 30-day month. Also reports the next
    block boundary, because crossing one re-prices the whole period."""
    if not math.isfinite(units) or units < 0:
        return json.dumps({"ok": False, "error": "units must be a number >= 0"})
    if isinstance(billing_days, bool) or not isinstance(billing_days, int):
        return json.dumps({"ok": False, "error": "billing_days must be a whole number"})
    if billing_days and not 1 <= billing_days <= 366:
        return json.dumps({"ok": False, "error": "billing_days must be between 1 and 366"})

    days = billing_days or 30
    bill = compute_bill(units, billing_days=days)
    # The retroactive block structure is the whole point of this tariff, so a bare
    # total without the nearby boundary is only half an answer.
    opportunities = boundary_opportunities(units, billing_days=days)
    return json.dumps(
        {
            "ok": True,
            "asked_units": round(float(units), 3),
            **bill,
            "nearest_boundary": opportunities[0] if opportunities else None,
        }
    )


def estimate_units_for_bill(bill_amount: float, billing_days: int = 0) -> str:
    """Work backwards: roughly how many units produce a bill of this LKR amount.

    Use this when someone asks the reverse question, e.g. "a Rs 3,400 bill is how
    many units?" or "how many units do I get for 5000 rupees?". Needs no stored
    profile. Because the tariff steps at each block, an exact amount is not always
    achievable; 'bill_at_those_units' and 'difference' report the closest real
    bill, so quote those rather than implying the amount lands exactly."""
    if not math.isfinite(bill_amount) or bill_amount < 0:
        return json.dumps({"ok": False, "error": "bill_amount must be a number >= 0"})
    if isinstance(billing_days, bool) or not isinstance(billing_days, int):
        return json.dumps({"ok": False, "error": "billing_days must be a whole number"})
    if billing_days and not 1 <= billing_days <= 366:
        return json.dumps({"ok": False, "error": "billing_days must be between 1 and 366"})
    return json.dumps({"ok": True, **units_for_bill(bill_amount, billing_days=billing_days or None)})


# --- Recommendation tools ---------------------------------------------------------


def find_savings() -> str:
    """Find the highest-value ways to cut the bill: retroactive slab-boundary
    opportunities (the big lever), the top energy-consuming appliances, and tips.
    Flags lower confidence when working from an estimate rather than a meter reading."""
    profile = state.load_profile()
    units, source = _resolve_units(profile)
    if units == 0:
        return json.dumps({"ok": False, "error": "no appliances or meter reading yet"})
    days = _billing_days(profile)

    current_bill = compute_bill(units, billing_days=days)
    opps = boundary_opportunities(units, billing_days=days)
    usage_result: dict[str, Any] = (
        localize_breakdown(estimate_total(_period_usages(profile)), _language(profile))
        if profile.get("appliances")
        else {"total_kwh": 0.0, "breakdown": []}
    )
    breakdown: list[dict[str, Any]] = usage_result["breakdown"]
    top_keys = [b["key"] for b in breakdown[:2]] or ["general"]
    tips: list[str] = []
    for k in top_keys:
        tips.extend(tips_for(k, _language(profile)))
    tips.extend(tips_for("general", _language(profile))[:1])

    confidence = (
        "high (based on your actual meter reading)"
        if source == "metered"
        else "approximate (based on appliance estimates — type the units from a bill or meter "
        "reading for exact boundary advice)"
    )
    # Only promise the disproportionate boundary win outright when metered.
    for o in opps:
        o["reliable"] = source == "metered"

    return json.dumps(
        {
            "ok": True,
            "units": units,
            "units_source": source,
            "billing_days": days,
            "language": _language(profile),
            "current_bill": current_bill,
            "confidence": confidence,
            "top_boundary_opportunity": opps[0] if opps else None,
            "all_boundary_opportunities": opps,
            "high_impact_appliances": breakdown[:3],
            "tips": tips,
        },
        ensure_ascii=False,
    )


def simulate_change(appliance: str, new_hours_per_day: float) -> str:
    """Show the bill impact of changing one appliance's daily usage to
    'new_hours_per_day' (e.g. running the AC 3h instead of 6h)."""
    profile = state.load_profile()
    appliances = profile.get("appliances", [])
    if not any(a["key"] == appliance for a in appliances):
        return json.dumps({"ok": False, "error": f"'{appliance}' is not in the household's list"})
    if not math.isfinite(new_hours_per_day) or not 0 <= new_hours_per_day <= 24:
        return json.dumps({"ok": False, "error": "new_hours_per_day must be between 0 and 24"})

    days = _billing_days(profile)
    current_estimate = estimate_total(_period_usages(profile))["total_kwh"]
    modified_profile = copy.deepcopy(profile)
    modified = modified_profile["appliances"]
    for a in modified:
        if a["key"] == appliance:
            a["hours_per_day"] = float(new_hours_per_day)
    new_estimate = estimate_total(_period_usages(modified_profile))["total_kwh"]
    baseline_units, source = _resolve_units(profile)
    estimated_kwh_change = round(current_estimate - new_estimate, 3)
    sim = simulate_reduction(
        baseline_units,
        estimated_kwh_change,
        billing_days=days,
    )
    return json.dumps(
        {
            "ok": True,
            "appliance": appliance,
            "new_hours_per_day": new_hours_per_day,
            "baseline_source": source,
            "estimated_before_kwh": current_estimate,
            "estimated_after_kwh": new_estimate,
            **sim,
        }
    )


def match_saving_tips(query: str = "") -> str:
    """Return relevant energy-saving tips. 'query' can name an appliance or topic;
    empty returns general tips. Backed by a curated, deterministic tip list."""
    language = _language(state.load_profile())
    return json.dumps(
        {"query": query, "language": language, "tips": matching_tips(query or "", language)},
        ensure_ascii=False,
    )
