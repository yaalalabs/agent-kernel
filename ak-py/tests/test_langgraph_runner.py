import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.langgraph.langgraph import LangGraphRunner

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class WeatherResponse(BaseModel):
    city: str
    conditions: str


def _mock_agent(result):
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()
    agent.agent.ainvoke = AsyncMock(return_value=result)
    return agent


def _mock_stream_agent(events, state_values):
    """Agent mock whose astream_events yields the given events and aget_state returns state_values."""
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()

    async def astream_events(input, config, version):
        for event in events:
            yield event

    agent.agent.astream_events = astream_events
    state = MagicMock()
    state.values = state_values
    agent.agent.aget_state = AsyncMock(return_value=state)
    return agent


def _message(content):
    message = MagicMock()
    message.content = content
    return message


def _chunk(content, additional_kwargs=None, model_provider=None, output_version=None):
    """A real `AIMessageChunk`, because the adapter reads `content_blocks`.

    A `MagicMock` would hand back another mock for that property rather than blocks, so the test would
    pin nothing. Building the real object also means these tests pin LangChain's own normalisation
    rather than a shape the adapter wishes for.

    `model_provider` is opt-in because it *changes* that normalisation, which is worth knowing:
    reasoning carried in `additional_kwargs` is only surfaced when the provider is known (without it
    `content_blocks` is empty), while an untyped `{"text": ...}` block normalises to text only when the
    provider is absent. So the reasoning tests set it and the plain-text tests do not, each matching
    the stream they stand in for.
    """
    metadata = {}
    if model_provider:
        metadata["model_provider"] = model_provider
    if output_version:
        metadata["output_version"] = output_version
    return AIMessageChunk(content=content, response_metadata=metadata, additional_kwargs=additional_kwargs or {})


