"""
Regression guards for the streaming contract in `Runtime.stream` (spec #523 §4).

Two of these guard failures that produce no other symptom. Nothing else in the suite references
`PostHook.on_stream_chunk`, so a loop that bypasses the hook chain stays green everywhere else; and
reasoning leaking into `delta` corrupts what plain-text consumers render and what the thread
recorder persists, without raising.
"""

import pytest

from agentkernel import Agent, Runner, Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.events import MessageEnd, MessageStart, ReasoningDelta, StepStart, TextDelta, ToolCallArgs, ToolCallStart
from agentkernel.core.hooks import PostHook
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
    """Yields a fixed script, so a test can hand the runtime events, bare strings, or both."""

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
    """Records every delta it is handed, and optionally rewrites or drops it."""

    def __init__(self, transform=None):
        self.seen = []
        self._transform = transform

    def name(self):
        return "recording-hook"

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_chunk(self, session, requests, agent, delta):
        self.seen.append(delta)
        return delta if self._transform is None else self._transform(delta)


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


@pytest.mark.asyncio
async def test_text_delta_populates_both_delta_and_event():
    chunks = await _collect([TextDelta(message_id="m1", content="hello")])

    assert chunks[0].delta == "hello"
    assert chunks[0].event == TextDelta(message_id="m1", content="hello")
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_hook_rewrite_is_written_back_into_the_event():
    # §4 rule 1: without the write-back, `delta` carries redacted text while `event` — the field a
    # protocol surface serialises — still carries the original.
    hook = RecordingHook(transform=lambda d: d.replace("secret", "[redacted]"))

    chunks = await _collect([TextDelta(message_id="m1", content="the secret")], hooks=[hook])

    assert hook.seen == ["the secret"]
    assert chunks[0].delta == "the [redacted]"
    assert chunks[0].event.content == "the [redacted]"


@pytest.mark.asyncio
async def test_hook_returning_none_drops_the_whole_chunk():
    # §4 rule 2: the event goes with the text, rather than a chunk with a null delta surviving.
    hook = RecordingHook(transform=lambda d: None if d == "drop" else d)

    chunks = await _collect(
        [TextDelta(message_id="m1", content="keep"), TextDelta(message_id="m1", content="drop")],
        hooks=[hook],
    )

    assert hook.seen == ["keep", "drop"]
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == ["keep"]
    assert _events(chunks) == [TextDelta(message_id="m1", content="keep")]


@pytest.mark.asyncio
async def test_non_text_events_skip_the_hook_chain():
    # §4 rule 3: a text-redaction hook must never be handed a JSON fragment or a tool name.
    hook = RecordingHook()
    script = [
        ToolCallStart(tool_call_id="t1", name="lookup"),
        ToolCallArgs(tool_call_id="t1", delta='{"q": "ak"}'),
        StepStart(name="node-a"),
    ]

    chunks = await _collect(script, hooks=[hook])

    assert hook.seen == []
    assert _events(chunks) == script
    assert all(chunk.delta is None for chunk in chunks)


@pytest.mark.asyncio
async def test_reasoning_reaches_hooks_but_never_reaches_delta():
    # §4 rule 5: a redaction hook must see reasoning, while a consumer concatenating `delta` must
    # not — REST SSE clients render it as the answer and ThreadRecorder persists it.
    hook = RecordingHook(transform=lambda d: d.upper())
    script = [
        ReasoningDelta(message_id="m1", content="thinking"),
        TextDelta(message_id="m1", content="answer"),
    ]

    chunks = await _collect(script, hooks=[hook])

    assert hook.seen == ["thinking", "answer"]
    reasoning, text = _events(chunks)[0], _events(chunks)[1]
    assert reasoning.content == "THINKING"  # the hook still edited it
    assert [chunk.delta for chunk in chunks if chunk.event is not None] == [None, "ANSWER"]


@pytest.mark.asyncio
async def test_str_yielding_runner_is_normalised_into_one_synthetic_message():
    # TRANSITIONAL (§4 rule 4). Delete with the branch in PR 6.
    chunks = await _collect(["Hel", "lo"])

    events = _events(chunks)
    assert [type(event) for event in events] == [MessageStart, TextDelta, TextDelta, MessageEnd]
    assert len({event.message_id for event in events}) == 1
    assert [chunk.delta for chunk in chunks if isinstance(chunk.event, TextDelta)] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_str_yielding_runner_tokens_pass_through_the_hook_chain():
    # TRANSITIONAL (§4 rule 4), and the reason the branch normalises rather than short-circuits: an
    # earlier draft yielded the str directly, silently disabling every on_stream_chunk hook until PR 6.
    hook = RecordingHook(transform=lambda d: None if d == "b" else d.upper())

    chunks = await _collect(["a", "b", "c"])
    assert [chunk.delta for chunk in chunks if isinstance(chunk.event, TextDelta)] == ["a", "b", "c"]

    chunks = await _collect(["a", "b", "c"], hooks=[hook])

    assert hook.seen == ["a", "b", "c"]
    assert [chunk.delta for chunk in chunks if isinstance(chunk.event, TextDelta)] == ["A", "C"]
    assert [event.content for event in _events(chunks) if isinstance(event, TextDelta)] == ["A", "C"]


@pytest.mark.asyncio
async def test_fully_redacted_str_stream_emits_neither_boundary():
    # TRANSITIONAL (§4 rule 4): allocating the message id and committing MessageStart are separate
    # steps. Emitting the boundary on the first str gives an AG-UI client an empty assistant bubble.
    hook = RecordingHook(transform=lambda d: None)

    chunks = await _collect(["a", "b"], hooks=[hook])

    assert _events(chunks) == []
    assert [chunk.done for chunk in chunks] == [True]


@pytest.mark.asyncio
async def test_event_yielding_runner_gets_no_synthetic_boundaries():
    # The transitional branch must stay inert for a migrated adapter: its own MessageStart/MessageEnd
    # are the only boundaries, so PR 4-6 adapters are not double-wrapped.
    script = [
        MessageStart(message_id="m1"),
        TextDelta(message_id="m1", content="hi"),
        MessageEnd(message_id="m1"),
    ]

    chunks = await _collect(script)

    assert _events(chunks) == script
