"""Post-execution hook blocking diagnosis-like and medication-like outbound language.

Registered on the ENTRY agent, `mathru_triage`, and nowhere else. Agent Kernel runs the
whole turn - including OpenAI SDK handoffs - inside one `runner.run()` call and then applies
the entry agent's post-hooks to the result, so a hook here sees `danger_sign_agent`'s final
text. A hook registered on a handoff target would never fire at all.

The two block categories produce different replacements. Naming a condition is a safety
failure that warrants the escalation response. Asking about a supplement is a benign
question that deserves a plain refusal: replying to "should I take folic acid?" with an
urgent escalation message would be its own kind of harm.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from agentkernel import PostHook
from agentkernel.core.model import AgentReplyText

import danger_signs
import escalation
from redaction import redact_text

log = logging.getLogger("mathru.hooks")

DATA_DIR = Path(__file__).parent / "data"
BLOCKED_LANGUAGE_FILE = "blocked_language.yaml"

DIAGNOSIS = "diagnosis"
MEDICATION = "medication"

# Replaces a reply that named a condition or framed a diagnosis.
DIAGNOSIS_BLOCK_RESPONSE = (
    "I cannot tell you what a symptom means, and I am not a clinician. If you are worried "
    "about your health or your baby's, please contact your PHM or go to your nearest hospital."
)

# Replaces a reply that named a medication, supplement, or remedy.
MEDICATION_BLOCK_RESPONSE = (
    "I cannot advise on any medicine or supplement. Please ask your PHM about this at your "
    "next visit, or sooner if you are worried. I am not a clinician."
)

# The standing note every symptom-related reply carries.
NOT_A_CLINICIAN_NOTE = "I am not a clinician."


@lru_cache(maxsize=None)
def load_blocked_language() -> dict[str, list[str]]:
    """Load and cache the block list."""
    with (DATA_DIR / BLOCKED_LANGUAGE_FILE).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return {
        key: [str(term) for term in (loaded.get(key) or [])]
        for key in ("condition_terms", "diagnosis_phrases", "medication_terms")
    }


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    prefix = r"\b" if term[:1].isalnum() else ""
    suffix = r"\b" if term[-1:].isalnum() else ""
    return re.compile(f"{prefix}{escaped}{suffix}", re.IGNORECASE)


def allowlisted_spans() -> list[str]:
    """Text the hook must never judge: legitimate safety output.

    Danger-sign action strings, the escalation responses, the standing note, and the hook's
    own replacements. These are subtracted from the reply before scanning, so a reply that
    carries a legitimate action string is still blocked if it *also* contains a diagnosis.
    """
    return [
        *danger_signs.action_strings(),
        danger_signs.FAILSAFE_ACTION,
        danger_signs.UNMATCHED_ACTION,
        escalation.ESCALATION_SENT_MESSAGE,
        escalation.ESCALATION_FAILED_MESSAGE,
        DIAGNOSIS_BLOCK_RESPONSE,
        MEDICATION_BLOCK_RESPONSE,
        NOT_A_CLINICIAN_NOTE,
    ]


def strip_allowlisted(text: str) -> str:
    """Remove every allowlisted span from the text, longest first."""
    remainder = text
    for span in sorted((span for span in allowlisted_spans() if span), key=len, reverse=True):
        remainder = re.sub(re.escape(span), " ", remainder, flags=re.IGNORECASE)
    return remainder


def classify(text: str) -> tuple[str | None, list[str]]:
    """Return (category, matched terms) for a reply, or (None, []) when it is clean.

    Diagnosis wins over medication when a reply trips both: naming a condition is the more
    serious failure and warrants the more urgent replacement.
    """
    if not text:
        return None, []

    remainder = strip_allowlisted(text)
    blocked = load_blocked_language()

    diagnosis_hits = [
        term
        for term in (*blocked["condition_terms"], *blocked["diagnosis_phrases"])
        if _term_pattern(term).search(remainder)
    ]
    if diagnosis_hits:
        return DIAGNOSIS, diagnosis_hits

    medication_hits = [term for term in blocked["medication_terms"] if _term_pattern(term).search(remainder)]
    if medication_hits:
        return MEDICATION, medication_hits

    return None, []


class BlockUnsafeLanguageHook(PostHook):
    """Replaces outbound replies containing diagnosis-like or medication-like language."""

    async def on_run(self, session: Any, requests: Any, agent: Any, agent_reply: Any) -> Any:
        if not isinstance(agent_reply, AgentReplyText):
            return agent_reply

        category, matched = classify(agent_reply.response)
        if category is None:
            return agent_reply

        # Logged with the original reply so the false-positive rate is measurable before
        # demo day. `mg`, `ml`, and `dose` are broad enough that there will be some.
        log.warning(
            "Blocked %s language in outbound reply. Matched %s. Original (redacted): %s",
            category,
            matched,
            redact_text(agent_reply.response),
        )

        agent_reply.response = DIAGNOSIS_BLOCK_RESPONSE if category == DIAGNOSIS else MEDICATION_BLOCK_RESPONSE
        return agent_reply

    def name(self) -> str:
        return "BlockUnsafeLanguageHook"
