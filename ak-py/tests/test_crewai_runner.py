from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crewai import Agent as CrewAgent
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.framework.crewai.crewai import CrewAIModule, CrewAIRunner


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


def _mock_crew(reply_text: str = "answer"):
    """Returns a Crew class mock whose instances reply with the given text."""
    crew_instance = MagicMock()
    result = MagicMock()
    result.raw = reply_text
    crew_instance.kickoff_async = AsyncMock(return_value=result)
    crew_cls = MagicMock(return_value=crew_instance)
    return crew_cls


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
    async def test_structured_output_is_added_to_transcript(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="research AI")]
        agent = _mock_agent(output_pydantic=ResearchReport)
        output = _crew_output(pydantic=ResearchReport(topic="AI", score=9), raw='{"topic": "AI", "score": 9}')

        memory_patch, task_patch, crew_patch = _patches(runner, output)
        with memory_patch, task_patch, crew_patch:
            reply = await runner.run(agent, session, requests)

        # The structured exchange must survive into the next turn's context
        transcript = session.get(CrewAIRunner.TRANSCRIPT_KEY)
        assert transcript == ["User: research AI", f"Assistant: {str(reply)}"]

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


class TestCrewAIModuleStructuredOutputConfig:
    """Test structured output schemas passed via the CrewAIModule constructor"""

    def _crew_agent(self, role="Researcher"):
        return CrewAgent(role=role, goal="Research topics", backstory="A researcher", verbose=False)

    def test_output_pydantic_forwarded_to_wrapped_agent(self):
        with Runtime(SessionStoreBuilder.build()):
            module = CrewAIModule([self._crew_agent()], output_pydantic={"Researcher": ResearchReport})
            wrapped = module.get_agent("Researcher")
            assert wrapped.output_pydantic is ResearchReport
            assert wrapped.output_json is None

    def test_output_json_forwarded_to_wrapped_agent(self):
        with Runtime(SessionStoreBuilder.build()):
            module = CrewAIModule([self._crew_agent()], output_json={"Researcher": ResearchReport})
            wrapped = module.get_agent("Researcher")
            assert wrapped.output_json is ResearchReport
            assert wrapped.output_pydantic is None

    def test_unmapped_agent_has_no_structured_output(self):
        with Runtime(SessionStoreBuilder.build()):
            agents = [self._crew_agent("Researcher"), self._crew_agent("Writer")]
            module = CrewAIModule(agents, output_pydantic={"Researcher": ResearchReport})
            assert module.get_agent("Researcher").output_pydantic is ResearchReport
            assert module.get_agent("Writer").output_pydantic is None
            assert module.get_agent("Writer").output_json is None

    def test_schemas_survive_reload(self):
        with Runtime(SessionStoreBuilder.build()):
            agent = self._crew_agent()
            module = CrewAIModule([agent], output_pydantic={"Researcher": ResearchReport})
            module.load([agent])
            assert module.get_agent("Researcher").output_pydantic is ResearchReport

    def test_property_setter_still_works(self):
        with Runtime(SessionStoreBuilder.build()):
            module = CrewAIModule([self._crew_agent()])
            wrapped = module.get_agent("Researcher")
            assert wrapped.output_pydantic is None
            wrapped.output_pydantic = ResearchReport
            assert wrapped.output_pydantic is ResearchReport


class TestDescribe:

    def test_without_transcript_returns_prompt(self):
        assert CrewAIRunner._describe("hello", None) == "hello"
        assert CrewAIRunner._describe("hello", []) == "hello"

    def test_with_transcript_prepends_history(self):
        description = CrewAIRunner._describe("Which countries hosted it?", ["User: Who won?", "Assistant: Sri Lanka"])
        assert "Previous conversation:" in description
        assert "User: Who won?" in description
        assert "Assistant: Sri Lanka" in description
        assert description.endswith("Current request:\nWhich countries hosted it?")


class TestTranscript:

    def test_none_session_returns_none(self):
        assert CrewAIRunner()._transcript(None) is None

    def test_creates_and_reuses_transcript(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        transcript = runner._transcript(session)
        assert transcript == []
        transcript.append("User: hi")
        assert runner._transcript(session) is transcript


class TestCrewAIRunnerRun:

    @pytest.mark.asyncio
    async def test_follow_up_prompt_includes_previous_conversation(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent()

        with (
            patch("agentkernel.framework.crewai.crewai.Crew", _mock_crew("Sri Lanka")) as crew_cls,
            patch("agentkernel.framework.crewai.crewai.Task") as task_cls,
            patch.object(runner, "_memory", return_value=None),
        ):
            reply = await runner.run(mock_agent, session, [AgentRequestText(text="Who won the 1996 cricket world cup?")])
            assert isinstance(reply, AgentReplyText)
            assert reply.text == "Sri Lanka"
            # First turn has no history
            assert task_cls.call_args.kwargs["description"] == "Who won the 1996 cricket world cup?"

            crew_cls.return_value.kickoff_async.return_value.raw = "India, Pakistan and Sri Lanka"
            reply = await runner.run(mock_agent, session, [AgentRequestText(text="Which countries hosted the tournament?")])
            assert reply.text == "India, Pakistan and Sri Lanka"

            description = task_cls.call_args.kwargs["description"]
            assert "User: Who won the 1996 cricket world cup?" in description
            assert "Assistant: Sri Lanka" in description
            assert description.endswith("Current request:\nWhich countries hosted the tournament?")

    @pytest.mark.asyncio
    async def test_transcript_is_capped(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent()

        with (
            patch("agentkernel.framework.crewai.crewai.Crew", _mock_crew()),
            patch("agentkernel.framework.crewai.crewai.Task"),
            patch.object(runner, "_memory", return_value=None),
        ):
            for i in range(CrewAIRunner.TRANSCRIPT_MAX_LINES):
                await runner.run(mock_agent, session, [AgentRequestText(text=f"question {i}")])

        transcript = session.get(CrewAIRunner.TRANSCRIPT_KEY)
        assert len(transcript) == CrewAIRunner.TRANSCRIPT_MAX_LINES
        # Oldest lines are dropped, most recent turn is kept
        assert transcript[-2] == f"User: question {CrewAIRunner.TRANSCRIPT_MAX_LINES - 1}"

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_fail_run(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent()

        memory = MagicMock()
        memory.remember.side_effect = RuntimeError("Memory requires an embedder")

        with (
            patch("agentkernel.framework.crewai.crewai.Crew", _mock_crew("still works")) as crew_cls,
            patch("agentkernel.framework.crewai.crewai.Task"),
            patch.object(runner, "_memory", return_value=memory),
        ):
            reply = await runner.run(mock_agent, session, [AgentRequestText(text="hello")])

        assert reply.text == "still works"
        # Broken memory is not handed to the crew
        assert crew_cls.call_args.kwargs["memory"] is None

    @pytest.mark.asyncio
    async def test_error_reply_is_not_added_to_transcript(self):
        runner = CrewAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent()

        crew_cls = _mock_crew()
        crew_cls.return_value.kickoff_async.side_effect = RuntimeError("boom")

        with (
            patch("agentkernel.framework.crewai.crewai.Crew", crew_cls),
            patch("agentkernel.framework.crewai.crewai.Task"),
            patch.object(runner, "_memory", return_value=None),
        ):
            await runner.run(mock_agent, session, [AgentRequestText(text="hello")])

        assert session.get(CrewAIRunner.TRANSCRIPT_KEY) == []
