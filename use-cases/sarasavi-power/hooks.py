"""Agent Kernel execution hooks — deterministic guardrails.

These make two promises non-negotiable instead of relying on the LLM to remember:
  * DisclaimerHook (post): every reply that quotes a money figure carries the
    "estimate, not an official CEB/LECO bill" note.
  * SafetyPreHook (pre): obvious unsafe-electrical / off-topic requests are refused
    up front (a deterministic backstop to the instruction-based guardrail).

Verified API (kernel.yaala.ai/docs/integrations/hooks):
    PreHook.on_run(session, agent, requests) -> list[AgentRequest] | AgentReply
      (return requests to continue; return an AgentReply to HALT)
    PostHook.on_run(session, requests, agent, agent_reply) -> AgentReply
    register: GoogleADKModule(AGENTS).pre_hook(agent, [...]).post_hook(agent, [...])

NOTE: the Sinhala/Tamil strings below are first-pass translations — have a native
speaker review them before launch.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy

from agentkernel import PostHook, PreHook
from agentkernel.core.model import AgentReplyText, AgentRequestText

from engine import compute_bill, estimate_total
from localization import LANGUAGE_LABELS, detect_language, normalize_language
from state import PROFILE_KEY

logger = logging.getLogger("sarasavi.hooks")

DISCLAIMERS = {
    "en": "Estimate only. Not an official CEB/LECO bill.",
    "si": "මෙය ඇස්තමේන්තුවක් පමණි. නිල CEB/LECO බිලක් නොවේ.",
    "ta": "இது ஒரு மதிப்பீடு மட்டுமே. அதிகாரப்பூர்வ CEB/LECO கட்டணப் பட்டியல் அல்ல.",
}

# Used once the household has given a real meter/bill reading. The figure is then
# a calculation from the published tariff, not an estimate, so saying "estimate"
# would be wrong; the "not official" half still has to stand.
METERED_DISCLAIMERS = {
    "en": "Calculated from the published CEB/LECO tariff. Not an official bill.",
    "si": "ප්‍රකාශිත CEB/LECO ගාස්තු අනුව ගණනය කර ඇත. නිල බිලක් නොවේ.",
    "ta": "வெளியிடப்பட்ட CEB/LECO கட்டண விகிதங்களின்படி கணக்கிடப்பட்டது. அதிகாரப்பூர்வ கட்டணப் பட்டியல் அல்ல.",
}

# Shown once per conversation. The notice has to be unmissable the first time
# money appears; repeating it on every reply afterwards is noise that trains
# people to ignore it.
_DISCLAIMER_SHOWN_KEY = "disclaimer_shown"

REFUSALS = {
    "en": (
        "For your safety I can't give wiring, meter, or repair instructions. Please contact a "
        "licensed electrician, or CEB on 1987 for a supply fault.\n\n"
        "I can still help you with:\n"
        "• Estimating your monthly units and bill\n"
        "• Finding which appliances cost you most\n"
        "• Showing how to get under the next tariff block"
    ),
    "si": (
        "ආරක්ෂාව සඳහා රැහැන්, මීටර හෝ අලුත්වැඩියා උපදෙස් දිය නොහැක. කරුණාකර බලපත්‍රලාභී "
        "විදුලි කාර්මිකයෙකු හමුවන්න, නැතහොත් විදුලි බාධාවක් සඳහා CEB 1987 අමතන්න.\n\n"
        "මට තවමත් උදව් කළ හැකි දේ:\n"
        "• ඔබේ මාසික ඒකක හා බිල ඇස්තමේන්තු කිරීම\n"
        "• වැඩිම විදුලිය වැය කරන උපකරණ සොයා ගැනීම\n"
        "• ඊළඟ අඩු තීරුවට යාමට ක්‍රමය පෙන්වීම"
    ),
    "ta": (
        "பாதுகாப்பிற்காக வயரிங்/மீட்டர்/பழுதுபார்ப்பு அறிவுறுத்தல்கள் தர முடியாது. உரிமம் பெற்ற "
        "மின்சாரத் தொழிலாளரை அணுகவும், அல்லது மின் தடைக்கு CEB 1987 ஐ அழைக்கவும்.\n\n"
        "நான் உதவக்கூடியவை:\n"
        "• உங்கள் மாதாந்திர யூனிட் மற்றும் கட்டணத்தை மதிப்பிடுதல்\n"
        "• அதிக மின்சாரம் செலவழிக்கும் உபகரணங்களைக் கண்டறிதல்\n"
        "• அடுத்த குறைந்த கட்டணப் படிக்குச் செல்லும் வழி"
    ),
}

# Deterministic backstop only — the LLM instructions do the nuanced screening.
_UNSAFE_TERMS = (
    "rewire",
    "re-wire",
    "wire the",
    "wiring the",
    "fix the wiring",
    "bypass the meter",
    "bypass meter",
    "tamper",
    "tap the line",
    "connect directly to the mains",
    "open the meter",
    "meter reversal",
    "slow the meter",
    # Sinhala / Tamil script (bypass, meter tampering) — unambiguous in this domain.
    "බයිපාස්",
    "මීටරය විවෘත",
    "මීටරය හරව",
    "பைபாஸ்",
    "மீட்டரை திற",
)

_MONEY_MARKERS = ("lkr", "rs.", "rs ", "rupee", "රු.", "ரூ")

# Match only a claim about the current/estimated bill. Savings amounts are left
# untouched because they represent a different engine result.
_BILL_PHRASE = (
    r"(?:(?:your\s+)?estimated(?:\s+monthly)?(?:\s+electricity)?\s+bill|current\s+bill|"
    r"ඇස්තමේන්තුගත[^.\d]{0,30}?බිල|மதிப்பிடப்பட்ட[^.\d]{0,30}?(?:கட்டணம்|மின்சாரக் கட்டணம்))"
)
_CURRENT_BILL_PATTERN = re.compile(
    rf"(?P<prefix>{_BILL_PHRASE}[^.\d]{{0,80}}?(?:(?:is|:|වන්නේ|ஆகும்)\s*)?(?:\*\*)?\s*)"
    r"(?:(?P<currency_before>LKR|Rs\.?|රු\.?|ரூ\.?)\s*(?P<amount_after>[\d,]+(?:\.\d+)?)|"
    r"(?P<amount_before>[\d,]+(?:\.\d+)?)\s*(?P<currency_after>LKR|Rs\.?|රු\.?|ரூ\.?))",
    re.IGNORECASE,
)


def _language_from_session(session, text: str = "") -> str:
    """Read the stored language directly from the session (hooks may run outside a
    ToolContext), falling back to script detection and then English."""
    detected = detect_language(text)
    if detected:
        return detected
    try:
        profile = session.get_non_volatile_cache().get(PROFILE_KEY, {}) or {}
        return normalize_language(profile.get("language"))
    except Exception:
        return "en"


class LanguagePreferenceHook(PreHook):
    """Persist consented preference and explicitly steer every model request."""

    async def on_run(self, session, agent, requests):
        text = " ".join(req.text or "" for req in requests if isinstance(req, AgentRequestText))
        detected = detect_language(text)
        active_language = detected
        try:
            cache = session.get_non_volatile_cache()
            profile = cache.get(PROFILE_KEY, {}) or {}
            if profile.get("consent") and profile.get("language") != detected:
                if detected:
                    updated = deepcopy(profile)
                    updated["language"] = detected
                    cache.set(PROFILE_KEY, updated)
                    profile = updated
                    logger.info("Updated session language from user input: %s", detected)
            if not active_language and profile.get("consent"):
                active_language = normalize_language(profile.get("language"))
        except Exception:
            logger.exception("Unable to persist detected session language")

        if active_language:
            label = LANGUAGE_LABELS[active_language]
            requirement = (
                f"[Required response language: {label} ({active_language}). "
                f"Reply only in {label}; do not switch to another language.]"
            )
            for request in requests:
                if isinstance(request, AgentRequestText) and requirement not in (request.text or ""):
                    request.text = f"{request.text}\n\n{requirement}"
        return requests

    def name(self) -> str:
        return "LanguagePreferenceHook"


class SafetyPreHook(PreHook):
    async def on_run(self, session, agent, requests):
        if requests and isinstance(requests[0], AgentRequestText):
            text = (requests[0].text or "").lower()
            if any(term in text for term in _UNSAFE_TERMS):
                lang = _language_from_session(session, text)
                return AgentReplyText(text=REFUSALS.get(lang, REFUSALS["en"]))
        return requests

    def name(self) -> str:
        return "SafetyPreHook"


class DisclaimerHook(PostHook):
    @staticmethod
    def _note(session, text: str) -> str:
        """Pick the wording that is actually true for this household."""
        language = _language_from_session(session, text)
        try:
            profile = session.get_non_volatile_cache().get(PROFILE_KEY, {}) or {}
            metered = profile.get("metered_units") is not None
        except Exception:
            metered = False
        source = METERED_DISCLAIMERS if metered else DISCLAIMERS
        return source.get(language, source["en"])

    @staticmethod
    def _already_shown(session) -> bool:
        try:
            return bool(session.get_non_volatile_cache().get(_DISCLAIMER_SHOWN_KEY, False))
        except Exception:
            return False

    @staticmethod
    def _mark_shown(session) -> None:
        try:
            session.get_non_volatile_cache().set(_DISCLAIMER_SHOWN_KEY, True)
        except Exception:
            logger.exception("Could not record that the disclaimer was shown")

    async def on_run(self, session, requests, agent, agent_reply):
        if isinstance(agent_reply, AgentReplyText):
            text = agent_reply.text or ""
            note = self._note(session, text)
            mentions_money = any(m in text.lower() for m in _MONEY_MARKERS)
            mentions_bill_number = any(ch.isdigit() for ch in text) and any(
                word in text.lower() for word in ("bill", "saving", "charge", "බිල", "கட்டணம்")
            )
            if (mentions_money or mentions_bill_number) and note not in text:
                if self._already_shown(session):
                    return agent_reply
                self._mark_shown(session)
                return AgentReplyText(text=f"{text}\n\n_{note}_", prompt=agent_reply.prompt)
        return agent_reply

    def name(self) -> str:
        return "DisclaimerHook"


class SafetyPostHook(PostHook):
    """Replace an unsafe electrical instruction if one escapes the model prompt."""

    async def on_run(self, session, requests, agent, agent_reply):
        if isinstance(agent_reply, AgentReplyText):
            text = (agent_reply.text or "").lower()
            if any(term in text for term in _UNSAFE_TERMS):
                lang = _language_from_session(session, text)
                return AgentReplyText(
                    text=REFUSALS.get(lang, REFUSALS["en"]),
                    prompt=agent_reply.prompt,
                )
        return agent_reply

    def name(self) -> str:
        return "SafetyPostHook"


def _expected_current_bill(session) -> float | None:
    """Compute the session's canonical current bill through the engine."""
    try:
        profile = session.get_non_volatile_cache().get(PROFILE_KEY, {}) or {}
        metered = profile.get("metered_units")
        if metered is None:
            appliances = profile.get("appliances", [])
            if not appliances:
                return None
            days = int(profile.get("billing_days") or 30)
            usages = [{**item, "days": days} for item in appliances]
            units = estimate_total(usages)["total_kwh"]
        else:
            days = int(profile.get("billing_days") or 30)
            units = float(metered)
        return float(compute_bill(units, billing_days=days)["total"])
    except (KeyError, TypeError, ValueError):
        logger.exception("Unable to verify bill amount from the session profile")
        return None


