"""
Stream event model for Agent Kernel's streaming contract.

`Runner.stream` yields members of the `StreamEvent` union rather than bare token strings, so a
consumer can tell prose from reasoning from a tool call, and can pair a start with its end. The
names are Agent Kernel's own, modelled on what the agent frameworks emit rather than on any wire
protocol, so a protocol rename does not ripple into every client; protocol adapters own the
mapping.

Two invariants hold across every member:

- **`type` is the discriminator.** Every class declares a distinct `Literal`, matching the
  request/reply models in `model.py`. The union is discriminated on it so a serialised event
  parses back to the class it came from — `StreamChunk` crosses the queue transport in
  distributed deployment topologies.
- **No field carries a framework-native object.** Every field is a `str`, so an event stays
  picklable and JSON-serialisable no matter which framework produced it.

`message_id` and `tool_call_id` correlate a start with its deltas and its end within a single run.
Adapters take them from the framework's own stream where one is available and generate
`uuid4().hex` otherwise. They are run-scoped and never persisted.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class StreamEventBase(BaseModel):
    """Common base for every stream event. `type` is the union discriminator."""

    type: str


class MessageStart(StreamEventBase):
    """Opens an assistant message. Paired with a `MessageEnd` carrying the same `message_id`."""

    type: Literal["message_start"] = "message_start"
    message_id: str
    role: str = "assistant"


class TextDelta(StreamEventBase):
    """A fragment of assistant prose. The only event projected into `StreamChunk.delta`."""

    type: Literal["text_delta"] = "text_delta"
    message_id: str
    content: str


class MessageEnd(StreamEventBase):
    """Closes the assistant message opened by `MessageStart`."""

    type: Literal["message_end"] = "message_end"
    message_id: str


class ToolCallStart(StreamEventBase):
    """Announces a tool invocation. Paired with `ToolCallEnd` on the same `tool_call_id`."""

    type: Literal["tool_call_start"] = "tool_call_start"
    tool_call_id: str
    name: str


class ToolCallArgs(StreamEventBase):
    """A fragment of a tool call's arguments."""

    type: Literal["tool_call_args"] = "tool_call_args"
    tool_call_id: str
    delta: str  # raw JSON fragment, as frameworks emit it — not necessarily valid JSON on its own


class ToolCallEnd(StreamEventBase):
    """Closes the tool call opened by `ToolCallStart`; its arguments are complete."""

    type: Literal["tool_call_end"] = "tool_call_end"
    tool_call_id: str


class ToolCallResult(StreamEventBase):
    """The value a tool returned, correlated to its call by `tool_call_id`."""

    type: Literal["tool_call_result"] = "tool_call_result"
    tool_call_id: str
    content: str


class StepStart(StreamEventBase):
    """Opens a named unit of agent work, such as a graph node or a reasoning step."""

    type: Literal["step_start"] = "step_start"
    name: str


class StepEnd(StreamEventBase):
    """Closes the step opened by `StepStart`."""

    type: Literal["step_end"] = "step_end"
    name: str


class ReasoningStart(StreamEventBase):
    """Opens a reasoning trace. Paired with `ReasoningEnd` on the same `message_id`."""

    type: Literal["reasoning_start"] = "reasoning_start"
    message_id: str


class ReasoningDelta(StreamEventBase):
    """
    A fragment of reasoning text.

    Passes through the post-hook chain so a redaction hook can inspect it, but is deliberately
    **not** projected into `StreamChunk.delta` — consumers that concatenate `delta` render or
    persist it as the answer. Enriched clients read reasoning from `StreamChunk.event`.
    """

    type: Literal["reasoning_delta"] = "reasoning_delta"
    message_id: str
    content: str


class ReasoningEnd(StreamEventBase):
    """Closes the reasoning trace opened by `ReasoningStart`."""

    type: Literal["reasoning_end"] = "reasoning_end"
    message_id: str


type StreamEvent = Annotated[
    Union[
        MessageStart,
        TextDelta,
        MessageEnd,
        ToolCallStart,
        ToolCallArgs,
        ToolCallEnd,
        ToolCallResult,
        StepStart,
        StepEnd,
        ReasoningStart,
        ReasoningDelta,
        ReasoningEnd,
    ],
    Field(discriminator="type"),
]
