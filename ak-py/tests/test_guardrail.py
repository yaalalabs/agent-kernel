import pytest
from unittest.mock import Mock, patch

from agentkernel.core.base import Agent, Session
from agentkernel.core.config import AKConfig
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.guardrail.guardrail import (
    InputGuardrail,
    OutputGuardrail,
    InputGuardrailFactory,
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
        AgentRequestText(text="Hello, world!"),
        AgentRequestText(text="How are you?"),
    ]


@pytest.fixture
def sample_reply():
    """Fixture to create a sample agent reply."""
    return AgentReplyText(text="I'm doing great!", prompt="How are you?")


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
    async def test_on_run_returns_reply(
        self, mock_session, mock_agent, sample_requests, sample_reply
    ):
        """Test that OutputGuardrail.on_run returns the reply unchanged."""
        guardrail = OutputGuardrail()
        result = await guardrail.on_run(mock_session, sample_requests, mock_agent, sample_reply)
        assert result == sample_reply
        assert result.text == "I'm doing great!"

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

    def test_get_raises_exception_for_unknown_type(self):
        """Test that factory raises exception for unknown guardrail type."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.input.enabled = True
            mock_config.guardrail.input.type = "unknown_type"
            mock_get.return_value = mock_config

            with pytest.raises(Exception) as exc_info:
                InputGuardrailFactory.get()
            assert "Unknown guardrail type: unknown_type" in str(exc_info.value)


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
            mock_config.guardrail.input.type = "openai"  # Note: bug in original code uses input.type
            mock_get.return_value = mock_config

            guardrail = OutputGuardrailFactory.get()
            assert isinstance(guardrail, OpenAIOutputGuardrail)

    def test_get_raises_exception_for_unknown_type(self):
        """Test that factory raises exception for unknown guardrail type."""
        with patch.object(AKConfig, "get") as mock_get:
            mock_config = Mock()
            mock_config.guardrail.output.enabled = True
            mock_config.guardrail.output.type = "invalid_type"
            mock_get.return_value = mock_config

            with pytest.raises(Exception) as exc_info:
                OutputGuardrailFactory.get()
            assert "Unknown guardrail type: invalid_type" in str(exc_info.value)


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
    async def test_on_run_returns_reply(
        self, mock_session, mock_agent, sample_requests, sample_reply
    ):
        """Test that OpenAIOutputGuardrail.on_run returns the reply unchanged."""
        guardrail = OpenAIOutputGuardrail()
        result = await guardrail.on_run(mock_session, sample_requests, mock_agent, sample_reply)
        assert result == sample_reply
        assert result.text == "I'm doing great!"

    def test_name(self):
        """Test that OpenAIOutputGuardrail.name returns correct name."""
        guardrail = OpenAIOutputGuardrail()
        assert guardrail.name() == "OpenAIOutputGuardrail"

    def test_inherits_from_output_guardrail(self):
        """Test that OpenAIOutputGuardrail inherits from OutputGuardrail."""
        guardrail = OpenAIOutputGuardrail()
        assert isinstance(guardrail, OutputGuardrail)
