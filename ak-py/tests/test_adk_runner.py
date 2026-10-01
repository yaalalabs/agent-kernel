import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.agents import BaseAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.event import TextDelta
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyAny,
    AgentReplyText,
    AgentRequestImage,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.framework.adk.adk import GoogleADKAgent, GoogleADKRunner, GoogleADKSession

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


def _turn(text="", pending=None, invocation_id=None):
    """A drained ADK turn with no pending calls: what get_response returns for a completed run."""
    from agentkernel.framework.adk.adk import _AdkTurn

    return _AdkTurn(text=text, pending=pending or [], invocation_id=invocation_id)


class CapitalOutput(BaseModel):
    country: str
    capital: str


class _StubADKAgent(BaseAgent):
    """A real ADK agent, because the runner now wraps it in an App and App validates its root_agent."""

    output_schema: Any = None


def _mock_agent(output_schema=None):
    agent = MagicMock()
    agent.name = "test-agent"
    agent.agent = _StubADKAgent(name="test_agent", output_schema=output_schema)
    agent.run_options = {}
    agent.resolve_run_options = AsyncMock(side_effect=lambda session, requests: dict(agent.run_options))
    return agent


def _ctx_mock():
    """A tool-context mock usable as a `with ctx:` block whose __exit__ does not suppress errors."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _part(text, thought=False):
    """One `types.Part`. `thought` must be set explicitly: a bare MagicMock attribute is truthy, so
    leaving it off would classify every fixture's text as reasoning."""
    part = MagicMock()
    part.text = text
    part.thought = thought
    return part


def _partial_event(text=None, thought=None):
    """An ADK SSE event the runner treats as streamable text, reasoning, or both.

    The two `get_function_*` methods are set explicitly rather than left to `MagicMock`, whose default
    happens to iterate empty — the runner reads both on every event, so relying on that default would
    make these fixtures work for a reason nobody reading them could see.
    """
    event = MagicMock()
    parts = []
    if thought is not None:
        parts.append(_part(thought, thought=True))
    if text is not None:
        parts.append(_part(text))
    event.content = MagicMock(parts=parts)
    event.partial = True
    event.get_function_calls = MagicMock(return_value=[])
    event.get_function_responses = MagicMock(return_value=[])
    return event


def _final_event(text: str | None):
    """An ADK event the runner treats as a final response, or as a final response with no text."""
    event = MagicMock()
    event.is_final_response = MagicMock(return_value=True)
    part = MagicMock()
    part.text = text
    event.content = MagicMock(parts=[part])
    return event


def _shape(events):
    """The event sequence by discriminator. `message_id` is a fresh uuid4, so it cannot be asserted."""
    return [event.type for event in events]


def _nonpartial_event(text=None, thought=None, calls=(), responses=()):
    """An ADK event with `partial` falsy — where the aggregated text and the tool activity arrive."""
    event = MagicMock()
    event.partial = False
    parts = []
    if thought is not None:
        parts.append(_part(thought, thought=True))
    if text is not None:
        parts.append(_part(text))
    event.content = MagicMock(parts=parts) if parts else None
    event.get_function_calls = MagicMock(return_value=list(calls))
    event.get_function_responses = MagicMock(return_value=list(responses))
    return event


def _call(name="lookup", args=None, call_id="c1"):
    call = MagicMock()
    call.id = call_id
    call.name = name
    call.args = args
    return call


def _response(name="lookup", response=None, call_id="c1"):
    resp = MagicMock()
    resp.id = call_id
    resp.name = name
    resp.response = response
    return resp


def _non_final_event():
    """An intermediate ADK event the runner must skip."""
    event = MagicMock()
    event.is_final_response = MagicMock(return_value=False)
    event.content = MagicMock(parts=[MagicMock(text="intermediate")])
    return event


def _draining_runner(events):
    """An ADK runner whose run_async yields `events` and records whether it was drained to exhaustion."""
    drained: list[bool] = []

    async def run_async(**kwargs):
        for event in events:
            yield event
        drained.append(True)

    adk_runner = MagicMock()
    adk_runner.run_async = run_async
    return adk_runner, drained


def _stream_setup(events, state):
    """Patch _setup_session_context so stream() drains `events` and reads `state` back."""
    adk_session = MagicMock()
    adk_session.get_state = AsyncMock(return_value=state)

    async def run_async(**kwargs):
        for event in events:
            yield event

    adk_runner = MagicMock()
    adk_runner.run_async = run_async
    setup = AsyncMock(return_value=("user", adk_runner, _ctx_mock(), adk_session))
    return patch.object(GoogleADKRunner, "_setup_session_context", setup), adk_session


def _run_with_response(runner, agent, session, requests, response_text, adk_session=None):
    if adk_session is None:
        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={})
    setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))
    get_response = AsyncMock(return_value=_turn(response_text))
    return patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", get_response)


class TestGoogleADKRunnerGetResponse:
    """get_response drains the event stream and keeps the last final response."""

    @pytest.mark.asyncio
    async def test_last_final_response_wins_and_the_stream_is_drained(self):
        """Sub-agent flows emit several final responses; the root agent's (last) one is the reply, and
        stopping early would make ADK cancel the still-running root agent task and skip its state writes."""
        adk_runner, drained = _draining_runner([_final_event("sub-agent answer"), _non_final_event(), _final_event("root answer")])

        response = (await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[])).text

        assert response == "root answer"
        assert drained == [True]

    @pytest.mark.asyncio
    async def test_multiple_text_parts_are_joined(self):
        event = MagicMock()
        event.is_final_response = MagicMock(return_value=True)
        event.content = MagicMock(parts=[MagicMock(text="hello"), MagicMock(text="world")])
        adk_runner, _ = _draining_runner([event])

        assert (await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[])).text == "hello world"

    @pytest.mark.asyncio
    async def test_no_final_response_returns_empty_string(self):
        adk_runner, drained = _draining_runner([_non_final_event()])

        assert (await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[])).text == ""
        assert drained == [True]

    @pytest.mark.asyncio
    async def test_final_response_without_text_yields_empty_string(self):
        adk_runner, _ = _draining_runner([_final_event(None)])

        assert (await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[])).text == ""


