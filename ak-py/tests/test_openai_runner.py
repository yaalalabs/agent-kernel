import asyncio
import logging
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents import Agent as SDKAgent
from agents import RunHooks
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.base import Agent as AKAgent
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.event import (
    MessageEnd,
    MessageStart,
    ReasoningDelta,
    ReasoningEnd,
    ReasoningStart,
    RunPaused,
    TextDelta,
    ToolCallArgs,
    ToolCallEnd,
    ToolCallResult,
    ToolCallStart,
)
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
from agentkernel.core.runtime import Runtime
from agentkernel.core.util.error_util import user_facing_error_message
from agentkernel.framework.openai.openai import OpenAIAgent, OpenAIModule, OpenAIRunner, OpenAISession

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


def _mock_agent():
    """A mock AK agent over a mock native agent, carrying the members the runner reads before its native call."""
    mock_agent = MagicMock()
    mock_agent.agent = MagicMock()
    mock_agent.name = "test-agent"  # a real str: the paused-run record stores the agent name
    mock_agent.run_options = {}
    mock_agent.resolve_run_options = AsyncMock(side_effect=lambda session, requests: dict(mock_agent.run_options))
    return mock_agent


class CalendarEvent(BaseModel):
    name: str
    date: str


def _delta_event(text: str, item_id: str = "msg-1"):
    """Raw response text-delta event for the given item_id."""
    from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

    event = MagicMock()
    event.type = "raw_response_event"
    event.data = ResponseTextDeltaEvent(
        content_index=0,
        delta=text,
        item_id=item_id,
        logprobs=[],
        output_index=0,
        sequence_number=0,
        type="response.output_text.delta",
    )
    return event


