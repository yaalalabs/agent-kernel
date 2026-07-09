from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.crewai.crewai import CrewAIRunner


class ResearchReport(BaseModel):
    topic: str
    score: int


def _crew_output(pydantic=None, json_dict=None, raw=""):
    output = MagicMock(spec=["pydantic", "json_dict", "raw"])
    output.pydantic = pydantic
    output.json_dict = json_dict
    output.raw = raw
    return output


def _mock_agent(output_pydantic=None, output_json=None):
    agent = MagicMock(spec=["agent", "crew", "name", "output_pydantic", "output_json"])
    agent.name = "Researcher"
    agent.agent = MagicMock()
    agent.crew = [agent.agent]
    agent.output_pydantic = output_pydantic
    agent.output_json = output_json
    return agent


def _patches(runner, crew_output):
    crew = MagicMock()
    crew.kickoff_async = AsyncMock(return_value=crew_output)
    return (
        patch.object(runner, "_memory", return_value=None),
        patch("agentkernel.framework.crewai.crewai.Task"),
        patch("agentkernel.framework.crewai.crewai.Crew", return_value=crew),
    )


class TestCrewAIRunnerStructuredOutput:
    """Test structured output detection on the CrewOutput"""

    @pytest.mark.asyncio
    async def test_pydantic_output_returns_agent_reply_any(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="research AI")]
        agent = _mock_agent(output_pydantic=ResearchReport)
        output = _crew_output(pydantic=ResearchReport(topic="AI", score=9), raw='{"topic": "AI", "score": 9}')

        memory_patch, task_patch, crew_patch = _patches(runner, output)
        with memory_patch, task_patch, crew_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"topic": "AI", "score": 9}
        assert reply.prompt == "research AI"

    @pytest.mark.asyncio
    async def test_json_dict_output_returns_agent_reply_any(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="research AI")]
        agent = _mock_agent(output_json=ResearchReport)
        output = _crew_output(json_dict={"topic": "AI", "score": 7}, raw='{"topic": "AI", "score": 7}')

        memory_patch, task_patch, crew_patch = _patches(runner, output)
        with memory_patch, task_patch, crew_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"topic": "AI", "score": 7}

    @pytest.mark.asyncio
    async def test_raw_only_output_returns_text(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="say hi")]
        agent = _mock_agent()
        output = _crew_output(raw="Hi there!")

        memory_patch, task_patch, crew_patch = _patches(runner, output)
        with memory_patch, task_patch, crew_patch:
            reply = await runner.run(agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.text == "Hi there!"

    @pytest.mark.asyncio
    async def test_output_config_forwarded_to_task(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="research AI")]
        agent = _mock_agent(output_pydantic=ResearchReport)
        output = _crew_output(raw="ok")

        memory_patch, task_patch, crew_patch = _patches(runner, output)
        with memory_patch, task_patch as mock_task, crew_patch:
            await runner.run(agent, session, requests)

        _, kwargs = mock_task.call_args
        assert kwargs["output_pydantic"] is ResearchReport
        assert kwargs["output_json"] is None
