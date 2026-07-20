from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText
from agentkernel.guardrail.walledai import WALLEDAI_PII_MAPPING_KEY, WalledAIOutputGuardrail


@pytest.fixture
def mock_session():
    """Fixture to create a mock Session object."""
    return Session("test-session-id")


@pytest.fixture
def guardrail(monkeypatch):
    """Fixture to create a WalledAIOutputGuardrail with mocked SDK clients."""
    monkeypatch.setenv("WALLED_API_KEY", "test-key")
    with patch("agentkernel.guardrail.walledai.WalledRedact"), patch("agentkernel.guardrail.walledai.WalledProtect"):
        return WalledAIOutputGuardrail()


def _pii_config(enabled: bool = True):
    """Build a mock AKConfig with output PII unmasking toggled."""
    mock_config = Mock()
    mock_config.guardrail.output.pii = enabled
    return mock_config


class TestWalledAIOutputGuardrail:
    """Tests for WalledAIOutputGuardrail unmasking behavior."""

    @pytest.mark.asyncio
    async def test_structured_reply_is_unmasked_and_stays_structured(self, guardrail, mock_session):
        """Test that an AgentReplyAny is returned as AgentReplyAny with placeholders replaced in content."""
        mock_session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, {"[NAME_1]": "John Doe"})
        reply = AgentReplyAny(content={"name": "[NAME_1]", "nested": {"note": "contact [NAME_1] today"}}, prompt="who?")

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert isinstance(result, AgentReplyAny)
        assert result.type == "other"
        assert result.content == {"name": "John Doe", "nested": {"note": "contact John Doe today"}}
        assert result.prompt == "who?"

    @pytest.mark.asyncio
    async def test_structured_reply_unmasking_with_json_special_characters(self, guardrail, mock_session):
        """Test that PII values with quotes and backslashes do not corrupt the structured content."""
        mock_session.get_non_volatile_cache().set(
            WALLEDAI_PII_MAPPING_KEY,
            {"[NAME_1]": 'O"Brien', "[PATH_1]": "C:\\Users\\obrien"},
        )
        reply = AgentReplyAny(content={"name": "[NAME_1]", "home": "[PATH_1]"})

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert isinstance(result, AgentReplyAny)
        assert result.content == {"name": 'O"Brien', "home": "C:\\Users\\obrien"}

    @pytest.mark.asyncio
    async def test_structured_reply_non_string_values_are_untouched(self, guardrail, mock_session):
        """Test that non-string values and non-string keys survive unmasking unchanged."""
        ts = datetime(2026, 1, 1)
        mock_session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, {"[NAME_1]": "John Doe"})
        reply = AgentReplyAny(content={"name": "[NAME_1]", "ts": ts, "counts": {1: 2}, "active": True})

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert isinstance(result, AgentReplyAny)
        assert result.content == {"name": "John Doe", "ts": ts, "counts": {1: 2}, "active": True}

    @pytest.mark.asyncio
    async def test_text_reply_is_unmasked_as_text(self, guardrail, mock_session):
        """Test that AgentReplyText unmasking behavior is unchanged."""
        mock_session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, {"[NAME_1]": "John Doe"})
        reply = AgentReplyText(response="Hello [NAME_1]!", prompt="greet")

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert isinstance(result, AgentReplyText)
        assert result.response == "Hello John Doe!"
        assert result.prompt == "greet"

    @pytest.mark.asyncio
    async def test_structured_reply_without_mapping_is_returned_unchanged(self, guardrail, mock_session):
        """Test that a structured reply passes through untouched when no mapping is stored."""
        reply = AgentReplyAny(content={"name": "[NAME_1]"})

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert result is reply

    @pytest.mark.asyncio
    async def test_structured_reply_with_pii_disabled_is_returned_unchanged(self, guardrail, mock_session):
        """Test that a structured reply passes through untouched when output PII unmasking is disabled."""
        mock_session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, {"[NAME_1]": "John Doe"})
        reply = AgentReplyAny(content={"name": "[NAME_1]"})

        with patch.object(AKConfig, "get", return_value=_pii_config(enabled=False)):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert result is reply

    @pytest.mark.asyncio
    async def test_image_reply_is_unmasked_and_stays_image(self, guardrail, mock_session):
        """Test that AgentReplyImage is returned as AgentReplyImage with text unmasked and image data preserved."""
        mock_session.get_non_volatile_cache().set(WALLEDAI_PII_MAPPING_KEY, {"[NAME_1]": "John Doe"})
        reply = AgentReplyImage(
            response="badge of [NAME_1]",
            image_data="base64encodeddata",
            name="badge.png",
            mime_type="image/png",
            prompt="show badge",
        )

        with patch.object(AKConfig, "get", return_value=_pii_config()):
            result = await guardrail.on_run(mock_session, [], Mock(), reply)

        assert isinstance(result, AgentReplyImage)
        assert result.response == "badge of John Doe"
        assert result.image_data == "base64encodeddata"
        assert result.name == "badge.png"
        assert result.mime_type == "image/png"
        assert result.prompt == "show badge"
