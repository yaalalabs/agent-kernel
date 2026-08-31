"""Gemini Live configuration and tool execution for voice calls.

The live call bypasses the text agents entirely (no orchestrator, no hooks), so
this module carries the persona + safety rules in the system prompt and executes
a voice-suitable subset of ``tool.py`` directly against the SAME Agent Kernel
session the text chat uses (session id = the caller's phone number). That is the
cross-channel guarantee: consent given on a call is honoured in chat and vice versa.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from agentkernel.core import Runtime
from agentkernel.core import ToolContext as AKToolContext
from google.genai import types

import speech
import state
import tool

logger = logging.getLogger("sarasavi.voice.live")

# Newest Live model on this key and the one the Amathum-AI bridge runs for
# Sinhala. Fall back to gemini-2.5-flash-native-audio-preview-12-2025 via env if
# 3.1 ever regresses; note 3.x Flash Live does not support NON_BLOCKING tools,
# which this use-case does not use.
LIVE_MODEL = os.environ.get("SARASAVI_VOICE_MODEL", "gemini-3.1-flash-live-preview")
LIVE_VOICE = os.environ.get("SARASAVI_VOICE_NAME", "Aoede")

# Turn-taking, in milliseconds. Both are overridable so a noisy line can be
# tuned without a redeploy.
SILENCE_DURATION_MS = int(os.environ.get("SARASAVI_VAD_SILENCE_MS", "800"))
PREFIX_PADDING_MS = int(os.environ.get("SARASAVI_VAD_PREFIX_MS", "0"))  # 0 = leave Google default

# Voice-suitable subset of tool.py. Excluded on purpose: list_appliances (reading
# a catalog aloud is bad voice UX — add_appliance resolves spoken names), export/
# delete (privacy actions belong in the auditable text channel), simulate_change
# and match_saving_tips (keep the schema small so Sinhala tool-calling stays sharp).
VOICE_TOOLS: dict[str, Callable[..., str]] = {
    "set_storage_consent": tool.set_storage_consent,
    "set_language": tool.set_language,
    "set_household": tool.set_household,
    "add_appliance": tool.add_appliance,
    "record_bill_reading": tool.record_bill_reading,
    "compute_current_bill": tool.compute_current_bill,
    "find_savings": tool.find_savings,
}


def _decl(
    name: str, description: str, properties: dict[str, types.Schema], required: list[str]
) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=types.Schema(type=types.Type.OBJECT, properties=properties, required=required),
    )


VOICE_TOOL_DECLARATIONS: list[types.FunctionDeclaration] = [
    _decl(
        "set_storage_consent",
        "Grant or revoke consent to remember the household profile. Call with true only after the caller clearly says yes.",
        {"consent": types.Schema(type=types.Type.BOOLEAN)},
        ["consent"],
    ),
    _decl(
        "set_language",
        "Store the caller's preferred language: en, si (Sinhala) or ta (Tamil).",
        {"language": types.Schema(type=types.Type.STRING)},
        ["language"],
    ),
    _decl(
        "set_household",
        "Record billing basics. billing_cycle is 'monthly' or 'bimonthly'; billing_days 0 keeps the cycle default.",
        {
            "billing_cycle": types.Schema(type=types.Type.STRING),
            "billing_days": types.Schema(type=types.Type.INTEGER),
        },
        [],
    ),
    _decl(
        "add_appliance",
        "Record one appliance the caller mentioned, with average daily hours. Spoken names like 'fridge' or 'ෆෑන් එක' are accepted.",
        {
            "appliance": types.Schema(
                type=types.Type.STRING, description="the appliance name exactly as the caller said it"
            ),
            "hours_per_day": types.Schema(type=types.Type.NUMBER, description="average daily hours the caller said"),
            "quantity": types.Schema(type=types.Type.INTEGER, description="how many of them; default 1"),
        },
        ["appliance", "hours_per_day"],
    ),
    _decl(
        "record_bill_reading",
        "Record the exact units (kWh) the caller read from their bill or meter. billing_days 0 keeps the current period.",
        {
            "units": types.Schema(type=types.Type.NUMBER),
            "billing_days": types.Schema(type=types.Type.INTEGER),
        },
        ["units"],
    ),
    _decl(
        "compute_current_bill",
        "Compute the current estimated bill in LKR from stored data. Say the returned total_spoken "
        "aloud exactly as written; the numeric total is for your reasoning only.",
        {},
        [],
    ),
    _decl(
        "find_savings",
        "Find the best ways to cut the bill, led by tariff slab-boundary opportunities. Say the "
        "_spoken money fields (current_bill.total_spoken, savings_spoken) exactly as written. The "
        "result also has a 'plan' field: that is written text for the WhatsApp channel, never read it "
        "aloud or spell out its numbering; instead say the same one or two highest-value actions in "
        "your own short spoken style.",
        {},
        [],
    ),
    _decl(
        "end_call",
        "Hang up the line. Call this only immediately after you have already spoken a short goodbye line "
        "and the caller has nothing further to ask; never call it mid-question.",
        {},
        [],
    ),
]

_SYSTEM_PROMPT = (
    "You are Sarasavi Power, the voice assistant of an electricity advisory service, answering a "
    "WhatsApp call from a Sri Lankan household about their electricity bill.\n"
    # Voice is not text: everything written is spoken aloud, so formatting characters
    # and written number styles are read out literally and ruin the call.
    # Sinhala is the majority language of the callers this serves, and the opening
    # line goes out before anyone has spoken, so there is nothing to detect from
    # yet. Opening in Sinhala and switching on the caller's first words is right
    # far more often than defaulting to English.
    "How to speak: open in SINHALA with one short line: 'ආයුබෝවන්. සරසවි පවර්. ඔබේ විදුලි බිල ගැන "
    "මට කොහොමද උදව් කරන්න පුළුවන්ද?'. Then speak whatever language the caller replies in, Sinhala, "
    "Tamil or English, and switch the moment they switch. Be warm but businesslike, the way a good utility "
    "help desk sounds. Keep every turn to one or two short sentences, then stop and let them talk; "
    "never deliver a paragraph. Ask one question at a time.\n"
    "This is speech, not text. Never say formatting characters: no asterisks, bullets, or headings. "
    "Money arrives in tool results twice: a raw number such as 1260.00 for your reasoning, and a "
    "ready-to-say '<name>_spoken' field right next to it (total_spoken, savings_spoken). When you "
    "say an amount, say the _spoken string EXACTLY as written, word for word. Never read the raw "
    "number as written, never say the letters 'LKR', and never say 'point', 'දශම' or 'බිංදුව' "
    "inside an amount. If an amount has no _spoken field, or the caller is speaking a different "
    "language than the _spoken text, convert the raw number yourself the same way: drop the decimal "
    "entirely when it is .00, otherwise whole rupees then cents. In Sinhala: 345.00 becomes "
    "'රුපියල් තුන්සිය හතලිස් පහයි' (no 'සත', no 'බින්දු'), and 350.58 becomes 'රුපියල් තුන්සිය පනහයි "
    "සත පනස් අටයි'. In English: 'three hundred and forty five rupees', and 'three hundred and fifty "
    "rupees and fifty eight cents'. Same rule for kWh, and the unit word leads the number in Sinhala and "
    "Tamil exactly like the currency word does: 520 kWh becomes 'කිලෝ වොට් පන්සිය විස්ස' or 'ඒකක "
    "පන්සිය විස්ස' in Sinhala (never 'පන්සිය විස්ස කිලෝ වොට්'), 'கிலோவாட் ஐநூற்று இருபது' in Tamil. "
    "English keeps its own order: 'five hundred and twenty units'. Never spell out 'kWh' or read a "
    "trailing '.00' on a unit count either. Round in speech, "
    "one decimal at most. Never read a list of appliances aloud; name the top two and stop. Never "
    "spell out tool names.\n"
    "Data rules: never work out units, bills, or savings yourself. Call the tools and say their "
    "numbers. Every figure is an estimate based on the published CEB and LECO domestic tariff, not "
    "an official bill; say that once, briefly, the first time you give an amount, not every time. "
    "You are an independent advisory service; never say or imply that you are CEB, LECO or PUCSL. "
    "Before storing anything, say the profile is kept for this conversation, get a clear yes, then "
    "call set_storage_consent.\n"
    "If you did not hear the caller clearly, say so plainly and ask them to repeat, rather than "
    "guessing at a number. If they go quiet, ask one short prompting question.\n"
    "Safety: never give wiring, meter, or electrical repair instructions. Tell them to contact a "
    "licensed electrician, or CEB on one nine eight seven for a supply fault, then offer what you "
    "can do instead. Decline anything unrelated to household electricity in one sentence and offer "
    "two things you can help with. For exporting or deleting their data, ask them to send a "
    "WhatsApp text message, so the request is on record.\n"
    "Ending the call: when the caller says goodbye, thanks you and is clearly done, or has nothing "
    "further to ask, speak one short warm closing line in the language of the call, for example "
    "'stuti, subha dawasak', then call end_call right after. Never call end_call before speaking "
    "that line, and never while the caller still seems to be mid question."
)


def _activity_detection() -> types.RealtimeInputConfig:
    """Turn-taking tuning. This is what the caller experiences as "lag".

    Gemini decides the caller has finished only after a continuous silence of
    ``silence_duration_ms``, and answers no sooner. Google's default is tuned for
    a headset in a quiet room; on a Sri Lankan phone line it left multi-second
    gaps after every sentence. 800 ms is short enough to feel like a conversation
    while still allowing the mid-sentence pauses Sinhala speech has more of than
    the American English these defaults were set against.
    """
    # Only the silence threshold is moved. Setting START_SENSITIVITY_LOW here once
    # looked like noise rejection and was in fact the opposite: it lowers how
    # readily speech is detected at all, and a whole call went by with the
    # caller's audio arriving and Gemini never registering a word of it. The
    # sensitivities stay at Google's defaults unless deliberately overridden.
    detection = types.AutomaticActivityDetection(silence_duration_ms=SILENCE_DURATION_MS)
    if PREFIX_PADDING_MS:
        detection.prefix_padding_ms = PREFIX_PADDING_MS
    return types.RealtimeInputConfig(automatic_activity_detection=detection)


def build_live_config() -> types.LiveConnectConfig:
    """LiveConnectConfig for a Sarasavi call: audio out, transcripts on, tools bound."""
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=_SYSTEM_PROMPT,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE))
        ),
        tools=[types.Tool(function_declarations=VOICE_TOOL_DECLARATIONS)],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=_activity_detection(),
    )


class VoiceToolExecutor:
    """Run ``tool.py`` functions outside an agent run, against the caller's session.

    Mirrors what ``GoogleADKRunner`` + ``Runtime.run`` do around tools: load the
    session by id, take its lock (which also serialises against a text message
    arriving mid-call), activate a ToolContext, run, persist, deactivate.
    """

    def __init__(self, phone_number: str):
        self._runtime = Runtime.current()
        self._session = self._runtime.sessions().load(phone_number)
        # Any registered agent satisfies the ToolContext constructor; state.py
        # only ever touches ctx.session.
        agents = self._runtime.agents()
        self._agent = agents.get("orchestrator") or next(iter(agents.values()), None)

    @property
    def session(self):
        return self._session

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        func = VOICE_TOOLS.get(name)
        if func is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        async with self._session:
            ctx = AKToolContext(self._runtime, self._agent, self._session, [])
            ctx.set()
            try:
                raw = func(**(args or {}))
                language = state.get_language()
            except TypeError as exc:
                return {"ok": False, "error": f"bad arguments: {exc}"}
            finally:
                ctx.reset()
            self._runtime.sessions().store(self._session)
        try:
            result = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            result = {"result": raw}
        # Gemini Live speaks the answer directly, so there is no text stage where
        # "LKR 1,260.00" could be rewritten. Instead every money field gains a
        # ready-to-say ``*_spoken`` sibling in the caller's language and the
        # system prompt tells the model to read those verbatim.
        if isinstance(result, dict):
            speech.annotate_spoken_amounts(result, language)
        logger.info("Voice tool %s -> ok=%s", name, result.get("ok", "n/a"))
        return result
