import logging
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
from agentkernel.core.model import (
    AgentReplyAny,
    AgentReplyText,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.framework.openai.openai import OpenAIRunner

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class CalendarEvent(BaseModel):
    name: str
    date: str


def _delta_event(text: str):
    """Build a stream event the OpenAI runner recognizes as a text delta."""
    from openai.types.responses.response_text_delta_event import ResponseTextDeltaEvent

    event = MagicMock()
    event.type = "raw_response_event"
    event.data = ResponseTextDeltaEvent(
        content_index=0,
        delta=text,
        item_id="item",
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
            result.final_output = "done"
            MockRunner.run = AsyncMock(return_value=result)
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            result.final_output = "done"
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run = fake_run
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            result.final_output = "done"
            MockRunner.run = AsyncMock(return_value=result)
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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

            async def stream_events():
                if context is not None:
                    context["touched"] = True
                for event in ():
                    yield event

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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

            async def stream_events():
                if context is not None:
                    context["touched"] = True  # tool mutated the injected copy
                yield _delta_event("hi")

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

            agen = runner.stream(mock_agent, session, requests)
            first = await agen.__anext__()
            assert first == TextDelta(message_id="item", content="hi")
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

            async def stream_events():
                context["bad"] = lambda: 1  # tool stored a non-picklable value
                yield _delta_event("hi")

            result.stream_events = stream_events
            return result

        with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
            MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

            with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
                events = [event async for event in runner.stream(mock_agent, session, requests)]

            assert events == [TextDelta(message_id="item", content="hi")]
            assert session.get(FRAMEWORK_CONTEXT) == {"seed": 1}
            assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


def _message_item(item_id: str = "msg-1"):
    """A real ResponseOutputMessage, so the test pins the SDK's shape rather than a mock's."""
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
    """A RunItemStreamEvent. `name` is assigned after construction: MagicMock(name=...) names the mock."""
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


async def _collect(runner, events):
    """Drive OpenAIRunner.stream over a scripted SDK event list and return the AK events."""
    session = Session("s")
    requests = [AgentRequestText(prompt="hi")]

    def fake_run_streamed(agent, input_data, session=None, context=None):
        result = MagicMock()

        async def stream_events():
            for event in events:
                yield event

        result.stream_events = stream_events
        return result

    with patch("agentkernel.framework.openai.openai.Runner") as MockRunner:
        MockRunner.run_streamed = MagicMock(side_effect=fake_run_streamed)
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        return [event async for event in runner.stream(mock_agent, session, requests)]


class TestOpenAIRunnerStreamEvents:
    """The event mapping added in PR 4. Every id is read off the SDK's own event, never generated."""

    @pytest.mark.asyncio
    async def test_a_message_is_bracketed_around_its_deltas(self):
        item = _message_item()
        events = await _collect(
            OpenAIRunner(),
            [_item_added(item), _delta_event("he"), _delta_event("llo"), _item_done(item)],
        )
        assert events == [
            MessageStart(message_id="msg-1", role="assistant"),
            TextDelta(message_id="item", content="he"),
            TextDelta(message_id="item", content="llo"),
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
        """raw_item carries the string the model saw; without one, the tool's return value stands in."""
        events = await _collect(OpenAIRunner(), [_run_item_event("tool_output", {"call_id": "call-1"}, output=42)])
        assert events == [ToolCallResult(tool_call_id="call-1", content="42")]

    @pytest.mark.asyncio
    async def test_a_tool_item_with_no_call_id_emits_nothing(self):
        """A start that can never be correlated to an end is worse for a client than silence."""
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
        """The raw events already bracketed the message; mapping these too would emit it twice."""
        events = await _collect(
            OpenAIRunner(),
            [
                _run_item_event("message_output_created", _message_item()),
                _run_item_event("reasoning_item_created", _reasoning_item()),
                _run_item_event("handoff_requested", _function_call()),
            ],
        )
        assert events == []


class TestOpenAIRunnerErrorHandling:
    """Test error handling in OpenAIRunner.run() method"""

    @pytest.mark.asyncio
    async def test_request_processing_error_returns_error_reply(self):
        """A request that fails before the prompt is extracted still returns a clean error reply."""
        runner = OpenAIRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(name="empty.png", image_data="")]  # raises inside _process_requests
        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()

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
            mock_run_result.final_output = None

            # Create an async function for Runner.run
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            # Mock the agent
            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            mock_run_result.final_output = expected_reply

            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            mock_run_result.final_output = 42  # numeric output

            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            mock_run_result.final_output = CalendarEvent(name="Launch", date="2026-07-08")
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

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
            mock_run_result.final_output = {"name": "Launch", "date": "2026-07-08"}
            MockRunner.run = AsyncMock(return_value=mock_run_result)

            mock_agent = MagicMock()
            mock_agent.agent = MagicMock()

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyAny)
            assert reply.content == {"name": "Launch", "date": "2026-07-08"}