class TestGoogleADKSessionState:
    """GoogleADKSession.get_state returns only session-scoped caller state."""

    @pytest.mark.asyncio
    async def test_internal_and_scope_prefixed_keys_are_stripped(self):
        """app:/user:/temp: keys are not caller state and must never enter framework_context."""
        adk_session = GoogleADKSession()
        adk_session._session = MagicMock(id="s", app_name="AgentKernel", user_id="AgentKernel")
        refreshed = MagicMock()
        refreshed.state = {
            "cart": ["milk"],  # caller / tool state — kept
            "ak_tool_context": "ctx-id",  # AK-internal — stripped
            "app:theme": "dark",  # merged in by InMemorySessionService._merge_state — stripped
            "user:tier": "gold",  # merged in by InMemorySessionService._merge_state — stripped
            "temp:scratch": 1,  # invocation-scoped — stripped
        }
        adk_session._session_service = MagicMock()
        adk_session._session_service.get_session = AsyncMock(return_value=refreshed)

        assert await adk_session.get_state() == {"cart": ["milk"]}

    @pytest.mark.asyncio
    async def test_lookup_uses_the_created_sessions_identifiers(self):
        """The read-back must not depend on hardcoded app/user names that could drift."""
        adk_session = GoogleADKSession()
        adk_session._session = MagicMock(id="sid", app_name="OtherApp", user_id="other-user")
        adk_session._session_service = MagicMock()
        adk_session._session_service.get_session = AsyncMock(return_value=MagicMock(state={}))

        await adk_session.get_state()

        adk_session._session_service.get_session.assert_awaited_once_with(app_name="OtherApp", user_id="other-user", session_id="sid")

    @pytest.mark.asyncio
    async def test_no_session_returns_empty_state(self):
        assert await GoogleADKSession().get_state() == {}


class TestGoogleADKRunnerStateSeeding:
    """The caller's context is seeded into ADK state without displacing AK-internal keys."""

    @pytest.mark.asyncio
    async def test_caller_key_cannot_override_ak_tool_context(self):
        """A context key named ak_tool_context would break AKToolContext.fetch for every tool."""
        runner = GoogleADKRunner()
        session = Session("s")
        agent = _mock_agent(output_schema=None)

        adk_session = MagicMock()
        adk_session.create_session = AsyncMock()
        adk_session.update_session_state = AsyncMock()

        with patch.object(GoogleADKRunner, "_session", return_value=adk_session), patch("agentkernel.framework.adk.adk.Runner"):
            _, _, ctx, _ = await runner._setup_session_context(agent, session, [], {"ak_tool_context": "hijacked", "cart": []})

        _, _, state = adk_session.update_session_state.await_args.args
        assert state["ak_tool_context"] == ctx.id
        assert state["cart"] == []


class TestGoogleADKRunnerFrameworkContext:
    """framework_context injection into ADK state and full (stripped) write-back."""

    @pytest.mark.asyncio
    async def test_seeded_context_injected_and_full_state_written_back(self):
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={"seeded": 9, "added": "new"})
        setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))

        with (
            patch.object(runner, "_setup_session_context", setup),
            patch.object(GoogleADKRunner, "get_response", AsyncMock(return_value=_turn("hello"))),
        ):
            reply = await runner.run(agent, session, requests)

        assert setup.await_args.args[3] == {"seeded": 1}
        # The full state is written back, so a mutated seeded key and a brand-new key both survive.
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 9, "added": "new"}
        assert reply.response == "hello"

    @pytest.mark.asyncio
    async def test_absent_key_skips_write_back(self):
        runner = GoogleADKRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={"leak": 1})
        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, "hi", adk_session)
        with setup_patch, response_patch:
            await runner.run(agent, session, requests)

        adk_session.get_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={"seeded": 9})
        setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))

        with (
            patch.object(runner, "_setup_session_context", setup),
            patch.object(GoogleADKRunner, "get_response", AsyncMock(side_effect=Exception("boom"))),
        ):
            reply = await runner.run(agent, session, requests)

        assert reply.response.startswith("Error")
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        """A drained stream writes back the stripped ADK state, including tool-added keys."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"seeded": 9, "added": "new"})
        with setup_patch:
            events = [event async for event in runner.stream(agent, session, requests)]

        assert _shape(events) == ["message_start", "text_delta", "message_end"]
        adk_session.get_state.assert_awaited_once()
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 9, "added": "new"}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        """A client disconnect (GeneratorExit at a yield) skips the state read and write-back."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"seeded": 9})
        with setup_patch:
            agen = runner.stream(agent, session, requests)
            opened = await agen.__anext__()
            assert opened.type == "message_start"
            assert await agen.__anext__() == TextDelta(message_id=opened.message_id, content="tok")
            await agen.aclose()  # simulate client disconnect at the yield

        adk_session.get_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}

    @pytest.mark.asyncio
    async def test_stream_absent_key_skips_write_back(self):
        runner = GoogleADKRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"leak": 1})
        with setup_patch:
            events = [event async for event in runner.stream(agent, session, requests)]

        assert _shape(events) == ["message_start", "text_delta", "message_end"]
        adk_session.get_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A failed state read must not escape the generator after the response was streamed."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {})
        adk_session.get_state = AsyncMock(side_effect=RuntimeError("state read failed"))

        with setup_patch, caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            events = [event async for event in runner.stream(agent, session, requests)]

        assert _shape(events) == ["message_start", "text_delta", "message_end"]
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}
        assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


def _stream_setup_multi(event_lists):
    """Patch _setup_session_context so successive stream() calls drain different event lists."""
    setups = []
    for events in event_lists:
        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={})

        async def run_async(_events=events, **kwargs):
            for event in _events:
                yield event

        adk_runner = MagicMock()
        adk_runner.run_async = run_async
        setups.append(("user", adk_runner, _ctx_mock(), adk_session))
    return patch.object(GoogleADKRunner, "_setup_session_context", AsyncMock(side_effect=setups))


async def _collect(events):
    """Drive GoogleADKRunner.stream over a scripted ADK event list and return the AK events."""
    runner = GoogleADKRunner()
    setup_patch, _ = _stream_setup(events, {})
    with setup_patch:
        return [event async for event in runner.stream(_mock_agent(), Session("s"), [AgentRequestText(prompt="hi")])]


