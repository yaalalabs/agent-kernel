"""
Regression guards for the streaming contract in `Runtime.stream` (specs #523 §4 and #670).

Several of these guard failures that produce no other symptom. Nothing else in the suite references
`PostHook.on_stream_event`, so a loop that bypasses the hook chain stays green everywhere else;
reasoning leaking into `delta` corrupts what plain-text consumers render and what the thread recorder
persists, without raising; and a hook returning a list is expected to end the chain, which no other
surface would reveal.
"""

import pytest
from pydantic import ValidationError

from agentkernel import Agent, Runner, Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    StepEnd,
    StepStart,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from agentkernel.core.hooks import PostHook, StreamHalt
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime


@pytest.fixture(autouse=True)
def isolate_system_hooks(monkeypatch):
    # The system hook chains are built from config at first use; pin them empty so these tests
    # exercise only the agent's own post-hooks, and clear them again so nothing leaks out.
    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    yield
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


class ScriptedRunner(Runner):
    """Yields a fixed script, so a test can hand the runtime AK events — or bare strings, to prove
    the runtime rejects them."""

    def __init__(self, script):
        super().__init__("ScriptedRunner")
        self._script = script

    async def run(self, agent, session, requests):
        return AgentReplyText(response="unused")

    async def stream(self, agent, session, requests):
        for item in self._script:
            yield item


class ScriptedAgent(Agent):

    def __init__(self, script, name="agent"):
        super().__init__(name, ScriptedRunner(script))

    def get_a2a_card(self):
        return None

    def get_description(self):
        return "scripted agent"

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class RecordingHook(PostHook):
    """Records every event it is handed, and optionally rewrites, replaces or drops it."""

    def __init__(self, transform=None, name="recording-hook"):
        self.seen = []
        self._transform = transform
        self._name = name

    def name(self):
        return self._name

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        self.seen.append(event)
        return event if self._transform is None else self._transform(event)


def _upper(event):
    return event.model_copy(update={"content": event.content.upper()})


async def _collect(script, hooks=(), session_id="s1"):
    runtime = Runtime(SessionStoreBuilder.build())
    agent = ScriptedAgent(script)
    for hook in hooks:
        agent.post_hooks.append(hook)
    runtime.register(agent)
    session = runtime.sessions().new(session_id)

    return [chunk async for chunk in runtime.stream(agent, session, [AgentRequestText(prompt="hi")])]


def _events(chunks):
    return [chunk.event for chunk in chunks if chunk.event is not None]


async def _collect_with_stores(script, hooks=(), session_id="s1"):
    """Like `_collect`, but also reports which sessions the runtime asked the store to persist."""
    runtime = Runtime(SessionStoreBuilder.build())
    agent = ScriptedAgent(script)
    for hook in hooks:
        agent.post_hooks.append(hook)
    runtime.register(agent)
    session = runtime.sessions().new(session_id)

    # Recorded only after `new()`, which stores the session itself (core/session/in_memory.py:104),
    # so `stored` reflects the run's own persistence and nothing else.
    stored = []
    runtime.sessions().store = stored.append

    chunks = [chunk async for chunk in runtime.stream(agent, session, [AgentRequestText(prompt="hi")])]
    return chunks, stored


class HaltingHook(PostHook):
    """Raises StreamHalt once it has seen `after` events."""

    def __init__(self, after=1, reason="withheld"):
        self.after = after
        self.reason = reason
        self.count = 0

    def name(self):
        return "halting-hook"

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        self.count += 1
        if self.count > self.after:
            raise StreamHalt(self.reason)
        return event


@pytest.mark.asyncio
async def test_text_delta_populates_both_delta_and_event():
    chunks = await _collect([TextDelta(message_id="m1", content="hello")])

    assert chunks[0].delta == "hello"
    assert chunks[0].event == TextDelta(message_id="m1", content="hello")
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_hook_rewrite_reaches_both_delta_and_event():
    # §4 rule 1, now structural: a hook rewriting text returns the rewritten event, and `delta` is
    # taken from whatever is finally emitted, so the field a protocol surface serialises and the field
    # a plain-text consumer reads cannot disagree.
    hook = RecordingHook(transform=lambda e: e.model_copy(update={"content": e.content.replace("secret", "[redacted]")}))

    chunks = await _collect([TextDelta(message_id="m1", content="the secret")], hooks=[hook])

    assert [event.content for event in hook.seen] == ["the secret"]
    assert chunks[0].delta == "the [redacted]"
    assert chunks[0].event.content == "the [redacted]"