class BillAccuracyHook(PostHook):
    """Correct a model-substituted current bill using the deterministic engine.

    The LLM normally quotes the tool result, but a small model can occasionally
    replace it with another plausible number. This hook changes only explicit
    current/estimated-bill claims and never touches savings figures.
    """

    async def on_run(self, session, requests, agent, agent_reply):
        if not isinstance(agent_reply, AgentReplyText):
            return agent_reply
        expected = _expected_current_bill(session)
        if expected is None:
            return agent_reply

        corrected = False

        def replace(match: re.Match) -> str:
            nonlocal corrected
            amount = match.group("amount_after") or match.group("amount_before")
            claimed = float(amount.replace(",", ""))
            if abs(claimed - expected) <= 0.01:
                return match.group(0)
            corrected = True
            if match.group("amount_after"):
                return f"{match.group('prefix')}{match.group('currency_before')} {expected:,.2f}"
            return f"{match.group('prefix')}{expected:,.2f} {match.group('currency_after')}"

        text = _CURRENT_BILL_PATTERN.sub(replace, agent_reply.text or "")
        if corrected:
            logger.warning("Corrected a model bill claim to the deterministic engine total")
            return AgentReplyText(text=text, prompt=agent_reply.prompt)
        return agent_reply

    def name(self) -> str:
        return "BillAccuracyHook"