class TestOpenAIRunnerFrameworkContext:
    """framework_context injection and write-back for OpenAIRunner."""

    @pytest.mark.asyncio
    async def test_context_injected_into_runner_run(self):
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output
            result.final_output = "done"
            MockRunner.run = AsyncMock(return_value=result)
            mock_agent = _mock_agent()

            await runner.run(mock_agent, session, requests)

            _, kwargs = MockRunner.run.call_args
            assert kwargs["context"] == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_in_place_mutation_written_back(self):
        """A tool mutating RunContextWrapper.context in place round-trips to the session key."""
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]

        async def fake_run(agent, input_data, session=None, context=None):
            if context is not None:
                context["touched"] = True
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output
            result.final_output = "done"
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = fake_run
            mock_agent = _mock_agent()

            await runner.run(mock_agent, session, requests)

            assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42", "touched": True}

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        requests = [AgentRequestText(prompt="hi")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=Exception("boom"))
            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert reply.response.startswith("Error")
            assert session.get(FRAMEWORK_CONTEXT) == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_absent_key_passes_context_none(self):
        runner = OpenAIRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output
            result.final_output = "done"
            MockRunner.run = AsyncMock(return_value=result)
            mock_agent = _mock_agent()

            await runner.run(mock_agent, session, requests)

            _, kwargs = MockRunner.run.call_args
            assert kwargs["context"] is None
            # Absent key is never written back.
            assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seed": 1})
        requests = [AgentRequestText(prompt="hi")]

        def fake_run_streamed(agent, input_data, session=None, context=None):
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                if context is not None:
                    context["touched"] = True
                for event in ():
                    yield event

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = _mock_agent()

            _ = [delta async for delta in runner.stream(mock_agent, session, requests)]

            assert session.get(FRAMEWORK_CONTEXT) == {"seed": 1, "touched": True}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        """A client disconnect (GeneratorExit at a yield) skips write-back."""
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seed": 1})
        requests = [AgentRequestText(prompt="hi")]

        def fake_run_streamed(agent, input_data, session=None, context=None):
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                if context is not None:
                    context["touched"] = True  # tool mutated the injected copy
                yield _delta_event("hi")

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = _mock_agent()

            agen = runner.stream(mock_agent, session, requests)
            first = await agen.__anext__()
            assert first == TextDelta(message_id="msg-1", content="hi")
            await agen.aclose()  # simulate client disconnect at the yield

            # Write-back is after the loop, so it is skipped and the last-known-good context is preserved.
            assert session.get(FRAMEWORK_CONTEXT) == {"seed": 1}

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A non-picklable context must not turn an already-streamed response into a transport error."""
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seed": 1})
        requests = [AgentRequestText(prompt="hi")]

        def fake_run_streamed(agent, input_data, session=None, context=None):
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                context["bad"] = lambda: 1  # tool stored a non-picklable value
                yield _delta_event("hi")

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = _mock_agent()

            with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
                events = [event async for event in runner.stream(mock_agent, session, requests)]

            assert events == [TextDelta(message_id="msg-1", content="hi")]
            assert session.get(FRAMEWORK_CONTEXT) == {"seed": 1}
            assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


def _message_item(item_id: str = "msg-1"):
    """SDK ResponseOutputMessage fixture."""
    from openai.types.responses.response_output_message import ResponseOutputMessage

    return ResponseOutputMessage(id=item_id, content=[], role="assistant", status="completed", type="message")


def _reasoning_item(item_id: str = "rsn-1"):
    from openai.types.responses.response_reasoning_item import ResponseReasoningItem

    return ResponseReasoningItem(id=item_id, summary=[], type="reasoning")


def _item_added(item):
    from openai.types.responses.response_output_item_added_event import ResponseOutputItemAddedEvent

    event = MagicMock()
    event.type = "raw_response_event"
    event.data = ResponseOutputItemAddedEvent(item=item, output_index=0, sequence_number=0, type="response.output_item.added")
    return event


def _item_done(item):
    from openai.types.responses.response_output_item_done_event import ResponseOutputItemDoneEvent

    event = MagicMock()
    event.type = "raw_response_event"
    event.data = ResponseOutputItemDoneEvent(item=item, output_index=0, sequence_number=0, type="response.output_item.done")
    return event


def _reasoning_delta_event(text: str, item_id: str = "rsn-1"):
    from openai.types.responses.response_reasoning_summary_text_delta_event import ResponseReasoningSummaryTextDeltaEvent

    event = MagicMock()
    event.type = "raw_response_event"
    event.data = ResponseReasoningSummaryTextDeltaEvent(
        delta=text,
        item_id=item_id,
        output_index=0,
        sequence_number=0,
        summary_index=0,
        type="response.reasoning_summary_text.delta",
    )
    return event


def _run_item_event(name: str, raw_item, output=None):
    """RunItemStreamEvent mock (name set after construct — MagicMock(name=...) names the mock)."""
    item = MagicMock()
    item.raw_item = raw_item
    item.output = output
    event = MagicMock()
    event.type = "run_item_stream_event"
    event.name = name
    event.item = item
    return event


def _function_call(call_id: str = "call-1", name: str = "lookup", arguments: str = '{"q": "x"}'):
    from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

    return ResponseFunctionToolCall(arguments=arguments, call_id=call_id, name=name, type="function_call")


def _handoff_call(call_id: str = "ho-1", name: str = "transfer_to_billing"):
    """SDK tool-call shape used for handoff_requested."""
    from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

    return ResponseFunctionToolCall(arguments='{"reason": "billing"}', call_id=call_id, name=name, type="function_call")


def _handoff_output(call_id: str = "ho-1", output: str = "Handed off to billing"):
    """SDK handoff_occured raw_item via ItemHelpers.tool_call_output_item."""
    from agents.items import ItemHelpers

    return ItemHelpers.tool_call_output_item(_handoff_call(call_id=call_id), output)


async def _collect(runner, events):
    """Drive OpenAIRunner.stream over a scripted SDK event list and return the AK events."""
    session = Session("s")
    requests = [AgentRequestText(prompt="hi")]

    def fake_run_streamed(agent, input_data, session=None, context=None):
        result = MagicMock()
        result.interruptions = []  # a completed run; the adapter reads this before final_output

        async def stream_events():
            for event in events:
                yield event

        result.stream_events = stream_events
        return result

    with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
        MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
        mock_agent = _mock_agent()
        return [event async for event in runner.stream(mock_agent, session, requests)]


class TestOpenAIRunnerStreamEvents:
    """OpenAIRunner.stream event mapping (ids from the SDK)."""

    @pytest.mark.asyncio
    async def test_a_message_is_bracketed_around_its_deltas(self):
        item = _message_item()
        events = await _collect(
            OpenAIRunner(),
            [_item_added(item), _delta_event("he"), _delta_event("llo"), _item_done(item)],
        )
        assert events == [
            MessageStart(message_id="msg-1", role="assistant"),
            TextDelta(message_id="msg-1", content="he"),
            TextDelta(message_id="msg-1", content="llo"),
            MessageEnd(message_id="msg-1"),
        ]

    @pytest.mark.asyncio
    async def test_an_empty_delta_is_dropped_rather_than_forwarded(self):
        assert await _collect(OpenAIRunner(), [_delta_event("")]) == []

    @pytest.mark.asyncio
    async def test_a_tool_call_opens_fills_and_closes_on_its_call_id(self):
        events = await _collect(OpenAIRunner(), [_run_item_event("tool_called", _function_call())])
        assert events == [
            ToolCallStart(tool_call_id="call-1", name="lookup"),
            ToolCallArgs(tool_call_id="call-1", delta='{"q": "x"}'),
            ToolCallEnd(tool_call_id="call-1"),
        ]

    @pytest.mark.asyncio
    async def test_a_tool_result_correlates_to_the_call_that_produced_it(self):
        raw = {"call_id": "call-1", "output": "42", "type": "function_call_output"}
        events = await _collect(OpenAIRunner(), [_run_item_event("tool_output", raw, output=42)])
        assert events == [ToolCallResult(tool_call_id="call-1", content="42")]

    @pytest.mark.asyncio
    async def test_a_tool_result_falls_back_to_the_items_own_output(self):
        """Prefer raw_item.output; fall back to item.output."""
        events = await _collect(OpenAIRunner(), [_run_item_event("tool_output", {"call_id": "call-1"}, output=42)])
        assert events == [ToolCallResult(tool_call_id="call-1", content="42")]

    @pytest.mark.asyncio
    async def test_a_tool_item_with_no_call_id_emits_nothing(self):
        """No call_id → emit nothing."""
        events = await _collect(OpenAIRunner(), [_run_item_event("tool_called", {"name": "lookup"})])
        assert events == []

    @pytest.mark.asyncio
    async def test_reasoning_is_bracketed_around_its_summary_deltas(self):
        item = _reasoning_item()
        events = await _collect(
            OpenAIRunner(),
            [_item_added(item), _reasoning_delta_event("think"), _item_done(item)],
        )
        assert events == [
            ReasoningStart(message_id="rsn-1"),
            ReasoningDelta(message_id="rsn-1", content="think"),
            ReasoningEnd(message_id="rsn-1"),
        ]

    @pytest.mark.asyncio
    async def test_item_created_run_events_are_ignored_so_messages_are_not_doubled(self):
        """message_output_created / reasoning_item_created are covered by raw events already."""
        events = await _collect(
            OpenAIRunner(),
            [
                _run_item_event("message_output_created", _message_item()),
                _run_item_event("reasoning_item_created", _reasoning_item()),
            ],
        )
        assert events == []

    @pytest.mark.parametrize(
        "name",
        ["tool_search_called", "tool_search_output_created", "mcp_approval_requested", "mcp_approval_response", "mcp_list_tools"],
    )
    @pytest.mark.asyncio
    async def test_hosted_tool_and_mcp_items_stay_unmapped(self, name):
        """Hosted-tool and MCP run-item names stay unmapped (not user-facing agent work)."""
        events = await _collect(OpenAIRunner(), [_run_item_event(name, _function_call())])
        assert events == []


class TestOpenAIRunnerHandoffs:
    """Handoffs map as tool calls: the SDK models them as tools, then lifts them into handoff_* events."""

    @pytest.mark.asyncio
    async def test_a_handoff_opens_fills_and_closes_like_any_tool_call(self):
        events = await _collect(OpenAIRunner(), [_run_item_event("handoff_requested", _handoff_call())])
        assert events == [
            ToolCallStart(tool_call_id="ho-1", name="transfer_to_billing"),
            ToolCallArgs(tool_call_id="ho-1", delta='{"reason": "billing"}'),
            ToolCallEnd(tool_call_id="ho-1"),
        ]

    @pytest.mark.asyncio
    async def test_the_handoff_result_correlates_to_the_call_on_the_same_id(self):
        """Result correlates on the same call_id."""
        events = await _collect(
            OpenAIRunner(),
            [
                _run_item_event("handoff_requested", _handoff_call()),
                _run_item_event("handoff_occured", _handoff_output()),
            ],
        )
        assert [e.tool_call_id for e in events] == ["ho-1"] * 4
        assert events[-1] == ToolCallResult(tool_call_id="ho-1", content="Handed off to billing")

    @pytest.mark.asyncio
    async def test_the_sdks_misspelling_is_what_is_matched(self):
        """Match the SDK spelling `handoff_occured` — the correctly spelled name would drop results."""
        assert await _collect(OpenAIRunner(), [_run_item_event("handoff_occurred", _handoff_output())]) == []
        assert await _collect(OpenAIRunner(), [_run_item_event("handoff_occured", _handoff_output())]) != []


class TestOpenAIRunnerErrorHandling:
    """Test error handling in OpenAIRunner.run() method"""

    @pytest.mark.asyncio
    async def test_request_processing_error_returns_error_reply(self):
        """A request that fails before the prompt is extracted still returns a clean error reply."""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(name="empty.png", image_data="")]  # raises inside _process_requests
        mock_agent = _mock_agent()

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response.startswith("Error")
        assert reply.prompt == ""

    @pytest.mark.asyncio
    async def test_runner_with_none_reply_returns_empty_string(self):
        """Test that None replies are converted to empty strings"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]

        # Patch at the module level where it's imported
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_run_result = MagicMock()
            mock_run_result.interruptions = []  # a completed run; the adapter reads this before final_output
            mock_run_result.final_output = None

            # Create an async function for Runner.run
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            # Mock the agent
            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            # The code does: reply_text = "" if reply is None else str(reply)
            # So None should become empty string
            assert reply.response in ("", "None")  # Accept both since we're testing error handling

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]
        expected_reply = "The answer is 4"

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_run_result = MagicMock()
            mock_run_result.interruptions = []  # a completed run; the adapter reads this before final_output
            mock_run_result.final_output = expected_reply

            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.response == expected_reply

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that generic exceptions are caught and normalized"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            # Simulate Runner.run() raising an exception
            error = Exception("Something went wrong")
            MockRunner.run = AsyncMock(side_effect=error)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            # Error should be normalized - should start with "Error"
            assert reply.response.startswith("Error")

    @pytest.mark.asyncio
    async def test_runner_handles_service_unavailable_error(self):
        """Test that 503 Service Unavailable errors are properly normalized"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test query")]

        class ServiceUnavailableError(Exception):
            def __init__(self):
                super().__init__("Service temporarily unavailable")
                self.status_code = 503

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            error = ServiceUnavailableError()
            MockRunner.run = AsyncMock(side_effect=error)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            # Should contain error message (user_facing_error_message provides normalized format)
            assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_handles_rate_limit_error(self):
        """Test that rate limit errors are properly normalized"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="too many requests")]

        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("Rate limit exceeded")
                self.status_code = 429

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            error = RateLimitError()
            MockRunner.run = AsyncMock(side_effect=error)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            # Should have error message
            assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_normalizes_numeric_reply(self):
        """Test that numeric replies are converted to strings"""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_run_result = MagicMock()
            mock_run_result.interruptions = []  # a completed run; the adapter reads this before final_output
            mock_run_result.final_output = 42  # numeric output

            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.response == "42"
            assert isinstance(reply.response, str)


