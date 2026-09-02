"""Agent Kernel tools for the Mathru PHM companion.

Identity is never a tool parameter. Each tool resolves the sender from
`ToolContext.get().session.id`, which the WhatsApp integration sets to the sender's phone
number. This stops the model from asserting who is speaking.

The one phone number that is a parameter is `phm_phone`: it is a data field the mother
supplies, like her MOH division, and cannot be derived from the session.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentkernel.core import ToolContext

import danger_signs
import escalation
import provenance
import schedules
import store

# Sri Lankan E.164 without the leading '+': country code 94 followed by 9 national digits.
PHONE_COUNTRY_CODE = "94"
PHONE_TOTAL_DIGITS = 11
PHONE_FORMAT_HINT = "Please give the number in the form 94XXXXXXXXX, for example 94771234567."

PLACEHOLDER_WARNING = (
    "The schedule data file has not been populated with Ministry of Health values yet. "
    "These dates are placeholders. Do not give them to the mother as real appointment dates. "
    "Tell her the schedule is not available yet and to check with her PHM."
)

NOT_REGISTERED = {
    "registered": False,
    "message": "This sender is not registered yet. Hand off to intake_agent to register them.",
}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def _error(message: str) -> str:
    return _json({"ok": False, "error": message})


def _session_id() -> str | None:
    """The current sender's session id, or None outside an agent invocation."""
    try:
        return ToolContext.get().session.id
    except RuntimeError:
        return None


def normalize_phone(raw: str) -> str:
    """Strip formatting and map a local 0XXXXXXXXX number onto its 94XXXXXXXXX form."""
    digits = re.sub(r"[\s\-()]", "", (raw or "").strip())
    digits = digits.removeprefix("+")
    if len(digits) == PHONE_TOTAL_DIGITS - 1 and digits.startswith("0"):
        digits = PHONE_COUNTRY_CODE + digits[1:]
    return digits


def validate_phm_phone(raw: str, session_id: str) -> tuple[str, str | None]:
    """Validate an assigned PHM number. Returns (normalized, error message or None).

    In phase 3 this field decides where a mother's symptom report is sent, so a typo would
    deliver her health information to a stranger. Both checks exist for that reason.
    """
    phone = normalize_phone(raw)
    if not phone.isdigit():
        return phone, f"That PHM number contains characters I could not read. {PHONE_FORMAT_HINT}"
    if not phone.startswith(PHONE_COUNTRY_CODE) or len(phone) != PHONE_TOTAL_DIGITS:
        return phone, f"That does not look like a Sri Lankan phone number. {PHONE_FORMAT_HINT}"
    if phone == session_id:
        return phone, (
            "That is your own number, not your PHM's. Your PHM's number is where your reports would be "
            "sent, so it must be different from yours. Please check and tell me your PHM's number."
        )
    return phone, None


def register_mother(
    first_name: str,
    moh_area: str,
    phm_phone: str,
    edd_iso: str = "",
    child_dob_iso: str = "",
) -> str:
    """Create or update the sender's registration record.

    Supply exactly one of edd_iso (expected delivery date) or child_dob_iso (child's date of
    birth) as a YYYY-MM-DD date, and pass an empty string for the other. Re-registering the
    same sender updates their record. Only call this after the mother has confirmed the
    details you read back to her.
    """
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation, so I did not save anything.")

    name = (first_name or "").strip()
    if not name:
        return _error("I still need the mother's first name.")
    # SPEC.md permits the first name only, so keep the leading token and discard the rest.
    name = name.split()[0]

    area = (moh_area or "").strip()
    if not area:
        return _error("I still need the MOH division.")

    phone, phone_error = validate_phm_phone(phm_phone, session_id)
    if phone_error:
        return _error(phone_error)

    edd = (edd_iso or "").strip()
    dob = (child_dob_iso or "").strip()
    if edd and dob:
        return _error("I need either an expected delivery date or a child's date of birth, not both.")
    if not edd and not dob:
        return _error("I need either an expected delivery date or a child's date of birth.")

    if edd:
        date_error = schedules.validate_edd(edd)
        if date_error:
            return _error(date_error)
    else:
        date_error = schedules.validate_child_dob(dob)
        if date_error:
            return _error(date_error)

    record = store.upsert_mother(
        session_id=session_id,
        first_name=name,
        moh_area=area,
        phm_phone=phone,
        edd_iso=edd or None,
        child_dob_iso=dob or None,
    )
    return _json({"ok": True, "registered": True, "record": record})


def get_mother_profile() -> str:
    """Return the sender's stored registration record, or a not-registered marker."""
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    record = store.get_mother(session_id)
    if record is None:
        return _json(NOT_REGISTERED)
    return _json({"registered": True, "record": record})


def _schedule_payload(calendar: dict[str, Any]) -> str:
    payload: dict[str, Any] = {"ok": True, **calendar}
    payload["next_due"] = schedules.next_due(calendar["visits"])
    if not provenance.is_sourced(calendar):
        payload["data_status"] = provenance.PLACEHOLDER
        payload["data_warning"] = PLACEHOLDER_WARNING
    return _json(payload)


