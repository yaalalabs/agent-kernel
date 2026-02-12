"""
Tests for OpenAIToolBuilder.

Since the OpenAI Agents SDK is an optional dependency, the SDK modules are mocked
to allow testing the tool binding logic without requiring the SDK to be installed.
"""

import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.base import Session
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import ToolBuilder, ToolContext


# ---------------------------------------------------------------------------
# Helpers – mock the OpenAI Agents SDK
# ---------------------------------------------------------------------------


def _make_openai_mocks():
    """Create mock modules for the OpenAI Agents SDK."""
    captured_tools = []

    def fake_function_tool(func):
        """Simulate agents.function_tool: wraps a callable into a tool object."""
        tool = MagicMock()
        tool.name = getattr(func, "__name__", "unknown")
        tool.description = getattr(func, "__doc__", "") or ""
        tool._func = func
        captured_tools.append(tool)
        return tool

    agents_mod = types.ModuleType("agents")
    agents_mod.Agent = MagicMock
    agents_mod.Runner = MagicMock
    agents_mod.function_tool = fake_function_tool

    memory_mod = types.ModuleType("agents.memory")
    session_mod = types.ModuleType("agents.memory.session")
    session_mod.SessionABC = MagicMock
    memory_mod.session = session_mod

    agents_mod.memory = memory_mod

    return agents_mod, memory_mod, session_mod, captured_tools


@pytest.fixture(autouse=True)
def _mock_openai_sdk():
    """Inject mock OpenAI SDK modules for every test in this file."""
    agents_mod, memory_mod, session_mod, _ = _make_openai_mocks()
    patches = {
        "agents": agents_mod,
        "agents.memory": memory_mod,
        "agents.memory.session": session_mod,
    }
    with patch.dict(sys.modules, patches):
        # Force re-import so the module picks up the mocks
        if "agentkernel.framework.openai.openai" in sys.modules:
            del sys.modules["agentkernel.framework.openai.openai"]
        if "agentkernel.framework.openai" in sys.modules:
            del sys.modules["agentkernel.framework.openai"]
        yield


def _get_builder():
    """Import OpenAIToolBuilder after mocks are in place."""
    from agentkernel.framework.openai.openai import OpenAIToolBuilder

    return OpenAIToolBuilder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenAIToolBuilderBindSync:
    def test_bind_sync_tool(self):
        def get_weather(city: str) -> str:
            """Get the weather for a city."""
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        # The mock function_tool wraps the callable; verify it was invoked
        assert tools[0].name == "get_weather"

    def test_bind_sync_tool_invocation(self):
        def get_weather(city: str) -> str:
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        # The underlying function should be callable
        result = tools[0]._func(city="Berlin")
        assert result == "Sunny in Berlin"


class TestOpenAIToolBuilderBindAsync:
    def test_bind_async_tool(self):
        async def get_weather(city: str) -> str:
            """Get weather async."""
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert tools[0].name == "get_weather"

    @pytest.mark.asyncio
    async def test_bind_async_tool_invocation(self):
        async def get_weather(city: str) -> str:
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = await tools[0]._func(city="London")
        assert result == "Rainy in London"


class TestOpenAIToolBuilderWithContext:
    def test_bind_with_tool_context(self):
        def get_weather(city: str, ctx: ToolContext) -> str:
            """Get weather with context."""
            return f"Weather in {city}, session={ctx.session.id}"

        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("openai-session")

        Builder = _get_builder()
        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                tools = Builder.bind([get_weather])
                assert len(tools) == 1
                result = tools[0]._func(city="NYC")
                assert "Weather in NYC" in result
                assert "session=openai-session" in result

    def test_bind_without_tool_context(self):
        def get_weather(city: str) -> str:
            return f"Weather in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0]._func(city="Rome")
        assert result == "Weather in Rome"


class TestOpenAIToolBuilderMultiple:
    def test_bind_multiple_tools(self):
        def get_weather(city: str) -> str:
            """Get weather."""
            return city

        def get_forecast(city: str, days: int = 7) -> str:
            """Get forecast."""
            return f"{city}:{days}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather, get_forecast])
        assert len(tools) == 2
        assert tools[0].name == "get_weather"
        assert tools[1].name == "get_forecast"


class TestOpenAIToolBuilderErrors:
    def test_bind_non_callable_raises(self):
        Builder = _get_builder()
        with pytest.raises(TypeError, match="Expected a callable"):
            Builder.bind(["not_a_function"])
