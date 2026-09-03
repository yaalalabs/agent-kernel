"""
Unit tests for `StreamBoundaryTracker` (`core/runtime.py`, spec #670).

The halt tests in `test_runtime_stream_events.py` exercise this class end to end, but only through a
full `Runtime.stream` run. These cover it directly, including the two malformed-sequence cases the
class deliberately tolerates rather than rejects — neither of which a well-behaved runner produces,
so nothing else would catch a change in that behaviour.
"""

from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningEnd,
    ReasoningStart,
    StepEnd,
    StepStart,
    TextDelta,
    ToolCallEnd,
    ToolCallStart,
)
from agentkernel.core.runtime import StreamBoundaryTracker


def test_each_kind_opens_and_closes():
    tracker = StreamBoundaryTracker()
    opens = [
        MessageStart(message_id="m1"),
        ReasoningStart(message_id="r1"),
        ToolCallStart(tool_call_id="t1", name="lookup"),
        StepStart(name="node-a"),
    ]
    for event in opens:
        tracker.observe(event)

    assert tracker.drain() == [
        StepEnd(name="node-a"),
        ToolCallEnd(tool_call_id="t1"),
        ReasoningEnd(message_id="r1"),
        MessageEnd(message_id="m1"),
    ]

    tracker = StreamBoundaryTracker()
    for event in opens:
        tracker.observe(event)
    for event in (MessageEnd(message_id="m1"), ReasoningEnd(message_id="r1"), ToolCallEnd(tool_call_id="t1"), StepEnd(name="node-a")):
        tracker.observe(event)

    assert tracker.drain() == []


def test_drain_is_innermost_first():
    # A tool call opened inside a message must be closed before the message it sits in.
    tracker = StreamBoundaryTracker()
    tracker.observe(MessageStart(message_id="m1"))
    tracker.observe(ToolCallStart(tool_call_id="t1", name="lookup"))

    assert tracker.drain() == [ToolCallEnd(tool_call_id="t1"), MessageEnd(message_id="m1")]


def test_drain_clears_what_it_returns():
    tracker = StreamBoundaryTracker()
    tracker.observe(MessageStart(message_id="m1"))

    assert tracker.drain() == [MessageEnd(message_id="m1")]
    assert tracker.drain() == []


def test_events_that_open_nothing_are_ignored():
    tracker = StreamBoundaryTracker()
    tracker.observe(TextDelta(message_id="m1", content="hi"))

    assert tracker.drain() == []


def test_closing_an_id_never_opened_is_a_no_op():
    tracker = StreamBoundaryTracker()
    tracker.observe(MessageStart(message_id="m1"))
    tracker.observe(MessageEnd(message_id="m2"))

    assert tracker.drain() == [MessageEnd(message_id="m1")]


def test_opening_the_same_id_twice_keeps_one_close():
    tracker = StreamBoundaryTracker()
    tracker.observe(MessageStart(message_id="m1"))
    tracker.observe(MessageStart(message_id="m1"))

    assert tracker.drain() == [MessageEnd(message_id="m1")]


def test_ids_of_the_same_value_across_kinds_do_not_collide():
    # The key is (kind, id), so a message and a tool call sharing an id stay separate — LangGraph
    # uses one `run_id` for both a message and its tool call (framework/langgraph/langgraph.py).
    tracker = StreamBoundaryTracker()
    tracker.observe(MessageStart(message_id="shared"))
    tracker.observe(ToolCallStart(tool_call_id="shared", name="lookup"))

    assert tracker.drain() == [ToolCallEnd(tool_call_id="shared"), MessageEnd(message_id="shared")]