def compute_antenatal_schedule() -> str:
    """Return the antenatal visit calendar for the sender, derived from her stored EDD."""
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    record = store.get_mother(session_id)
    if record is None:
        return _json(NOT_REGISTERED)
    if not record["edd_iso"]:
        return _error("This sender is registered with a child's date of birth, so there is no antenatal calendar.")

    return _schedule_payload(schedules.antenatal_visits(record["edd_iso"]))


def compute_immunization_schedule() -> str:
    """Return the immunisation calendar for the sender, derived from the stored date of birth."""
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    record = store.get_mother(session_id)
    if record is None:
        return _json(NOT_REGISTERED)
    if not record["child_dob_iso"]:
        return _error("This sender is registered with an expected delivery date, so there is no immunisation calendar.")

    return _schedule_payload(schedules.immunization_visits(record["child_dob_iso"]))


def next_appointment() -> str:
    """Return the single next due visit for the sender, from whichever calendar applies."""
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    record = store.get_mother(session_id)
    if record is None:
        return _json(NOT_REGISTERED)

    if record["edd_iso"]:
        calendar = schedules.antenatal_visits(record["edd_iso"])
    else:
        calendar = schedules.immunization_visits(record["child_dob_iso"])

    payload: dict[str, Any] = {
        "ok": True,
        "kind": calendar["kind"],
        "next_due": schedules.next_due(calendar["visits"]),
    }
    if not provenance.is_sourced(calendar):
        payload["data_status"] = provenance.PLACEHOLDER
        payload["data_warning"] = PLACEHOLDER_WARNING
    return _json(payload)


# Every reply arising from a symptom report carries this, per SPEC.md.
STANDING_NOTE = "I am not a clinician."

NOT_A_PHM = {
    "ok": False,
    "error": "This sender is not a registered PHM, so PHM capabilities are not available.",
}


async def screen_danger_signs(symptom_text: str) -> str:
    """Screen a mother's reported symptoms against the danger-sign reference table.

    Pass the mother's own description of her symptoms through unchanged, in her own words.
    You do not decide how urgent it is: the severity and the action string come back from
    this tool and must be relayed as written. When the severity is red this tool has already
    escalated to her PHM before returning.
    """
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    decision = danger_signs.screen(symptom_text)
    payload: dict[str, Any] = {
        "ok": True,
        "severity": decision["severity"],
        "matched_signs": decision["matched_signs"],
        "action": decision["action"],
        "reason": decision["reason"],
        "standing_note": STANDING_NOTE,
        "relay_action_verbatim": True,
    }
    if decision["table_status"] != provenance.SOURCED:
        payload["data_status"] = provenance.PLACEHOLDER

    if not decision["escalate"]:
        return _json(payload)

    record = store.get_mother(session_id)
    if record is None:
        # Nobody to escalate to, so she must be told to seek care herself. Never imply that
        # anything was sent on her behalf.
        payload["escalated"] = False
        payload["escalation_blocked_reason"] = "sender is not registered, so no PHM is assigned"
        payload["message_for_mother"] = escalation.ESCALATION_FAILED_MESSAGE
        return _json(payload)

    payload.update(await escalation.escalate(record, decision["severity"], decision["matched_signs"], symptom_text))
    return _json(payload)


def resolve_role() -> str:
    """Return whether this sender is a registered PHM, a registered mother, or neither.

    Call this first to decide where to route. A sender can be both: PHM capabilities follow
    the PHM role, but a sender who has a mother record can always report symptoms.
    """
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")

    is_phm = store.is_registered_phm(session_id)
    is_mother = store.get_mother(session_id) is not None

    if is_phm:
        role = "phm"
    elif is_mother:
        role = "mother"
    else:
        role = "unknown"

    return _json(
        {
            "ok": True,
            "role": role,
            "is_phm": is_phm,
            "is_registered_mother": is_mother,
            "may_report_symptoms": is_mother,
        }
    )


def phm_caseload() -> str:
    """Return the calling PHM's registered mothers and her open escalations."""
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")
    if not store.is_registered_phm(session_id):
        return _json(NOT_A_PHM)

    mothers = [
        {
            "first_name": mother["first_name"],
            "moh_area": mother["moh_area"],
            "edd_iso": mother["edd_iso"],
            "child_dob_iso": mother["child_dob_iso"],
        }
        for mother in store.mothers_for_phm(session_id)
    ]
    escalations = store.open_escalations_for_phm(session_id)

    return _json(
        {
            "ok": True,
            "mothers": mothers,
            "mother_count": len(mothers),
            "open_escalations": escalations,
            "open_escalation_count": len(escalations),
            "undelivered_count": sum(1 for item in escalations if item["delivery"] == store.UNDELIVERED),
        }
    )


def acknowledge_escalation(escalation_id: int) -> str:
    """Mark one of the calling PHM's open escalations as acknowledged.

    This closes the escalation on the PHM's caseload. It sends nothing to the mother.
    """
    session_id = _session_id()
    if session_id is None:
        return _error("I could not identify this conversation.")
    if not store.is_registered_phm(session_id):
        return _json(NOT_A_PHM)

    record = store.acknowledge_escalation(escalation_id, session_id)
    if record is None:
        return _error(f"No escalation with id {escalation_id} belongs to this PHM.")

    return _json({"ok": True, "acknowledged": True, "escalation": record})
