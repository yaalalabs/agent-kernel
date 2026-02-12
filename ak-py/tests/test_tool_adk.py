"""
Tests for ADKToolBuilder.

Since the Google ADK SDK is an optional dependency, the SDK modules are mocked
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
# Helpers – mock the Google ADK SDK
# ---------------------------------------------------------------------------


class FakeFunctionTool:
    """Simulates google.adk.tools.FunctionTool."""

    def __init__(self, func):
        self._func = func
        self.name = getattr(func, "__name__", "unknown")


def _install_adk_mocks(adk_context_state=None):
    """Create and install mock modules for the Google ADK SDK."""
    # google namespace
    google_mod = types.ModuleType("google")
    google_mod.__path__ = []

    # google.adk
    adk_mod = types.ModuleType("google.adk")
    adk_mod.__path__ = []
    google_mod.adk = adk_mod

    # google.adk.agents
    agents_mod = types.ModuleType("google.adk.agents")
    agents_mod.BaseAgent = MagicMock

    # get_current_context mock
    if adk_context_state is not None:
        ctx = MagicMock()
        ctx.state = adk_context_state
        agents_mod.get_current_context = MagicMock(return_value=ctx)
    else:
        agents_mod.get_current_context = MagicMock(side_effect=Exception("No ADK context"))

    adk_mod.agents = agents_mod

    # google.adk.runners
    runners_mod = types.ModuleType("google.adk.runners")
    runners_mod.Runner = MagicMock
    adk_mod.runners = runners_mod

    # google.adk.sessions
    sessions_mod = types.ModuleType("google.adk.sessions")
    sessions_mod.BaseSessionService = MagicMock
    sessions_mod.InMemorySessionService = MagicMock
    adk_mod.sessions = sessions_mod

    # google.adk.tools
    tools_mod = types.ModuleType("google.adk.tools")
    tools_mod.FunctionTool = FakeFunctionTool
    adk_mod.tools = tools_mod

    # google.genai
    genai_mod = types.ModuleType("google.genai")
    genai_mod.__path__ = []
    genai_types = types.ModuleType("google.genai.types")
    genai_types.Content = MagicMock
    genai_types.Part = MagicMock
    genai_types.Blob = MagicMock
    genai_types.FileData = MagicMock
    genai_mod.types = genai_types
    google_mod.genai = genai_mod

    patches = {
        "google": google_mod,
        "google.adk": adk_mod,
        "google.adk.agents": agents_mod,
        "google.adk.runners": runners_mod,
        "google.adk.sessions": sessions_mod,
        "google.adk.tools": tools_mod,
        "google.genai": genai_mod,
        "google.genai.types": genai_types,
    }
    return patches


@pytest.fixture(autouse=True)
def _mock_adk_sdk():
    """Inject mock Google ADK SDK modules for every test."""
    patches = _install_adk_mocks()
    with patch.dict(sys.modules, patches):
        # Force re-import
        for mod_key in list(sys.modules):
            if "agentkernel.framework.adk" in mod_key:
                del sys.modules[mod_key]
        yield


def _get_builder():
    from agentkernel.framework.adk.adk import ADKToolBuilder

    return ADKToolBuilder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestADKToolBuilderBindSync:
    def test_bind_sync_tool(self):
        def get_weather(city: str) -> str:
            """Get the weather."""
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], FakeFunctionTool)
        assert tools[0].name == "get_weather"

    def test_bind_sync_invocation(self):
        def get_weather(city: str) -> str:
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0]._func(city="Berlin")
        assert result == "Sunny in Berlin"


class TestADKToolBuilderBindAsync:
    def test_bind_async_tool(self):
        async def get_weather(city: str) -> str:
            """Get weather async."""
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert tools[0].name == "get_weather"

    @pytest.mark.asyncio
    async def test_bind_async_invocation(self):
        async def get_weather(city: str) -> str:
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = await tools[0]._func(city="London")
        assert result == "Rainy in London"


class TestADKToolBuilderWithContextState:
    def test_bind_with_context_via_adk_state(self):
        """When ADK context state has ak_runtime/ak_session, they should be used."""
        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("adk-state-session")

        patches = _install_adk_mocks(
            adk_context_state={
                "ak_runtime": mock_runtime,
                "ak_session": mock_session,
            }
        )

        def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, session={ctx.session.id}, has_runtime={ctx.runtime is not None}"

        with patch.dict(sys.modules, patches):
            for mod_key in list(sys.modules):
                if "agentkernel.framework.adk" in mod_key:
                    del sys.modules[mod_key]

            Builder = _get_builder()
            tools = Builder.bind([get_weather])
            result = tools[0]._func(city="Tokyo")
            assert "session=adk-state-session" in result
            assert "has_runtime=True" in result

    def test_bind_with_context_fallback(self):
        """When ADK context is unavailable, falls back to Session.current() / Runtime.current()."""
        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("fallback-session")

        def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, session={ctx.session.id}"

        Builder = _get_builder()
        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                tools = Builder.bind([get_weather])
                result = tools[0]._func(city="Paris")
                assert "session=fallback-session" in result


class TestADKToolBuilderWithoutContext:
    def test_bind_without_context(self):
        def get_weather(city: str) -> str:
            return f"Weather in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0]._func(city="Rome")
        assert result == "Weather in Rome"


class TestADKToolBuilderMultiple:
    def test_bind_multiple_tools(self):
        def tool_a(x: str) -> str:
            """Tool A."""
            return x

        def tool_b(y: int) -> int:
            """Tool B."""
            return y

        Builder = _get_builder()
        tools = Builder.bind([tool_a, tool_b])
        assert len(tools) == 2
        assert tools[0].name == "tool_a"
        assert tools[1].name == "tool_b"
