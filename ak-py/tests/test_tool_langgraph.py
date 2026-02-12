"""
Tests for LangGraphToolBuilder.

Since LangGraph / LangChain is an optional dependency, the SDK modules are mocked
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
# Helpers – mock LangChain / LangGraph SDK
# ---------------------------------------------------------------------------


class FakeStructuredTool:
    """Simulates langchain_core.tools.StructuredTool."""

    def __init__(self, func=None, coroutine=None, name="", description=""):
        self._func = func
        self._coroutine = coroutine
        self.name = name
        self.description = description

    @classmethod
    def from_function(cls, func=None, coroutine=None, name="", description=""):
        return cls(func=func, coroutine=coroutine, name=name, description=description)

    def invoke(self, **kwargs):
        if self._func:
            return self._func(**kwargs)
        raise RuntimeError("No sync function bound")

    async def ainvoke(self, **kwargs):
        if self._coroutine:
            return await self._coroutine(**kwargs)
        raise RuntimeError("No async coroutine bound")


def _install_langgraph_mocks():
    """Create and install mock modules for LangChain/LangGraph."""
    # langchain_core
    lc_core = types.ModuleType("langchain_core")
    lc_core.__path__ = []

    lc_messages = types.ModuleType("langchain_core.messages")
    lc_messages.HumanMessage = MagicMock
    lc_core.messages = lc_messages

    lc_runnables = types.ModuleType("langchain_core.runnables")
    lc_runnables.RunnableConfig = MagicMock
    lc_core.runnables = lc_runnables

    lc_tools = types.ModuleType("langchain_core.tools")
    lc_tools.StructuredTool = FakeStructuredTool
    lc_core.tools = lc_tools

    # langgraph
    lg = types.ModuleType("langgraph")
    lg.__path__ = []

    lg_checkpoint = types.ModuleType("langgraph.checkpoint")
    lg_checkpoint.__path__ = []

    lg_checkpoint_base = types.ModuleType("langgraph.checkpoint.base")
    lg_checkpoint_base.BaseCheckpointSaver = MagicMock
    lg_checkpoint_base.Checkpoint = MagicMock
    lg_checkpoint_base.CheckpointMetadata = MagicMock
    lg_checkpoint_base.CheckpointTuple = MagicMock
    lg_checkpoint.base = lg_checkpoint_base

    lg_graph = types.ModuleType("langgraph.graph")
    lg_graph.__path__ = []
    lg_graph_state = types.ModuleType("langgraph.graph.state")
    lg_graph_state.CompiledStateGraph = MagicMock
    lg_graph.state = lg_graph_state

    lg.checkpoint = lg_checkpoint
    lg.graph = lg_graph

    # pydantic is already available (real dependency)

    patches = {
        "langchain_core": lc_core,
        "langchain_core.messages": lc_messages,
        "langchain_core.runnables": lc_runnables,
        "langchain_core.tools": lc_tools,
        "langgraph": lg,
        "langgraph.checkpoint": lg_checkpoint,
        "langgraph.checkpoint.base": lg_checkpoint_base,
        "langgraph.graph": lg_graph,
        "langgraph.graph.state": lg_graph_state,
    }
    return patches


@pytest.fixture(autouse=True)
def _mock_langgraph_sdk():
    """Inject mock LangChain/LangGraph SDK modules for every test."""
    patches = _install_langgraph_mocks()
    with patch.dict(sys.modules, patches):
        for mod_key in list(sys.modules):
            if "agentkernel.framework.langgraph" in mod_key:
                del sys.modules[mod_key]
        yield


def _get_builder():
    from agentkernel.framework.langgraph.langgraph import LangGraphToolBuilder

    return LangGraphToolBuilder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLangGraphToolBuilderBindSync:
    def test_bind_sync_tool(self):
        def get_weather(city: str) -> str:
            """Get weather for a city."""
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], FakeStructuredTool)
        assert tools[0].name == "get_weather"
        assert tools[0]._func is not None
        assert tools[0]._coroutine is None

    def test_bind_sync_invocation(self):
        def get_weather(city: str) -> str:
            return f"Sunny in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0].invoke(city="Berlin")
        assert result == "Sunny in Berlin"


class TestLangGraphToolBuilderBindAsync:
    def test_bind_async_tool(self):
        async def get_weather(city: str) -> str:
            """Get weather async."""
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        assert len(tools) == 1
        assert tools[0].name == "get_weather"
        assert tools[0]._coroutine is not None
        assert tools[0]._func is None

    @pytest.mark.asyncio
    async def test_bind_async_invocation(self):
        async def get_weather(city: str) -> str:
            return f"Rainy in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = await tools[0].ainvoke(city="London")
        assert result == "Rainy in London"


class TestLangGraphToolBuilderWithContext:
    def test_bind_with_tool_context(self):
        def get_weather(city: str, ctx: ToolContext) -> str:
            return f"Weather in {city}, session={ctx.session.id}"

        mock_runtime = MagicMock(spec=Runtime)
        mock_session = Session("lg-session")

        Builder = _get_builder()
        with patch.object(Runtime, "current", return_value=mock_runtime):
            with patch.object(Session, "current", return_value=mock_session):
                tools = Builder.bind([get_weather])
                result = tools[0].invoke(city="NYC")
                assert "session=lg-session" in result

    def test_bind_without_tool_context(self):
        def get_weather(city: str) -> str:
            return f"Weather in {city}"

        Builder = _get_builder()
        tools = Builder.bind([get_weather])
        result = tools[0].invoke(city="Rome")
        assert result == "Weather in Rome"


class TestLangGraphToolBuilderMultiple:
    def test_bind_multiple_tools(self):
        def tool_a(x: str) -> str:
            """Tool A."""
            return x

        async def tool_b(y: str) -> str:
            """Tool B."""
            return y

        Builder = _get_builder()
        tools = Builder.bind([tool_a, tool_b])
        assert len(tools) == 2
        assert tools[0].name == "tool_a"
        assert tools[1].name == "tool_b"
        # First is sync, second is async
        assert tools[0]._func is not None
        assert tools[1]._coroutine is not None


class TestLangGraphToolBuilderErrors:
    def test_bind_non_callable_raises(self):
        Builder = _get_builder()
        with pytest.raises(TypeError, match="Expected a callable"):
            Builder.bind(["not_a_function"])