@pytest.mark.asyncio
async def test_hook_returning_none_drops_the_whole_chunk():
    # §4 rule 2: the event goes with the text, rather than a chunk with a null delta surviving.
    hook = RecordingHook(transform=lambda e: None if e.content == "drop" else e)

    chunks = await _collect(
        [TextDelta(message_id="m1", content="keep"), TextDelta(message_id="m1", content="drop")],
        hooks=[hook],
    )

    assert [event.content for event in hook.seen] == ["keep", "drop"]
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == ["keep"]
    assert _events(chunks) == [TextDelta(message_id="m1", content="keep")]


@pytest.mark.asyncio
async def test_every_event_reaches_the_hook_chain():
    # #670: tool calls and step boundaries used to bypass the chain entirely, so no hook could
    # inspect a tool's arguments or its result before they reached the client. Reverses the
    # assertion this test made under the #523 contract.
    hook = RecordingHook()
    script = [
        ToolCallStart(tool_call_id="t1", name="lookup"),
        ToolCallArgs(tool_call_id="t1", delta='{"q": "ak"}'),
        StepStart(name="node-a"),
    ]

    chunks = await _collect(script, hooks=[hook])

    assert hook.seen == script
    assert _events(chunks) == script
    assert all(chunk.delta is None for chunk in chunks)


@pytest.mark.asyncio
async def test_reasoning_reaches_hooks_but_never_reaches_delta():
    # §4 rule 5: a redaction hook must see reasoning, while a consumer concatenating `delta` must
    # not — REST SSE clients render it as the answer and ThreadRecorder persists it.
    hook = RecordingHook(transform=_upper)
    script = [
        ReasoningDelta(message_id="m1", content="thinking"),
        TextDelta(message_id="m1", content="answer"),
    ]

    chunks = await _collect(script, hooks=[hook])

    assert [event.content for event in hook.seen] == ["thinking", "answer"]
    reasoning, text = _events(chunks)[0], _events(chunks)[1]
    assert reasoning.content == "THINKING"  # the hook still edited it
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == [None, "ANSWER"]


@pytest.mark.asyncio
async def test_a_str_yielding_runner_now_fails_loudly():
    """The transition is over: PR 1's normalisation branch is gone, so an unmigrated adapter is a
    hard error rather than being quietly patched up.

    Asserting the `ValidationError` specifically, not merely an absence of output (§4 rule 6): the
    branch used to synthesise boundaries around bare strings, and its removal has to surface as a
    failure a developer cannot miss. `StreamChunk.event` is a discriminated union of the AK events,
    so a `str` cannot satisfy it.
    """
    with pytest.raises(ValidationError):
        await _collect(["Hel", "lo"])


@pytest.mark.asyncio
async def test_event_yielding_runner_gets_no_synthetic_boundaries():
    # A migrated adapter owns its boundaries end to end: its own MessageStart/MessageEnd
    # are the only boundaries, so PR 4-6 adapters are not double-wrapped.
    script = [
        MessageStart(message_id="m1"),
        TextDelta(message_id="m1", content="hi"),
        MessageEnd(message_id="m1"),
    ]

    chunks = await _collect(script)

    assert _events(chunks) == script


@pytest.mark.asyncio
async def test_a_list_return_emits_every_event_in_order():
    # The many-out return is the release half of hold-and-release: without it a hook that holds
    # fragments has no way to emit the assembled whole plus the boundary that closes it.
    released = [TextDelta(message_id="m1", content="assembled"), MessageEnd(message_id="m1")]
    hook = RecordingHook(transform=lambda e: released if e.type == "message_end" else e)

    chunks = await _collect([MessageStart(message_id="m1"), MessageEnd(message_id="m1")], hooks=[hook])

    assert _events(chunks) == [MessageStart(message_id="m1"), *released]
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == [None, "assembled", None]


@pytest.mark.asyncio
async def test_a_list_return_ends_the_chain():
    # `return event` and `return [event]` are deliberately not equivalent, and nothing else in the
    # suite would reveal it: a list is emitted as-is and the hooks after it never see those events.
    first = RecordingHook(transform=lambda e: [e], name="first")
    second = RecordingHook(name="second")

    await _collect([TextDelta(message_id="m1", content="hi")], hooks=[first, second])

    assert [event.type for event in first.seen] == ["text_delta"]
    assert second.seen == []


