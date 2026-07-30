import asyncio
import logging
from contextlib import asynccontextmanager
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, FunctionToolset, RunContext
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


def _mock_stream_agent(deltas, on_stream=None):
    """
    Build a mock agent whose ``run_stream`` is an async context manager yielding the given deltas, so
    ``stream()`` can be driven (and closed mid-stream) without Pydantic AI's real anyio scopes. The deps
    the runner injected are recorded on ``captured_deps``; ``on_stream`` mutates them like a native tool.
    """
    mock_agent = MagicMock()
    mock_agent.captured_deps = None

    @asynccontextmanager
    async def run_stream(content, message_history=None, deps=None):
        mock_agent.captured_deps = deps
        result = MagicMock()

        async def stream_text(delta=True):
            if on_stream is not None and deps is not None:
                on_stream(deps)
            for d in deltas:
                yield d

        result.stream_text = stream_text
        result.all_messages = MagicMock(return_value=[])
        yield result

    mock_agent.agent = MagicMock()
    mock_agent.agent.run_stream = run_stream
    return mock_agent


class TestPydanticAIRunnerFrameworkContext:
    """
    framework_context injection and write-back for PydanticAIRunner. ``deps`` is Pydantic AI's only
    caller-dependency slot and AK owns it — the runner previously passed no ``deps=`` at all, so every
    agent received the ``None`` default. Fidelity matches OpenAI (full round-trip), because tools mutate
    the injected object in place through ``RunContext.deps``.
    """

    @pytest.mark.asyncio
    async def test_context_injected_as_deps(self):
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"user_id": "42"})

        mock_agent = _mock_agent(output="done")
        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        _, kwargs = mock_agent.agent.run.call_args
        assert kwargs["deps"] == {"user_id": "42"}
        # History handling is unchanged by the injection.
        assert "message_history" in kwargs

    @pytest.mark.asyncio
    async def test_absent_key_passes_deps_none(self):
        """Matches today's implicit behaviour: no context set means the deps default."""
        runner = PydanticAIRunner()
        session = Session("s")

        mock_agent = _mock_agent(output="done")
        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        _, kwargs = mock_agent.agent.run.call_args
        assert kwargs["deps"] is None
        assert session.get_framework_context() is None

    @pytest.mark.asyncio
    async def test_in_place_mutation_written_back(self):
        """A RunContext-taking tool mutating ctx.deps round-trips to the session key."""
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"cart": []})

        mock_result = MagicMock()
        mock_result.output = "done"
        mock_result.all_messages = MagicMock(return_value=[])

        async def fake_run(content, message_history=None, deps=None):
            deps["cart"].append("apple")
            return mock_result

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = fake_run

        await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = PydanticAIRunner()
        session = Session("s")
        session.set_framework_context({"cart": []})

        mock_agent = MagicMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = AsyncMock(side_effect=Exception("boom"))

        reply = await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

        assert isinstance(reply, AgentReplyText)
        assert session.get_framework_context() == {"cart": []}

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        """Uses the real run_stream path: a native tool mutates ctx.deps, write-back stores it."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        native = Agent(model=TestModel(custom_output_text="ok"), name="s", deps_type=dict)

        @native.tool
        def add_item(ctx: RunContext[dict], item: str) -> str:
            """Append an item to the caller's cart carried in deps."""
            ctx.deps["cart"].append("apple")
            return "added"

        agent = PydanticAIAgent("s", runner, native)

        deltas = [delta async for delta in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert deltas
        assert session.get_framework_context() == {"cart": ["apple"]}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        """
        A client disconnect (GeneratorExit at a yield) skips the write-back after the delta loop.
        Mocks run_stream rather than using TestModel: closing the generator mid-stream from the test task
        cannot unwind Pydantic AI's real anyio cancel scope, which is a test-harness limit, not a runner one.
        """
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        mock_agent = _mock_stream_agent(["hello", " world"], on_stream=lambda deps: deps["cart"].append("apple"))

        agen = runner.stream(mock_agent, session, [AgentRequestText(prompt="hi")])
        assert await agen.__anext__() == "hello"
        await agen.aclose()  # simulate client disconnect at the yield

        assert session.get_framework_context() == {"cart": []}

    @pytest.mark.asyncio
    async def test_stream_injects_deps_and_absent_key_passes_none(self):
        runner = PydanticAIRunner()
        session = Session("stream-session")

        mock_agent = _mock_stream_agent(["hi"])
        _ = [delta async for delta in runner.stream(mock_agent, session, [AgentRequestText(prompt="hi")])]
        assert mock_agent.captured_deps is None
        assert session.get_framework_context() is None

        session.set_framework_context({"user_id": "42"})
        mock_agent = _mock_stream_agent(["hi"])
        _ = [delta async for delta in runner.stream(mock_agent, session, [AgentRequestText(prompt="hi")])]
        assert mock_agent.captured_deps == {"user_id": "42"}

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A non-picklable context must not turn an already-streamed response into a transport error."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        session.set_framework_context({"cart": []})

        native = Agent(model=TestModel(custom_output_text="ok"), name="s", deps_type=dict)

        @native.tool
        def stash_callable(ctx: RunContext[dict], item: str) -> str:
            """Store a non-picklable value, standing in for a tool that stashes a live handle."""
            ctx.deps["bad"] = lambda: 1
            return "stashed"

        agent = PydanticAIAgent("s", runner, native)

        with caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            deltas = [delta async for delta in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        assert deltas
        assert session.get_framework_context() == {"cart": []}
        assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


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


class TestPydanticAIRunnerStreaming:
    """
    Cover PydanticAIRunner.stream() — the adapter's headline differentiator (every sibling except
    OpenAI stubs stream() with NotImplementedError), and previously the only capability shipped with
    no automated test. The e2e harness can't drive SSE, but a generator-level unit test can: it
    asserts deltas are yielded and that session history is persisted from the streamed result,
    mirroring the run() tests. Uses the real TestModel streaming path rather than mocks.
    """

    @pytest.mark.asyncio
    async def test_stream_yields_deltas_and_persists_history(self):
        runner = PydanticAIRunner()
        session = Session("stream-session")
        native = Agent(model=TestModel(custom_output_text="hello world from stream"), name="s")
        agent = PydanticAIAgent("s", runner, native)

        deltas = [delta async for delta in runner.stream(agent, session, [AgentRequestText(prompt="hi")])]

        # Real token deltas were produced and reassemble into the model output.
        assert deltas
        assert all(isinstance(d, str) and d for d in deltas)
        assert "".join(deltas) == "hello world from stream"

        # The streamed run persisted its message history into the framework session (jsonable form),
        # so a follow-up turn resumes the conversation just like the run() path.
        fw_session = session.get(FRAMEWORK)
        assert isinstance(fw_session, PydanticAISession)
        assert fw_session.messages
        assert ModelMessagesTypeAdapter.validate_python(fw_session.messages)

    @pytest.mark.asyncio
    async def test_stream_no_valid_content_yields_nothing(self):
        """A request list with no usable content short-circuits before invoking the agent."""
        runner = PydanticAIRunner()
        session = Session("stream-session")
        native = Agent(model=TestModel(custom_output_text="unused"), name="s")
        agent = PydanticAIAgent("s", runner, native)

        deltas = [delta async for delta in runner.stream(agent, session, [])]

        assert deltas == []
        assert session.get(FRAMEWORK) is None


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