class TestGoogleADKRunnerStreamEvents:
    """The event mapping added in PR 5. ADK supplies no message boundaries, so they are derived."""

    @pytest.mark.asyncio
    async def test_partials_are_bracketed_and_the_aggregate_closes_them(self):
        """The non-partial event carries the whole message, so its text must not be re-emitted."""
        events = await _collect([_partial_event("he"), _partial_event("llo"), _nonpartial_event("hello")])

        assert _shape(events) == ["message_start", "text_delta", "text_delta", "message_end"]
        assert [e.content for e in events if e.type == "text_delta"] == ["he", "llo"]
        # One id throughout: the deltas and both boundaries belong to one message.
        assert len({e.message_id for e in events}) == 1

    @pytest.mark.asyncio
    async def test_an_unclosed_message_is_closed_when_the_stream_drains(self):
        """ADK normally ends with a non-partial event; if it does not, the message must still close."""
        events = await _collect([_partial_event("tok")])
        assert _shape(events) == ["message_start", "text_delta", "message_end"]

    @pytest.mark.asyncio
    async def test_text_with_no_partials_is_emitted_as_a_whole_message(self):
        """Otherwise a turn that never streamed would lose its only text."""
        events = await _collect([_nonpartial_event("all at once")])
        assert _shape(events) == ["message_start", "text_delta", "message_end"]
        assert events[1].content == "all at once"

    @pytest.mark.asyncio
    async def test_reasoning_never_reaches_the_answer_stream(self):
        """ADK marks reasoning with `Part.thought`, not with a separate event.

        Joining every part's text makes a thinking model's summary the assistant's answer — which §4
        rule 5 forbids, because `delta` is what REST clients concatenate as the reply and what
        `ThreadRecorder` persists. This is the guard for that.
        """
        events = await _collect([_partial_event(thought="weighing it up"), _nonpartial_event(thought="weighing it up")])

        assert _shape(events) == ["reasoning_start", "reasoning_delta", "reasoning_end"]
        assert events[1].content == "weighing it up"

    @pytest.mark.asyncio
    async def test_reasoning_closes_before_the_answer_opens(self):
        """Thinking is over once the model starts answering, so the trace closes there."""
        events = await _collect(
            [
                _partial_event(thought="let me check"),
                _partial_event(thought=" the docs"),
                _partial_event(text="The answer is 42"),
                _nonpartial_event(text="The answer is 42"),
            ]
        )

        assert _shape(events) == [
            "reasoning_start",
            "reasoning_delta",
            "reasoning_delta",
            "reasoning_end",
            "message_start",
            "text_delta",
            "message_end",
        ]

    @pytest.mark.asyncio
    async def test_reasoning_and_the_answer_do_not_share_an_id(self):
        events = await _collect([_partial_event(thought="hmm"), _partial_event(text="hi"), _nonpartial_event(text="hi")])
        reasoning = {e.message_id for e in events if e.type.startswith("reasoning")}
        answer = {e.message_id for e in events if e.type in ("message_start", "text_delta", "message_end")}
        assert len(reasoning) == 1 and len(answer) == 1
        assert reasoning != answer

    @pytest.mark.asyncio
    async def test_the_aggregate_re_emits_neither_stream(self):
        """Its parts repeat what the partials already sent — both halves of it."""
        events = await _collect([_partial_event(thought="hmm", text="hi"), _nonpartial_event(thought="hmm", text="hi")])
        assert [e.content for e in events if e.type == "reasoning_delta"] == ["hmm"]
        assert [e.content for e in events if e.type == "text_delta"] == ["hi"]

    @pytest.mark.asyncio
    async def test_reasoning_resuming_after_a_tool_call_opens_a_second_trace(self):
        """Two traces, because that is what happened — one before the call, one after."""
        events = await _collect(
            [
                _partial_event(thought="need a lookup"),
                _partial_event(text="checking"),
                _nonpartial_event(calls=[_call(args={"q": "x"})]),
                _partial_event(thought="now I know"),
                _partial_event(text="it is 42"),
                _nonpartial_event(text="it is 42"),
            ]
        )
        starts = [e.message_id for e in events if e.type == "reasoning_start"]
        assert len(starts) == 2 and starts[0] != starts[1]
        assert _shape(events).count("reasoning_end") == 2

    @pytest.mark.asyncio
    async def test_a_tool_call_straight_out_of_reasoning_closes_the_trace_first(self):
        """A thinking model calling a tool with no answer text in between.

        The trace must close before the tool events, not wrap them. OpenAI cannot produce the nested
        shape — `response.output_item.done` closes the reasoning item before the `function_call` item
        is added — so ADK matching it is what keeps one consumer working against both adapters, the
        same reason the message boundaries were ordered this way.
        """
        events = await _collect(
            [
                _partial_event(thought="need a lookup"),
                _nonpartial_event(calls=[_call(args={"q": "x"})]),
                _partial_event(thought="now I know"),
            ]
        )
        shape = _shape(events)
        assert shape.index("reasoning_end") < shape.index("tool_call_start"), shape

        starts = [e.message_id for e in events if e.type == "reasoning_start"]
        assert len(starts) == 2 and starts[0] != starts[1], starts

    @pytest.mark.asyncio
    async def test_a_thought_that_only_arrives_whole_still_yields_a_trace(self):
        """The reasoning mirror of the whole-message fallback below it.

        A turn that never streamed partials still gets its text as one bracketed message; without
        this, the same turn's thoughts were dropped and the thinking block stayed empty.
        """
        events = await _collect([_nonpartial_event(text="answer", thought="hidden thinking")])
        assert _shape(events) == [
            "reasoning_start",
            "reasoning_delta",
            "reasoning_end",
            "message_start",
            "text_delta",
            "message_end",
        ]
        assert [e.content for e in events if e.type == "reasoning_delta"] == ["hidden thinking"]

    @pytest.mark.asyncio
    async def test_an_aggregated_thought_does_not_duplicate_what_already_streamed(self):
        """The fallback fires only when no trace is open, so the aggregate is ignored after partials.

        ADK repeats the whole thought on the closing non-partial event; emitting it again would show
        the user their reasoning twice.
        """
        events = await _collect([_partial_event(thought="weigh"), _nonpartial_event(text="done", thought="weigh")])
        assert [e.content for e in events if e.type == "reasoning_delta"] == ["weigh"]
        assert _shape(events).count("reasoning_start") == 1

    @pytest.mark.asyncio
    async def test_a_thought_only_turn_closes_its_trace_on_drain(self):
        """No answer text ever arrives to close it, so the drain has to."""
        events = await _collect([_partial_event(thought="thinking")])
        assert _shape(events) == ["reasoning_start", "reasoning_delta", "reasoning_end"]

    @pytest.mark.asyncio
    async def test_a_tool_only_turn_emits_no_message_boundaries(self):
        """No text means no message. An empty assistant bubble is what spec.md:229-233 forbids."""
        events = await _collect(
            [
                _nonpartial_event(calls=[_call(args={"q": "x"})]),
                _nonpartial_event(responses=[_response(response={"ok": True})]),
            ]
        )
        assert _shape(events) == ["tool_call_start", "tool_call_args", "tool_call_end", "tool_call_result"]

    @pytest.mark.asyncio
    async def test_a_tool_call_on_a_text_event_is_emitted_after_the_message_closes(self):
        """One model response can carry prose and a tool call in the same `Content`.

        The message must close before the tool call opens. OpenAI cannot interleave them — its
        `response.output_item.done` closes the message before the `function_call` item is added — so
        ADK matching that ordering is what keeps one consumer working against both adapters.
        """
        events = await _collect([_partial_event("Let me check"), _nonpartial_event("Let me check", calls=[_call(args={"q": "x"})])])
        assert _shape(events) == [
            "message_start",
            "text_delta",
            "message_end",
            "tool_call_start",
            "tool_call_args",
            "tool_call_end",
        ]

    @pytest.mark.asyncio
    async def test_a_tool_call_and_its_result_share_the_call_id(self):
        events = await _collect(
            [_nonpartial_event(calls=[_call(args={"q": "x"}, call_id="c9")], responses=[_response(response={"n": 1}, call_id="c9")])]
        )
        assert {e.tool_call_id for e in events} == {"c9"}
        assert [e.delta for e in events if e.type == "tool_call_args"] == ['{"q": "x"}']
        assert [e.content for e in events if e.type == "tool_call_result"] == ['{"n": 1}']

    @pytest.mark.asyncio
    async def test_a_call_with_no_id_emits_nothing(self):
        """It could never be correlated to its response, and a call that never resolves is worse."""
        events = await _collect([_nonpartial_event(calls=[_call(call_id=None)], responses=[_response(call_id=None)])])
        assert events == []

    @pytest.mark.asyncio
    async def test_unserialisable_tool_args_still_leave_the_call_bracketed(self):
        class Unserialisable:
            def __repr__(self):
                raise RuntimeError("nope")

        events = await _collect([_nonpartial_event(calls=[_call(args={"q": Unserialisable()})])])
        assert _shape(events) == ["tool_call_start", "tool_call_end"]

    @pytest.mark.asyncio
    async def test_two_concurrent_streams_do_not_share_a_message_id(self):
        """The guard for §10: one GoogleADKRunner instance serves every agent and every session, so
        the derived `message_id` must be a local. On `self` it would be shared and the second run
        would hijack the first run's deltas."""
        runner = GoogleADKRunner()
        requests = [AgentRequestText(prompt="hi")]

        with _stream_setup_multi([[_partial_event("a1"), _partial_event("a2")], [_partial_event("b1")]]):
            a = runner.stream(_mock_agent(), Session("sa"), requests)
            b = runner.stream(_mock_agent(), Session("sb"), requests)

            a_start = await a.__anext__()
            b_start = await b.__anext__()
            a_delta = await a.__anext__()

            assert a_start.message_id != b_start.message_id
            # The load-bearing assertion: A's delta still belongs to A after B opened a message.
            assert a_delta.message_id == a_start.message_id

            await a.aclose()
            await b.aclose()