# WhatsApp does not use standard Markdown: emphasis is *single* asterisks, and it
# has no headings or links. Models reliably emit `**bold**`, `### Heading` and
# `[text](url)` anyway, which WhatsApp renders as literal punctuation — visible on
# almost every reply that has any structure. Prompting helps but leaks, so the
# conversion is done deterministically here.
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_ITALIC = re.compile(r"__(.+?)__", re.S)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*#*\s*$", re.M)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_MD_BULLET = re.compile(r"^([ \t]*)[-*+][ \t]+", re.M)
_BLANK_RUN = re.compile(r"\n{3,}")

# Em/en dashes read as machine-written text and are awkward on a phone keyboard,
# so replies use ordinary punctuation. A numeric range keeps a plain hyphen; every
# other dash becomes a comma, which is grammatical wherever the model used one as
# an aside. Enforced here because the model reaches for them constantly.
_DASH_RANGE = re.compile(r"(?<=\d)\s*[—–]\s*(?=\d)")
_DASH_CLAUSE = re.compile(r"\s*[—–]\s*")


def to_whatsapp_markup(text: str) -> str:
    """Rewrite Markdown the model emitted into WhatsApp's own markup."""
    if not text:
        return text
    out = _DASH_RANGE.sub("-", text)
    out = _DASH_CLAUSE.sub(", ", out)
    out = _MD_HEADING.sub(r"*\1*", out)
    out = _MD_BOLD.sub(r"*\1*", out)
    out = _MD_ITALIC.sub(r"_\1_", out)
    out = _MD_LINK.sub(r"\1 (\2)", out)
    out = _MD_BULLET.sub(r"\1• ", out)
    out = _BLANK_RUN.sub("\n\n", out)
    return out.strip()


class WhatsAppFormatHook(PostHook):
    """Normalize Markdown to WhatsApp markup on every outgoing reply."""

    async def on_run(self, session, requests, agent, agent_reply):
        if isinstance(agent_reply, AgentReplyText):
            formatted = to_whatsapp_markup(agent_reply.text or "")
            if formatted != (agent_reply.text or ""):
                return AgentReplyText(text=formatted, prompt=agent_reply.prompt)
        return agent_reply

    def name(self) -> str:
        return "WhatsAppFormatHook"


def register_hooks(module, agents) -> None:
    """Attach the safety pre-hook and disclaimer post-hook to every agent, so the
    guarantees hold no matter which agent produces the user-facing reply."""
    for agent in agents:
        module.pre_hook(agent, [LanguagePreferenceHook(), SafetyPreHook()]).post_hook(
            agent,
            [SafetyPostHook(), BillAccuracyHook(), WhatsAppFormatHook(), DisclaimerHook()],
        )
