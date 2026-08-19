import json
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StepEnd,
    StepStart,
    StreamEvent,
    StreamEventBase,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)


class _Envelope(BaseModel):
    """Parses a serialised event back through the discriminated union, as StreamChunk does."""

    event: StreamEvent


ALL_EVENTS = [
    MessageStart(message_id="m1"),
    TextDelta(message_id="m1", content="hello"),
    MessageEnd(message_id="m1"),
    ToolCallStart(tool_call_id="t1", name="lookup"),
    ToolCallArgs(tool_call_id="t1", delta='{"q": "ak'),
    ToolCallEnd(tool_call_id="t1"),
    ToolCallResult(tool_call_id="t1", content="42"),
    StepStart(name="node-a"),
    StepEnd(name="node-a"),
    ReasoningStart(message_id="m1"),
    ReasoningDelta(message_id="m1", content="thinking"),
    ReasoningEnd(message_id="m1"),
]


def test_every_union_member_is_covered_by_the_event_list():
    # Guards the round-trip test below: a new event class with no sample silently skips it.
    union, _field_info = get_args(StreamEvent.__value__)
    declared = set(get_args(union))
    assert {type(ev) for ev in ALL_EVENTS} == declared


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda ev: ev.type)
def test_event_round_trips_through_the_discriminated_union(event):
    payload = _Envelope(event=event).model_dump()
    parsed = _Envelope.model_validate(payload).event

    assert type(parsed) is type(event)
    assert parsed == event


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda ev: ev.type)
def test_event_is_json_serialisable(event):
    # No field may carry a framework-native object: a StreamChunk crosses the queue transport. The
    # scalar set matches spec §1 rule 4 rather than being narrower than it, so an int or bool field
    # added by a later adapter PR is accepted here instead of failing a spec-legal change.
    dumped = event.model_dump()
    assert json.loads(json.dumps(dumped)) == dumped
    assert all(isinstance(value, (str, int, bool)) for value in dumped.values())


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda ev: ev.type)
def test_event_declares_a_distinct_type_discriminator(event):
    assert isinstance(event, StreamEventBase)
    assert event.type == type(event).model_fields["type"].default


def test_type_discriminators_are_unique():
    types = [ev.type for ev in ALL_EVENTS]
    assert len(set(types)) == len(types)


def test_union_rejects_an_unknown_type():
    with pytest.raises(ValidationError):
        _Envelope.model_validate({"event": {"type": "no_such_event", "message_id": "m1"}})


def test_union_rejects_a_bare_string():
    # The mechanism that makes a runner yielding bare strings fail loudly at the StreamChunk
    # boundary, naming the offending field, rather than degrading into a silently empty stream.
    with pytest.raises(ValidationError):
        _Envelope.model_validate({"event": "hello"})
