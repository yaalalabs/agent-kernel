"""
Tests for the outbound event mapping (spec #523 §9, `integration/agui/mapping.py`).

The exhaustiveness test is the load-bearing one. `to_agui` returns `None` for an AK event AG-UI has
no equivalent for, and the handler skips `None` — so an event type added by a later adapter PR with
no branch here would disappear from every AG-UI client with nothing failing anywhere. Enumerating the
union and demanding an explicit decision per member is what makes that impossible.
"""

from typing import get_args

import pytest
from ag_ui.core import (
    EventType,
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

from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StepEnd,
    StepStart,
    StreamEvent,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from agentkernel.integration.agui.mapping import _AGUI_MESSAGE_ROLES, to_agui

# Every member of the StreamEvent union, with the AG-UI class it must produce. A member that AG-UI
# genuinely has no equivalent for belongs in DELIBERATELY_UNMAPPED instead — it is empty today
# because all twelve map, and a new member must be added to one list or the other.
EXPECTED_MAPPING = [
    (MessageStart(message_id="m1"), TextMessageStartEvent),
    (TextDelta(message_id="m1", content="hello"), TextMessageContentEvent),
    (MessageEnd(message_id="m1"), TextMessageEndEvent),
    (ToolCallStart(tool_call_id="t1", name="lookup"), ToolCallStartEvent),
    (ToolCallArgs(tool_call_id="t1", delta='{"q":'), ToolCallArgsEvent),
    (ToolCallEnd(tool_call_id="t1"), ToolCallEndEvent),
    (ToolCallResult(tool_call_id="t1", content="42"), ToolCallResultEvent),
    (StepStart(name="node-a"), StepStartedEvent),
    (StepEnd(name="node-a"), StepFinishedEvent),
    (ReasoningStart(message_id="r1"), ReasoningMessageStartEvent),
    (ReasoningDelta(message_id="r1", content="thinking"), ReasoningMessageContentEvent),
    (ReasoningEnd(message_id="r1"), ReasoningMessageEndEvent),
]

DELIBERATELY_UNMAPPED: list[type] = []


def test_every_union_member_has_an_explicit_decision():
    """A new AK event type must be mapped or explicitly declared unmappable — it cannot be
    forgotten, because forgetting it is silent everywhere else."""
    union, _field_info = get_args(StreamEvent.__value__)
    declared = set(get_args(union))
    decided = {type(event) for event, _ in EXPECTED_MAPPING} | set(DELIBERATELY_UNMAPPED)

    assert declared == decided, f"stream events with no to_agui decision: {declared - decided}"


@pytest.mark.parametrize("event,expected", EXPECTED_MAPPING, ids=lambda arg: getattr(arg, "type", ""))
def test_event_maps_to_its_agui_class(event, expected):
    assert isinstance(to_agui(event), expected)


def test_deliberately_unmapped_events_return_none():
    # Vacuous while the list is empty; it is the assertion that the list is honest once it is not.
    for unmapped in DELIBERATELY_UNMAPPED:
        assert to_agui(unmapped.model_construct()) is None


def test_an_unknown_event_type_returns_none_rather_than_raising():
    """The `case _` fallthrough. A forward-compatibility guard, not a live path: the exhaustiveness
    test above is what keeps a real AK event from reaching it."""

    class _Future(MessageStart):
        type: str = "future_event"

    assert to_agui(_Future(message_id="m1")) is None


class TestFieldsCarryThrough:
    """The renames are where a mapping breaks silently — a wrong field name still produces a
    well-formed event, just an empty one."""

    def test_text_message_start_carries_id_and_role(self):
        event = to_agui(MessageStart(message_id="m1"))
        assert event.message_id == "m1"
        assert event.role == "assistant"
        assert event.type == EventType.TEXT_MESSAGE_START

    def test_text_delta_content_becomes_delta(self):
        event = to_agui(TextDelta(message_id="m1", content="hello"))
        assert (event.message_id, event.delta) == ("m1", "hello")

    def test_tool_call_start_name_becomes_tool_call_name(self):
        event = to_agui(ToolCallStart(tool_call_id="t1", name="lookup"))
        assert (event.tool_call_id, event.tool_call_name) == ("t1", "lookup")

    def test_tool_call_args_delta_carries_the_raw_json_fragment(self):
        event = to_agui(ToolCallArgs(tool_call_id="t1", delta='{"q": "ak'))
        assert event.delta == '{"q": "ak'

    def test_step_name_becomes_step_name(self):
        assert to_agui(StepStart(name="node-a")).step_name == "node-a"
        assert to_agui(StepEnd(name="node-a")).step_name == "node-a"

    def test_reasoning_maps_to_the_reasoning_message_family(self):
        """Not the THINKING_* events: those are the pre-0.1.13 spelling and carry no message id,
        so AK's correlated reasoning events could not round-trip through them."""
        start = to_agui(ReasoningStart(message_id="r1"))
        assert (start.message_id, start.role) == ("r1", "reasoning")
        assert to_agui(ReasoningDelta(message_id="r1", content="hmm")).delta == "hmm"
        assert to_agui(ReasoningEnd(message_id="r1")).message_id == "r1"


class TestToolCallResultMessageId:
    """AG-UI requires a message_id on a tool result and AK's event carries none, so the mapping
    generates one. Guarded because returning None instead would drop every tool result silently."""

    def test_result_is_fully_populated(self):
        event = to_agui(ToolCallResult(tool_call_id="t1", content="42"))
        assert (event.tool_call_id, event.content, event.role) == ("t1", "42", "tool")
        assert event.message_id

    def test_each_result_is_its_own_message(self):
        first = to_agui(ToolCallResult(tool_call_id="t1", content="42"))
        second = to_agui(ToolCallResult(tool_call_id="t2", content="43"))
        assert first.message_id != second.message_id


class TestRoleDegradation:
    """MessageStart.role is a plain str in AK so core/ owes nothing to AG-UI's vocabulary, but
    AG-UI's field is a four-value literal. An adapter's odd role must not fail the whole run."""

    @pytest.mark.parametrize("role", ["assistant", "user", "system", "developer"])
    def test_an_agui_role_passes_through(self, role):
        assert to_agui(MessageStart(message_id="m1", role=role)).role == role

    def test_an_unknown_role_falls_back_to_assistant(self):
        assert to_agui(MessageStart(message_id="m1", role="bot")).role == "assistant"

    def test_the_role_set_mirrors_the_sdk(self):
        """`_AGUI_MESSAGE_ROLES` hand-copies `TextMessageRole` so `ag_ui` stays a type-only import in
        `mapping.py`. If the SDK adds a role, the frozenset silently degrades it to `assistant`
        instead of passing it through, and the two tests above would still pass."""
        from ag_ui.core.events import TextMessageRole

        assert _AGUI_MESSAGE_ROLES == set(get_args(TextMessageRole))


def test_every_mapped_event_serialises_through_the_sdk_encoder():
    """The handler never hand-rolls the wire format; anything to_agui returns must survive the
    encoder's `by_alias=True, exclude_none=True` dump."""
    from ag_ui.encoder import EventEncoder

    encoder = EventEncoder()
    for event, _ in EXPECTED_MAPPING:
        frame = encoder.encode(to_agui(event))
        assert frame.startswith("data: ") and frame.endswith("\n\n")