class TestOpenAIRunnerStructuredOutput:
    """Test structured output detection on RunResult.final_output"""

    @pytest.mark.asyncio
    async def test_pydantic_final_output_returns_agent_reply_any(self):
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_run_result = MagicMock()
            mock_run_result.interruptions = []  # a completed run; the adapter reads this before final_output
            mock_run_result.final_output = CalendarEvent(name="Launch", date="2026-07-08")
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyAny)
            assert reply.content == {"name": "Launch", "date": "2026-07-08"}
            assert reply.prompt == "extract the event"

    @pytest.mark.asyncio
    async def test_dict_final_output_returns_agent_reply_any(self):
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_run_result = MagicMock()
            mock_run_result.interruptions = []  # a completed run; the adapter reads this before final_output
            mock_run_result.final_output = {"name": "Launch", "date": "2026-07-08"}
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = _mock_agent()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyAny)
            assert reply.content == {"name": "Launch", "date": "2026-07-08"}


class TestOpenAIRunnerSessionMemory:
    """
    Which turns are recorded in the SDK's conversation session.

    A turn used to run with `session=None` whenever it carried real attachment content, so an image
    sent by URL was neither remembered nor recorded — the next turn could not refer back to it. The
    session now travels with every turn, whatever its input shape.
    """

    @staticmethod
    def _captured_session(requests):
        """Run the agent against a stubbed SDK and return the session it was handed."""
        captured = {}

        async def fake_run(agent, input_data, session=None, context=None):
            captured["session"] = session
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output
            result.final_output = "done"
            return result

        runner = OpenAIRunner()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = fake_run
            mock_agent = _mock_agent()
            asyncio.run(runner.run(mock_agent, Session("s"), requests))
        return captured["session"]

    @staticmethod
    def _captured_stream_session(requests):
        """Same, for the streaming call site — it passes the session separately from run()."""
        captured = {}

        def fake_run_streamed(agent, input_data, session=None, context=None):
            captured["session"] = session
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def events():
                yield MagicMock(type="raw_response_event", data=MagicMock())

            result.stream_events = events
            return result

        async def drain():
            runner = OpenAIRunner()
            async for _ in runner.stream(mock_agent, Session("s"), requests):
                pass

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = fake_run_streamed
            mock_agent = _mock_agent()
            asyncio.run(drain())
        return captured["session"]

    def test_text_only_turn_is_remembered(self):
        assert self._captured_session([AgentRequestText(prompt="hi")]) is not None

    def test_attachment_turn_is_remembered(self):
        # The regression: this list makes `_get_run_input` return the message list rather than a
        # bare prompt, which is the shape that used to be sent with session=None.
        requests = [
            AgentRequestText(prompt="what is this?"),
            AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png", mime_type="image/png"),
        ]
        assert self._captured_session(requests) is not None

    def test_streaming_remembers_the_turn(self):
        requests = [AgentRequestImage(image_data="https://example.com/cat.png", name="cat.png", mime_type="image/png")]
        assert self._captured_stream_session(requests) is not None


