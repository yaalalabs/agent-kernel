"""Escalation delivery to the assigned PHM.

Nothing here is bound as a tool. `screen_danger_signs` calls `escalate()` internally when
its Python-side decision is `red`, so escalation is never a separate model decision.

Agent Kernel exposes no public API for sending a message outside a request turn: the
WhatsApp handler's `_send_message` is private and there is no client class. So this module
calls the WhatsApp Cloud API directly, reading credentials from `Config.get().whatsapp`, and
mirrors the request the handler itself builds.

Delivery can legitimately fail. A PHM whose 24-hour customer service window has closed
cannot be reached with a freeform message. When that happens the escalation is still
persisted, as undelivered, and the caller is told to direct the mother to seek care herself.
Silence is never an acceptable outcome here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from agentkernel.core import Config

import store
from redaction import redact_phone

log = logging.getLogger("mathru.escalation")

EXCERPT_MAX_CHARS = 300
REQUEST_TIMEOUT_SECONDS = 15.0

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


async def send_whatsapp(to_number: str, text: str) -> None:
    """Send one WhatsApp text via the Cloud API. Raises on any failure."""
    config = Config.get().whatsapp
    if not config.access_token or not config.phone_number_id:
        raise RuntimeError("WhatsApp credentials are not configured")

    url = f"https://graph.facebook.com/{config.api_version or 'v24.0'}/{config.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {config.access_token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()


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
        await send_whatsapp(phm_phone, message)
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
