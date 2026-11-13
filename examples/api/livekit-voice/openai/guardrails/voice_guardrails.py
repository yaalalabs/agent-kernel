"""
Guardrails for a realtime voice call, written as ordinary Agent Kernel hooks.

- `TypedChatPIIRedactor` (pre-hook, `on_run`): redacts PII in typed chat before the model sees it.
- `VoiceOutputGuardrail` (post-hook, `on_stream_event`): checks the agent's live transcript and cuts the agent off
  when it says a blocked phrase, and redacts PII in its captions.

One hook instance serves every call, so per-call state lives in `session.get_volatile_cache()`, which Agent Kernel
clears when the call ends.

The regex PII detection here is for demonstration. Use a dedicated PII detection service in production.
"""

import logging
import os
import re

from agentkernel.core import (
    Agent,
    AgentReply,
    AgentRequest,
    AgentRequestText,
    PostHook,
    PreHook,
    Session,
)
from agentkernel.core.event import AudioDelta, Interrupt, MessageEnd, StreamEvent, TextDelta

_log = logging.getLogger("voice_guardrails")

_PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,18}\b")),
    ("PHONE", re.compile(r"\+?\d[\d ()-]{7,}\d")),
]


def redact_pii(text: str) -> str:
    """Replace emails, card numbers and phone numbers in `text` with a placeholder."""
    for label, pattern in _PII_PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return text


class TypedChatPIIRedactor(PreHook):
    """Redacts PII in typed chat, so the model never sees it. Caller audio is not text and is not checked here."""

    async def on_run(
        self, session: Session, agent: Agent, requests: list[AgentRequest]
    ) -> list[AgentRequest] | AgentReply:
        for request in requests:
            if isinstance(request, AgentRequestText):
                redacted = redact_pii(request.prompt)
                if redacted != request.prompt:
                    _log.info(f"session={session.id} redacted PII in typed chat")
                    request.prompt = redacted
        return requests

    def name(self) -> str:
        return "TypedChatPIIRedactor"


class VoiceOutputGuardrail(PostHook):
    """Guards what the agent says: cuts it off on a blocked phrase, and redacts PII in its captions.

    - Blocked phrases: the live transcript is checked every `debounce_chars` new characters, not on every fragment.
      When it trips, the hook emits an `Interrupt`, so the edge drops the audio it has buffered, then drops the rest
      of the turn's audio and caption. Audio that already played cannot be taken back, so a short part of the phrase
      may be heard. Phrases come from `VOICE_GUARDRAIL_BLOCKED` (comma-separated).
    - Caption PII: PII can be split across text fragments, so the turn's caption is held and released once, redacted,
      at `message_end`. The LiveKit edge publishes a caption at the turn end anyway, so holding adds no visible delay.
      Captions and audio are separate events: the agent still says the PII out loud unless it is cut off or
      instructed not to.

    Both live in one hook because a tripped turn must also drop the held caption: a hook that returns a list ends
    the chain for that event, so a second hook would never see the `Interrupt`.
    """

    _TEXT = "voice_output_guardrail.text"
    _CHECKED = "voice_output_guardrail.checked"
    _TRIPPED = "voice_output_guardrail.tripped"
    _MESSAGE_ID = "voice_output_guardrail.message_id"

    def __init__(self, debounce_chars: int = 40) -> None:
        blocked = os.environ.get("VOICE_GUARDRAIL_BLOCKED", "guaranteed return,guaranteed profit,insider tip")
        self._blocked = [phrase.strip().lower() for phrase in blocked.split(",") if phrase.strip()]
        self._debounce_chars = debounce_chars

    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
        return agent_reply

    async def on_stream_event(
        self, session: Session, requests: list[AgentRequest], agent: Agent, event: StreamEvent
    ) -> StreamEvent | list[StreamEvent] | None:
        cache = session.get_volatile_cache()

        if isinstance(event, MessageEnd):
            text, tripped, message_id = (
                cache.get(self._TEXT, ""),
                cache.get(self._TRIPPED, False),
                cache.get(self._MESSAGE_ID),
            )
            self._reset(cache)
            if tripped or not text:
                return event
            redacted = redact_pii(text)
            if redacted != text:
                _log.info(f"session={session.id} redacted PII in the agent's caption")
            return [TextDelta(message_id=message_id or event.message_id, content=redacted), event]

        if isinstance(event, Interrupt):
            # A barge-in ends the turn's speech; its caption is not published.
            self._reset(cache)
            return event

        if cache.get(self._TRIPPED, False):
            # The rest of a tripped turn is not spoken or captioned.
            return None if isinstance(event, (AudioDelta, TextDelta)) else event

        if not isinstance(event, TextDelta):
            return event

        text = cache.get(self._TEXT, "") + event.content
        cache.set(self._TEXT, text)
        cache.set(self._MESSAGE_ID, cache.get(self._MESSAGE_ID) or event.message_id)
        if len(text) - cache.get(self._CHECKED, 0) >= self._debounce_chars:
            cache.set(self._CHECKED, len(text))
            hit = next((phrase for phrase in self._blocked if phrase in text.lower()), None)
            if hit is not None:
                cache.set(self._TRIPPED, True)
                _log.warning(f"session={session.id} output guardrail tripped on '{hit}': cutting the agent off")
                return [Interrupt()]
        return None  # held until message_end

    def _reset(self, cache) -> None:
        for key in (self._TEXT, self._CHECKED, self._TRIPPED, self._MESSAGE_ID):
            cache.delete(key)

    def name(self) -> str:
        return "VoiceOutputGuardrail"
