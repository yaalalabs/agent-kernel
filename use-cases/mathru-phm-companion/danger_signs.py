"""Danger-sign matching and severity decision.

The model never decides severity. It passes the mother's raw text to `screen()` and receives
a decision made here, in Python, by keyword matching against `data/danger_signs.yaml`.

Every failure mode leans toward escalation:

===========================  ==========  =========
Condition                    Severity    Escalates
===========================  ==========  =========
exception during matching    red         yes
table not `sourced`          red         yes
matched a red entry          red         yes
matched an amber entry       amber       no
symptom text, no match       amber       no
no symptom text at all       green       no
===========================  ==========  =========

`screen()` never raises. An unhandled error inside it would otherwise reach a mother as a
generic failure, which is silently the same as telling her nothing is wrong.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

import provenance

log = logging.getLogger("mathru.danger_signs")

DATA_DIR = Path(__file__).parent / "data"
DANGER_SIGNS_FILE = "danger_signs.yaml"

RED = "red"
AMBER = "amber"
GREEN = "green"

# Table severities are restricted to red and amber. `green` is a system-level state meaning
# no symptom was reported, and is never a value in the table.
TABLE_SEVERITIES = (RED, AMBER)

FAILSAFE_ACTION = (
    "Please contact your PHM or your nearest hospital now. I am not a clinician and I cannot " "assess symptoms."
)
UNMATCHED_ACTION = (
    "I could not match what you described to anything in my reference list, so I cannot tell you "
    "how urgent it is. Please tell your PHM about this. If it gets worse, or you are worried, go "
    "to your nearest hospital. I am not a clinician."
)
NO_SYMPTOM_ACTION = "No symptom was reported."


@lru_cache(maxsize=None)
def load_table() -> dict[str, Any]:
    """Load and cache the danger-sign reference table."""
    with (DATA_DIR / DANGER_SIGNS_FILE).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{DANGER_SIGNS_FILE} must contain a YAML mapping")
    return loaded


def action_strings() -> list[str]:
    """Every action string in the table, for the post-execution hook's allowlist.

    Returns an empty list rather than raising: the hook must keep working even if the table
    is unreadable, and an empty allowlist is the conservative outcome there.
    """
    try:
        return [str(sign["action"]) for sign in load_table().get("signs") or [] if sign.get("action")]
    except Exception:  # noqa: BLE001 - the hook must never fail closed on a data error
        log.exception("Could not read danger-sign action strings for the hook allowlist")
        return []


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Case-insensitive, word-boundary pattern for one keyword or phrase.

    The boundary is only applied at an edge that is actually a word character, so phrases
    ending in punctuation still match.
    """
    escaped = re.escape(keyword.strip())
    prefix = r"\b" if keyword[:1].isalnum() else ""
    suffix = r"\b" if keyword[-1:].isalnum() else ""
    return re.compile(f"{prefix}{escaped}{suffix}", re.IGNORECASE)


def _matches(text: str, sign: dict[str, Any]) -> bool:
    for keyword in sign.get("keywords") or []:
        if keyword and _keyword_pattern(str(keyword)).search(text):
            return True
    return False


def _decision(severity: str, action: str, matched: list[str], reason: str, table_status: str | None) -> dict[str, Any]:
    return {
        "severity": severity,
        "matched_signs": matched,
        "action": action,
        "reason": reason,
        "table_status": table_status,
        "escalate": severity == RED,
    }


def _failsafe(reason: str, table_status: str | None) -> dict[str, Any]:
    return _decision(RED, FAILSAFE_ACTION, [], reason, table_status)


def _screen(symptom_text: str) -> dict[str, Any]:
    text = (symptom_text or "").strip()
    if not text:
        return _decision(GREEN, NO_SYMPTOM_ACTION, [], "no symptom reported", None)

    table = load_table()
    status = table.get("status")

    # An unpopulated table cannot rule anything out, so it must not be allowed to reassure.
    # Only an exact `sourced` counts: a typo must fail toward escalation, not away from it.
    if not provenance.is_sourced(table):
        return _failsafe(f"danger-sign table is not sourced (status: {status!r})", status)

    matched_signs = [sign for sign in table.get("signs") or [] if _matches(text, sign)]
    if not matched_signs:
        return _decision(AMBER, UNMATCHED_ACTION, [], "symptom reported, no table match", status)

    matched_ids = [str(sign.get("id")) for sign in matched_signs]
    red_signs = [sign for sign in matched_signs if sign.get("severity") == RED]

    if red_signs:
        return _decision(
            RED, str(red_signs[0].get("action") or FAILSAFE_ACTION), matched_ids, "matched a red sign", status
        )

    # Floored at amber: a reported symptom never resolves to green.
    return _decision(
        AMBER, str(matched_signs[0].get("action") or UNMATCHED_ACTION), matched_ids, "matched an amber sign", status
    )


def screen(symptom_text: str) -> dict[str, Any]:
    """Decide a severity for reported symptoms. Never raises; fails toward escalation."""
    try:
        return _screen(symptom_text)
    except Exception as exc:  # noqa: BLE001 - deliberate: any failure escalates
        log.exception("Danger-sign screening failed, escalating as red")
        return _failsafe(f"screening error: {type(exc).__name__}", None)
