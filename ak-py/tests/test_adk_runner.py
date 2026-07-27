import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.model import AgentReplyAny, AgentReplyText, AgentRequestText
from agentkernel.framework.adk.adk import GoogleADKRunner, GoogleADKSession

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


def _partial_event(text: str):
    """An ADK SSE event the runner treats as a streamable text delta."""
    event = MagicMock()
    part = MagicMock()
    part.text = text
    event.content = MagicMock(parts=[part])
    event.partial = True
    return event


def _stream_setup(events, state):
    """Patch _setup_session_context so stream() drains `events` and reads `state` back."""
    adk_session = MagicMock()
    adk_session.get_state = AsyncMock(return_value=state)

    async def run_async(**kwargs):
        for event in events:
            yield event

    adk_runner = MagicMock()
    adk_runner.run_async = run_async
    setup = AsyncMock(return_value=("user", adk_runner, _ctx_mock(), adk_session))
    return patch.object(GoogleADKRunner, "_setup_session_context", setup), adk_session


def _run_with_response(runner, agent, session, requests, response_text, adk_session=None):
    if adk_session is None:
        adk_session = MagicMock()
        adk_session.get_state = AsyncMock(return_value={})
    setup = AsyncMock(return_value=("user", MagicMock(), _ctx_mock(), adk_session))
    get_response = AsyncMock(return_value=response_text)
    return patch.object(runner, "_setup_session_context", setup), patch.object(GoogleADKRunner, "get_response", get_response)


class TestGoogleADKSessionState:
    """GoogleADKSession.get_state returns only session-scoped caller state."""

    @pytest.mark.asyncio
    async def test_internal_and_scope_prefixed_keys_are_stripped(self):
        """app:/user:/temp: keys are not caller state and must never enter framework_context."""
        adk_session = GoogleADKSession()
        adk_session._session = MagicMock(id="s", app_name="AgentKernel", user_id="AgentKernel")
        refreshed = MagicMock()
        refreshed.state = {
            "cart": ["milk"],  # caller / tool state — kept
            "ak_tool_context": "ctx-id",  # AK-internal — stripped
            "app:theme": "dark",  # merged in by InMemorySessionService._merge_state — stripped
            "user:tier": "gold",  # merged in by InMemorySessionService._merge_state — stripped
            "temp:scratch": 1,  # invocation-scoped — stripped
        }
        adk_session._session_service = MagicMock()
        adk_session._session_service.get_session = AsyncMock(return_value=refreshed)

        assert await adk_session.get_state() == {"cart": ["milk"]}

    @pytest.mark.asyncio
    async def test_lookup_uses_the_created_sessions_identifiers(self):
        """The read-back must not depend on hardcoded app/user names that could drift."""
        adk_session = GoogleADKSession()
        adk_session._session = MagicMock(id="sid", app_name="OtherApp", user_id="other-user")
        adk_session._session_service = MagicMock()
        adk_session._session_service.get_session = AsyncMock(return_value=MagicMock(state={}))

        await adk_session.get_state()

        adk_session._session_service.get_session.assert_awaited_once_with(app_name="OtherApp", user_id="other-user", session_id="sid")

    @pytest.mark.asyncio
    async def test_no_session_returns_empty_state(self):
        assert await GoogleADKSession().get_state() == {}


class TestGoogleADKRunnerStateSeeding:
    """The caller's context is seeded into ADK state without displacing AK-internal keys."""

    @pytest.mark.asyncio
    async def test_caller_key_cannot_override_ak_tool_context(self):
        """A context key named ak_tool_context would break AKToolContext.fetch for every tool."""
        runner = GoogleADKRunner()
        session = Session("s")
        agent = _mock_agent(output_schema=None)

        adk_session = MagicMock()
        adk_session.create_session = AsyncMock()
        adk_session.update_session_state = AsyncMock()

        with patch.object(GoogleADKRunner, "_session", return_value=adk_session), patch("agentkernel.framework.adk.adk.Runner"):
            _, _, ctx, _ = await runner._setup_session_context(agent, session, [], {"ak_tool_context": "hijacked", "cart": []})

        _, _, state = adk_session.update_session_state.await_args.args
        assert state["ak_tool_context"] == ctx.id
        assert state["cart"] == []


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

    @pytest.mark.asyncio
    async def test_stream_normal_drain_writes_back(self):
        """A drained stream writes back the stripped ADK state, including tool-added keys."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"seeded": 9, "added": "new"})
        with setup_patch:
            deltas = [delta async for delta in runner.stream(agent, session, requests)]

        assert deltas == ["tok"]
        adk_session.get_state.assert_awaited_once()
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 9, "added": "new"}

    @pytest.mark.asyncio
    async def test_stream_disconnect_leaves_context_intact(self):
        """A client disconnect (GeneratorExit at a yield) skips the state read and write-back."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"seeded": 9})
        with setup_patch:
            agen = runner.stream(agent, session, requests)
            first = await agen.__anext__()
            assert first == "tok"
            await agen.aclose()  # simulate client disconnect at the yield

        adk_session.get_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}

    @pytest.mark.asyncio
    async def test_stream_absent_key_skips_write_back(self):
        runner = GoogleADKRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {"leak": 1})
        with setup_patch:
            deltas = [delta async for delta in runner.stream(agent, session, requests)]

        assert deltas == ["tok"]
        adk_session.get_state.assert_not_called()
        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_stream_write_back_failure_is_logged_not_raised(self, caplog):
        """A failed state read must not escape the generator after the response was streamed."""
        runner = GoogleADKRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]
        agent = _mock_agent(output_schema=None)

        setup_patch, adk_session = _stream_setup([_partial_event("tok")], {})
        adk_session.get_state = AsyncMock(side_effect=RuntimeError("state read failed"))

        with setup_patch, caplog.at_level(logging.ERROR, logger="ak.core.runner"):
            deltas = [delta async for delta in runner.stream(agent, session, requests)]

        assert deltas == ["tok"]
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}
        assert any("framework_context write-back was skipped" in r.message for r in caplog.records)


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
