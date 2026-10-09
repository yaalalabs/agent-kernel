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
- **No field carries a framework-native object.** Every field is composed of JSON primitives — a
  `str`, `int`, `bool`, a model built only from those, or a `JsonValue` for a field whose shape
  the framework owns — so an event stays picklable and JSON-serialisable no matter which framework
  produced it. `JsonValue` is the widest a field may go: it still rejects a framework-native
  object, which a bare `Any` would admit.

`message_id` and `tool_call_id` correlate a start with its deltas and its end within a single run.
Adapters take them from the framework's own stream where one is available and generate
`uuid4().hex` otherwise. They are run-scoped and never persisted.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, JsonValue


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


class AudioDelta(StreamEventBase):
    """A fragment of audio returned by the model."""

    type: Literal["audio_delta"] = "audio_delta"
    message_id: str
    content: str


class Interrupt(StreamEventBase):
    """The user interrupted the model's in-progress turn (barge-in)."""

    type: Literal["interrupt"] = "interrupt"


class AgentChanged(StreamEventBase):
    """
    The agent speaking in a realtime conversation changed.

    Ordered with the output it divides: what came before it was said by `previous_agent`, what
    follows by `agent`. Sent once when a realtime connection opens, with no `previous_agent` and
    with `agents`, every agent the conversation can hand off to (the starting one first), so an edge
    can show the whole team before any of it speaks; and again on every framework-native handoff.
    An edge that shows each agent separately switches speaker on it; an edge with a single voice
    line can ignore it.
    """

    type: Literal["agent_changed"] = "agent_changed"
    agent: str
    previous_agent: str | None = None
    agents: list[str] | None = None


class PausedInterruption(BaseModel):
    """
    One thing a human must decide before a paused run can continue.

    Lives here rather than in model.py because both the paused reply and the RunPaused event carry
    it, and model.py imports this module — the reverse would be circular.

    id: str : unique across every paused run the session holds, so a decision resolves to its run
        even when the caller names none. Adapters use the framework's own id
    kind: Literal["tool_call", "input_required", "confirmation"] : Agent Kernel's own vocabulary,
        named after what the frameworks produce
    tool_name: str | None : the tool awaiting approval, when there is one
    arguments: str | None : JSON-encoded call arguments
    message: str | None : what to show the human
    payload: JsonValue : the question's own shape, as the framework produced it. Any JSON value,
        not just an object, because a framework is free to pose a question as a bare list or string
    """

    id: str
    kind: Literal["tool_call", "input_required", "confirmation"]
    tool_name: str | None = None
    arguments: str | None = None
    message: str | None = None
    payload: JsonValue = None


class RunPaused(StreamEventBase):
    """
    The run stopped and needs a human before it can continue.

    Terminal for the run but not an error: Runtime.stream emits it as an ordinary chunk, drains any
    open boundary, then ends with StreamChunk(done=True) — never through StreamChunk.error. The
    opaque per-framework resume state stays in the session and never rides on the event.

    `agent` is the one field a client cannot derive: a resume must name the agent that paused, and
    a request that named none was served by the default agent, so without it a streaming client
    cannot answer its own pause. It mirrors `AgentPausedReplyAny.agent` on the non-streaming path.
    """

    type: Literal["run_paused"] = "run_paused"
    run_id: str
    agent: str
    interruptions: list[PausedInterruption]


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
        AudioDelta,
        Interrupt,
        AgentChanged,
        RunPaused,
    ],
    Field(discriminator="type"),
]
