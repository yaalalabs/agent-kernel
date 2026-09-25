from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from agentkernel.core import Session
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import (
    AgentReplyAny,
    AgentReplyText,
    AgentRequestAny,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.core.runtime import Runtime
from agentkernel.core.util.error_util import user_facing_error_message
from agentkernel.framework.smolagents.smolagents import SmolagentsAgent, SmolagentsModule, SmolagentsRunner

FRAMEWORK_CONTEXT = Session.Keys.FRAMEWORK_CONTEXT.value


class TestSmolagentsRunnerFrameworkContext:
    """framework_context injection (additional_args) and filtered write-back for SmolagentsRunner."""

    @pytest.mark.asyncio
    async def test_context_injected_and_seeded_keys_round_trip(self):
        runner = SmolagentsRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]

        mock_agent = MagicMock()
        # A tool mutated the seeded key and also added a brand-new internal entry.
        mock_agent.agent.state = {"seeded": 5, "internal": "leak"}

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = "ok"
            await runner.run(mock_agent, session, requests)

            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "hi", reset=False, additional_args={"seeded": 1})

        # Only the seeded key round-trips; the brand-new internal key is dropped.
        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 5}

    @pytest.mark.asyncio
    async def test_no_context_call_is_unchanged(self):
        """With no framework_context set, the call must not include additional_args."""
        runner = SmolagentsRunner()
        session = Session("s")
        requests = [AgentRequestText(prompt="hi")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = "ok"
            await runner.run(mock_agent, session, requests)

            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "hi", reset=False)

        assert session.get(FRAMEWORK_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_error_leaves_stored_context_intact(self):
        runner = SmolagentsRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        requests = [AgentRequestText(prompt="hi")]

        mock_agent = MagicMock()
        mock_agent.agent.state = {"seeded": 5}

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.side_effect = ValueError("boom")
            await runner.run(mock_agent, session, requests)

        assert session.get(FRAMEWORK_CONTEXT) == {"seeded": 1}


class TestSmolagentsRunnerErrorHandling:
    """Test error handling and memory persistence in SmolagentsRunner.run()"""

    @pytest.mark.asyncio
    async def test_runner_with_none_reply_returns_empty_string(self):
        """Test that None replies are converted to empty strings"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="hello")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            mock_to_thread.return_value = None
            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.response in ("", "None")

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="Hello smolagents")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory") as mock_hydrate,
            patch.object(runner, "_sync_memory") as mock_sync,
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            mock_to_thread.return_value = "Hello user!"

            reply = await runner.run(mock_agent, session, requests)

            mock_hydrate.assert_called_once_with(mock_agent, session)
            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "Hello smolagents", reset=False)
            mock_sync.assert_called_once_with(mock_agent, session)

            assert isinstance(reply, AgentReplyText)
            assert reply.response == "Hello user!"

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that execution exceptions fall back to the secure user_facing_error_message"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="Fail me")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            error = ValueError("Secret API key expired!")
            mock_to_thread.side_effect = error

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.response == user_facing_error_message(error)

    @pytest.mark.asyncio
    async def test_runner_normalizes_numeric_reply(self):
        """Test that numeric replies are converted to strings"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="what is 2+2?")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            mock_to_thread.return_value = 42

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.response == "42"
            assert isinstance(reply.response, str)

    @pytest.mark.asyncio
    async def test_runner_handles_non_text_request(self):
        """Test that runner gracefully rejects non-text inputs like images"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(image_data="base64data", name="image.png", type="image", mime_type="image/png")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "unable to handle content other than text" in reply.response

    @pytest.mark.asyncio
    async def test_runner_skips_request_any_and_handles_empty_prompt(self):
        """Test that AgentRequestAny is skipped and empty prompts are rejected"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestAny(content={"foo": "bar"}, name="custom_data", type="other", mime_type="other"), AgentRequestText(prompt="   ")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "No valid text prompt found" in reply.response


class FinalAnswer(BaseModel):
    verdict: str
    confidence: float


class TestSmolagentsRunnerStructuredOutput:
    """Test structured output detection on the final_answer value"""

    @pytest.mark.asyncio
    async def test_dict_reply_returns_agent_reply_any(self):
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="classify this")]

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = {"verdict": "spam", "confidence": 0.97}

            reply = await runner.run(MagicMock(), session, requests)

            assert isinstance(reply, AgentReplyAny)
            assert reply.content == {"verdict": "spam", "confidence": 0.97}
            assert reply.prompt == "classify this"

    @pytest.mark.asyncio
    async def test_pydantic_reply_returns_agent_reply_any(self):
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(prompt="classify this")]

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = FinalAnswer(verdict="ham", confidence=0.5)

            reply = await runner.run(MagicMock(), session, requests)

            assert isinstance(reply, AgentReplyAny)
            assert reply.content == {"verdict": "ham", "confidence": 0.5}


