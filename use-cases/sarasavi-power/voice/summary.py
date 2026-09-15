"""Post-call record + recap so the text chat knows what happened on the call.

The recap is a service record, not a transcript. A caller who has just hung up
does not want their own words read back; they want what the call established:
when it was, what it was about, what got recorded, and whether it is resolved.
"""

from __future__ import annotations

import datetime
import logging
import os

from hooks import DISCLAIMERS, to_whatsapp_markup

logger = logging.getLogger("sarasavi.voice.summary")

# The call summary is written by the cheap text model, not the live one.
BRIEF_MODEL = os.environ.get("SARASAVI_MODEL", "gemini-2.5-flash")

LAST_CALL_KEY = "last_voice_call"
_MAX_TRANSCRIPT_LINES = 30

# What each voice tool means in a customer-facing record.
_TOOL_OUTCOMES = {
    "set_storage_consent": "Consent recorded",
    "set_language": "Language preference saved",
    "set_household": "Billing cycle recorded",
    "add_appliance": "Appliance usage recorded",
    "record_bill_reading": "Meter reading recorded",
    "compute_current_bill": "Bill estimate calculated",
    "find_savings": "Savings options identified",
}

# Which tools indicate the caller actually got the answer they rang for, rather
# than only having details taken down.
_RESOLVING_TOOLS = {"compute_current_bill", "find_savings"}


def _spoken(transcript: list[str], speaker: str) -> str:
    """Rejoin one speaker's streamed transcript chunks into readable text.

    Gemini streams transcription in fragments ("Sarasavi Power, how can", " I
    help"), each stored as its own line and already carrying its leading space.
    Concatenating (not space-joining) is what reconstitutes the sentence.
    """
    prefix = f"{speaker}: "
    chunks = [line[len(prefix) :] for line in transcript if line.startswith(prefix)]
    return " ".join("".join(chunks).split()).strip()


async def store_call_summary(executor, transcript: list[str], tools_used: list[str]) -> None:
    """Persist a compact call record in the caller's session (same store as chat).

    ``executor`` is the call's VoiceToolExecutor: it already holds the loaded
    session and runtime, so writing goes through the same lock + store discipline.
    """
    record = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "transcript": transcript[-_MAX_TRANSCRIPT_LINES:],
        "tools_used": tools_used,
    }
    try:
        session = executor.session
        async with session:
            session.get_non_volatile_cache().set(LAST_CALL_KEY, record)
            executor._runtime.sessions().store(session)
    except Exception:
        logger.exception("Failed to store call summary")


def _topic(transcript: list[str], tools_used: list[str]) -> str:
    """Fallback topic when the model summary is unavailable.

    Deliberately crude: the caller's own words, clipped. Used only if the
    summarising call fails, because a clipped sentence still beats no record.
    """
    asked = _spoken(transcript, "caller")
    if asked:
        return asked if len(asked) <= 140 else asked[:140].rsplit(" ", 1)[0] + "..."
    if tools_used:
        return "Household electricity details"
    return "General enquiry"


_BRIEF_PROMPT = (
    "Below is a transcript of a phone call between a household electricity assistant and a caller.\n"
    "Write ONE short sentence, at most 18 words, saying what the caller wanted. Write it in the same "
    "language the caller used. Report it in the third person, like a service note ('Caller asked how "
    "to reduce a 27 unit monthly bill'). No greeting, no preamble, no quotes, no dashes.\n\n"
)


async def brief_topic(transcript: list[str]) -> str | None:
    """A one-line written summary of the call, or None if it cannot be produced.

    The raw transcript is unusable as a summary: it is the caller's unedited
    speech, mid-sentence clips and all. A small text model turns it into the one
    line a service record actually needs. Best-effort only, the recap falls back
    to the clipped transcript if this fails.
    """
    caller = _spoken(transcript, "caller")
    if not caller:
        return None

    conversation = "\n".join(line for line in transcript if line.startswith(("caller: ", "agent: ")))
    try:
        from google import genai
        from google.genai import types

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=BRIEF_MODEL,
            contents=_BRIEF_PROMPT + conversation[-4000:],
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=2048),
        )
        text = (response.text or "").strip().strip('"')
        return " ".join(text.split()) or None
    except Exception:
        logger.exception("Could not summarise the call; falling back to the transcript")
        return None


def _outcome(tools_used: list[str]) -> tuple[str, list[str]]:
    """Resolution status plus the concrete actions taken on the call."""
    # dict.fromkeys keeps first-use order while removing repeats.
    actions = [_TOOL_OUTCOMES[name] for name in dict.fromkeys(tools_used) if name in _TOOL_OUTCOMES]
    if any(name in _RESOLVING_TOOLS for name in tools_used):
        return "Answered on the call", actions
    if actions:
        return "Details recorded, estimate not yet requested", actions
    return "No details recorded", actions


def recap_text(
    transcript: list[str],
    tools_used: list[str] | None = None,
    started_at: datetime.datetime | None = None,
    duration_seconds: float | None = None,
    brief: str | None = None,
) -> str | None:
    """A short service record of the call; None when there is nothing to report.

    Returns None unless the caller actually spoke: picking up and hanging up
    produced a recap of a half-finished greeting, which is pure noise.
    """
    if not _spoken(transcript, "caller"):
        return None

    tools_used = tools_used or []
    status, actions = _outcome(tools_used)

    lines = ["📞 *Call summary / ඇමතුම් සාරාංශය*"]
    if started_at is not None:
        # Callers read this in their own day, not in UTC.
        local = started_at.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        lines.append(f"*Time:* {local:%Y-%m-%d %H:%M} (Sri Lanka)")
    if duration_seconds is not None:
        minutes, seconds = divmod(int(duration_seconds), 60)
        lines.append(f"*Duration:* {minutes}m {seconds}s" if minutes else f"*Duration:* {seconds}s")

    lines.append(f"*Discussed:* {brief or _topic(transcript, tools_used)}")
    if actions:
        lines.append("*Recorded:*")
        lines.extend(f"• {action}" for action in actions)
    lines.append(f"*Status:* {status}")

    if "compute_current_bill" not in tools_used and "find_savings" not in tools_used:
        lines.append("\nSend a message here any time to get your bill estimate.")

    recap = "\n".join(lines)
    # Sent outside the agent run, so the post-hooks that normally attach the
    # disclaimer and strip Markdown never see it; apply the shared rules here
    # rather than keeping a second copy of the wording.
    if any(name in _RESOLVING_TOOLS for name in tools_used):
        recap = f"{recap}\n\n_{DISCLAIMERS['en']}_"
    return to_whatsapp_markup(recap)
