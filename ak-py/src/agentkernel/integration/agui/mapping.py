"""
Outbound mapping: an Agent Kernel `StreamEvent` onto its AG-UI equivalent.

A pure function with a branch per AK discriminator, not a lookup table: several branches rename a
field or fill one AK does not carry, which a type-to-type dict would fight. It returns `None` for an
AK event AG-UI has no equivalent for, and the handler skips those — that is what "never emit an event
type we cannot fully populate" means in code.

**The `None` branch is only safe because of the exhaustiveness test.** `tests/test_agui_mapping.py`
enumerates every member of the `StreamEvent` union and asserts each has an explicit decision, so an
event type added by a later adapter PR cannot silently vanish from AG-UI. The test is what prevents
it, not the shape of this module.

Three mapping decisions are worth stating, because none of them is mechanical:

- **Reasoning maps to the `REASONING_MESSAGE_*` events, not `THINKING_*`.** The thinking family is
  the pre-0.1.13 spelling and carries no message id; the reasoning family carries one, which is a
  1:1 fit for AK's reasoning events. AK has no concept matching the phase-level `ReasoningStart` /
  `ReasoningEnd` that wrap the message, so neither is emitted.
- **`ToolCallResult` is given a fresh `message_id`.** AG-UI requires one — the result becomes a tool
  message in the client's list — and AK's event does not carry one, because no framework supplies it.
  A generated id is correct rather than a stand-in: each result genuinely is a new message. The
  first-party Pydantic AI adapter does exactly this (`pydantic_ai/ui/ag_ui/_event_stream.py:290`).
- **An unrecognised role degrades instead of failing.** `MessageStart.role` is a plain `str` in AK so
  that `core/` owes nothing to AG-UI's vocabulary, but AG-UI's field is a four-value literal. A
  custom adapter's unexpected role would otherwise raise mid-stream and turn a working run into a
  `RunError`, so it falls back to `assistant`.
"""

import logging
from typing import TYPE_CHECKING, Literal, Optional, cast
from uuid import uuid4

from ...core.event import StreamEvent

if TYPE_CHECKING:  # ag_ui ships in the optional `agui` extra, so it is a type-only import here
    from ag_ui.core import BaseEvent

_log = logging.getLogger("ak.integration.agui.mapping")

_AGUIMessageRole = Literal["developer", "system", "assistant", "user"]
_AGUI_MESSAGE_ROLES = frozenset({"developer", "system", "assistant", "user"})


def to_agui(event: StreamEvent) -> Optional["BaseEvent"]:
    """Translate one AK stream event into its AG-UI event.

    :param event: The event carried on a `StreamChunk`.
    :return: The AG-UI event to emit, or None when AG-UI has no equivalent for this AK event.
    """
    from ag_ui.core import (
        ReasoningMessageContentEvent,
        ReasoningMessageEndEvent,
        ReasoningMessageStartEvent,
        StepFinishedEvent,
        StepStartedEvent,
        TextMessageContentEvent,
        TextMessageEndEvent,
        TextMessageStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        ToolCallResultEvent,
        ToolCallStartEvent,
    )

    match event.type:
        case "message_start":
            return TextMessageStartEvent(message_id=event.message_id, role=_message_role(event.role))
        case "text_delta":
            return TextMessageContentEvent(message_id=event.message_id, delta=event.content)
        case "message_end":
            return TextMessageEndEvent(message_id=event.message_id)
        case "tool_call_start":
            return ToolCallStartEvent(tool_call_id=event.tool_call_id, tool_call_name=event.name)
        case "tool_call_args":
            return ToolCallArgsEvent(tool_call_id=event.tool_call_id, delta=event.delta)
        case "tool_call_end":
            return ToolCallEndEvent(tool_call_id=event.tool_call_id)
        case "tool_call_result":
            return ToolCallResultEvent(message_id=uuid4().hex, tool_call_id=event.tool_call_id, content=event.content, role="tool")
        case "step_start":
            return StepStartedEvent(step_name=event.name)
        case "step_end":
            return StepFinishedEvent(step_name=event.name)
        case "reasoning_start":
            return ReasoningMessageStartEvent(message_id=event.message_id, role="reasoning")
        case "reasoning_delta":
            return ReasoningMessageContentEvent(message_id=event.message_id, delta=event.content)
        case "reasoning_end":
            return ReasoningMessageEndEvent(message_id=event.message_id)
        case _:
            _log.debug(f"No AG-UI equivalent for stream event '{event.type}'; not emitted")
            return None


def _message_role(role: str) -> _AGUIMessageRole:
    """Keep an AK message role only when AG-UI knows it, so one odd role cannot fail a run."""
    if role in _AGUI_MESSAGE_ROLES:
        return cast(_AGUIMessageRole, role)  # the membership test is the proof the literal type needs
    _log.debug(f"Message role '{role}' is not an AG-UI role; emitting as 'assistant'")
    return "assistant"
