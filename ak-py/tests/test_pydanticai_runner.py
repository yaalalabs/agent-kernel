import asyncio
import logging
from contextlib import asynccontextmanager
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, FunctionToolset, RunContext
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.run import AgentRunResultEvent
from pydantic_core import to_jsonable_python

from agentkernel.core import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.core.session.serde import BinarySerde
from agentkernel.core.tool import SystemToolFactory
from agentkernel.framework.pydanticai.pydanticai import FRAMEWORK, PydanticAIAgent, PydanticAIRunner, PydanticAISession


class CalendarEvent(BaseModel):
    name: str
    date: str


def _mock_agent(output, messages=None):
    """
    Build a mock wrapping a native Pydantic AI agent whose ``run()`` returns a result with ``.output``.
    ``run()`` is an instance method on the agent itself, so the mock lives on ``mock_agent.agent.run``.
    """
    mock_run_result = MagicMock()
    mock_run_result.output = output
    mock_run_result.all_messages = MagicMock(return_value=messages or [])

    mock_agent = MagicMock()
    mock_agent.agent = MagicMock()
    mock_agent.agent.run = AsyncMock(return_value=mock_run_result)
    return mock_agent


def _mock_stream_events_agent(events, on_stream=None, messages=None):
    """
    Build a mock agent whose ``run_stream_events`` is an async context manager yielding ``events`` and
    then the terminal ``AgentRunResultEvent``, so ``stream()`` can be driven (and closed mid-stream)
    without Pydantic AI's real anyio scopes. The deps the runner injected are recorded on
    ``captured_deps``; ``on_stream`` mutates them like a native tool would.

    The events themselves are real SDK objects (see the ``_text_*`` helpers), so these tests pin the
    wire shape rather than a mock's.
    """
    mock_agent = MagicMock()
    mock_agent.captured_deps = None

    @asynccontextmanager
    async def run_stream_events(content, message_history=None, deps=None, **kwargs):
        mock_agent.captured_deps = deps

        async def stream():
            if on_stream is not None and deps is not None:
                on_stream(deps)
            for event in events:
                yield event
            result = MagicMock()
            result.all_messages = MagicMock(return_value=messages or [])
            yield AgentRunResultEvent(result=result)

        yield stream()

    mock_agent.agent = MagicMock()
    mock_agent.agent.run_stream_events = run_stream_events
    return mock_agent


def _text_start(index=0, content="", part_id=None):
    return PartStartEvent(index=index, part=TextPart(content=content, id=part_id))


def _text_delta(index=0, content="x"):
    return PartDeltaEvent(index=index, delta=TextPartDelta(content_delta=content))


def _text_end(index=0):
    return PartEndEvent(index=index, part=TextPart(content=""))


def _thinking_start(index=0, content=""):
    return PartStartEvent(index=index, part=ThinkingPart(content=content))


def _thinking_delta(index=0, content="reasoning"):
    return PartDeltaEvent(index=index, delta=ThinkingPartDelta(content_delta=content))


def _thinking_end(index=0):
    return PartEndEvent(index=index, part=ThinkingPart(content=""))


def _tool_start(index=0, name="lookup", args=None, tool_call_id="t1"):
    return PartStartEvent(index=index, part=ToolCallPart(tool_name=name, args=args, tool_call_id=tool_call_id))


def _tool_args_delta(index=0, args_delta='{"q": "x"}', tool_call_id="t1"):
    return PartDeltaEvent(index=index, delta=ToolCallPartDelta(args_delta=args_delta, tool_call_id=tool_call_id))


def _tool_end(index=0, name="lookup", tool_call_id="t1"):
    return PartEndEvent(index=index, part=ToolCallPart(tool_name=name, args=None, tool_call_id=tool_call_id))


def _tool_result(name="lookup", content="42", tool_call_id="t1"):
    return FunctionToolResultEvent(part=ToolReturnPart(tool_name=name, content=content, tool_call_id=tool_call_id))


async def _collect(runner, events, session=None, on_stream=None, messages=None):
    """Drive PydanticAIRunner.stream over a scripted SDK event list and return the AK events."""
    session = session if session is not None else Session("stream-session")
    agent = _mock_stream_events_agent(events, on_stream=on_stream, messages=messages)
    collected = [event async for event in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]
    return collected, agent


def _shape(events):
    """The event sequence by discriminator. Derived ids are uuid4, so they cannot be asserted."""
    return [event.type for event in events]


