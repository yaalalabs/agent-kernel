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
from agentkernel.framework.autogen.autogen import AutogenRunner


class TestAutogenRunnerErrorHandling:
    """Test error handling and memory persistence in AutogenRunner.run()"""

    @pytest.mark.asyncio
    async def test_runner_with_normal_text_reply(self):
        """Test normal text reply handling"""
        runner = AutogenRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="Hello autogen")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_session"),
            patch("agentkernel.framework.autogen.autogen.autogen.UserProxyAgent") as mock_proxy,
            patch("agentkernel.framework.autogen.autogen.asyncio.to_thread") as mock_to_thread,
        ):
            mock_result = MagicMock()
            mock_result.summary = "Hello user!"
            mock_to_thread.return_value = mock_result

            reply = await runner.run(mock_agent, session, requests)

            mock_proxy.assert_called_once()
            mock_to_thread.assert_called_once()

            assert isinstance(reply, AgentReplyText)
            assert reply.text == "Hello user!"

    @pytest.mark.asyncio
    async def test_runner_handles_generic_exception(self):
        """Test that execution exceptions fall back to the secure user_facing_error_message"""
        runner = AutogenRunner()
        session = Session("test-session")
        requests = [AgentRequestText(text="Fail me")]

        mock_agent = MagicMock()

        with (
            patch.object(runner, "_session"),
            patch("agentkernel.framework.autogen.autogen.autogen.UserProxyAgent"),
            patch("agentkernel.framework.autogen.autogen.asyncio.to_thread") as mock_to_thread,
        ):

            error = ValueError("Secret API key expired!")
            mock_to_thread.side_effect = error

            reply = await runner.run(mock_agent, session, requests)

            assert isinstance(reply, AgentReplyText)
            assert reply.text == user_facing_error_message(error)

    @pytest.mark.asyncio
    async def test_runner_handles_non_text_request(self):
        """Test that runner gracefully rejects non-text inputs like images"""
        runner = AutogenRunner()
        session = Session("test-session")
        requests = [AgentRequestImage(image_data="base64data", name="image.png", type="image", mime_type="image/png")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "unable to handle content other than text" in reply.text

    @pytest.mark.asyncio
    async def test_runner_skips_request_any_and_handles_empty_prompt(self):
        """Test that AgentRequestAny is skipped and empty prompts are rejected"""
        runner = AutogenRunner()
        session = Session("test-session")
        requests = [AgentRequestAny(content={"foo": "bar"}, name="custom_data", type="other", mime_type="other"), AgentRequestText(text="   ")]

        reply = await runner.run(MagicMock(), session, requests)

        assert isinstance(reply, AgentReplyText)
        assert "No valid text prompt found" in reply.text
