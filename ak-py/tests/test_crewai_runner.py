from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.framework.crewai.crewai import CrewAIRunner


def _mock_crew(reply_text: str = "answer"):
    """Returns a Crew class mock whose instances reply with the given text."""
    crew_instance = MagicMock()
    result = MagicMock()
    result.raw = reply_text
    crew_instance.kickoff_async = AsyncMock(return_value=result)
    crew_cls = MagicMock(return_value=crew_instance)
    return crew_cls


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
        mock_agent = MagicMock()

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
        mock_agent = MagicMock()

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
        mock_agent = MagicMock()

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
        mock_agent = MagicMock()

        crew_cls = _mock_crew()
        crew_cls.return_value.kickoff_async.side_effect = RuntimeError("boom")

        with (
            patch("agentkernel.framework.crewai.crewai.Crew", crew_cls),
            patch("agentkernel.framework.crewai.crewai.Task"),
            patch.object(runner, "_memory", return_value=None),
        ):
            await runner.run(mock_agent, session, [AgentRequestText(text="hello")])

        assert session.get(CrewAIRunner.TRANSCRIPT_KEY) == []