class TestPydanticAIRunnerFrameworkContext:
    """
    framework_context injection and write-back for PydanticAIRunner. The context is injected as ``deps``,
    and tools mutating it through ``RunContext.deps`` round-trip back to the session.
    """

    @pytest.mark.asyncio
    async def test_context_injected_as_deps(self):
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"user_id": "42"})

        mock_agent = _mock_agent(output="done")
        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        _, kwargs = mock_agent.agent.run.call_args
        assert kwargs["deps"] == {"user_id": "42"}
        # History handling is unchanged by the injection.
        assert "message_history" in kwargs

    @pytest.mark.asyncio
    async def test_absent_key_passes_deps_none(self):
        """Matches today's implicit behaviour: no context set means the deps default."""
        runner = PydanticAIRunner()
        session = Session("s")

        mock_agent = _mock_agent(output="done")
        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        _, kwargs = mock_agent.agent.run.call_args
        assert kwargs["deps"] is None
        assert session.get_framework_context() is None

    @pytest.mark.asyncio
    async def test_in_place_mutation_written_back(self):
        """A RunContext-taking tool mutating ctx.deps round-trips to the session key."""
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"cart": []})

        mock_result = MagicMock()
        mock_result.output = "done"
        mock_result.all_messages = MagicMock(return_value=[])

        async def fake_run(content, message_history=None, deps=None):
            deps["cart"].append("apple")
            return mock_result

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = fake_run

        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"cart": []})

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=Exception("boom"))

        reply = await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentReplyText)
        assert session.get_framework_context() == {"cart": []}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        """Uses the real run_stream path: a native tool mutates ctx.deps, write-back stores it."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        native = Agent(model=TestModel(custom_output_text="ok"), name="s", deps_type=dict)

        @native.tool
        def add_item(ctx: RunContext[dict], item: str) -> str:
            """Append an item to the caller's cart carried in deps."""
            ctx.deps["cart"].append("apple")
            return "added"

        agent = PydanticAIAgent("s", runner, native)

        deltas = [delta async for delta in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert deltas
        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        """
        A client disconnect (GeneratorExit at a yield) skips the write-back after the delta loop.
        Mocks run_stream because closing the generator from the test task cannot unwind Pydantic AI's
        real anyio cancel scope.
        """
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        mock_agent = _mock_stream_events_agent(
            [_text_start(content="hello"), _text_delta(content=" world"), _text_end()],
            on_stream=lambda deps: deps["cart"].append("apple"),
        )

        agen = runner.stream(mock_agent, session, [AgentRequestText(prompt="hi")])
        first = await agen.__anext__()
        assert first.type == "message_start"
        await agen.aclose()  # simulate client disconnect at the yield

        assert session.get_framework_context() == {"cart": []}

    @pytest.mark.asyncio
    async def test_stream_injects_deps_and_absent_key_passes_none(self):
        runner = PydanticAIRunner()
        session = Session("stream-session")

        _, mock_agent = await _collect(runner, [_text_start(content="hi"), _text_end()], session=session)
        assert mock_agent.captured_deps is None
        assert session.get_framework_context() is None

        session.set_framework_context({"user_id": "42"})
        _, mock_agent = await _collect(runner, [_text_start(content="hi"), _text_end()], session=session)
        assert mock_agent.captured_deps == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A non-picklable context must not turn an already-streamed response into a transport error."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        native = Agent(model=TestModel(custom_output_text="ok"), name="s", deps_type=dict)

        @native.tool
        def stash_callable(ctx: RunContext[dict], item: str) -> str:
            """Store a non-picklable value, standing in for a tool that stashes a live handle."""
            ctx.deps["bad"] = lambda: 1
            return "stashed"

        agent = PydanticAIAgent("s", runner, native)

        with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            deltas = [delta async for delta in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert deltas
        assert session.get_framework_context() == {"cart": []}
        assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


class TestPydanticAIRunnerErrorHandling:
    """Test error handling in PydanticAIRunner.run() method"""

    @pytest.mark.asyncio
    async def test_runner_with_none_reply_returns_empty_string(self):
        """Test that None outputs are converted to empty strings"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]

        reply = await runner.run(_mock_agent(output=None), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == ""

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]
        expected_reply = "The answer is 4"

        reply = await runner.run(_mock_agent(output=expected_reply), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == expected_reply

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that generic exceptions are caught and normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test")]

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=Exception("Something went wrong"))

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        # Error should be normalized - should start with "Error"
        assert reply.response.startswith("Error")

    @pytest.mark.asyncio
    async def test_runner_handles_service_unavailable_error(self):
        """Test that 503 Service Unavailable errors are properly normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test query")]

        class ServiceUnavailableError(Exception):
            def __init__(self):
                super().__init__("Service temporarily unavailable")
                self.status_code = 503

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=ServiceUnavailableError())

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_handles_rate_limit_error(self):
        """Test that rate limit errors are properly normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="too many requests")]

        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("Rate limit exceeded")
                self.status_code = 429

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=RateLimitError())

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_normalizes_numeric_reply(self):
        """Test that numeric outputs are converted to strings"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]

        reply = await runner.run(_mock_agent(output=42), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "42"
        assert isinstance(reply.response, str)

    @pytest.mark.asyncio
    async def test_runner_no_valid_content_short_circuits(self):
        """Test that a request list with no usable content short-circuits without invoking the agent"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent(output="should not be used")

        reply = await runner.run(mock_agent, session, [])

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Sorry. No valid content found in the requests"
        mock_agent.agent.run.assert_not_called()


class TestPydanticAIRunnerStructuredOutput:
    """Test structured output detection on AgentRunResult.output"""

    @pytest.mark.asyncio
    async def test_pydantic_output_returns_agent_reply_any(self):
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        reply = await runner.run(_mock_agent(output=CalendarEvent(name="Launch", date="2026-07-08")), session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"name": "Launch", "date": "2026-07-08"}
        assert reply.prompt == "extract the event"

    @pytest.mark.asyncio
    async def test_dict_output_returns_agent_reply_any(self):
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        reply = await runner.run(_mock_agent(output={"name": "Launch", "date": "2026-07-08"}), session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"name": "Launch", "date": "2026-07-08"}


class TestPydanticAIRunnerStreaming:
    """
    PydanticAIRunner.stream() yields AK events and persists session history from the streamed result,
    mirroring the run() tests. Uses the real TestModel streaming path rather than mocks, so this is
    what proves `run_stream_events` is driven correctly against the real SDK.
    """

    @pytest.mark.asyncio
    async def test_stream_yields_bracketed_events_and_persists_history(self):
        runner = PydanticAIRunner()
        session = Session("stream-session")
        native = Agent(model=TestModel(custom_output_text="hello world from stream"), name="s")
        agent = PydanticAIAgent("s", runner, native)

        events = [event async for event in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        # Real events from the real SDK: the message is bracketed and its deltas reassemble into it.
        assert events
        assert events[0].type == "message_start"
        assert events[-1].type == "message_end"
        assert "".join(e.content for e in events if e.type == "text_delta") == "hello world from stream"
        # One message, so every boundary and delta carries the same id.
        assert len({e.message_id for e in events}) == 1

        # The streamed run persisted its message history into the framework session (jsonable form),
        # so a follow-up turn resumes the conversation just like the run() path.
        fw_session = session.get(FRAMEWORK)
        assert isinstance(fw_session, PydanticAISession)
        assert fw_session.messages
        assert ModelMessagesTypeAdapter.validate_python(fw_session.messages)

    @pytest.mark.asyncio
    async def test_stream_no_valid_content_yields_nothing(self):
        """A request list with no usable content short-circuits before invoking the agent."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        native = Agent(model=TestModel(custom_output_text="unused"), name="s")
        agent = PydanticAIAgent("s", runner, native)

        deltas = [delta async for delta in runner.stream(agent, session, [])]

        assert deltas == []
        assert session.get(FRAMEWORK) is None


class TestPydanticAIRunnerStreamEvents:
    """The event mapping added in PR 6. Every stream is driven by the part events; the ids come from
    the framework where it supplies one and are derived where it does not."""

    @pytest.mark.asyncio
    async def test_a_message_is_bracketed_around_its_deltas(self):
        events, _ = await _collect(PydanticAIRunner(), [_text_start(content="he"), _text_delta(content="llo"), _text_end()])
        assert _shape(events) == ["message_start", "text_delta", "text_delta", "message_end"]
        assert "".join(e.content for e in events if e.type == "text_delta") == "hello"
        assert len({e.message_id for e in events}) == 1

    @pytest.mark.asyncio
    async def test_the_providers_part_id_is_used_when_it_supplies_one(self):
        events, _ = await _collect(PydanticAIRunner(), [_text_start(content="hi", part_id="prov-1"), _text_end()])
        assert {e.message_id for e in events} == {"prov-1"}

    @pytest.mark.asyncio
    async def test_an_empty_start_emits_no_delta(self):
        events, _ = await _collect(PydanticAIRunner(), [_text_start(content=""), _text_end()])
        assert _shape(events) == ["message_start", "message_end"]

    @pytest.mark.asyncio
    async def test_reasoning_maps_to_its_own_stream_and_never_to_the_answer(self):
        """§4 rule 5: reasoning must not reach `StreamChunk.delta`, so it can never be a TextDelta."""
        events, _ = await _collect(PydanticAIRunner(), [_thinking_start(content="th"), _thinking_delta(content="inking"), _thinking_end()])
        assert _shape(events) == ["reasoning_start", "reasoning_delta", "reasoning_delta", "reasoning_end"]
        assert "".join(e.content for e in events if e.type == "reasoning_delta") == "thinking"

    @pytest.mark.asyncio
    async def test_reasoning_and_the_answer_do_not_share_an_id(self):
        events, _ = await _collect(
            PydanticAIRunner(),
            [_thinking_start(index=0, content="t"), _thinking_end(index=0), _text_start(index=1, content="a"), _text_end(index=1)],
        )
        reasoning = {e.message_id for e in events if e.type.startswith("reasoning")}
        answer = {e.message_id for e in events if e.type in ("message_start", "text_delta", "message_end")}
        assert reasoning and answer and not (reasoning & answer)

    @pytest.mark.asyncio
    async def test_a_tool_call_opens_fills_and_closes_on_its_own_id(self):
        events, _ = await _collect(
            PydanticAIRunner(),
            [_tool_start(args=None), _tool_args_delta(args_delta='{"q": "x"}'), _tool_end()],
        )
        assert _shape(events) == ["tool_call_start", "tool_call_args", "tool_call_end"]
        assert {e.tool_call_id for e in events} == {"t1"}
        assert [e.delta for e in events if e.type == "tool_call_args"] == ['{"q": "x"}']

    @pytest.mark.asyncio
    async def test_dict_arguments_are_serialised(self):
        """Providers differ: some stream JSON text, others hand over a parsed dict."""
        events, _ = await _collect(PydanticAIRunner(), [_tool_start(args={"q": "x"}), _tool_end()])
        assert [e.delta for e in events if e.type == "tool_call_args"] == ['{"q": "x"}']

    @pytest.mark.asyncio
    async def test_a_tool_result_correlates_to_the_call(self):
        events, _ = await _collect(PydanticAIRunner(), [_tool_start(), _tool_end(), _tool_result(content="42")])
        assert _shape(events) == ["tool_call_start", "tool_call_end", "tool_call_result"]
        assert {e.tool_call_id for e in events} == {"t1"}
        assert [e.content for e in events if e.type == "tool_call_result"] == ["42"]

    @pytest.mark.asyncio
    async def test_the_tool_call_event_is_ignored_so_calls_are_not_doubled(self):
        """The part events already opened, filled and closed the call — the same reason OpenAI ignores
        `message_output_created`."""
        events, _ = await _collect(
            PydanticAIRunner(),
            [
                _tool_start(args={"q": "x"}),
                _tool_end(),
                FunctionToolCallEvent(part=ToolCallPart(tool_name="lookup", args={"q": "x"}, tool_call_id="t1")),
            ],
        )
        assert _shape(events).count("tool_call_start") == 1

    @pytest.mark.asyncio
    async def test_a_repeated_index_gets_a_new_id_rather_than_colliding(self):
        """The deviation from §10's sketch. `index` is scoped to one response and the SDK states a
        repeat *replaces* the part, so using it as the id would splice two unrelated messages into one
        bubble in any AG-UI client. The old stream is closed before the new one opens."""
        events, _ = await _collect(
            PydanticAIRunner(),
            [_text_start(index=0, content="first"), _text_start(index=0, content="second"), _text_end(index=0)],
        )
        assert _shape(events) == ["message_start", "text_delta", "message_end", "message_start", "text_delta", "message_end"]
        ids = [e.message_id for e in events if e.type == "message_start"]
        assert len(set(ids)) == 2

    @pytest.mark.asyncio
    async def test_a_delta_for_a_part_that_never_opened_is_dropped(self):
        """There is no id to correlate it to, and inventing one strands the fragment in a message no
        boundary describes."""
        events, _ = await _collect(PydanticAIRunner(), [_text_delta(index=7, content="orphan")])
        assert events == []

    @pytest.mark.asyncio
    async def test_an_unclosed_part_is_closed_when_the_stream_drains(self):
        events, _ = await _collect(PydanticAIRunner(), [_text_start(content="hi")])
        assert _shape(events) == ["message_start", "text_delta", "message_end"]

    @pytest.mark.asyncio
    async def test_the_history_write_back_reads_the_terminal_result_event(self):
        """`all_messages()` now comes off the `agent_run_result` event captured as it passed, not off
        the context manager's value."""
        session = Session("stream-session")
        events, _ = await _collect(PydanticAIRunner(), [_text_start(content="hi"), _text_end()], session=session, messages=[{"kind": "request"}])
        assert events
        assert session.get(FRAMEWORK).messages == [{"kind": "request"}]


class TestPydanticAISessionSerialization:
    """
    Serialization round-trip that has no analog in the sibling adapters: their session state is
    plain dicts/strings, but PydanticAISession holds Pydantic AI message history. It is stored in
    the jsonable form (to_jsonable_python) precisely so a BinarySerde pickle survives Pydantic AI's
    fast release cadence — this test guards that the history survives a pickle round-trip intact.
    """

    @staticmethod
    def _real_history() -> list:
        """Produce a non-trivial history of real ModelRequest/ModelResponse instances via TestModel."""

        async def go() -> list:
            agent = Agent(model=TestModel(), name="serde")
            r1 = await agent.run("hello")
            r2 = await agent.run("and again", message_history=r1.all_messages())
            return r2.all_messages()

        return asyncio.run(go())

    def test_session_survives_binaryserde_roundtrip(self):
        messages = self._real_history()
        jsonable = to_jsonable_python(messages)
        assert len(messages) >= 2 and all(isinstance(m, dict) for m in jsonable)

        fw_session = PydanticAISession()
        fw_session.messages = jsonable

        restored: PydanticAISession = BinarySerde.loads(BinarySerde.dumps(fw_session))

        assert isinstance(restored, PydanticAISession)
        assert restored.messages == jsonable
        # The jsonable form reconstructs into real Pydantic AI messages identically.
        reconstructed = ModelMessagesTypeAdapter.validate_python(restored.messages)
        assert len(reconstructed) == len(messages)
        assert to_jsonable_python(reconstructed) == jsonable

    def test_session_nested_in_full_session_roundtrip(self):
        """The stores pickle the whole Session; the PydanticAISession under FRAMEWORK survives it."""
        jsonable = to_jsonable_python(self._real_history())
        session = Session("serde-session")
        fw_session = PydanticAISession()
        fw_session.messages = jsonable
        session.set(FRAMEWORK, fw_session)

        restored_session: Session = BinarySerde.loads(BinarySerde.dumps(session))
        restored_fw = restored_session.get(FRAMEWORK)

        assert isinstance(restored_fw, PydanticAISession)
        assert restored_fw.messages == jsonable


class TestPydanticAIMultimodalWiring:
    """
    Guards design.md's explicit requirement: missing override_system_prompt/attach_tool would make
    multimodal support silently degrade rather than error. With multimodal enabled, both wiring
    points must fire during PydanticAIAgent.__init__ — this test fails loudly if either breaks,
    instead of passing vacuously.
    """

    def test_multimodal_wiring_fires_on_init(self, monkeypatch):
        # Enable multimodal for this test only (monkeypatch restores afterwards).
        monkeypatch.setattr(AKConfig.get().multimodal, "enabled", True)

        # With multimodal on, the system-tool prompt suffix is non-empty — so override_system_prompt
        # has real content to register.
        suffix = SystemToolFactory.get_system_prompt_suffix()
        assert suffix

        native = Agent(model=TestModel(), name="mm", description="multimodal agent")

        # Spy on instructions() — Pydantic AI's instructions have no public read-back, so we assert
        # override_system_prompt fired by observing the decorator registration call itself.
        with mock.patch.object(native, "instructions", wraps=native.instructions) as instructions_spy:
            PydanticAIAgent("mm", PydanticAIRunner(), native)

        # override_system_prompt() invoked the instructions decorator during __init__.
        assert instructions_spy.called

        # attach_tool() registered the multimodal analyze-attachments system tool on the toolset.
        function_toolset = next(ts for ts in native.toolsets if isinstance(ts, FunctionToolset))
        assert any("analyze" in name for name in function_toolset.tools)


class TestPydanticAIAgentDescription:
    """get_description() returns description= when set, else falls back to string instructions."""

    def test_description_returned_when_set(self):
        native = Agent(model=TestModel(), name="d", description="a described agent", instructions="ignored")
        assert PydanticAIAgent("d", PydanticAIRunner(), native).get_description() == "a described agent"

    def test_falls_back_to_instructions_when_description_unset(self):
        native = Agent(model=TestModel(), name="i", instructions="you do math")
        assert PydanticAIAgent("i", PydanticAIRunner(), native).get_description() == "you do math"

    def test_empty_when_neither_set(self):
        native = Agent(model=TestModel(), name="n")
        assert PydanticAIAgent("n", PydanticAIRunner(), native).get_description() == ""