class TestSmolagentsRunOptions:
    """Declared run options merge into agent.run's kwargs; reset and additional_args stay AK-owned (spec #754)."""

    def test_reserved_keys(self):
        assert set(SmolagentsAgent.RESERVED_RUN_OPTIONS) == {"task", "reset", "additional_args", "stream", "return_full_result"}

    @pytest.mark.asyncio
    async def test_max_steps_is_forwarded_beside_reset(self):
        runner = SmolagentsRunner()
        mock_agent = MagicMock()
        mock_agent.run_options = {"max_steps": 4}

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = "ok"
            await runner.run(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])

            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "hi", max_steps=4, reset=False)

    @pytest.mark.asyncio
    async def test_bypassed_reset_and_additional_args_are_overwritten_by_the_ak_owned_values(self):
        runner = SmolagentsRunner()
        session = Session("s")
        session.set(FRAMEWORK_CONTEXT, {"seeded": 1})
        mock_agent = MagicMock()
        mock_agent.agent.state = {"seeded": 1}
        mock_agent.run_options = {"max_steps": 4, "reset": True, "additional_args": {"bypass": 1}}

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = "ok"
            await runner.run(mock_agent, session, [AgentRequestText(prompt="hi")])

            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "hi", max_steps=4, reset=False, additional_args={"seeded": 1})

        assert mock_agent.run_options == {"max_steps": 4, "reset": True, "additional_args": {"bypass": 1}}

    @pytest.mark.asyncio
    async def test_bypassed_additional_args_is_dropped_when_there_is_no_framework_context(self):
        runner = SmolagentsRunner()
        mock_agent = MagicMock()
        mock_agent.run_options = {"max_steps": 4, "additional_args": {"bypass": 1}}

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):
            mock_to_thread.return_value = "ok"
            await runner.run(mock_agent, Session("s"), [AgentRequestText(prompt="hi")])

            mock_to_thread.assert_called_once_with(mock_agent.agent.run, "hi", max_steps=4, reset=False)

    def test_module_resolves_the_agent_by_its_native_name_and_rejects_reserved_keys(self):
        from smolagents import ToolCallingAgent

        native = ToolCallingAgent(tools=[], model=MagicMock(), name="smol_reserved")

        with Runtime(SessionStoreBuilder.build()):
            module = SmolagentsModule([native])

            with pytest.raises(ValueError) as exc:
                module.run_options(native, reset=True)
            assert "'reset'" in str(exc.value)
            assert "'smolagents'" in str(exc.value)

            module.run_options(native, max_steps=6)
            assert module.get_agent("smol_reserved").run_options == {"max_steps": 6}

            hook = object()
            module.pre_hook(native, [hook]).post_hook(native, [hook])  # resolved by the smolagents name rule
            assert module.get_agent("smol_reserved").pre_hooks == [hook]
            assert module.get_agent("smol_reserved").post_hooks == [hook]
