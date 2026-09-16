"""
Tools for the Disaster Response & Resource Coordination Agent.

Everything in this file that looks like a "database" (VOLUNTEER_DIRECTORY, the in-memory
_STATE store, etc.) is DUMMY DATA meant to be swapped out for real integrations later:
  - _STATE               -> Redis / DynamoDB / Cosmos DB (see agent-kernel/examples/memory)
  - VOLUNTEER_DIRECTORY  -> a real donor/volunteer CRM or spreadsheet
  - dispatch_notification-> the WhatsApp Business API (agent-kernel has a whatsapp channel,
                             see agent-kernel/examples/api/whatsapp)

The module-level _STATE dict is intentionally process-global (not per-session). A disaster
response spans many users/sessions over days, so "memory" here is scoped by region, not by
chat session, and is shared by every agent and every request that hits this running process.
This satisfies local testing needs; for real deployments point it at a persistent store.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

# --------------------------------------------------------------------------------------
# WhatsApp Cloud API config (real integration for dispatch_notification).
#
# By default this stays in DUMMY mode (no real messages sent) unless WHATSAPP_ENABLED=true
# and the required Meta credentials are set. Uses the same env var names as Agent Kernel's
# built-in WhatsApp integration (ak-py/src/agentkernel/integration/whatsapp) for consistency:
#
#     $env:WHATSAPP_ENABLED = "true"
#     $env:AK_WHATSAPP__ACCESS_TOKEN = "your_permanent_access_token"
#     $env:AK_WHATSAPP__PHONE_NUMBER_ID = "123456789012345"
#     $env:AK_WHATSAPP__API_VERSION = "v21.0"        # optional
#
# NOTE: Meta's Cloud API only allows free-form text to a number that has messaged your
# business within the last 24h, or to numbers added as verified test recipients in the Meta
# Developer sandbox. Cold outbound to real volunteers/donors requires a pre-approved message
# template instead of plain text - see README.md for details.
# --------------------------------------------------------------------------------------
WHATSAPP_ENABLED = os.environ.get("WHATSAPP_ENABLED", "false").strip().lower() in ("1", "true", "yes")
WHATSAPP_ACCESS_TOKEN = os.environ.get("AK_WHATSAPP__ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("AK_WHATSAPP__PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.environ.get("AK_WHATSAPP__API_VERSION", "v21.0")


def _send_whatsapp_message(to_number: str, text: str) -> dict[str, Any]:
    """Send a real WhatsApp text message via Meta's Cloud API, or report why it was skipped.

    :param to_number: Recipient phone number (with or without a leading '+').
    :param text: Message body.
    :return: Dict with sent: bool, and either provider_message_id or reason.
    """
    if not WHATSAPP_ENABLED:
        return {"sent": False, "reason": "dummy mode (WHATSAPP_ENABLED not set) - message simulated only"}
    if not (WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID):
        return {"sent": False, "reason": "WHATSAPP_ENABLED=true but AK_WHATSAPP__ACCESS_TOKEN / "
                                          "AK_WHATSAPP__PHONE_NUMBER_ID are not set"}
    if not to_number:
        return {"sent": False, "reason": "No phone number on file for the recipient"}

    clean_number = re.sub(r"[^\d]", "", to_number)
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_number,
        "type": "text",
        "text": {"body": text},
    }
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        message_id = (data.get("messages") or [{}])[0].get("id")
        return {"sent": True, "provider_message_id": message_id}
    except httpx.HTTPStatusError as e:
        return {"sent": False, "reason": f"WhatsApp API error {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:  # noqa: BLE001 - surface any transport error back through the tool result
        return {"sent": False, "reason": f"Error sending WhatsApp message: {e}"}

# --------------------------------------------------------------------------------------
# Dummy "database" of volunteers / donors who can be dispatched to fulfil a need.
# In production this would come from a CRM, spreadsheet, or registration system.
#
# All phone numbers below (and on the seeded offers further down) are set to the SAME real,
# WhatsApp-Cloud-API-verified test number so that any match - same-region or cross-region -
# actually dispatches successfully while WHATSAPP_ENABLED=true. Meta's test sandbox only
# allows sending to numbers explicitly added as verified test recipients; distinct fake
# numbers per donor look nicer but will silently fail to send. Swap these for real donor/
# volunteer numbers (added as additional verified test recipients, or in production once
# past sandbox mode) as you onboard them.
# --------------------------------------------------------------------------------------
VOLUNTEER_DIRECTORY: list[dict[str, Any]] = [
    {
        "id": "vol-001",
        "name": "Nimal Perera",
        "phone": "+94760048658",
        "region": "galle",
        "resource_types": ["drinking water", "water", "food packs", "food"],
    },
    {
        "id": "vol-002",
        "name": "Kamala Silva",
        "phone": "+94760048658",
        "region": "galle",
        "resource_types": ["medicine", "medical supplies", "first aid"],
    },
    {
        "id": "vol-003",
        "name": "Ruwan Fernando",
        "phone": "+94760048658",
        "region": "colombo",
        "resource_types": ["drinking water", "water", "blankets", "clothing"],
    },
    {
        "id": "vol-004",
        "name": "Dilani Jayasuriya",
        "phone": "+94760048658",
        "region": "matara",
        "resource_types": ["food packs", "food", "shelter", "tents"],
    },
    {
        "id": "vol-005",
        "name": "Sunil Rathnayake",
        "phone": "+94760048658",
        "region": "ratnapura",
        "resource_types": ["boats", "rescue", "medicine", "medical supplies"],
    },
    {
        "id": "vol-006",
        "name": "Anusha Wickramasinghe",
        "phone": "+94760048658",
        "region": "kalutara",
        "resource_types": ["drinking water", "water", "food packs", "food"],
    },
]

# Resources considered life-critical get a higher base urgency weight (0-5 scale).
# Canonical resource categories: each maps a canonical name (what gets stored on every
# request/offer, and what match_resources compares) to its criticality (0-5, used by
# score_urgency) and every synonym/phrasing that should resolve to it. This exists because
# match_resources requires an exact resource_type match between a need and an offer, and
# real messages are inconsistent - "food" vs "food packs" vs "meals" are all the same thing
# to a human but were previously treated as unrelated resource types, silently preventing
# otherwise-good matches. submit_intake runs every resource_type through _canonical_resource_type
# so "food" and "food packs" both become "food packs" before anything else sees them.
RESOURCE_CATEGORIES: dict[str, dict[str, Any]] = {
    "drinking water": {
        "criticality": 5,
        "synonyms": {"drinking water", "water", "clean water", "potable water", "bottled water"},
    },
    "food packs": {
        "criticality": 4,
        "synonyms": {"food packs", "food pack", "food", "meals", "dry rations", "ration packs", "rations"},
    },
    "medicine": {
        "criticality": 5,
        "synonyms": {"medicine", "medicines", "medical supplies", "medication", "meds",
                     "first aid", "first aid kit", "first aid kits"},
    },
    "shelter": {
        "criticality": 4,
        "synonyms": {"shelter", "tents", "tent", "temporary shelter"},
    },
    "boats": {
        "criticality": 4,
        "synonyms": {"boats", "boat"},
    },
    "rescue": {
        "criticality": 5,
        "synonyms": {"rescue", "evacuation", "rescue boat"},
    },
    "blankets": {
        "criticality": 3,
        "synonyms": {"blankets", "blanket"},
    },
    "clothing": {
        "criticality": 2,
        "synonyms": {"clothing", "clothes"},
    },
    "hygiene kits": {
        "criticality": 3,
        "synonyms": {"hygiene kits", "hygiene kit", "sanitation kits", "sanitary kits"},
    },
}

# Derived flat lookup kept for score_urgency's simple dict.get(record["resource_type"], ...).
RESOURCE_CRITICALITY: dict[str, int] = {
    name: info["criticality"] for name, info in RESOURCE_CATEGORIES.items()
}
DEFAULT_CRITICALITY = 3

# Synonym -> canonical name, sorted longest-phrase-first so a more specific synonym (e.g.
# "first aid kit") is checked before a shorter one that might otherwise substring-match
# something unintended.
_SYNONYM_TO_CANONICAL: list[tuple[str, str]] = sorted(
    (
        (synonym, canonical)
        for canonical, info in RESOURCE_CATEGORIES.items()
        for synonym in info["synonyms"]
    ),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def _canonical_resource_type(raw: str) -> str:
    """Map a free-form resource type to its canonical category, so "food" and "food packs"
    (or "water" and "drinking water") are treated as the same thing for matching/scoring.

    Tries an exact synonym match first, then falls back to substring containment (e.g. "food
    supplies for the family" contains "food"). If nothing matches, returns the normalized raw
    string unchanged - it just won't benefit from synonym-aware matching, and will only match
    another intake with the exact same unrecognized phrasing.
    """
    text = _normalize(raw)
    if not text:
        return "unspecified"
    for synonym, canonical in _SYNONYM_TO_CANONICAL:
        if text == synonym:
            return canonical
    for synonym, canonical in _SYNONYM_TO_CANONICAL:
        if synonym in text or text in synonym:
            return canonical
    return text

# Keyword bank used to detect vulnerable-group indicators in free-form text.
VULNERABLE_KEYWORDS: dict[str, list[str]] = {
    "children": ["child", "children", "kids", "infant", "infants", "baby", "babies", "newborn"],
    "elderly": ["elderly", "elder", "senior", "old age", "grandparent", "grandmother", "grandfather"],
    "pregnant": ["pregnant", "expecting", "maternity"],
    "disabled": ["disab", "wheelchair", "blind", "deaf", "special needs"],
    "medical": ["sick", "ill", "patient", "injured", "wound", "diabetic", "insulin", "asthma", "medication"],
}

# Keyword bank used to detect logistics/transport signals in free-form text. Used by both
# "need" messages (does the requester have a way to receive/collect the resource?) and "offer"
# messages (can the donor deliver it themselves?).
TRANSPORT_KEYWORDS: dict[str, list[str]] = {
    "no_transport": [
        "no transport", "no vehicle", "cannot travel", "can't travel", "stranded",
        "no way to get", "unable to travel", "roads blocked", "road is blocked",
        "cut off", "no way to reach",
    ],
    "can_deliver": [
        "can deliver", "will deliver", "have a vehicle", "have transport", "will transport",
        "can transport", "have a truck", "have a van", "can drop off", "able to deliver",
    ],
}

# Approximate road distances (km) between the regions used in this demo's seed/volunteer data.
# For a real deployment, replace this with a geocoding + routing API call (e.g. Google Maps
# Distance Matrix) - these are illustrative, hand-entered values, not live routing data.
REGION_DISTANCE_KM: dict[frozenset[str], int] = {
    frozenset({"colombo", "galle"}): 116,
    frozenset({"colombo", "matara"}): 160,
    frozenset({"colombo", "kalutara"}): 43,
    frozenset({"colombo", "ratnapura"}): 101,
    frozenset({"galle", "matara"}): 45,
    frozenset({"galle", "kalutara"}): 73,
    frozenset({"galle", "ratnapura"}): 109,
    frozenset({"matara", "ratnapura"}): 138,
    frozenset({"matara", "kalutara"}): 116,
    frozenset({"kalutara", "ratnapura"}): 62,
}
# Distance assumed for any region pair not in the table above (e.g. an unrecognized town) -
# treated as "far enough that proximity scoring should heavily discount it".
DEFAULT_DISTANCE_KM = 250


def _distance_km(region_a: str, region_b: str) -> int:
    """Approximate road distance between two regions, 0 if they're the same region."""
    a, b = _normalize(region_a), _normalize(region_b)
    if a == b:
        return 0
    return REGION_DISTANCE_KM.get(frozenset({a, b}), DEFAULT_DISTANCE_KM)


def _detect_transport_flag(raw_message: str, message_type: str) -> bool | None:
    """Detect a transport/logistics signal in free-form text.

    For a "need": True means the requester explicitly has no transport (delivery required),
    False means unspecified/has their own way to collect it.
    For an "offer": True means the donor explicitly can deliver, False means unspecified/pickup
    likely required.
    Returns None only if the message_type itself is unrecognized.
    """
    if message_type not in ("need", "offer"):
        return None
    text = _normalize(raw_message)
    if message_type == "need":
        return any(kw in text for kw in TRANSPORT_KEYWORDS["no_transport"])
    return any(kw in text for kw in TRANSPORT_KEYWORDS["can_deliver"])

# --------------------------------------------------------------------------------------
# In-memory, process-global "live" state. Structure:
# _STATE[region] = {
#   "requests": {request_id: {...}},   # open "needs"
#   "offers":   {offer_id: {...}},     # open "offers"
# }
# _INTAKE_BUFFER[intake_id] = {...}    # scratch space between intake -> priority -> dispatch
# --------------------------------------------------------------------------------------
_STATE: dict[str, dict[str, dict[str, Any]]] = {}
_INTAKE_BUFFER: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _region_store(region: str) -> dict[str, dict[str, Any]]:
    key = _normalize(region) or "unspecified"
    return _STATE.setdefault(key, {"requests": {}, "offers": {}})


def _find_record_by_id(record_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Find a request/offer record by id across ALL regions, returning (record, region_key).

    Needed because match_resources can now surface cross-region matches - a record's own
    region can no longer be assumed from the caller's region argument.
    """
    for region_key, region_store in _STATE.items():
        for pool in ("requests", "offers"):
            record = region_store[pool].get(record_id)
            if record is not None:
                return record, region_key
    return None, None


def _seed_demo_data() -> None:
    """Seed a couple of standing offers so the very first matching demo has something to match against."""
    if _STATE:
        return
    galle = _region_store("galle")
    offer_id = f"offer-{uuid.uuid4().hex[:8]}"
    galle["offers"][offer_id] = {
        "id": offer_id,
        "region": "galle",
        "resource_type": "drinking water",
        "quantity": 200,
        "unit": "liters",
        "donor_name": "Galle Community Trust",
        "donor_phone": "+94760048658",
        "status": "open",
        "created_at": _now(),
        "transport_flag": None,
        "history": ["seeded demo offer"],
    }
    colombo = _region_store("colombo")
    offer_id2 = f"offer-{uuid.uuid4().hex[:8]}"
    colombo["offers"][offer_id2] = {
        "id": offer_id2,
        "region": "colombo",
        "resource_type": "food packs",
        "quantity": 50,
        "unit": "packs",
        "donor_name": "Colombo Rotary Club",
        "donor_phone": "+94760048658",
        "status": "open",
        "created_at": _now(),
        "transport_flag": None,
        "history": ["seeded demo offer"],
    }
    # A donor who explicitly CAN deliver - lets the transport-matching demo scenario ("Elderly
    # couple needs medicine urgently in Matara, no transport") show a real cross-region match
    # out of the box, without needing to seed extra data by hand.
    ratnapura = _region_store("ratnapura")
    offer_id3 = f"offer-{uuid.uuid4().hex[:8]}"
    ratnapura["offers"][offer_id3] = {
        "id": offer_id3,
        "region": "ratnapura",
        "resource_type": "medicine",
        "quantity": 30,
        "unit": "kits",
        "donor_name": "Ratnapura Medical Volunteers",
        "donor_phone": "+94760048658",
        "status": "open",
        "created_at": _now(),
        "transport_flag": True,  # explicitly able to deliver
        "history": ["seeded demo offer - donor can deliver"],
    }


_seed_demo_data()


# ========================================================================================
# INTAKE AGENT TOOLS
# ========================================================================================
def submit_intake(
    message_type: str,
    resource_type: str,
    quantity: int,
    unit: str,
    location: str,
    raw_message: str,
    contact_name: str = "",
    contact_phone: str = "",
) -> str:
    """Record a structured intake extracted from a free-form disaster-relief message.

    :param message_type: Either "need" (a request for resources) or "offer" (resources available).
    :param resource_type: The kind of resource, e.g. "drinking water", "food packs", "medicine", "shelter".
    :param quantity: The numeric quantity mentioned, or 1 if unspecified.
    :param unit: Unit for the quantity, e.g. "liters", "packs", "people", "boxes", "units".
    :param location: The region/town affected, e.g. "Galle", "Colombo".
    :param raw_message: The original free-form message, verbatim.
    :param contact_name: Name of the requester/donor if mentioned, else empty string.
    :param contact_phone: Phone number of the requester/donor if mentioned, else empty string.
    :return: JSON string with the generated intake_id and the stored record.
    """
    message_type = _normalize(message_type)
    if message_type not in ("need", "offer"):
        message_type = "need"

    intake_id = f"intake-{uuid.uuid4().hex[:8]}"
    record = {
        "intake_id": intake_id,
        "message_type": message_type,
        "resource_type": _canonical_resource_type(resource_type),
        "quantity": max(int(quantity or 1), 1),
        "unit": unit or "units",
        "region": _normalize(location) or "unspecified",
        "location_display": location or "Unspecified",
        "raw_message": raw_message,
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "created_at": _now(),
        "urgency_score": None,
        "vulnerable_groups": [],
        "transport_flag": _detect_transport_flag(raw_message, message_type),
        "matches": [],
    }
    _INTAKE_BUFFER[intake_id] = record
    return json.dumps({"intake_id": intake_id, "record": record}, indent=2)


def get_region_status(region: str) -> str:
    """Return all currently open requests (needs) and offers for a region, for live tracking.

    :param region: The region/town to look up, e.g. "Galle".
    :return: JSON string with open requests and offers for that region.
    """
    store = _region_store(region)
    return json.dumps(
        {
            "region": _normalize(region),
            "open_requests": [r for r in store["requests"].values() if r["status"] != "fulfilled"],
            "open_offers": [o for o in store["offers"].values() if o["status"] != "fulfilled"],
        },
        indent=2,
    )


# ========================================================================================
# PRIORITY & MATCHING AGENT TOOLS
# ========================================================================================
def score_urgency(intake_id: str, vulnerable_groups: str = "") -> str:
    """Score the urgency of a "need" intake using a deterministic tool (not model judgement).

    Combines resource criticality, quantity, and vulnerable-group indicators found in the
    message or supplied explicitly, into a 0-100 urgency score.

    :param intake_id: The intake_id returned by submit_intake.
    :param vulnerable_groups: Comma-separated vulnerable groups the caller has identified
        (any of: children, elderly, pregnant, disabled, medical), or empty string.
    :return: JSON string with urgency_score (0-100), band (low/medium/high/critical), and rationale.
    """
    record = _INTAKE_BUFFER.get(intake_id)
    if record is None:
        return json.dumps({"error": f"No intake found for intake_id={intake_id}"})

    text = _normalize(record["raw_message"])
    detected: set[str] = set()
    for group, keywords in VULNERABLE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            detected.add(group)
    for group in (g.strip().lower() for g in vulnerable_groups.split(",") if g.strip()):
        if group in VULNERABLE_KEYWORDS:
            detected.add(group)

    criticality = RESOURCE_CRITICALITY.get(record["resource_type"], DEFAULT_CRITICALITY)  # 0-5
    quantity_factor = min(record["quantity"] / 20.0, 1.0)  # larger asks -> slightly more urgent, capped

    base = criticality * 12  # 0-60
    vulnerability_bonus = min(len(detected) * 12, 36)  # up to +36
    quantity_bonus = quantity_factor * 4  # up to +4

    score = round(min(base + vulnerability_bonus + quantity_bonus, 100))

    if score >= 80:
        band = "critical"
    elif score >= 60:
        band = "high"
    elif score >= 35:
        band = "medium"
    else:
        band = "low"

    record["urgency_score"] = score
    record["urgency_band"] = band
    record["vulnerable_groups"] = sorted(detected)

    return json.dumps(
        {
            "intake_id": intake_id,
            "urgency_score": score,
            "urgency_band": band,
            "vulnerable_groups": sorted(detected),
            "rationale": (
                f"resource criticality={criticality}/5, vulnerable_groups={sorted(detected) or 'none'}, "
                f"quantity={record['quantity']} {record['unit']}"
            ),
        },
        indent=2,
    )


def match_resources(intake_id: str) -> str:
    """Match an intake against the opposite pool across ALL regions using a scoring tool.

    A "need" is matched against open offers of the same resource_type; an "offer" is matched
    against open needs of the same resource_type. Candidates are no longer limited to the same
    region - a same-region match still wins on proximity, but a distant match is surfaced (and
    ranked lower) rather than hidden, since real disaster response often has to move resources
    between nearby regions when the local area has nothing to offer.

    The match score (0-100) combines:
      - quantity coverage (up to 45 pts): how much of the requested/offered quantity this
        candidate can cover.
      - proximity (up to 30 pts): 30 for the same region, decaying with approximate road
        distance for cross-region candidates (see REGION_DISTANCE_KM).
      - status (up to 10 pts): candidate is still fully open (not partially matched already).
      - transport compatibility (up to 15 pts): rewards pairing a requester who has no transport
        with a donor who can deliver, especially important for cross-region matches.

    :param intake_id: The intake_id returned by submit_intake.
    :return: JSON string with a ranked list of candidate matches, each including distance_km
        and a short transport_note explaining the transport-compatibility contribution.
    """
    record = _INTAKE_BUFFER.get(intake_id)
    if record is None:
        return json.dumps({"error": f"No intake found for intake_id={intake_id}"})

    pool_key = "offers" if record["message_type"] == "need" else "requests"
    candidates = [
        c
        for region_store in _STATE.values()
        for c in region_store[pool_key].values()
        if c["resource_type"] == record["resource_type"] and c["status"] != "fulfilled"
    ]

    requester_transport_flag = record.get("transport_flag")  # True = need has NO transport

    scored = []
    for c in candidates:
        coverage = min(c["quantity"] / max(record["quantity"], 1), 1.0)
        coverage_pts = coverage * 45

        distance_km = _distance_km(record["region"], c["region"])
        same_region = distance_km == 0
        proximity_pts = 30 if same_region else max(0, round(30 - distance_km / 7))

        status_pts = 10 if c["status"] == "open" else 0

        # Transport compatibility: matters most when the requester has no transport of their
        # own, especially once the match crosses regions. If the counterpart (offer) is flagged
        # as able to deliver, that fully bridges the gap; otherwise a same-region match still
        # gets partial credit since delivery distance is short regardless.
        candidate_transport_flag = c.get("transport_flag")
        if requester_transport_flag is True and candidate_transport_flag is True:
            transport_pts = 15
            transport_note = "requester has no transport; matched donor can deliver - good fit"
        elif requester_transport_flag is True and same_region:
            transport_pts = 8
            transport_note = "requester has no transport; same-region match keeps delivery short"
        elif requester_transport_flag is True:
            transport_pts = 0
            transport_note = "requester has no transport and this match is in another region - " \
                              "confirm delivery capability before dispatching"
        else:
            transport_pts = 10
            transport_note = "no transport constraint detected"

        match_score = round(coverage_pts + proximity_pts + status_pts + transport_pts)
        scored.append({
            **c,
            "match_score": match_score,
            "distance_km": distance_km,
            "transport_note": transport_note,
        })

    scored.sort(key=lambda c: c["match_score"], reverse=True)
    record["matches"] = scored

    return json.dumps(
        {
            "intake_id": intake_id,
            "message_type": record["message_type"],
            "resource_type": record["resource_type"],
            "region": record["region"],
            "candidate_count": len(scored),
            "matches": scored[:5],
        },
        indent=2,
    )


# ========================================================================================
# DEDUP & DISPATCH AGENT TOOLS
# ========================================================================================
def check_pending_duplicates(intake_id: str) -> str:
    """Check memory for an existing open request/offer in the same region before creating a new one.

    :param intake_id: The intake_id returned by submit_intake.
    :return: JSON string listing any existing open record(s) that look like duplicates.
    """
    record = _INTAKE_BUFFER.get(intake_id)
    if record is None:
        return json.dumps({"error": f"No intake found for intake_id={intake_id}"})

    store = _region_store(record["region"])
    pool_key = "requests" if record["message_type"] == "need" else "offers"
    duplicates = [
        r
        for r in store[pool_key].values()
        if r["resource_type"] == record["resource_type"] and r["status"] != "fulfilled"
    ]

    return json.dumps(
        {
            "intake_id": intake_id,
            "region": record["region"],
            "resource_type": record["resource_type"],
            "duplicate_count": len(duplicates),
            "duplicates": duplicates,
        },
        indent=2,
    )


def finalize_record(intake_id: str, duplicate_id: str = "") -> str:
    """Create a new pending record for an intake, or merge it into an existing duplicate.

    If duplicate_id is provided (from check_pending_duplicates), the intake's quantity is
    merged into that existing open record instead of creating a new one, preventing duplicate
    entries for the same ongoing need/offer in a region.

    :param intake_id: The intake_id returned by submit_intake.
    :param duplicate_id: The id of an existing open request/offer to merge into, or empty string
        to create a brand new record.
    :return: JSON string with the final stored record and whether it was merged or newly created.
    """
    record = _INTAKE_BUFFER.get(intake_id)
    if record is None:
        return json.dumps({"error": f"No intake found for intake_id={intake_id}"})

    store = _region_store(record["region"])
    pool_key = "requests" if record["message_type"] == "need" else "offers"

    if duplicate_id and duplicate_id in store[pool_key]:
        existing = store[pool_key][duplicate_id]
        existing["quantity"] += record["quantity"]
        existing["history"].append(
            f"{_now()}: merged additional {record['quantity']} {record['unit']} "
            f"from message: '{record['raw_message']}'"
        )
        if record["message_type"] == "need":
            existing["urgency_score"] = max(existing.get("urgency_score") or 0, record["urgency_score"] or 0)
            existing["vulnerable_groups"] = sorted(
                set(existing.get("vulnerable_groups", [])) | set(record["vulnerable_groups"])
            )
        if existing.get("transport_flag") is not True and record.get("transport_flag") is True:
            existing["transport_flag"] = True
        final_record = existing
        merged = True
    else:
        new_id = f"{'req' if record['message_type'] == 'need' else 'off'}-{uuid.uuid4().hex[:8]}"
        final_record = {
            "id": new_id,
            "region": record["region"],
            "location_display": record["location_display"],
            "resource_type": record["resource_type"],
            "quantity": record["quantity"],
            "unit": record["unit"],
            "message_type": record["message_type"],
            "contact_name": record["contact_name"],
            "contact_phone": record["contact_phone"],
            "urgency_score": record["urgency_score"],
            "urgency_band": record.get("urgency_band"),
            "vulnerable_groups": record["vulnerable_groups"],
            "transport_flag": record.get("transport_flag"),
            "status": "open",
            "created_at": _now(),
            "history": [f"{_now()}: created from message: '{record['raw_message']}'"],
        }
        store[pool_key][new_id] = final_record
        merged = False

    return json.dumps(
        {
            "intake_id": intake_id,
            "merged": merged,
            "record": final_record,
            "matches_found_earlier": record.get("matches", []),
        },
        indent=2,
    )


def dispatch_notification(record_id: str, matched_id: str, region: str = "") -> str:
    """Simulate notifying the matched volunteer/donor via WhatsApp and update both records' status.

    This is a DUMMY dispatch: it looks up a phone number from the offer/request itself (or the
    volunteer directory as a fallback) and returns a fake WhatsApp message id. Swap this for a
    real WhatsApp Business API call later (see agent-kernel/examples/api/whatsapp).

    :param record_id: The id of the just-created/updated request or offer (from finalize_record).
    :param matched_id: The id of the matched counterpart record to notify (from match_resources).
    :param region: Unused - kept only for backward compatibility with older callers. Both
        records are now looked up by id across all regions, since matches can be cross-region.
    :return: JSON string confirming the (simulated) dispatch, including who was notified.
    """
    source, source_region = _find_record_by_id(record_id)
    target, target_region = _find_record_by_id(matched_id)

    if source is None or target is None:
        return json.dumps(
            {
                "error": "Could not find one or both records to dispatch between.",
                "record_id_found": source is not None,
                "matched_id_found": target is not None,
            }
        )

    phone = target.get("contact_phone") or target.get("donor_phone")
    name = target.get("contact_name") or target.get("donor_name")
    if not phone:
        fallback = next(
            (
                v
                for v in VOLUNTEER_DIRECTORY
                if v["region"] == target_region and source["resource_type"] in v["resource_types"]
            ),
            None,
        )
        if fallback:
            phone = fallback["phone"]
            name = fallback["name"]

    cross_region = source_region != target_region
    distance_km = _distance_km(source_region or "", target_region or "")
    logistics_note = (
        f" This is a cross-region match ({source_region.title()} <-> {target_region.title()}, "
        f"~{distance_km} km) - confirm transport/delivery before dispatching."
        if cross_region else ""
    )

    message_id = f"wa-{uuid.uuid4().hex[:10]}"
    whatsapp_text = (
        f"[Disaster Response Coordination] Match found for {source['quantity']} {source['unit']} "
        f"of {source['resource_type']} (ref {source['id']}, {source_region.title()}) matched with "
        f"{target['id']} ({target_region.title()}). Please coordinate delivery.{logistics_note}"
    )

    send_result = _send_whatsapp_message(phone, whatsapp_text)
    if send_result.get("sent"):
        message_id = send_result["provider_message_id"] or message_id

    source["status"] = "matched"
    target["status"] = "matched"
    source.setdefault("history", []).append(f"{_now()}: dispatched WhatsApp notification {message_id} to {name or 'unknown contact'}")
    target.setdefault("history", []).append(f"{_now()}: notified via WhatsApp {message_id} about matching record {record_id}")

    return json.dumps(
        {
            "status": "dispatched" if send_result.get("sent") else "simulated",
            "channel": "whatsapp",
            "message_id": message_id,
            "whatsapp_send_result": send_result,
            "notified_name": name or "Unknown - no phone on file",
            "notified_phone": phone or "N/A",
            "message_text": whatsapp_text,
            "cross_region": cross_region,
            "distance_km": distance_km,
            "source_record_id": record_id,
            "matched_record_id": matched_id,
        },
        indent=2,
    )