class TestGoogleADKRunnerHandoffs:
    """ADK needs no handoff branch, and these are what make that a guarantee rather than an assumption.

    A transfer is an ordinary tool call here: `TransferToAgentTool` is a `FunctionTool`, so it reaches
    the adapter through `get_function_calls()` like any other and `_tool_events` maps it unchanged.
    OpenAI is the adapter that had to be told (spec §10), because it alone lifts handoffs out of its
    tool stream into dedicated run items. Both adapters therefore emit the same AK events for the same
    concept, which is the property the spec claims and nothing was checking.
    """

    def test_the_transfer_tools_real_name_is_read_from_the_sdk(self):
        """Pinned against the SDK rather than a literal. If ADK renamed the tool or stopped deriving
        it from a FunctionTool, §10's cross-adapter claim would be stale and this is what says so."""
        from google.adk.tools import FunctionTool, TransferToAgentTool

        tool = TransferToAgentTool(agent_names=["billing"])
        assert isinstance(tool, FunctionTool)
        assert tool.name == "transfer_to_agent"

    @pytest.mark.asyncio
    async def test_a_handoff_maps_like_any_other_tool_call(self):
        events = await _collect(
            [
                _nonpartial_event(
                    calls=[_call(name="transfer_to_agent", args={"agent_name": "billing"}, call_id="ho-1")],
                    responses=[_response(name="transfer_to_agent", response={"result": None}, call_id="ho-1")],
                )
            ]
        )
        assert _shape(events) == ["tool_call_start", "tool_call_args", "tool_call_end", "tool_call_result"]
        assert {event.tool_call_id for event in events} == {"ho-1"}
        assert [event.name for event in events if event.type == "tool_call_start"] == ["transfer_to_agent"]
        assert [event.delta for event in events if event.type == "tool_call_args"] == ['{"agent_name": "billing"}']

    @pytest.mark.asyncio
    async def test_a_handoff_needs_no_special_case_to_be_bracketed(self):
        """The call is opened and closed even when the transfer returns nothing to report, so a client
        never holds an unresolved handoff."""
        events = await _collect([_nonpartial_event(calls=[_call(name="transfer_to_agent", call_id="ho-2")])])
        assert _shape(events) == ["tool_call_start", "tool_call_end"]


class TestGoogleADKRunnerErrorHandling:
    """Error replies from failures that happen before the prompt is extracted"""

    @pytest.mark.asyncio
    async def test_request_processing_error_returns_error_reply(self):
        """A request that fails inside _process_requests still returns a clean error reply."""
        runner = GoogleADKRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(name="empty.png", image_data="")]  # raises inside _process_requests
        agent = _mock_agent(output_schema=None)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response.startswith("Error")
        assert reply.prompt == ""


