"""Translate an Agent Kernel `StreamEvent` into its AG-UI equivalent."""

import logging
from typing import TYPE_CHECKING, Literal, Optional, cast
from uuid import uuid4

from ...core.event import StreamEvent

if TYPE_CHECKING:
    from ag_ui.core import BaseEvent

_log = logging.getLogger("ak.integration.agui.mapping")

_AGUIMessageRole = Literal["developer", "system", "assistant", "user"]
_AGUI_MESSAGE_ROLES = frozenset({"developer", "system", "assistant", "user"})


class AGUIMapper:
    """Map one AK stream event to an AG-UI event, or None if there is no equivalent."""

    @staticmethod
    def to_agui(event: StreamEvent) -> Optional["BaseEvent"]:
        """Return the AG-UI event for `event`, or None when AG-UI has no equivalent."""
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
                return TextMessageStartEvent(message_id=event.message_id, role=AGUIMapper._message_role(event.role))
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

    @staticmethod
    def _message_role(role: str) -> _AGUIMessageRole:
        """Return `role` if AG-UI knows it, otherwise `assistant`."""
        if role in _AGUI_MESSAGE_ROLES:
            return cast(_AGUIMessageRole, role)
        _log.debug(f"Message role '{role}' is not an AG-UI role; emitting as 'assistant'")
        return "assistant"