@pytest.mark.asyncio
async def test_single_event_returns_compose_along_the_chain():
    # A single return is carried into the next hook, so the second hook sees the first's rewrite.
    first = RecordingHook(transform=lambda e: e.model_copy(update={"content": e.content + "-one"}), name="first")
    second = RecordingHook(transform=lambda e: e.model_copy(update={"content": e.content + "-two"}), name="second")

    chunks = await _collect([TextDelta(message_id="m1", content="base")], hooks=[first, second])

    assert [event.content for event in second.seen] == ["base-one"]
    assert chunks[0].event.content == "base-one-two"
    assert chunks[0].delta == "base-one-two"


@pytest.mark.asyncio
async def test_changing_the_event_type_on_a_single_return_raises():
    # Accident detection on the rewrite path: a single return means "this event, rewritten", so a
    # changed type is almost certainly a mistake. Pydantic cannot catch it — a MessageEnd is a
    # perfectly valid StreamEvent — and a deliberate type change uses the list form instead.
    hook = RecordingHook(transform=lambda e: MessageEnd(message_id="m1"))

    with pytest.raises(TypeError, match="recording-hook"):
        await _collect([TextDelta(message_id="m1", content="hi")], hooks=[hook])


@pytest.mark.asyncio
async def test_halt_closes_open_boundaries_then_yields_one_error_chunk():
    script = [
        MessageStart(message_id="m1"),
        ToolCallStart(tool_call_id="t1", name="lookup"),
        TextDelta(message_id="m1", content="never sent"),
    ]
    hook = HaltingHook(after=2, reason="withheld: secret")

    chunks = await _collect(script, hooks=[hook])

    # Innermost first: the tool call opened inside the message is closed before the message.
    assert _events(chunks) == [
        MessageStart(message_id="m1"),
        ToolCallStart(tool_call_id="t1", name="lookup"),
        ToolCallEnd(tool_call_id="t1"),
        MessageEnd(message_id="m1"),
    ]
    assert chunks[-1].error == "withheld: secret"
    assert chunks[-1].done is True
    assert not any(chunk.done and chunk.error is None for chunk in chunks)


@pytest.mark.asyncio
async def test_a_halted_run_stores_no_session():
    # A halted turn must leave no trace in conversation state, matching the pre-hook halt.
    chunks, stored = await _collect_with_stores([MessageStart(message_id="m1")], hooks=[HaltingHook(after=0)])

    assert stored == []
    assert chunks[-1].error == "withheld"

    chunks, stored = await _collect_with_stores([MessageStart(message_id="m1"), MessageEnd(message_id="m1")])

    assert len(stored) == 1
    assert chunks[-1].done is True and chunks[-1].error is None


@pytest.mark.asyncio
async def test_halt_with_nothing_open_emits_only_the_error_chunk():
    chunks = await _collect([StepStart(name="node-a")], hooks=[HaltingHook(after=0)])

    assert _events(chunks) == []
    assert len(chunks) == 1
    assert chunks[0].error == "withheld"
    assert chunks[0].done is True


@pytest.mark.asyncio
async def test_a_non_halt_exception_propagates_unchanged():
    # Deliberate asymmetry: StreamHalt is a teardown a hook asked for, any other exception is a
    # defect, and dressing it up as a clean end-of-stream would hide it.
    class ExplodingHook(RecordingHook):
        async def on_stream_event(self, session, requests, agent, event):
            raise RuntimeError("hook is broken")

    with pytest.raises(RuntimeError, match="hook is broken"):
        await _collect([TextDelta(message_id="m1", content="hi")], hooks=[ExplodingHook()])


@pytest.mark.asyncio
async def test_with_no_hooks_every_event_type_passes_through_unchanged():
    # The "no subscriber, no behaviour change" guarantee, over the whole StreamEvent union.
    script = [
        MessageStart(message_id="m1"),
        TextDelta(message_id="m1", content="hi"),
        MessageEnd(message_id="m1"),
        ReasoningStart(message_id="r1"),
        ReasoningDelta(message_id="r1", content="thinking"),
        ReasoningEnd(message_id="r1"),
        ToolCallStart(tool_call_id="t1", name="lookup"),
        ToolCallArgs(tool_call_id="t1", delta='{"q": "ak"}'),
        ToolCallEnd(tool_call_id="t1"),
        ToolCallResult(tool_call_id="t1", content="42"),
        StepStart(name="node-a"),
        StepEnd(name="node-a"),
    ]

    chunks = await _collect(script)

    assert _events(chunks) == script
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == [None, "hi"] + [None] * 10
    assert chunks[-1].done is True