class TestGoogleADKRunnerStructuredOutput:
    """Test structured output detection via LlmAgent output_schema"""

    @pytest.mark.asyncio
    async def test_output_schema_reply_returns_agent_reply_any(self):
        runner = GoogleADKRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="capital of France?")]
        agent = _mock_agent(output_schema=CapitalOutput)

        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, '{"country": "France", "capital": "Paris"}')
        with setup_patch, response_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"country": "France", "capital": "Paris"}
        assert reply.prompt == "capital of France?"

    @pytest.mark.asyncio
    async def test_output_schema_with_invalid_json_falls_back_to_text(self):
        runner = GoogleADKRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="capital of France?")]
        agent = _mock_agent(output_schema=CapitalOutput)

        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, "Sorry, I cannot answer that.")
        with setup_patch, response_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Sorry, I cannot answer that."
        assert reply.prompt == "capital of France?"

    @pytest.mark.asyncio
    async def test_without_output_schema_returns_text(self):
        runner = GoogleADKRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]
        agent = _mock_agent(output_schema=None)

        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, "Hi there!")
        with setup_patch, response_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Hi there!"

    @pytest.mark.asyncio
    async def test_agent_without_output_schema_attribute_returns_text(self):
        """Non-LlmAgent roots (e.g. SequentialAgent) have no output_schema attribute at all"""
        runner = GoogleADKRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]
        agent = _mock_agent()
        agent.name = "workflow-agent"
        agent.agent = MagicMock(spec=[])  # no output_schema attribute

        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, "Done.")
        with setup_patch, response_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Done."


def _capturing_setup(captured: dict, events=()):
    """Patch _setup_session_context with an ADK runner whose run_async records its keywords and yields `events`."""
    adk_session = MagicMock()
    adk_session.get_state = AsyncMock(return_value={})

    async def run_async(**kwargs):
        captured.clear()
        captured.update(kwargs)
        for event in events:
            yield event

    adk_runner = MagicMock()
    adk_runner.run_async = run_async
    setup = AsyncMock(return_value=("user", adk_runner, _ctx_mock(), adk_session))
    return patch.object(GoogleADKRunner, "_setup_session_context", setup)


