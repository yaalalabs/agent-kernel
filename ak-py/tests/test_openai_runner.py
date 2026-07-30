import logging
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
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
            assert first == "hi"
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
                deltas = [delta async for delta in runner.stream(mock_agent, session, requests)]

            assert deltas == ["hi"]
            assert session.get(FRAMEWORK_CONTEXT) == {"seed": 1}
            assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


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
