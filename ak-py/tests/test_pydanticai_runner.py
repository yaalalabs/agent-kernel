import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, FunctionToolset
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.test import TestModel
from pydantic_core import to_jsonable_python

from agentkernel.core import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.core.session.serde import BinarySerde
from agentkernel.core.tool import SystemToolFactory
from agentkernel.framework.pydanticai.pydanticai import FRAMEWORK, PydanticAIAgent, PydanticAIRunner, PydanticAISession


class CalendarEvent(BaseModel):
    name: str
    date: str


def _mock_agent(output, messages=None):
    """
    Build a mock wrapping a native Pydantic AI agent whose ``run()`` returns a result with ``.output``.

    Note the mock-target correction from ``test_openai_runner.py``: Pydantic AI has no module-level
    ``Runner`` class (the OpenAI SDK calls ``Runner.run(agent.agent, ...)`` as a free function). Here
    ``run()`` is an instance method on the agent object itself, so the mock lives on
    ``mock_agent.agent.run`` and returns a result whose structured value is on ``.output`` (not
    ``.final_output``). ``.all_messages()`` returns an empty list so history persistence is a no-op.
    """
    mock_run_result = MagicMock()
    mock_run_result.output = output
    mock_run_result.all_messages = MagicMock(return_value=messages or [])

    mock_agent = MagicMock()
    mock_agent.agent = MagicMock()
    mock_agent.agent.run = AsyncMock(return_value=mock_run_result)
    return mock_agent


class TestPydanticAIRunnerErrorHandling:
    """Test error handling in PydanticAIRunner.run() method"""

    @pytest.mark.asyncio
    async def test_runner_with_none_reply_returns_empty_string(self):
        """Test that None outputs are converted to empty strings"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]

        reply = await runner.run(_mock_agent(output=None), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == ""

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]
        expected_reply = "The answer is 4"

        reply = await runner.run(_mock_agent(output=expected_reply), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == expected_reply

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that generic exceptions are caught and normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test")]

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=Exception("Something went wrong"))

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        # Error should be normalized - should start with "Error"
        assert reply.response.startswith("Error")

    @pytest.mark.asyncio
    async def test_runner_handles_service_unavailable_error(self):
        """Test that 503 Service Unavailable errors are properly normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="test query")]

        class ServiceUnavailableError(Exception):
            def __init__(self):
                super().__init__("Service temporarily unavailable")
                self.status_code = 503

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=ServiceUnavailableError())

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_handles_rate_limit_error(self):
        """Test that rate limit errors are properly normalized"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="too many requests")]

        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("Rate limit exceeded")
                self.status_code = 429

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=RateLimitError())

        reply = await runner.run(mock_agent, session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "Error" in reply.response

    @pytest.mark.asyncio
    async def test_runner_normalizes_numeric_reply(self):
        """Test that numeric outputs are converted to strings"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]

        reply = await runner.run(_mock_agent(output=42), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "42"
        assert isinstance(reply.response, str)

    @pytest.mark.asyncio
    async def test_runner_no_valid_content_short_circuits(self):
        """Test that a request list with no usable content short-circuits without invoking the agent"""
        runner = PydanticAIRunner()
        session = Session("test-session")
        mock_agent = _mock_agent(output="should not be used")

        reply = await runner.run(mock_agent, session, [])

        assert isinstance(reply, AgentReplyText)
        assert reply.response == "Sorry. No valid content found in the requests"
        mock_agent.agent.run.assert_not_called()


class TestPydanticAIRunnerStructuredOutput:
    """Test structured output detection on AgentRunResult.output"""

    @pytest.mark.asyncio
    async def test_pydantic_output_returns_agent_reply_any(self):
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        reply = await runner.run(_mock_agent(output=CalendarEvent(name="Launch", date="2026-07-08")), session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"name": "Launch", "date": "2026-07-08"}
        assert reply.prompt == "extract the event"

    @pytest.mark.asyncio
    async def test_dict_output_returns_agent_reply_any(self):
        runner = PydanticAIRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="extract the event")]

        reply = await runner.run(_mock_agent(output={"name": "Launch", "date": "2026-07-08"}), session, requests)

        assert isinstance(reply, AgentReplyAny)
        assert reply.content == {"name": "Launch", "date": "2026-07-08"}