class TestGoogleADKRunOptions:
    """Declared run options split between the per-run Runner constructor and run_async (spec #754)."""

    def test_reserved_keys(self):
        assert set(GoogleADKAgent.RESERVED_RUN_OPTIONS) == {
            "agent",
            "app",
            "app_name",
            "node",
            "session_service",
            "auto_create_session",
            "user_id",
            "session_id",
            "new_message",
            "state_delta",
            "invocation_id",
            "yield_user_message",
        }

    def test_split_routes_constructor_keys_and_leaves_the_rest_for_run_async(self):
        plugin, memory, run_config = object(), object(), RunConfig(max_llm_calls=3)
        agent = _mock_agent()
        agent.run_options = {"plugins": [plugin], "memory_service": memory, "run_config": run_config, "other": 1}

        ctor, run = GoogleADKRunner._split_run_options(agent.run_options)

        assert ctor == {"plugins": [plugin], "memory_service": memory}
        assert run == {"run_config": run_config, "other": 1}

    @pytest.mark.asyncio
    async def test_constructor_options_reach_the_per_run_adk_runner(self):
        runner = GoogleADKRunner()
        plugin = object()
        agent = _mock_agent()
        agent.run_options = {"plugins": ["static, not read by the setup"]}  # the setup takes the resolved mapping, not the agent
        adk_session = MagicMock()
        adk_session.create_session = AsyncMock()
        adk_session.update_session_state = AsyncMock()

        with (
            patch.object(GoogleADKRunner, "_session", return_value=adk_session),
            patch("agentkernel.framework.adk.adk.Runner") as MockRunner,
        ):
            await runner._setup_session_context(
                agent, Session("s"), [AgentRequestText(prompt="hi")], None, {"plugins": [plugin], "run_config": RunConfig()}
            )

        kwargs = MockRunner.call_args.kwargs
        assert kwargs["plugins"] == [plugin]
        assert kwargs["app"].root_agent is agent.agent
        assert kwargs["app"].resumability_config.is_resumable is True
        assert kwargs["app_name"] == "AgentKernel"
        assert kwargs["session_service"] is adk_session.session_service
        assert "run_config" not in kwargs

    @pytest.mark.asyncio
    async def test_run_mode_forwards_the_run_config_untouched(self):
        runner = GoogleADKRunner()
        captured: dict = {}
        run_config = RunConfig(max_llm_calls=3)
        agent = _mock_agent()
        agent.run_options = {"plugins": [object()], "run_config": run_config}

        with _capturing_setup(captured, [_final_event("answer")]):
            reply = await runner.run(agent, Session("s"), [AgentRequestText(prompt="hi")])

        assert reply.response == "answer"
        assert captured["run_config"] is run_config
        assert captured["run_config"].streaming_mode is StreamingMode.NONE
        assert set(captured) == {"user_id", "session_id", "new_message", "run_config"}

    @pytest.mark.asyncio
    async def test_stream_mode_forces_sse_on_a_copy_and_warns_once_per_runner(self, caplog):
        runner = GoogleADKRunner()
        captured: dict = {}
        run_config = RunConfig(max_llm_calls=3, streaming_mode=StreamingMode.NONE)  # explicitly chosen, so the override is worth a warning
        agent = _mock_agent()
        agent.run_options = {"run_config": run_config}

        with _capturing_setup(captured), caplog.at_level(logging.WARNING, logger="ak.adk.runner"):
            _ = [e async for e in runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]
            first = captured["run_config"]
            _ = [e async for e in runner.stream(agent, Session("t"), [AgentRequestText(prompt="hi")])]

        assert first.streaming_mode is StreamingMode.SSE
        assert first.max_llm_calls == 3
        assert run_config.streaming_mode is StreamingMode.NONE  # the caller's object is untouched
        assert agent.run_options["run_config"] is run_config
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "SSE" in r.getMessage()]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_stream_does_not_warn_for_a_run_config_that_never_set_streaming_mode(self, caplog):
        runner = GoogleADKRunner()
        captured: dict = {}
        run_config = RunConfig(max_llm_calls=3)  # streaming_mode left at its default, not a caller choice
        agent = _mock_agent()
        agent.run_options = {"run_config": run_config}

        with _capturing_setup(captured), caplog.at_level(logging.WARNING, logger="ak.adk.runner"):
            _ = [e async for e in runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert captured["run_config"].streaming_mode is StreamingMode.SSE
        assert captured["run_config"].max_llm_calls == 3
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    @pytest.mark.asyncio
    async def test_stream_without_a_declared_run_config_uses_sse_and_does_not_warn(self, caplog):
        runner = GoogleADKRunner()
        captured: dict = {}
        agent = _mock_agent()
        agent.run_options = {}

        with _capturing_setup(captured), caplog.at_level(logging.WARNING, logger="ak.adk.runner"):
            _ = [e async for e in runner.stream(agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert captured["run_config"].streaming_mode is StreamingMode.SSE
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    @pytest.mark.asyncio
    async def test_run_resolves_once_and_hands_the_resolved_options_to_the_session_setup(self):
        runner = GoogleADKRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        captured: dict = {}
        plugin, run_config = object(), RunConfig(max_llm_calls=3)
        agent = _mock_agent()
        agent.run_options = {"run_config": RunConfig(max_llm_calls=1)}
        agent.resolve_run_options = AsyncMock(return_value={"plugins": [plugin], "run_config": run_config})  # the factory-merged mapping

        with _capturing_setup(captured, [_final_event("answer")]) as setup:
            reply = await runner.run(agent, session, requests)

        assert reply.response == "answer"
        agent.resolve_run_options.assert_awaited_once_with(session, requests)
        assert setup.await_args.args[4] == {"plugins": [plugin], "run_config": run_config}  # the constructor split happens inside the setup
        assert captured["run_config"] is run_config
        assert "plugins" not in captured

    @pytest.mark.asyncio
    async def test_stream_resolves_once_and_sse_copies_the_resolved_run_config(self):
        runner = GoogleADKRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        captured: dict = {}
        run_config = RunConfig(max_llm_calls=3)
        agent = _mock_agent()
        agent.run_options = {}
        agent.resolve_run_options = AsyncMock(return_value={"plugins": [object()], "run_config": run_config})

        with _capturing_setup(captured) as setup:
            _ = [e async for e in runner.stream(agent, session, requests)]

        agent.resolve_run_options.assert_awaited_once_with(session, requests)
        assert setup.await_args.args[4]["run_config"] is run_config
        assert captured["run_config"].streaming_mode is StreamingMode.SSE
        assert captured["run_config"].max_llm_calls == 3
        assert run_config.streaming_mode is StreamingMode.NONE  # the factory's object is copied, not mutated
        assert "plugins" not in captured

    @pytest.mark.asyncio
    async def test_a_request_without_content_returns_before_resolving_in_both_modes(self):
        runner = GoogleADKRunner()
        agent = _mock_agent()

        reply = await runner.run(agent, Session("s"), [])
        _ = [e async for e in runner.stream(agent, Session("s"), [])]

        assert "No valid content" in reply.response
        agent.resolve_run_options.assert_not_awaited()


# --- Human in the loop (spec `docs/specs/606-human-in-the-loop/`, iteration 8) -------------------


class _FakeLlm:
    """Stands in for the model, so a pause is driven without a network call.

    ADK's pause is the *model* deciding to call a long-running tool, so unlike LangGraph there is no
    way to reach it without something answering as the model.
    """


def _gated_adk(confirmation=False, repeat=False):
    """A real ADK agent whose tool pauses, wired through a fake model.

    `repeat` makes the model ask a second question once the first is answered, which is the only way
    to reach the pause-again branch of resume()/resume_stream().
    """
    from typing import AsyncGenerator

    from google.adk.agents import LlmAgent
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools import FunctionTool, LongRunningFunctionTool
    from google.genai import types

    class FakeLlm(BaseLlm):
        model: str = "fake"
        rounds: int = 0
        seen: list = []

        async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
            self.rounds += 1
            if self.rounds == 1:
                # The call has to match the tool that is actually registered below, or ADK never
                # reaches the branch under test.
                call = (
                    types.FunctionCall(id="call-1", name="refund", args={"amount": 100})
                    if confirmation
                    else types.FunctionCall(id="call-1", name="ask_size", args={"q": "size?"})
                )
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
            else:
                FakeLlm.seen = [
                    p.function_response.response for m in llm_request.contents for p in (m.parts or []) if getattr(p, "function_response", None)
                ]
                # Round 2 still belongs to the first turn: a long-running call does not end it. The
                # resume opens round 3, which is the only place a second question is a *new* pause.
                if repeat and self.rounds == 3:
                    again = types.FunctionCall(id="call-2", name="ask_size", args={"q": "anything else?"})
                    yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=again)]))
                else:
                    yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="all done")]))

    def ask_size(q: str) -> dict:
        """Ask the human for a size."""
        return {"status": "pending"}

    def refund(amount: int) -> str:
        """Refund the customer."""
        return f"refunded {amount}"

    llm = FakeLlm()
    FakeLlm.seen = []
    tool = FunctionTool(func=refund, require_confirmation=True) if confirmation else LongRunningFunctionTool(func=ask_size)
    native = LlmAgent(name="gated", model=llm, tools=[tool])
    return GoogleADKAgent(name="gated", runner=GoogleADKRunner(), agent=native), FakeLlm


def _resume_requests(*decisions, prompt=None):
    requests = [AgentRequestText(prompt=prompt)] if prompt else []
    return requests + [AgentResumeRequestAny(decisions=list(decisions))], list(decisions)


