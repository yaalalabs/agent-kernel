from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.adk.adk import GoogleADKRunner

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


def _run_with_response(runner, agent, session, requests, response_text, adk_session=None):
    if adk_session is None:
        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={})
    setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))
    get_response = AsyncMock(return_value=response_text)
    return patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", get_response)


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
        # get_state returns the accumulated state with ak_tool_context already stripped.
        adk_session.get_state = AsyncMock(return_value={"seeded": 9, "added": "new"})
        setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))

        with patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", AsyncMock(return_value="hello")):
            reply = await runner.run(agent, session, requests)

        # The loaded context is injected into _setup_session_context.
        assert setup.await_args.args[3] == {"seeded": 1}
        # Full stripped state is written back: a mutated seeded key AND a brand-new key both survive.
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