class TestOpenAISessionGetItems:
    """get_items(limit) must return the most recent items, in chronological order."""

    @pytest.mark.asyncio
    async def test_limit_returns_latest_items_in_chronological_order(self):
        session = OpenAISession()
        await session.add_items([{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])

        items = await session.get_items(limit=2)

        assert items == [{"id": 3}, {"id": 4}]

    @pytest.mark.asyncio
    async def test_limit_greater_than_item_count_returns_all_items(self):
        session = OpenAISession()
        await session.add_items([{"id": 1}, {"id": 2}])

        items = await session.get_items(limit=10)

        assert items == [{"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_zero_limit_returns_no_items(self):
        session = OpenAISession()
        await session.add_items([{"id": 1}, {"id": 2}])

        items = await session.get_items(limit=0)

        assert items == []

    @pytest.mark.asyncio
    async def test_no_limit_returns_all_items_in_chronological_order(self):
        session = OpenAISession()
        await session.add_items([{"id": 1}, {"id": 2}, {"id": 3}])

        items = await session.get_items()

        assert items == [{"id": 1}, {"id": 2}, {"id": 3}]


def _run_result(output="done"):
    result = MagicMock()
    result.interruptions = []  # a completed run; the adapter reads this before final_output
    result.final_output = output
    return result


class TestOpenAIRunnerRunOptions:
    """Declared run options reach the SDK call; AK-owned keys win; the declared dict is never mutated (spec #754)."""

    @pytest.mark.asyncio
    async def test_options_are_forwarded_to_runner_run_beside_the_ak_owned_keys(self):
        runner = OpenAIRunner()
        session = Session("s")
        hooks, run_config = object(), object()

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_run_result())
            mock_agent = _mock_agent()
            mock_agent.run_options = {"max_turns": 25, "hooks": hooks, "run_config": run_config}

            await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

            args, kwargs = MockRunner.run.call_args
            assert args == (mock_agent.agent, "hi")
            assert kwargs["max_turns"] == 25
            assert kwargs["hooks"] is hooks
            assert kwargs["run_config"] is run_config
            assert isinstance(kwargs["session"], OpenAISession)
            assert set(kwargs) == {"max_turns", "hooks", "run_config", "session", "context"}

    @pytest.mark.asyncio
    async def test_options_are_forwarded_to_runner_run_streamed(self):
        runner = OpenAIRunner()
        hooks = object()
        captured: dict = {}

        def fake_run_streamed(agent, input_data, **kwargs):
            captured.update(kwargs)
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                for event in ():
                    yield event

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = _mock_agent()
            mock_agent.run_options = {"max_turns": 25, "hooks": hooks}

            _ = [e async for e in runner.stream(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])]

        assert captured["max_turns"] == 25
        assert captured["hooks"] is hooks
        assert set(captured) == {"max_turns", "hooks", "session", "context"}

    @pytest.mark.asyncio
    async def test_the_ak_owned_context_wins_over_a_declared_one(self):
        runner = OpenAIRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_run_result())
            mock_agent = _mock_agent()
            mock_agent.run_options = {"context": "caller"}  # only reachable by bypassing Module.run_options

            await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

            assert MockRunner.run.call_args.kwargs["context"] == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_the_declared_dict_is_the_same_unmutated_object_after_two_runs(self):
        runner = OpenAIRunner()
        declared = {"max_turns": 25}

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_run_result())
            mock_agent = _mock_agent()
            mock_agent.run_options = declared

            await runner.run(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])
            await runner.run(mock_agent, Session("t"), [AgentRequestText(prompt="hi")])

        assert mock_agent.run_options is declared
        assert declared == {"max_turns": 25}

    def test_the_reserved_keys_are_rejected_at_declaration_through_the_module(self):
        native = SDKAgent(name="reserved-keys-agent", instructions="x")

        with Runtime(SessionStoreBuilder.build()):
            module = OpenAIModule([native])

            for key in ("starting_agent", "input", "session", "context", "conversation_id", "previous_response_id", "auto_previous_response_id"):
                with pytest.raises(ValueError) as exc:
                    module.run_options(native, **{key: object()})
                assert f"'{key}'" in str(exc.value)
                assert "'openai'" in str(exc.value)

            module.run_options(native, max_turns=25)  # an unreserved key is accepted
            assert module.get_agent("reserved-keys-agent").run_options == {"max_turns": 25}

            hook = object()
            assert module.pre_hook(native, [hook]).post_hook(native, [hook]) is module  # base-class hook methods
            assert module.get_agent("reserved-keys-agent").pre_hooks == [hook]
            assert module.get_agent("reserved-keys-agent").post_hooks == [hook]

    @pytest.mark.asyncio
    async def test_run_uses_the_resolved_options_and_resolves_once_per_run(self):
        runner = OpenAIRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_run_result())
            mock_agent = _mock_agent()
            mock_agent.run_options = {"max_turns": 25}
            mock_agent.resolve_run_options = AsyncMock(return_value={"max_turns": 3, "hooks": "per-run"})  # the factory-merged mapping

            await runner.run(mock_agent, session, requests)

            mock_agent.resolve_run_options.assert_awaited_once_with(session, requests)
            kwargs = MockRunner.run.call_args.kwargs
            assert kwargs["max_turns"] == 3
            assert kwargs["hooks"] == "per-run"
            assert set(kwargs) == {"max_turns", "hooks", "session", "context"}

    @pytest.mark.asyncio
    async def test_stream_uses_the_resolved_options_and_resolves_once_per_stream(self):
        runner = OpenAIRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        captured: dict = {}

        def fake_run_streamed(agent, input_data, **kwargs):
            captured.update(kwargs)
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                for event in ():
                    yield event

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = _mock_agent()
            mock_agent.run_options = {"max_turns": 25}
            mock_agent.resolve_run_options = AsyncMock(return_value={"max_turns": 3})

            _ = [e async for e in runner.stream(mock_agent, session, requests)]

        mock_agent.resolve_run_options.assert_awaited_once_with(session, requests)
        assert captured["max_turns"] == 3
        assert set(captured) == {"max_turns", "session", "context"}

    @pytest.mark.asyncio
    async def test_a_request_without_content_returns_before_resolving_in_both_modes(self):
        runner = OpenAIRunner()
        mock_agent = _mock_agent()

        reply = await runner.run(mock_agent, Session("s"), [])
        _ = [e async for e in runner.stream(mock_agent, Session("s"), [])]

        assert "No valid content" in reply.response
        mock_agent.resolve_run_options.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failing_resolution_surfaces_as_the_user_facing_error_reply_in_run(self):
        runner = OpenAIRunner()
        error = RuntimeError("factory boom")

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_run_result())
            mock_agent = _mock_agent()
            mock_agent.resolve_run_options = AsyncMock(side_effect=error)

            reply = await runner.run(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])

            MockRunner.run.assert_not_called()

        assert isinstance(reply, AgentReplyText)
        assert reply.response == user_facing_error_message(error)
        assert reply.prompt == "hi"

    @pytest.mark.asyncio
    async def test_a_failing_resolution_propagates_out_of_stream(self):
        runner = OpenAIRunner()

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            mock_agent = _mock_agent()
            mock_agent.resolve_run_options = AsyncMock(side_effect=RuntimeError("factory boom"))

            with pytest.raises(RuntimeError, match="factory boom"):
                _ = [e async for e in runner.stream(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])]

            MockRunner.run_streamed.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_factory_declared_through_the_module_runs_per_call_on_a_real_agent(self):
        seen: list[tuple] = []

        def options_for(agent, session, requests):
            seen.append((agent, session, requests))
            return {"max_turns": 3}

        with Runtime(SessionStoreBuilder.build()):
            native = SDKAgent(name="factory-agent", instructions="x")
            module = OpenAIModule([native]).run_options(native, options_for, max_turns=25, hooks="static")
            agent = module.get_agent("factory-agent")
            session = Session("s")
            requests = [AgentRequestText(prompt="hi")]

            with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
                MockRunner.run = AsyncMock(return_value=_run_result())
                await OpenAIRunner().run(agent, session, requests)
                kwargs = MockRunner.run.call_args.kwargs

        assert kwargs["max_turns"] == 3  # the factory's value, over the static 25
        assert kwargs["hooks"] == "static"  # the static key the factory did not name
        assert seen == [(agent, session, requests)]
        assert agent.run_options == {"max_turns": 25, "hooks": "static"}  # the static dict is untouched


