from unittest.mock import Mock, patch

import pytest

from agentkernel.core.base import Agent, Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyAny, AgentReplyImage, AgentReplyText, AgentRequestText
from agentkernel.core.util.factory import AKConfigError
from agentkernel.guardrail.guardrail import (
    BaseGuardrailUtil,
    InputGuardrail,
    InputGuardrailFactory,
    OutputGuardrail,
    OutputGuardrailFactory,
)
from agentkernel.guardrail.openai import OpenAIInputGuardrail, OpenAIOutputGuardrail


@pytest.fixture
def mock_session():
    """Fixture to create a mock Session object."""
    return Session("test-session-id")


@pytest.fixture
def mock_agent():
    """Fixture to create a mock Agent object."""
    agent = Mock(spec=Agent)
    agent.name = "test-agent"
    return agent


@pytest.fixture
def sample_requests():
    """Fixture to create sample agent requests."""
    return [
        AgentRequestText(prompt="Hello, world!"),
        AgentRequestText(prompt="How are you?"),
    ]


@pytest.fixture
def sample_reply():
    """Fixture to create a sample agent reply."""
    return AgentReplyText(response="I'm doing great!", prompt="How are you?")


class TestInputGuardrail:
    """Tests for InputGuardrail class."""

    @pytest.mark.asyncio
    async def test_on_run_returns_requests(self, mock_session, mock_agent, sample_requests):
        """Test that InputGuardrail.on_run returns the requests unchanged."""
        guardrail = InputGuardrail()
        result = await guardrail.on_run(mock_session, mock_agent, sample_requests)
        assert result == sample_requests
        assert len(result) == 2

    def test_name(self):
        """Test that InputGuardrail.name returns correct name."""
        guardrail = InputGuardrail()
        assert guardrail.name() == "InputGuardrail"


class TestOutputGuardrail:
    """Tests for OutputGuardrail class."""

    @pytest.mark.asyncio
    async def test_on_run_returns_reply(self, mock_session, mock_agent, sample_requests, sample_reply):
        """Test that OutputGuardrail.on_run returns the reply unchanged."""
        guardrail = OutputGuardrail()
        result = await guardrail.on_run(mock_session, sample_requests, mock_agent, sample_reply)
        assert result == sample_reply
        assert result.response == "I'm doing great!"

    def test_name(self):
        """Test that OutputGuardrail.name returns correct name."""
        guardrail = OutputGuardrail()
        assert guardrail.name() == "OutputGuardrail"


class TestInputGuardrailFactory:
    """Tests for InputGuardrailFactory class."""

    def test_get_returns_input_guardrail_when_disabled(self, monkeypatch):
        """Test that factory returns InputGuardrail when guardrail is disabled."""
        # Mock the config to disable guardrail
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = False
            mock_get.return_value = mock_config

            guardrail = InputGuardrailFactory.get()
            assert isinstance(guardrail, InputGuardrail)
            assert not isinstance(guardrail, OpenAIInputGuardrail)

    def test_get_returns_openai_guardrail_when_enabled(self, monkeypatch):
        """Test that factory returns OpenAIInputGuardrail when enabled with openai type."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = True
            mock_config.guardrail.input.type = "openai"
            mock_get.return_value = mock_config

            guardrail = InputGuardrailFactory.get()
            assert isinstance(guardrail, OpenAIInputGuardrail)

    def test_get_raises_akconfigerror_for_unknown_type(self):
        """An unknown, non-dotted type fails loud with AKConfigError."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = True
            mock_config.guardrail.input.type = "unknown_type"
            mock_get.return_value = mock_config

            with pytest.raises(AKConfigError) as exc_info:
                InputGuardrailFactory.get()
            assert "unknown_type" in str(exc_info.value)

    def test_get_resolves_byo_dotted_path(self):
        """A dotted path to an InputGuardrail subclass resolves (bring-your-own)."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = True
            mock_config.guardrail.input.type = "agentkernel.guardrail.openai.OpenAIInputGuardrail"
            mock_get.return_value = mock_config

            assert isinstance(InputGuardrailFactory.get(), OpenAIInputGuardrail)

    def test_get_rejects_non_subclass_dotted_path(self):
        """A dotted path that is not an InputGuardrail subclass is a config error."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = True
            mock_config.guardrail.input.type = "builtins.str"
            mock_get.return_value = mock_config

            with pytest.raises(AKConfigError):
                InputGuardrailFactory.get()