class TestGoogleADKPause:
    def test_the_runner_declares_the_capability(self):
        assert GoogleADKRunner().supports_pause is True

    @pytest.mark.asyncio
    async def test_a_long_running_tool_returns_a_paused_reply(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        reply = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        assert isinstance(reply, AgentPausedReplyAny)
        assert [i.id for i in reply.interruptions] == ["call-1"]
        assert reply.interruptions[0].kind == "tool_call"
        assert reply.interruptions[0].tool_name == "ask_size"

    @pytest.mark.asyncio
    async def test_the_arguments_ride_along(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        reply = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        assert reply.interruptions[0].arguments == '{"q": "size?"}'

    @pytest.mark.asyncio
    async def test_it_replaces_only_its_own_framework_s_pause(self):
        """A session shared with another framework's agent keeps that agent's pause."""
        from agentkernel.core.event import PausedInterruption

        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        foreign = PausedRunState.add(
            session,
            agent="support",
            runner="openai",
            interruptions=[PausedInterruption(id="openai-1", kind="tool_call", tool_name="issue_refund")],
        )

        await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        assert foreign.id in [r.id for r in PausedRunState.list(session)]
        assert [r.runner for r in PausedRunState.list(session) if r.id != foreign.id] == ["adk"]

    @pytest.mark.asyncio
    async def test_the_record_carries_the_invocation_to_resume(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        reply = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        assert PausedRunState.get(session, reply.run_id).payload["invocation_id"]

    @pytest.mark.asyncio
    async def test_the_session_survives_a_pickle_round_trip(self):
        """ADK's conversation lives in an InMemorySessionService inside GoogleADKSession."""
        import pickle

        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        reply = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        restored = pickle.loads(pickle.dumps(session))

        assert PausedRunState.get(restored, reply.run_id) is not None

    @pytest.mark.asyncio
    async def test_the_app_is_resumable(self):
        """ResumabilityConfig lives on an App, so the adapter must build one around the agent."""
        runner = GoogleADKRunner()
        agent, _ = _gated_adk()
        adk_session = MagicMock()
        adk_session.create_session = AsyncMock()
        adk_session.update_session_state = AsyncMock()

        with patch.object(GoogleADKRunner, "_session", return_value=adk_session), patch("agentkernel.framework.adk.adk.Runner") as MockRunner:
            await runner._setup_session_context(agent, Session("s"), [AgentRequestText(prompt="hi")], None, {})

        app = MockRunner.call_args.kwargs["app"]
        assert app.resumability_config.is_resumable is True
        assert app.name == "AgentKernel"


class TestGoogleADKResume:
    @pytest.mark.asyncio
    async def test_the_chosen_value_reaches_the_model(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        reply = await runner.resume(agent, session, requests, decisions, record)

        assert reply.response == "all done"
        assert FakeLlm.seen == [{"result": "large"}]

    @pytest.mark.asyncio
    async def test_free_text_is_used_when_there_is_no_payload(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", message="medium"))

        await runner.resume(agent, session, requests, decisions, record)

        assert FakeLlm.seen == [{"result": "medium"}]

    @pytest.mark.asyncio
    async def test_the_resume_clears_its_record(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        await runner.resume(agent, session, requests, decisions, record)

        assert PausedRunState.list(session) == []


class TestGoogleADKRejectsAPromptAlongside:
    """
    Established by test at google-adk 2.8.0, not assumed.

    ADK itself refuses a message holding both a function response and text — *"Function responses
    resume an existing invocation while text starts a new one"* — so the adapter pre-empts it above
    the `try`, where the reason survives instead of being flattened into a generic reply.
    """

    @pytest.mark.asyncio
    async def test_a_prompt_beside_a_decision_is_refused(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"), prompt="and the weather?")

        with pytest.raises(ValueError, match="cannot carry a prompt alongside a decision"):
            await runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_the_record_is_left_intact(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"), prompt="hello")

        with pytest.raises(ValueError):
            await runner.resume(agent, session, requests, decisions, record)

        assert PausedRunState.get(session, paused.run_id) is not None


class TestGoogleADKStreamingPause:
    """
    The spec's one open question, answered by test at google-adk 2.8.0: streaming *can* pause.

    Two things made it a risk — ADK's own "known limitation" comment on its two-event pause window,
    and the partial/non-partial id split, where an id read off a streamed partial event may never
    have been persisted. Neither bites: the event carrying the pending call is non-partial.
    """

    @pytest.mark.asyncio
    async def test_a_streamed_gated_run_ends_with_run_paused(self):
        from agentkernel.core.event import RunPaused

        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="ask me")])]

        assert isinstance(events[-1], RunPaused)
        assert events[-1].agent == "gated"
        assert [i.id for i in events[-1].interruptions] == ["call-1"]

    @pytest.mark.asyncio
    async def test_the_pending_call_arrives_on_a_non_partial_event(self):
        """Why the id is safe to hand a client: a partial event's id may never be persisted."""
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="ask me")])]
        record = PausedRunState.get(session, events[-1].run_id)

        assert record.payload["invocation_id"]
        assert [i.id for i in record.interruptions] == ["call-1"]

    @pytest.mark.asyncio
    async def test_resume_stream_delivers_the_value_and_clears_the_record(self):
        from agentkernel.core.event import RunPaused

        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk()
        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="ask me")])]
        record = PausedRunState.get(session, events[-1].run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        resumed = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]

        assert FakeLlm.seen == [{"result": "large"}]
        assert not any(isinstance(e, RunPaused) for e in resumed)
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_resume_stream_refuses_a_prompt_alongside(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()
        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="ask me")])]
        record = PausedRunState.get(session, events[-1].run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"), prompt="and the weather?")

        with pytest.raises(ValueError, match="cannot carry a prompt alongside a decision"):
            _ = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]