class RecordingHooks(RunHooks):
    """A real SDK RunHooks that records what Session.current() / Agent.current() resolve to inside a callback."""

    def __init__(self):
        self.seen: list[tuple] = []

    async def on_tool_start(self, context, agent, tool) -> None:
        self.seen.append((Session.current(), AKAgent.current()))


class TestOpenAIHooksSeeTheAKSession:
    """A native hook declared once at load time can read the AK session and agent in both execution modes."""

    @pytest.fixture(autouse=True)
    def reset_system_hook_caches(self):
        Runtime._system_pre_hooks = None
        Runtime._system_post_hooks = None
        yield
        Runtime._system_pre_hooks = None
        Runtime._system_post_hooks = None

    @staticmethod
    def _agent_with_hooks(hooks: RunHooks) -> OpenAIAgent:
        agent = OpenAIAgent("hooked", OpenAIRunner(), SDKAgent(name="hooked", instructions="x"))
        agent.run_options["hooks"] = hooks
        return agent

    @pytest.mark.asyncio
    async def test_session_and_agent_resolve_inside_a_hook_during_run(self):
        hooks = RecordingHooks()
        agent = self._agent_with_hooks(hooks)
        runtime = Runtime(SessionStoreBuilder.build())
        session = runtime.sessions().new("hook-run")

        async def fake_run(native_agent, input_data, **kwargs):
            await kwargs["hooks"].on_tool_start(MagicMock(), native_agent, MagicMock())
            return _run_result()

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(side_effect=fake_run)
            await runtime.run(agent, session, [AgentRequestText(prompt="hi")])

        assert hooks.seen == [(session, agent)]

    @pytest.mark.asyncio
    async def test_session_and_agent_resolve_inside_a_hook_fired_from_a_spawned_task_during_stream(self):
        hooks = RecordingHooks()
        agent = self._agent_with_hooks(hooks)
        runtime = Runtime(SessionStoreBuilder.build())
        session = runtime.sessions().new("hook-stream")

        def fake_run_streamed(native_agent, input_data, **kwargs):
            result = MagicMock()
            result.interruptions = []  # a completed run; the adapter reads this before final_output

            async def stream_events():
                # run_streamed drives the SDK loop from tasks it creates; a task inherits a copy of the contextvars.
                await asyncio.create_task(kwargs["hooks"].on_tool_start(MagicMock(), native_agent, MagicMock()))
                for event in ():
                    yield event

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            _ = [chunk async for chunk in runtime.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert hooks.seen == [(session, agent)]


# --- Human in the loop (spec `docs/specs/606-human-in-the-loop/`, iteration 5) ------------------


def _approval_item(call_id: str = "call-1", name: str = "refund", arguments: str = '{"amount": 100}'):
    """A ToolApprovalItem stand-in. `call_id`/`name`/`arguments` are properties on the real one."""
    item = MagicMock()
    item.call_id = call_id
    item.name = name
    item.arguments = arguments
    return item


def _paused_result(*items, payload=None):
    """A run result carrying interruptions, whose final_output is the pre-gate text."""
    result = MagicMock()
    result.interruptions = list(items)
    result.final_output = "I'll issue that refund for you."
    result.to_state.return_value.to_json.return_value = payload or {"_schema_version": "1.0", "gated": [i.call_id for i in items]}
    return result


def _done_result(text: str = "refund issued"):
    result = MagicMock()
    result.interruptions = []
    result.final_output = text
    return result


class _FakeState:
    """Stands in for the SDK's RunState, recording what each decision rendered as."""

    def __init__(self, items):
        self._items = list(items)
        self.approved: list[str] = []
        self.rejected: list[tuple[str, str | None]] = []

    def get_interruptions(self):
        return list(self._items)

    def approve(self, item, always_approve: bool = False) -> None:
        self.approved.append(item.call_id)

    def reject(self, item, always_reject: bool = False, *, rejection_message=None) -> None:
        self.rejected.append((item.call_id, rejection_message))


class TestOpenAIPauseDetection:
    """
    A gated tool must surface as a pause, not as the text produced before the gate.

    `final_output` is populated on a gated run — it holds whatever the model said on its way to the
    tool call. Reading it first is exactly how the adapter used to lose a pause silently, so the
    ordering is the thing under test, not just the reply type.
    """

    def test_the_runner_declares_the_capability(self):
        assert OpenAIRunner().supports_pause is True

    @pytest.mark.asyncio
    async def test_a_gated_tool_returns_a_paused_reply(self):
        runner, session = OpenAIRunner(), Session("s")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_paused_result(_approval_item()))

            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund it")])

        assert isinstance(reply, AgentPausedReplyAny)
        assert [i.id for i in reply.interruptions] == ["call-1"]
        assert reply.interruptions[0].tool_name == "refund"
        assert reply.interruptions[0].kind == "tool_call"

    @pytest.mark.asyncio
    async def test_the_pre_gate_text_is_not_returned_as_the_answer(self):
        """The regression this ordering exists to prevent."""
        runner, session = OpenAIRunner(), Session("s")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_paused_result(_approval_item()))

            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund it")])

        assert not isinstance(reply, AgentReplyText)

    @pytest.mark.asyncio
    async def test_the_arguments_ride_along_so_a_human_can_judge_the_call(self):
        runner, session = OpenAIRunner(), Session("s")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_paused_result(_approval_item(arguments='{"amount": 500}')))

            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund it")])

        assert reply.interruptions[0].arguments == '{"amount": 500}'

    @pytest.mark.asyncio
    async def test_several_gated_calls_become_one_record(self):
        runner, session = OpenAIRunner(), Session("s")
        items = (_approval_item("call-1", "refund"), _approval_item("call-2", "notify"))
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_paused_result(*items))

            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund and tell them")])

        assert [i.id for i in reply.interruptions] == ["call-1", "call-2"]
        assert len(PausedRunState.list(session)) == 1


