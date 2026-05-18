from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.core import Session
from agentkernel.core.model import (
    AgentReplyText,
    AgentRequestAny,
    AgentRequestImage,
    AgentRequestText,
)
from agentkernel.core.util.error_util import user_facing_error_message
from agentkernel.framework.smolagents.smolagents import SmolagentsRunner


class TestSmolagentsRunnerErrorHandling:
    """Test error handling and memory persistence in SmolagentsRunner.run()"""

    @pytest.mark.asyncio
    async def test_runner_with_none_reply_returns_empty_string(self):
        """Test that None replies are converted to empty strings"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="hello")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            mock_to_thread.return_value = None
            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.text in ("", "None")

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="Hello smolagents")]

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
            assert reply.text == "Hello user!"

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that execution exceptions fall back to the secure user_facing_error_message"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="Fail me")]

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
            assert reply.text == user_facing_error_message(error)

    @pytest.mark.asyncio
    async def test_runner_normalizes_numeric_reply(self):
        """Test that numeric replies are converted to strings"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="what is 2+2?")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_hydrate_memory"),
            patch.object(runner, "_sync_memory"),
            patch("agentkernel.framework.smolagents.smolagents.asyncio.to_thread") as mock_to_thread,
        ):

            mock_to_thread.return_value = 42

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.text == "42"
            assert isinstance(reply.text, str)

    @pytest.mark.asyncio
    async def test_runner_handles_non_text_request(self):
        """Test that runner gracefully rejects non-text inputs like images"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(image_data="base64data", name="image.png", type="image", mime_type="image/png")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "unable to handle content other than text" in reply.text

    @pytest.mark.asyncio
    async def test_runner_skips_request_any_and_handles_empty_prompt(self):
        """Test that AgentRequestAny is skipped and empty prompts are rejected"""
        runner = SmolagentsRunner()
        session = Session("test-session")
        requests = [AgentRequestAny(content={"foo": "bar"}, name="custom_data", type="other", mime_type="other"), AgentRequestText(text="   ")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "No valid text prompt found" in reply.text