class TestLangGraphRunnerFrameworkContext:
    """framework_context spread into the input state and declared-channel write-back."""

    @pytest.mark.asyncio
    async def test_caller_keys_spread_into_input_and_declared_channels_round_trip(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42", "ephemeral": "x"})
        requests = [AgentRequestText(prompt="hi")]
        # Only 'user_id' is a declared channel that comes back on result; 'ephemeral' is dropped.
        result = {"messages": [_message("hello")], "user_id": "99"}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        input_state = kwargs["input"]
        assert input_state["user_id"] == "42"
        assert input_state["ephemeral"] == "x"
        assert "messages" in input_state

        # 'user_id' round-trips from result; 'ephemeral' keeps its seeded value.
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "99", "ephemeral": "x"}

    @pytest.mark.asyncio
    async def test_messages_not_overwritten_by_context(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"messages": "EVIL"})
        requests = [AgentRequestText(prompt="hi")]
        result = {"messages": [_message("hello")]}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        input_state = kwargs["input"]
        assert input_state["messages"] != "EVIL"
        assert isinstance(input_state["messages"], list)

    @pytest.mark.asyncio
    async def test_absent_key_skips_write_back(self):
        runner = LangGraphRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        result = {"messages": [_message("hello")]}
        agent = _mock_agent(result)

        await runner.run(agent, session, requests)

        _, kwargs = agent.agent.ainvoke.call_args
        assert set(kwargs["input"].keys()) == {"messages"}
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent({})
        agent.agent.ainvoke = AsyncMock(side_effect=Exception("boom"))

        reply = await runner.run(agent, session, requests)

        assert reply.response.startswith("Error")
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        event = {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("tok")}}
        agent = _mock_stream_agent([event], {"user_id": "99"})

        events = [event async for event in runner.stream(agent, session, requests)]

        assert events == [MessageStart(message_id="run-1"), TextDelta(message_id="run-1", content="tok")]
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "99"}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        event = {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("tok")}}
        agent = _mock_stream_agent([event], {"user_id": "99"})

        agen = runner.stream(agent, session, requests)
        assert await agen.__anext__() == MessageStart(message_id="run-1")
        assert await agen.__anext__() == TextDelta(message_id="run-1", content="tok")
        await agen.aclose()  # simulate client disconnect at the yield

        agent.agent.aget_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A failed aget_state must not escape the generator after the response was streamed."""
        runner = LangGraphRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]
        event = {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("tok")}}
        agent = _mock_stream_agent([event], {})
        agent.agent.aget_state = AsyncMock(side_effect=RuntimeError("state read failed"))

        with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            events = [event async for event in runner.stream(agent, session, requests)]

        assert events == [MessageStart(message_id="run-1"), TextDelta(message_id="run-1", content="tok")]
        assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}
        assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


async def _collect(events):
    """Drive LangGraphRunner.stream over a scripted astream_events list and return the AK events."""
    runner = LangGraphRunner()
    session = Session("s")
    requests = [AgentRequestText(prompt="hi")]
    agent = _mock_stream_agent(events, {})
    return [event async for event in runner.stream(agent, session, requests)]


class TestLangGraphRunnerStreamEvents:
    """LangGraphRunner.stream event mapping (ids are LangChain run_ids)."""

    @pytest.mark.asyncio
    async def test_a_message_is_bracketed_around_its_deltas(self):
        events = await _collect(
            [
                {"event": "on_chat_model_start", "run_id": "run-1", "data": {}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("he")}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("llo")}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert events == [
            MessageStart(message_id="run-1"),
            TextDelta(message_id="run-1", content="he"),
            TextDelta(message_id="run-1", content="llo"),
            MessageEnd(message_id="run-1"),
        ]

    @pytest.mark.asyncio
    async def test_a_tool_call_only_turn_emits_no_message_boundaries(self):
        """Empty chat-model turns must not emit MessageStart/End (tool-only turns would otherwise
        bracket an empty assistant message)."""
        events = await _collect(
            [
                {"event": "on_chat_model_start", "run_id": "m1", "data": {}},
                {"event": "on_chat_model_stream", "run_id": "m1", "data": {"chunk": _chunk("")}},
                {"event": "on_chat_model_end", "run_id": "m1", "data": {}},
                {"event": "on_tool_start", "run_id": "t1", "name": "update_state", "data": {"input": {}}},
                {"event": "on_tool_end", "run_id": "t1", "data": {"output": "ok"}},
            ]
        )
        assert [e.type for e in events] == ["tool_call_start", "tool_call_args", "tool_call_end", "tool_call_result"]

    @pytest.mark.asyncio
    async def test_two_model_calls_do_not_share_a_message_id(self):
        """Nested model calls use distinct run_ids; `started` is keyed per id so an inner end
        does not close the outer message."""
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "outer", "data": {"chunk": _chunk("o")}},
                {"event": "on_chat_model_stream", "run_id": "inner", "data": {"chunk": _chunk("i")}},
                {"event": "on_chat_model_end", "run_id": "inner", "data": {}},
                {"event": "on_chat_model_end", "run_id": "outer", "data": {}},
            ]
        )
        assert [(e.type, e.message_id) for e in events] == [
            ("message_start", "outer"),
            ("text_delta", "outer"),
            ("message_start", "inner"),
            ("text_delta", "inner"),
            ("message_end", "inner"),
            ("message_end", "outer"),
        ]

    @pytest.mark.asyncio
    async def test_a_list_content_chunk_yields_only_its_text_blocks(self):
        """List content blocks: keep text, skip non-text blocks."""
        chunk = _chunk([{"text": "a"}, {"type": "tool_use"}, {"text": "b"}])
        events = await _collect([{"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": chunk}}])
        assert events == [
            MessageStart(message_id="run-1"),
            TextDelta(message_id="run-1", content="a"),
            TextDelta(message_id="run-1", content="b"),
        ]

    @pytest.mark.asyncio
    async def test_an_empty_chunk_is_dropped_rather_than_forwarded(self):
        events = await _collect([{"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("")}}])
        assert events == []

    @pytest.mark.asyncio
    async def test_a_tool_call_opens_fills_and_closes_on_its_run_id(self):
        events = await _collect([{"event": "on_tool_start", "run_id": "tool-1", "name": "lookup", "data": {"input": {"q": "x"}}}])
        assert events == [
            ToolCallStart(tool_call_id="tool-1", name="lookup"),
            ToolCallArgs(tool_call_id="tool-1", delta='{"q": "x"}'),
            ToolCallEnd(tool_call_id="tool-1"),
        ]

    @pytest.mark.asyncio
    async def test_tool_arguments_that_cannot_be_serialised_yield_no_args_event(self):
        """Unserialisable tool input → no ToolCallArgs; call still bracketed."""

        class Unserialisable:
            def __repr__(self):
                raise RuntimeError("nope")

        events = await _collect([{"event": "on_tool_start", "run_id": "tool-1", "name": "lookup", "data": {"input": {"q": Unserialisable()}}}])
        assert events == [ToolCallStart(tool_call_id="tool-1", name="lookup"), ToolCallEnd(tool_call_id="tool-1")]

    @pytest.mark.asyncio
    async def test_a_tool_result_prefers_the_tool_messages_content(self):
        message = MagicMock()
        message.content = "42"
        events = await _collect([{"event": "on_tool_end", "run_id": "tool-1", "data": {"output": message}}])
        assert events == [ToolCallResult(tool_call_id="tool-1", content="42")]

    @pytest.mark.asyncio
    async def test_a_bare_tool_output_is_stringified(self):
        events = await _collect([{"event": "on_tool_end", "run_id": "tool-1", "data": {"output": 42}}])
        assert events == [ToolCallResult(tool_call_id="tool-1", content="42")]

    @pytest.mark.asyncio
    async def test_chain_and_prompt_events_map_to_nothing(self):
        """on_chain_* / on_prompt_* are not mapped to steps."""
        events = await _collect(
            [
                {"event": "on_chain_start", "run_id": "c1", "name": "agent", "data": {}},
                {"event": "on_prompt_end", "run_id": "p1", "data": {}},
                {"event": "on_chain_end", "run_id": "c1", "name": "agent", "data": {}},
            ]
        )
        assert events == []


def _reasoning_chunk(text, **kwargs):
    """A chunk whose only content is a reasoning block carrying `text`."""
    return _chunk([{"type": "reasoning", "id": "rs", "reasoning": text}], model_provider="openai", **kwargs)


class TestLangGraphRunnerReasoning:
    """Reasoning mapping.

    The adapter used to read `chunk.content`, where `ChatOpenAI` reasoning never appears — it arrives in
    `additional_kwargs` with `content` left empty, so nothing was ever emitted and the gap was recorded
    as "LangGraph reports no reasoning". `content_blocks` is what surfaces it.

    Reasoning ids are generated rather than read off the block, so these assert the *shape* and the id
    relationships, never a literal id.
    """

    @pytest.mark.asyncio
    async def test_reasoning_is_bracketed_around_its_deltas_on_its_own_id(self):
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("weigh")}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("ing")}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert [e.type for e in events] == ["reasoning_start", "reasoning_delta", "reasoning_delta", "reasoning_end"]
        assert [e.content for e in events if isinstance(e, ReasoningDelta)] == ["weigh", "ing"]

        # One id for the whole trace, and it is not the run_id the message stream would have used.
        ids = {e.message_id for e in events}
        assert len(ids) == 1
        assert ids != {"run-1"}

    @pytest.mark.asyncio
    async def test_reasoning_in_additional_kwargs_is_found(self):
        """The decisive case, and the reason this mapping exists.

        This is the live `ChatOpenAI` shape: reasoning in `additional_kwargs`, raw `content` an empty
        list. A filter over `content` cannot find it no matter how it is written, so this test fails
        against any adapter that reads `content` instead of `content_blocks`.
        """
        chunk = _chunk(
            [],
            model_provider="openai",
            additional_kwargs={"reasoning": {"id": "rs_1", "type": "reasoning", "summary": [{"type": "summary_text", "text": "weighing options"}]}},
        )
        assert chunk.content == []  # the point: there is nothing here to filter

        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": chunk}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert [e.type for e in events] == ["reasoning_start", "reasoning_delta", "reasoning_end"]
        assert [e.content for e in events if isinstance(e, ReasoningDelta)] == ["weighing options"]

    @pytest.mark.asyncio
    async def test_a_summary_shaped_block_is_read_when_content_blocks_leaves_it_alone(self):
        """At `output_version="v1"` the block keeps `summary[]` and carries no `reasoning` key.

        `content_blocks` normalises the summary into `reasoning` at the default output version but
        passes it through untouched at v1, so a reader of `reasoning` alone silently finds nothing.
        """
        chunk = _chunk(
            [{"type": "reasoning", "id": "rs", "summary": [{"type": "summary_text", "text": "from "}, {"type": "summary_text", "text": "summary"}]}],
            model_provider="openai",
            output_version="v1",
        )
        assert all("reasoning" not in block for block in chunk.content_blocks)  # nothing under the usual key

        events = await _collect([{"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": chunk}}])
        assert [e.content for e in events if isinstance(e, ReasoningDelta)] == ["from summary"]

    @pytest.mark.asyncio
    async def test_answer_text_closes_reasoning_and_the_two_never_share_an_id(self):
        """Thinking is over once the model starts answering, so the answer closes the trace first."""
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("hmm")}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("Hi")}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert [e.type for e in events] == [
            "reasoning_start",
            "reasoning_delta",
            "reasoning_end",
            "message_start",
            "text_delta",
            "message_end",
        ]
        thinking = {e.message_id for e in events if e.type.startswith("reasoning_")}
        answer = {e.message_id for e in events if e.type in ("message_start", "text_delta", "message_end")}
        assert answer == {"run-1"}
        assert not (thinking & answer)

    @pytest.mark.asyncio
    async def test_reasoning_after_the_answer_opens_a_second_trace(self):
        """Reasoning that resumes after a tool call is a new trace, not a reopening of the closed one."""
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("first")}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _chunk("answer")}},
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("second")}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert [e.type for e in events].count("reasoning_start") == 2
        traces = [e.message_id for e in events if e.type == "reasoning_start"]
        assert traces[0] != traces[1]

    @pytest.mark.asyncio
    async def test_a_reasoning_only_turn_opens_no_message(self):
        """§4 rule 4: a turn that produced no prose must not render as an empty assistant bubble."""
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "run-1", "data": {"chunk": _reasoning_chunk("thinking")}},
                {"event": "on_chat_model_end", "run_id": "run-1", "data": {}},
            ]
        )
        assert [e.type for e in events] == ["reasoning_start", "reasoning_delta", "reasoning_end"]
        assert not [e for e in events if e.type in ("message_start", "message_end")]

    @pytest.mark.asyncio
    async def test_two_concurrent_runs_do_not_share_a_reasoning_id(self):
        """The analogue of `test_two_model_calls_do_not_share_a_message_id`, guarding the new local.

        `reasoning` is keyed per run id and lives inside `stream()`, so a nested model call gets its own
        trace and one call's end cannot close another's.
        """
        events = await _collect(
            [
                {"event": "on_chat_model_stream", "run_id": "outer", "data": {"chunk": _reasoning_chunk("o")}},
                {"event": "on_chat_model_stream", "run_id": "inner", "data": {"chunk": _reasoning_chunk("i")}},
                {"event": "on_chat_model_end", "run_id": "inner", "data": {}},
                {"event": "on_chat_model_end", "run_id": "outer", "data": {}},
            ]
        )
        starts = {e.message_id for e in events if isinstance(e, ReasoningStart)}
        assert len(starts) == 2

        # The inner end closes only the inner trace; the outer one is still open to close afterwards.
        ends = [e.message_id for e in events if isinstance(e, ReasoningEnd)]
        assert len(ends) == 2 and ends[0] != ends[1]
        outer_id = next(e.message_id for e in events if isinstance(e, ReasoningStart))
        assert ends[-1] == outer_id


class TestLangGraphRunnerStructuredOutput:
    """Test structured output detection via the structured_response result key"""

    @pytest.mark.asyncio
    async def test_structured_response_model_returns_agent_reply_any(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="weather in Colombo?")]
        result = {
            "messages": [_message("WeatherResponse(city='Colombo', conditions='sunny')")],
            "structured_response": WeatherResponse(city="Colombo", conditions="sunny"),
        }
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"city": "Colombo", "conditions": "sunny"}
        assert reply.prompt == "weather in Colombo?"

    @pytest.mark.asyncio
    async def test_structured_response_dict_returns_agent_reply_any(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="weather?")]
        result = {
            "messages": [_message("...")],
            "structured_response": {"city": "Colombo", "conditions": "sunny"},
        }
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"city": "Colombo", "conditions": "sunny"}

    @pytest.mark.asyncio
    async def test_without_structured_response_returns_last_message_text(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]
        result = {"messages": [_message("first"), _message("Hi there!")]}
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Hi there!"
        assert reply.prompt == "hello"
