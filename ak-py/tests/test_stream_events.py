import json
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from agentkernel.core.event import (
    AudioDelta,
    Interrupt,
    MessageEnd,
    MessageStart,
    PausedInterruption,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    RunPaused,
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
    AudioDelta(message_id="m1", content="YmFzZTY0Cg=="),
    Interrupt(),
    RunPaused(run_id="run-1", agent="refunds", interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")]),
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


def _leaves(value):
    """Yields every scalar inside a dumped event, descending through lists and dicts."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


@pytest.mark.parametrize("event", ALL_EVENTS, ids=lambda ev: ev.type)
def test_event_is_json_serialisable(event):
    """No field may carry a framework-native object: a StreamChunk crosses the queue transport.

    Descends rather than checking top-level values only, because RunPaused.interruptions is a list
    of models — the invariant is that every leaf is a JSON primitive, not that every field is.
    """
    dumped = event.model_dump()
    assert json.loads(json.dumps(dumped)) == dumped
    assert all(leaf is None or isinstance(leaf, (str, int, bool)) for leaf in _leaves(dumped))


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