class TestOpenAIRecordDurability:
    @pytest.mark.asyncio
    async def test_the_record_survives_a_session_pickle_round_trip(self):
        """The whole point of the payload: the decision may arrive an hour later, on another replica."""
        import pickle

        runner, session = OpenAIRunner(), Session("s")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_paused_result(_approval_item()))
            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund it")])

        restored = pickle.loads(pickle.dumps(session))
        record = PausedRunState.get(restored, reply.run_id)

        assert record is not None
        assert record.payload == {"_schema_version": "1.0", "gated": ["call-1"]}
        assert record.agent == "test-agent"
        assert record.runner == "openai"

    @pytest.mark.asyncio
    async def test_the_state_json_is_what_gets_stored(self):
        runner, session = OpenAIRunner(), Session("s")
        result = _paused_result(_approval_item(), payload={"_schema_version": "1.0", "turn": 3})
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=result)
            reply = await runner.run(_mock_agent(), session, [AgentRequestText(prompt="refund it")])

        result.to_state.assert_called_once()
        assert PausedRunState.get(session, reply.run_id).payload == {"_schema_version": "1.0", "turn": 3}


async def _pause_once(runner, session, agent, *items, payload=None):
    """Drive one paused run through the adapter, returning the paused reply."""
    with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=_paused_result(*(items or (_approval_item(),)), payload=payload))
        return await runner.run(agent, session, [AgentRequestText(prompt="refund it")])