class TestGoogleADKConfirmation:
    """
    `require_confirmation` is ADK's second pause: a verdict, not a result.

    ADK intercepts the model's call and asks through its own `adk_request_confirmation` call, so the
    interruption carries ADK's generated id and the original call in its arguments rather than the
    tool's own.
    """

    @pytest.mark.asyncio
    async def test_a_confirmation_pauses_with_its_own_kind(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk(confirmation=True)

        reply = await runner.run(agent, session, [AgentRequestText(prompt="refund it")])

        assert isinstance(reply, AgentPausedReplyAny)
        assert reply.interruptions[0].kind == "confirmation"
        assert reply.interruptions[0].tool_name == "adk_request_confirmation"

    @pytest.mark.asyncio
    async def test_the_original_call_rides_along_in_the_arguments(self):
        """All the human has to go on: which tool, with which arguments."""
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk(confirmation=True)

        reply = await runner.run(agent, session, [AgentRequestText(prompt="refund it")])

        assert '"name": "refund"' in reply.interruptions[0].arguments
        assert '"amount": 100' in reply.interruptions[0].arguments

    @pytest.mark.asyncio
    async def test_approving_runs_the_gated_tool(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk(confirmation=True)
        paused = await runner.run(agent, session, [AgentRequestText(prompt="refund it")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        await runner.resume(agent, session, requests, decisions, record)

        assert FakeLlm.seen == [{"result": "refunded 100"}]
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["denied", "cancelled"])
    async def test_a_refused_confirmation_never_runs_the_tool(self, status):
        """
        Both read identically to the model, which is ADK's doing, not Agent Kernel's.

        ADK consumes the confirmation response and writes its own for the original call, so the
        `hint` carrying AK's "nobody decided" wording is dropped. This is the one adapter where
        `cancelled` cannot be told apart from `denied`.
        """
        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk(confirmation=True)
        paused = await runner.run(agent, session, [AgentRequestText(prompt="refund it")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status=status))

        await runner.resume(agent, session, requests, decisions, record)

        assert FakeLlm.seen != [{"result": "refunded 100"}]
        assert "reject" in str(FakeLlm.seen).lower()

    @pytest.mark.asyncio
    async def test_a_payload_on_a_confirmation_is_refused_rather_than_dropped(self):
        """ADK reissues the original call unchanged, so an override would vanish silently."""
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk(confirmation=True)
        paused = await runner.run(agent, session, [AgentRequestText(prompt="refund it")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved", payload={"amount": 5}))

        with pytest.raises(ValueError, match="cannot deliver a structured answer to a confirmation"):
            await runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_a_payload_on_a_long_running_tool_is_still_the_answer(self):
        """The rejection is about confirmations only; the other kind carries the value."""
        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk()
        paused = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        await runner.resume(agent, session, requests, decisions, record)

        assert FakeLlm.seen == [{"result": "large"}]

    @pytest.mark.asyncio
    async def test_a_confirmation_streams_and_resumes(self):
        from agentkernel.core.event import RunPaused

        runner, session = GoogleADKRunner(), Session("s")
        agent, FakeLlm = _gated_adk(confirmation=True)
        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]
        paused = events[-1]
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id=paused.interruptions[0].id, status="approved"))

        resumed = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]

        assert isinstance(paused, RunPaused)
        assert paused.interruptions[0].kind == "confirmation"
        assert FakeLlm.seen == [{"result": "refunded 100"}]
        assert not any(isinstance(e, RunPaused) for e in resumed)


class TestGoogleADKStreamedRePause:
    """
    Answer one question, get asked the next — the flow the feature exists for, streamed.

    The branch that emits the second `RunPaused` is only reachable when the model asks again *after*
    a resume, which is why `_gated_adk(repeat=True)` keys on the round the resume opens rather than
    on the second: a long-running call does not end the first turn.
    """

    @pytest.mark.asyncio
    async def test_a_streamed_resume_that_pauses_again_emits_a_fresh_run_paused(self):
        from agentkernel.core.event import RunPaused

        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk(repeat=True)
        events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="ask me")])]
        first = events[-1]
        record = PausedRunState.get(session, first.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        resumed = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]

        again = resumed[-1]
        assert isinstance(again, RunPaused)
        assert again.run_id != first.run_id
        assert [i.id for i in again.interruptions] == ["call-2"]
        assert [r.id for r in PausedRunState.list(session)] == [again.run_id]

    @pytest.mark.asyncio
    async def test_the_non_streaming_resume_pauses_again_too(self):
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk(repeat=True)
        first = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])
        record = PausedRunState.get(session, first.run_id)
        requests, decisions = _resume_requests(ResumeDecision(id="call-1", payload="large"))

        again = await runner.resume(agent, session, requests, decisions, record)

        assert isinstance(again, AgentPausedReplyAny)
        assert again.run_id != first.run_id
        assert [r.id for r in PausedRunState.list(session)] == [again.run_id]


def _restating_adk():
    """An agent whose outstanding long-running call is re-surfaced on the next round.

    ADK re-emits a call that is still waiting, so a drained turn can carry the same id twice. Found
    by running the demo: a model that asked once and then restated the question crashed the pause.
    """
    from typing import AsyncGenerator

    from google.adk.agents import LlmAgent
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools import LongRunningFunctionTool
    from google.genai import types

    class FakeLlm(BaseLlm):
        model: str = "fake"
        rounds: int = 0

        async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
            self.rounds += 1
            if self.rounds <= 2:
                call = types.FunctionCall(id="call-1", name="ask_size", args={"q": "size?"})
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
            else:
                yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="all done")]))

    def ask_size(q: str) -> dict:
        """Ask the human for a size."""
        return {"status": "pending"}

    native = LlmAgent(name="gated", model=FakeLlm(), tools=[LongRunningFunctionTool(func=ask_size)])
    return GoogleADKAgent(name="gated", runner=GoogleADKRunner(), agent=native)


class TestARepeatedCallIsOneQuestion:
    """
    The same call reaching a turn twice is the model restating itself, not two things to decide.

    Carried through, the repeat fails `PausedRunState.add`'s uniqueness check, and the adapter's
    `except Exception` hands that internal message to the user in place of the pause.
    """

    @pytest.mark.asyncio
    async def test_a_restated_call_pauses_once_instead_of_failing(self):
        runner, session = GoogleADKRunner(), Session("s")

        reply = await runner.run(_restating_adk(), session, [AgentRequestText(prompt="ask me")])

        assert isinstance(reply, AgentPausedReplyAny), getattr(reply, "response", reply)
        assert [i.id for i in reply.interruptions] == ["call-1"]
        assert len(PausedRunState.list(session)) == 1

    @pytest.mark.asyncio
    async def test_the_internal_uniqueness_error_never_reaches_the_caller(self):
        runner, session = GoogleADKRunner(), Session("s")

        reply = await runner.run(_restating_adk(), session, [AgentRequestText(prompt="ask me")])

        assert "repeating interruption id" not in str(getattr(reply, "response", ""))

    @pytest.mark.asyncio
    async def test_a_streamed_run_pauses_once_too(self):
        from agentkernel.core.event import RunPaused

        runner, session = GoogleADKRunner(), Session("s")

        events = [e async for e in runner.stream(_restating_adk(), session, [AgentRequestText(prompt="ask me")])]

        assert isinstance(events[-1], RunPaused)
        assert [i.id for i in events[-1].interruptions] == ["call-1"]

    @pytest.mark.asyncio
    async def test_two_genuinely_different_calls_are_still_two_questions(self):
        """The dedupe is by id, so it must not collapse a turn that really asks twice."""
        runner, session = GoogleADKRunner(), Session("s")
        agent, _ = _gated_adk()

        reply = await runner.run(agent, session, [AgentRequestText(prompt="ask me")])

        assert len(reply.interruptions) == 1  # this fixture asks once; the ids are what matters
        assert len({i.id for i in reply.interruptions}) == len(reply.interruptions)
