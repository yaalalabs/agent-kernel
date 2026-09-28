"""Escalation delivery to the assigned PHM.

Nothing here is bound as a tool. `screen_danger_signs` calls `escalate()` internally when
its Python-side decision is `red`, so escalation is never a separate model decision.

Delivery uses Agent Kernel's public WhatsAppOutboundAdapter. Its reply context explicitly
names the assigned PHM, independently of the sender of the current request.

Delivery can legitimately fail. A PHM whose 24-hour customer service window has closed
cannot be reached with a freeform message. When that happens the escalation is still
persisted, as undelivered, and the caller is told to direct the mother to seek care herself.
Silence is never an acceptable outcome here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agentkernel.core.model import AgentReplyText
from agentkernel.whatsapp import WhatsAppOutboundAdapter

import phm_registry
import store
from redaction import redact_phone

log = logging.getLogger("mathru.escalation")

EXCERPT_MAX_CHARS = 300

# Shown to the mother when her report was escalated and the PHM was reached.
ESCALATION_SENT_MESSAGE = (
    "I have sent your message to your PHM. Please contact your PHM or go to your nearest "
    "hospital now. Do not wait for a reply here. I am not a clinician."
)

# Shown to the mother when delivery failed. It must not imply that help is on the way.
ESCALATION_FAILED_MESSAGE = (
    "I could not reach your PHM just now. Please contact your PHM yourself, or go to your "
    "nearest hospital now. Do not wait for a reply here. I am not a clinician."
)


def excerpt(symptom_text: str) -> str:
    """Trim the mother's own words to a bounded, verbatim excerpt.

    The wording is deliberately not paraphrased: a midwife triaging a report needs how the
    mother actually described it, not a model's summary of it.
    """
    text = " ".join((symptom_text or "").split())
    if len(text) <= EXCERPT_MAX_CHARS:
        return text
    return text[: EXCERPT_MAX_CHARS - 1].rstrip() + "…"


def _stage(record: dict[str, Any]) -> str:
    """How far along the mother is, using only stored values.

    The EDD is sent raw rather than converted to a gestational week: the week would have to
    be derived from `term_gestational_weeks`, which is still a placeholder, and a caveated
    number a midwife has to remember to discount is worse than the stored date she can
    convert herself.
    """
    if record.get("edd_iso"):
        return f"Pregnant, EDD {record['edd_iso']}"

    dob = record.get("child_dob_iso")
    if not dob:
        return "Stage unknown"

    try:
        born = datetime.fromisoformat(dob).date()
        age_weeks = (datetime.now(timezone.utc).date() - born).days // 7
        return f"Child born {dob} (age {age_weeks} weeks)"
    except ValueError:
        return f"Child born {dob}"


def build_message(record: dict[str, Any], severity: str, matched_signs: list[str], words: str) -> str:
    """The WhatsApp text delivered to the PHM.

    The mother's phone number is deliberately not in the body. The PHM has her in her
    caseload, and the first name plus excerpt identify her. The number is in the delivery
    envelope and the stored row.
    """
    signs = ", ".join(matched_signs) if matched_signs else "none matched"
    sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        f"MATHRU ESCALATION - SEVERITY {severity.upper()}\n"
        f"Mother: {record.get('first_name', 'unknown')}, {record.get('moh_area', 'unknown')} MOH\n"
        f"Stage: {_stage(record)}\n"
        f"Matched signs: {signs}\n"
        f'Her words: "{words}"\n'
        f"Sent {sent_at}. This is an automated triage message, not a clinical assessment."
    )


async def escalate(
    record: dict[str, Any], severity: str, matched_signs: list[str], symptom_text: str
) -> dict[str, Any]:
    """Deliver an escalation to the mother's assigned PHM and persist the outcome.

    Always persists, whether delivery succeeded or failed, and always returns a message for
    the mother that is truthful about which of those happened.
    """
    words = excerpt(symptom_text)
    phm_phone = record["phm_phone"]
    message = build_message(record, severity, matched_signs, words)

    delivery = store.DELIVERED
    delivery_error: str | None = None

    try:
        if not phm_registry.is_approved(phm_phone, record["moh_area"]):
            raise ValueError("Assigned PHM is not verified for this MOH division")
        await WhatsAppOutboundAdapter().deliver(AgentReplyText(prompt="", response=message), {"to": phm_phone})
        log.info("Escalation delivered to PHM %s", redact_phone(phm_phone))
    except Exception as exc:  # noqa: BLE001 - every delivery failure is recorded, never raised
        delivery = store.UNDELIVERED
        delivery_error = f"{type(exc).__name__}: {exc}"
        log.error(
            "Escalation delivery to PHM %s FAILED: %s. Recording as undelivered.",
            redact_phone(phm_phone),
            delivery_error,
        )

    escalation = store.record_escalation(
        session_id=record["session_id"],
        severity=severity,
        matched_signs=matched_signs,
        excerpt=words,
        phm_phone=phm_phone,
        delivery=delivery,
        delivery_error=delivery_error,
    )

    return {
        "escalated": True,
        "escalation_id": escalation["id"],
        "delivered": delivery == store.DELIVERED,
        "message_for_mother": (ESCALATION_SENT_MESSAGE if delivery == store.DELIVERED else ESCALATION_FAILED_MESSAGE),
    }
