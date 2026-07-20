from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.adk.adk import GoogleADKRunner


class CapitalOutput(BaseModel):
    country: str
    capital: str


def _mock_agent(output_schema=None):
    agent = MagicMock()
    agent.name = "test-agent"
    agent.agent = MagicMock(spec=["output_schema"])
    agent.agent.output_schema = output_schema
    return agent


def _run_with_response(runner, agent, session, requests, response_text):
    setup = AsyncMock(return_value=("user", MagicMock(), MagicMock()))
    get_response = AsyncMock(return_value=response_text)
    return patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", get_response)


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