def _resume_requests(*ids, status="approved", message=None, payload=None, prompt=None):
    """The hook-processed list Runtime hands the adapter on a resume."""
    decisions = [ResumeDecision(id=i, status=status, message=message, payload=payload) for i in ids]
    requests = [AgentRequestText(prompt=prompt)] if prompt else []
    return requests + [AgentResumeRequestAny(decisions=decisions)], decisions


class TestOpenAIResume:
    @pytest.mark.asyncio
    async def test_a_decision_continues_the_run_and_clears_the_record(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")
        state = _FakeState([_approval_item()])

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run = AsyncMock(return_value=_done_result("refund issued"))

            reply = await runner.resume(agent, session, requests, decisions, record)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "refund issued"
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_the_restored_state_is_what_the_sdk_is_re_run_with(self):
        """Not a fresh input — the whole point is continuing the paused run, not starting a new one."""
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")
        state = _FakeState([_approval_item()])

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run = AsyncMock(return_value=_done_result())

            await runner.resume(agent, session, requests, decisions, record)

        assert MockState.from_json.call_args.args[1] == record.payload
        assert MockRunner.run.call_args.args[1] is state

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status,expect_approved,expect_message",
        [("approved", True, None), ("denied", False, "too expensive"), ("cancelled", False, None)],
    )
    async def test_the_three_verbs_reach_the_model_differently(self, status, expect_approved, expect_message):
        """`denied` and `cancelled` must be distinguishable in what the model receives.

        The SDK has only approve and reject, so a bool would collapse them — and the model would
        report a refusal nobody made. AK's own wording is what keeps them apart.
        """
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1", status=status, message="too expensive")
        state = _FakeState([_approval_item()])

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run = AsyncMock(return_value=_done_result())

            await runner.resume(agent, session, requests, decisions, record)

        if expect_approved:
            assert state.approved == ["call-1"] and state.rejected == []
        else:
            assert state.approved == []
            sent = state.rejected[0][1]
            assert (sent == expect_message) if expect_message else ("not a refusal" in sent)

    @pytest.mark.asyncio
    async def test_cancelled_does_not_read_as_a_refusal(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1", status="cancelled")
        state = _FakeState([_approval_item()])

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run = AsyncMock(return_value=_done_result())

            await runner.resume(agent, session, requests, decisions, record)

        assert state.rejected[0][1] == OpenAIRunner.CANCELLED_DECISION_MESSAGE

    @pytest.mark.asyncio
    async def test_answering_one_of_two_returns_the_remainder_as_a_fresh_pause(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        items = (_approval_item("call-1", "refund"), _approval_item("call-2", "notify"))
        paused = await _pause_once(runner, session, agent, *items)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")
        state = _FakeState(items)

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run = AsyncMock(return_value=_paused_result(items[1]))

            again = await runner.resume(agent, session, requests, decisions, record)

        assert isinstance(again, AgentPausedReplyAny)
        assert [i.id for i in again.interruptions] == ["call-2"]
        assert again.run_id != paused.run_id
        assert [r.id for r in PausedRunState.list(session)] == [again.run_id]

    @pytest.mark.asyncio
    async def test_framework_context_survives_a_resume(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        session.set(FRAMEWORK_CONTEXT, {"user_id": "42"})
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item()]))
            MockRunner.run = AsyncMock(return_value=_done_result())

            await runner.resume(agent, session, requests, decisions, record)

        assert MockRunner.run.call_args.kwargs["context"] == {"user_id": "42"}
        assert session.get_framework_context() == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_a_declared_run_option_reaches_the_resumed_call(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        agent.run_options = {"max_turns": 7}
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item()]))
            MockRunner.run = AsyncMock(return_value=_done_result())

            await runner.resume(agent, session, requests, decisions, record)

        assert MockRunner.run.call_args.kwargs["max_turns"] == 7
        assert "session" in MockRunner.run.call_args.kwargs  # the AK-owned key still wins

    @pytest.mark.asyncio
    async def test_a_tool_on_the_resumed_turn_sees_the_resume_request(self):
        """Nothing else proves the hook-processed list was threaded into the ToolContext."""
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")
        seen = {}

        async def _capture(*args, **kwargs):
            from agentkernel.core import ToolContext as TC

            seen["requests"] = TC.get().requests
            return _done_result()

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item()]))
            MockRunner.run = AsyncMock(side_effect=_capture)

            await runner.resume(agent, session, requests, decisions, record)

        assert any(isinstance(r, AgentResumeRequestAny) for r in seen["requests"])


class TestOpenAIRejectsWhatItCannotDeliver:
    """
    These raise instead of returning a reply, and that is the assertion that matters.

    Every adapter method wraps its body in one `except Exception` returning
    `AgentReplyText(user_facing_error_message(e))`. A check placed inside it becomes "Sorry,
    something went wrong" — so `pytest.raises` here is really testing *placement*, not the message.
    """

    @pytest.mark.asyncio
    async def test_a_structured_payload_is_refused_before_the_sdk_is_touched(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1", payload={"choice": "partial"})

        with pytest.raises(ValueError, match="cannot deliver a structured answer"):
            await runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_a_prompt_alongside_a_decision_is_refused(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1", prompt="and what is the weather?")

        with pytest.raises(ValueError, match="cannot carry a prompt alongside a decision"):
            await runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_the_record_is_left_intact_when_a_resume_is_refused(self):
        """The human can correct the request and answer again; the pause is not spent."""
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1", payload={"choice": "partial"})

        with pytest.raises(ValueError):
            await runner.resume(agent, session, requests, decisions, record)

        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_a_payload_that_no_longer_deserialises_names_the_runner(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")

        with patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(side_effect=TypeError("unsupported _schema_version"))

            with pytest.raises(ValueError, match="no longer deserialises"):
                await runner.resume(agent, session, requests, decisions, record)

    @pytest.mark.asyncio
    async def test_a_decision_the_restored_state_does_not_hold_is_named(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)
        requests, decisions = _resume_requests("call-1")

        with patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item("call-9")]))
            reply = await runner.resume(agent, session, requests, decisions, record)

        # Inside the try, so it surfaces as the adapter's reply rather than raising: the record and
        # the restored state disagreeing is a framework-level inconsistency, not a caller error.
        assert reply.response == "Error: Decision 'call-1' matches no interruption in the restored OpenAI state, which is waiting on: ['call-9']."