class TestOutputGuardrailFactory:
    """Tests for OutputGuardrailFactory class."""

    def test_get_returns_output_guardrail_when_disabled(self):
        """Test that factory returns OutputGuardrail when guardrail is disabled."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.output.enabled = False
            mock_get.return_value = mock_config

            guardrail = OutputGuardrailFactory.get()
            assert isinstance(guardrail, OutputGuardrail)
            assert not isinstance(guardrail, OpenAIOutputGuardrail)

    def test_get_returns_openai_guardrail_when_enabled(self):
        """Test that factory returns OpenAIOutputGuardrail when enabled with openai type."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.output.enabled = True
            mock_config.guardrail.output.type = "openai"
            mock_get.return_value = mock_config

            guardrail = OutputGuardrailFactory.get()
            assert isinstance(guardrail, OpenAIOutputGuardrail)

    def test_get_raises_akconfigerror_for_unknown_type(self):
        """An unknown, non-dotted type fails loud with AKConfigError."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.output.enabled = True
            mock_config.guardrail.output.type = "invalid_type"
            mock_get.return_value = mock_config

            with pytest.raises(AKConfigError) as exc_info:
                OutputGuardrailFactory.get()
            assert "invalid_type" in str(exc_info.value)

    def test_get_resolves_byo_dotted_path(self):
        """A dotted path to an OutputGuardrail subclass resolves (bring-your-own)."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.output.enabled = True
            mock_config.guardrail.output.type = "agentkernel.guardrail.openai.OpenAIOutputGuardrail"
            mock_get.return_value = mock_config

            assert isinstance(OutputGuardrailFactory.get(), OpenAIOutputGuardrail)


class TestOpenAIInputGuardrail:
    """Tests for OpenAIInputGuardrail class."""

    @pytest.mark.asyncio
    async def test_on_run_returns_requests(self, mock_session, mock_agent, sample_requests):
        """Test that OpenAIInputGuardrail.on_run returns the requests unchanged."""
        guardrail = OpenAIInputGuardrail()
        result = await guardrail.on_run(mock_session, mock_agent, sample_requests)
        assert result == sample_requests
        assert len(result) == 2

    def test_name(self):
        """Test that OpenAIInputGuardrail.name returns correct name."""
        guardrail = OpenAIInputGuardrail()
        assert guardrail.name() == "OpenAIInputGuardrail"

    def test_inherits_from_input_guardrail(self):
        """Test that OpenAIInputGuardrail inherits from InputGuardrail."""
        guardrail = OpenAIInputGuardrail()
        assert isinstance(guardrail, InputGuardrail)


class TestOpenAIOutputGuardrail:
    """Tests for OpenAIOutputGuardrail class."""

    @pytest.mark.asyncio
    async def test_on_run_returns_reply(self, mock_session, mock_agent, sample_requests, sample_reply):
        """Test that OpenAIOutputGuardrail.on_run returns the reply unchanged."""
        guardrail = OpenAIOutputGuardrail()
        result = await guardrail.on_run(mock_session, sample_requests, mock_agent, sample_reply)
        assert result == sample_reply
        assert result.response == "I'm doing great!"

    def test_name(self):
        """Test that OpenAIOutputGuardrail.name returns correct name."""
        guardrail = OpenAIOutputGuardrail()
        assert guardrail.name() == "OpenAIOutputGuardrail"

    def test_inherits_from_output_guardrail(self):
        """Test that OpenAIOutputGuardrail inherits from OutputGuardrail."""
        guardrail = OpenAIOutputGuardrail()
        assert isinstance(guardrail, OutputGuardrail)


class TestBaseGuardrailUtil:
    """Tests for the shared text extraction utilities."""

    def test_extract_text_from_text_reply(self):
        reply = AgentReplyText(response="hello", prompt="hi")
        assert BaseGuardrailUtil._extract_text_from_reply(reply) == "hello"

    def test_extract_text_from_structured_reply_returns_json(self):
        """Structured replies must be scanned as their JSON serialization, not skipped."""
        import json

        content = {"city": "Colombo", "temp_c": 31}
        reply = AgentReplyAny(content=content)
        assert BaseGuardrailUtil._extract_text_from_reply(reply) == json.dumps(content)

    def test_extract_text_from_image_reply(self):
        """Image replies must have their caption text scanned, not silently skipped."""
        reply = AgentReplyImage(response="a caption", image_data="base64data", name="pic.png")
        assert BaseGuardrailUtil._extract_text_from_reply(reply) == "a caption"
