from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.langgraph.langgraph import LangGraphRunner


class WeatherResponse(BaseModel):
    city: str
    conditions: str


def _mock_agent(result):
    agent = MagicMock()
    agent._system_prompt = ""
    agent.agent = MagicMock()
    agent.agent.ainvoke = AsyncMock(return_value=result)
    return agent


def _message(content):
    message = MagicMock()
    message.content = content
    return message


class TestLangGraphRunnerStructuredOutput:
    """Test structured output detection via the structured_response result key"""

    @pytest.mark.asyncio
    async def test_structured_response_model_returns_agent_reply_any(self):
        runner = LangGraphRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="weather in Colombo?")]
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
        requests = [AgentRequestText(text="weather?")]
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
        requests = [AgentRequestText(text="hello")]
        result = {"messages": [_message("first"), _message("Hi there!")]}
        agent = _mock_agent(result)

        reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.text == "Hi there!"
        assert reply.prompt == "hello"