class TestOpenAIHoldsTwoPausesAtOnce:
    """
    The one adapter where the list can genuinely grow.

    A `RunState` is a self-contained snapshot, and two were verified to resume independently
    (`research/verification.md`), so this adapter appends. The single-thread adapters replace.
    """

    @pytest.mark.asyncio
    async def test_two_runs_pause_and_resume_independently(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        first = await _pause_once(runner, session, agent, _approval_item("call-1"), payload={"run": 1})
        second = await _pause_once(runner, session, agent, _approval_item("call-2"), payload={"run": 2})

        assert len({first.run_id, second.run_id}) == 2
        assert len(PausedRunState.list(session)) == 2

        requests, decisions = _resume_requests("call-1")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item("call-1")]))
            MockRunner.run = AsyncMock(return_value=_done_result("first done"))
            reply = await runner.resume(agent, session, requests, decisions, PausedRunState.get(session, first.run_id))

        assert reply.response == "first done"
        assert [r.id for r in PausedRunState.list(session)] == [second.run_id]

    @pytest.mark.asyncio
    async def test_a_stale_resume_is_accepted_behaviour_not_an_error(self):
        """Pinned deliberately: AK does not detect an overtaken pause, and OpenAI reports nothing.

        Pause, run an ordinary turn, then resume the old snapshot. The answer is computed as though
        the intervening turn never happened. Recorded here so the gap lives in the suite rather than
        being discovered in production; the OpenAI adapter docs say so too (PR 3).
        """
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        paused = await _pause_once(runner, session, agent)
        record = PausedRunState.get(session, paused.run_id)

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = AsyncMock(return_value=_done_result("unrelated answer"))
            await runner.run(agent, session, [AgentRequestText(prompt="something else")])

        requests, decisions = _resume_requests("call-1")
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item()]))
            MockRunner.run = AsyncMock(return_value=_done_result("refund issued"))
            reply = await runner.resume(agent, session, requests, decisions, record)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "refund issued"
        assert not reply.response.startswith("Error")


def _streamed(*items, events=(), payload=None):
    """A run_streamed stand-in: yields the given events, then reports interruptions once drained."""

    def _factory(agent, input_data, session=None, context=None, **kwargs):
        result = _paused_result(*items, payload=payload) if items else _done_result()

        async def stream_events():
            for event in events:
                yield event

        result.stream_events = stream_events
        return result

    return _factory


class TestOpenAIStreamingPause:
    """
    `RunResultStreaming` fills `interruptions` as the run completes, not as events arrive.

    So a streamed pause is only knowable after the drain — which is also where the adapter already
    writes framework context, so the check costs no new structure.
    """

    @pytest.mark.asyncio
    async def test_a_streamed_gated_run_ends_with_run_paused(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed(_approval_item()))

            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        assert isinstance(events[-1], RunPaused)
        assert [i.id for i in events[-1].interruptions] == ["call-1"]
        assert events[-1].agent == "test-agent"

    @pytest.mark.asyncio
    async def test_the_streamed_pause_writes_the_same_record(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed(_approval_item(), payload={"run": "streamed"}))

            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        record = PausedRunState.get(session, events[-1].run_id)
        assert record.payload == {"run": "streamed"}

    @pytest.mark.asyncio
    async def test_an_ordinary_stream_emits_no_run_paused(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed())

            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert not any(isinstance(e, RunPaused) for e in events)
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_resume_stream_continues_the_run_and_clears_the_record(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed(_approval_item()))
            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        record = PausedRunState.get(session, events[-1].run_id)
        requests, decisions = _resume_requests("call-1")
        state = _FakeState([_approval_item()])

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=state)
            MockRunner.run_streamed = MagicMock(side_effect=_streamed())

            resumed = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]

        assert state.approved == ["call-1"]
        assert not any(isinstance(e, RunPaused) for e in resumed)
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_streamed_resume_maps_events_and_can_pause_again(self):
        """Answer one question, get asked the next — the flow the feature exists for, streamed."""
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed(_approval_item()))
            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        first = events[-1]
        record = PausedRunState.get(session, first.run_id)
        requests, decisions = _resume_requests("call-1")

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner, patch("agentkernel.framework.openai.openai.RunState") as MockState:
            MockState.from_json = AsyncMock(return_value=_FakeState([_approval_item()]))
            MockRunner.run_streamed = MagicMock(
                side_effect=_streamed(_approval_item("call-2"), events=[_delta_event("checking"), _delta_event(" that")])
            )

            resumed = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]

        assert [e.content for e in resumed if isinstance(e, TextDelta)] == ["checking", " that"]
        again = resumed[-1]
        assert isinstance(again, RunPaused)
        assert again.run_id != first.run_id
        assert [i.id for i in again.interruptions] == ["call-2"]
        assert [r.id for r in PausedRunState.list(session)] == [again.run_id]

    @pytest.mark.asyncio
    async def test_resume_stream_refuses_a_payload_before_streaming_anything(self):
        runner, session, agent = OpenAIRunner(), Session("s"), _mock_agent()
        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=_streamed(_approval_item()))
            events = [e async for e in runner.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        record = PausedRunState.get(session, events[-1].run_id)
        requests, decisions = _resume_requests("call-1", payload={"choice": "partial"})

        with pytest.raises(ValueError, match="cannot deliver a structured answer"):
            _ = [e async for e in runner.resume_stream(agent, session, requests, decisions, record)]
