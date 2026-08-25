import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.event import TextDelta
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestImage, AgentRequestText
from agentkernel.framework.adk.adk import GoogleADKRunner, GoogleADKSession

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class CapitalOutput(BaseModel):
    country: str
    capital: str


def _mock_agent(output_schema=None):
    agent = MagicMock()
    agent.name = "test-agent"
    agent.agent = MagicMock(spec=["output_schema"])
    agent.agent.output_schema = output_schema
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
    get_response = AsyncMock(return_value=response_text)
    return patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", get_response)


class TestGoogleADKRunnerGetResponse:
    """get_response drains the event stream and keeps the last final response."""

    @pytest.mark.asyncio
    async def test_last_final_response_wins_and_the_stream_is_drained(self):
        """Sub-agent flows emit several final responses; the root agent's (last) one is the reply, and
        stopping early would make ADK cancel the still-running root agent task and skip its state writes."""
        adk_runner, drained = _draining_runner([_final_event("sub-agent answer"), _non_final_event(), _final_event("root answer")])

        response = await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[])

        assert response == "root answer"
        assert drained == [True]

    @pytest.mark.asyncio
    async def test_multiple_text_parts_are_joined(self):
        event = MagicMock()
        event.is_final_response = MagicMock(return_value=True)
        event.content = MagicMock(parts=[MagicMock(text="hello"), MagicMock(text="world")])
        adk_runner, _ = _draining_runner([event])

        assert await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[]) == "hello world"

    @pytest.mark.asyncio
    async def test_no_final_response_returns_empty_string(self):
        adk_runner, drained = _draining_runner([_non_final_event()])

        assert await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[]) == ""
        assert drained == [True]

    @pytest.mark.asyncio
    async def test_final_response_without_text_yields_empty_string(self):
        adk_runner, _ = _draining_runner([_final_event(None)])

        assert await GoogleADKRunner.get_response(runner=adk_runner, user_id="user", session_id="s", parts=[]) == ""


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

        with patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", AsyncMock(return_value="hello")):
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
        agent = MagicMock()
        agent.name = "workflow-agent"
        agent.agent = MagicMock(spec=[])  # no output_schema attribute

        setup_patch, response_patch = _run_with_response(runner, agent, session, requests, "Done.")
        with setup_patch, response_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Done."
