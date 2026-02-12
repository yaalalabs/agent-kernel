"""
Tests for CrewAIToolBuilder.

Since CrewAI is an optional dependency, the SDK modules are mocked
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
# Helpers – mock the CrewAI SDK
# ---------------------------------------------------------------------------


class FakeCrewAITool:
    """Simulates the object returned by crewai.tools.tool()."""

    def __init__(self, func):
        self._func = func
        self.name = getattr(func, "__name__", "unknown")
        self.description = getattr(func, "__doc__", "") or ""


def _install_crewai_mocks():
    """Create and install mock modules for CrewAI."""
    crewai_mod = types.ModuleType("crewai")
    crewai_mod.Agent = MagicMock
    crewai_mod.Crew = MagicMock
    crewai_mod.Task = MagicMock

    crewai_memory = types.ModuleType("crewai.memory")
    crewai_memory_ext = types.ModuleType("crewai.memory.external")
    crewai_memory_ext_mod = types.ModuleType("crewai.memory.external.external_memory")
    crewai_memory_ext_mod.ExternalMemory = MagicMock
    crewai_memory_ext.external_memory = crewai_memory_ext_mod
    crewai_memory.external = crewai_memory_ext

    crewai_memory_storage = types.ModuleType("crewai.memory.storage")
    crewai_memory_storage_iface = types.ModuleType("crewai.memory.storage.interface")
    crewai_memory_storage_iface.Storage = MagicMock
    crewai_memory_storage.interface = crewai_memory_storage_iface
    crewai_memory.storage = crewai_memory_storage

    crewai_tools = types.ModuleType("crewai.tools")
    crewai_tools.tool = lambda func: FakeCrewAITool(func)

    crewai_mod.memory = crewai_memory
    crewai_mod.tools = crewai_tools

    patches = {
        "crewai": crewai_mod,
        "crewai.memory": crewai_memory,
        "crewai.memory.external": crewai_memory_ext,
        "crewai.memory.external.external_memory": crewai_memory_ext_mod,
        "crewai.memory.storage": crewai_memory_storage,
        "crewai.memory.storage.interface": crewai_memory_storage_iface,
        "crewai.tools": crewai_tools,
    }
    return patches


@pytest.fixture(autouse=True)
def _mock_crewai_sdk():
    """Inject mock CrewAI SDK modules for every test."""
    patches = _install_crewai_mocks()
    with patch.dict(sys.modules, patches):
        for mod_key in list(sys.modules):
            if "agentkernel.framework.crewai" in mod_key:
                del sys.modules[mod_key]
        yield


def _get_builder():
    from agentkernel.framework.crewai.crewai import CrewAIToolBuilder

    return CrewAIToolBuilder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrewAIToolBuilderBindSync:
    def test_bind_sync_tool(self):
        def get_weather(city: str) -> str:
            """Get weather for a city."""
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], FakeCrewAITool)
        assert tools[0].name == "get_weather"

    def test_bind_sync_invocation(self):
        def get_weather(city: str) -> str:
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0]._func(city="Berlin")
        assert result == "Sunny in Berlin"


class TestCrewAIToolBuilderBindAsync:
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


class TestCrewAIToolBuilderWithContext:
    def test_bind_with_tool_context(self):
        def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, session={ctx.session.id}"

        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("crewai-session")

        Builder = _get_builder()
        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                tools = Builder.bind([get_weather])
                result = tools[0]._func(city="NYC")
                assert "session=crewai-session" in result

    def test_bind_without_tool_context(self):
        def get_weather(city: str) -> str:
            return f"Weather in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0]._func(city="Rome")
        assert result == "Weather in Rome"


class TestCrewAIToolBuilderMultiple:
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


class TestCrewAIToolBuilderErrors:
    def test_bind_non_callable_raises(self):
        Builder = _get_builder()
        with pytest.raises(TypeError, match="Expected a callable"):
            Builder.bind(["not_a_function"])