class TestPydanticAISessionSerialization:
    """
    Serialization round-trip that has no analog in the sibling adapters: their session state is
    plain dicts/strings, but PydanticAISession holds Pydantic AI message history. It is stored in
    the jsonable form (to_jsonable_python) precisely so a BinarySerde pickle survives Pydantic AI's
    fast release cadence — this test guards that the history survives a pickle round-trip intact.
    """

    @staticmethod
    def _real_history() -> list:
        """Produce a non-trivial history of real ModelRequest/ModelResponse instances via TestModel."""

        async def go() -> list:
            agent = Agent(model=TestModel(), name="serde")
            r1 = await agent.run("hello")
            r2 = await agent.run("and again", message_history=r1.all_messages())
            return r2.all_messages()

        return asyncio.run(go())

    def test_session_survives_binaryserde_roundtrip(self):
        messages = self._real_history()
        jsonable = to_jsonable_python(messages)
        assert len(messages) >= 2 and all(isinstance(m, dict) for m in jsonable)

        fw_session = PydanticAISession()
        fw_session.messages = jsonable

        restored: PydanticAISession = BinarySerde.loads(BinarySerde.dumps(fw_session))

        assert isinstance(restored, PydanticAISession)
        assert restored.messages == jsonable
        # The jsonable form reconstructs into real Pydantic AI messages identically.
        reconstructed = ModelMessagesTypeAdapter.validate_python(restored.messages)
        assert len(reconstructed) == len(messages)
        assert to_jsonable_python(reconstructed) == jsonable

    def test_session_nested_in_full_session_roundtrip(self):
        """The stores pickle the whole Session; the PydanticAISession under FRAMEWORK survives it."""
        jsonable = to_jsonable_python(self._real_history())
        session = Session("serde-session")
        fw_session = PydanticAISession()
        fw_session.messages = jsonable
        session.set(FRAMEWORK, fw_session)

        restored_session: Session = BinarySerde.loads(BinarySerde.dumps(session))
        restored_fw = restored_session.get(FRAMEWORK)

        assert isinstance(restored_fw, PydanticAISession)
        assert restored_fw.messages == jsonable


class TestPydanticAIMultimodalWiring:
    """
    Guards design.md's explicit requirement: missing override_system_prompt/attach_tool would make
    multimodal support silently degrade rather than error. With multimodal enabled, both wiring
    points must fire during PydanticAIAgent.__init__ — this test fails loudly if either breaks,
    instead of passing vacuously.
    """

    def test_multimodal_wiring_fires_on_init(self, monkeypatch):
        # Enable multimodal for this test only (monkeypatch restores afterwards).
        monkeypatch.setattr(AKConfig.get().multimodal, "enabled", True)

        # With multimodal on, the system-tool prompt suffix is non-empty — so override_system_prompt
        # has real content to register.
        suffix = SystemToolFactory.get_system_prompt_suffix()
        assert suffix

        native = Agent(model=TestModel(), name="mm", description="multimodal agent")

        # Spy on instructions() — Pydantic AI's instructions have no public read-back, so we assert
        # override_system_prompt fired by observing the decorator registration call itself.
        with mock.patch.object(native, "instructions", wraps=native.instructions) as instructions_spy:
            PydanticAIAgent("mm", PydanticAIRunner(), native)

        # override_system_prompt() invoked the instructions decorator during __init__.
        assert instructions_spy.called

        # attach_tool() registered the multimodal analyze-attachments system tool on the toolset.
        function_toolset = next(ts for ts in native.toolsets if isinstance(ts, FunctionToolset))
        assert any("analyze" in name for name in function_toolset.tools)


class TestPydanticAIAgentDescription:
    """get_description() returns description= when set, else falls back to string instructions."""

    def test_description_returned_when_set(self):
        native = Agent(model=TestModel(), name="d", description="a described agent", instructions="ignored")
        assert PydanticAIAgent("d", PydanticAIRunner(), native).get_description() == "a described agent"

    def test_falls_back_to_instructions_when_description_unset(self):
        native = Agent(model=TestModel(), name="i", instructions="you do math")
        assert PydanticAIAgent("i", PydanticAIRunner(), native).get_description() == "you do math"

    def test_empty_when_neither_set(self):
        native = Agent(model=TestModel(), name="n")
        assert PydanticAIAgent("n", PydanticAIRunner(), native).get_description() == ""
