import asyncio
import pytest
from langchain_core.tools import StructuredTool

from agentkernel.framework.langgraph.langgraph import LangGraphToolBuilder


# Sample tool functions
def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny"


def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


async def async_lookup(name: str) -> str:
    """Asynchronously look up a name."""
    return f"Found: {name}"


async def async_multiply(x: int, y: int) -> int:
    """Asynchronously multiply two numbers."""
    return x * y


def no_params() -> str:
    """A tool that takes no parameters."""
    return "done"


def multi_type_params(text: str, count: int, flag: bool = False) -> str:
    """A tool with multiple parameter types."""
    return f"{text}-{count}-{flag}"


# bind – basic behaviour
class TestLangGraphToolBuilderBind:

    def test_bind_returns_list(self):
        tools = LangGraphToolBuilder.bind([get_weather])
        assert isinstance(tools, list)

    def test_bind_returns_structured_tools(self):
        tools = LangGraphToolBuilder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], StructuredTool)

    def test_bind_multiple_functions(self):
        tools = LangGraphToolBuilder.bind([get_weather, add, no_params])
        assert len(tools) == 3
        assert all(isinstance(t, StructuredTool) for t in tools)

    def test_bind_empty_list(self):
        tools = LangGraphToolBuilder.bind([])
        assert tools == []

    def test_bind_preserves_order(self):
        tools = LangGraphToolBuilder.bind([get_weather, add, no_params])
        assert tools[0].name == "get_weather"
        assert tools[1].name == "add"
        assert tools[2].name == "no_params"


# Tool metadata – name, description, args_schema
class TestToolMetadata:

    def test_tool_name_matches_function(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        assert tool.name == "get_weather"

    def test_tool_description_from_docstring(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        assert tool.description == "Returns the weather for a given city."

    def test_tool_args_schema_contains_properties(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        schema = tool.args_schema.model_json_schema()
        assert "properties" in schema
        assert "city" in schema["properties"]

    def test_multi_param_args_schema(self):
        [tool] = LangGraphToolBuilder.bind([add])
        schema = tool.args_schema.model_json_schema()
        assert "a" in schema["properties"]
        assert "b" in schema["properties"]

    def test_no_params_tool_name(self):
        [tool] = LangGraphToolBuilder.bind([no_params])
        assert tool.name == "no_params"

    def test_multi_type_params_schema(self):
        [tool] = LangGraphToolBuilder.bind([multi_type_params])
        schema = tool.args_schema.model_json_schema()
        assert "text" in schema["properties"]
        assert "count" in schema["properties"]
        assert "flag" in schema["properties"]

    def test_description_falls_back_to_name_when_no_docstring(self):
        def nodoc(x: str) -> str:
            return x

        nodoc.__doc__ = None
        [tool] = LangGraphToolBuilder.bind([nodoc])
        assert tool.description == "nodoc"


# Sync function wrapping and invocation
class TestSyncFunctionInvocation:

    def test_invoke_single_param(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        result = tool.invoke({"city": "Tokyo"})
        assert result == "Weather in Tokyo: sunny"

    def test_invoke_multiple_params(self):
        [tool] = LangGraphToolBuilder.bind([add])
        result = tool.invoke({"a": 3, "b": 4})
        assert result == 7

    def test_invoke_no_params(self):
        [tool] = LangGraphToolBuilder.bind([no_params])
        result = tool.invoke({})
        assert result == "done"

    def test_invoke_with_default_params(self):
        [tool] = LangGraphToolBuilder.bind([multi_type_params])
        result = tool.invoke({"text": "hello", "count": 5})
        assert result == "hello-5-False"

    def test_invoke_with_explicit_default_override(self):
        [tool] = LangGraphToolBuilder.bind([multi_type_params])
        result = tool.invoke({"text": "hello", "count": 5, "flag": True})
        assert result == "hello-5-True"


# Async function wrapping and invocation
class TestAsyncFunctionWrapping:

    def test_bind_async_returns_structured_tools(self):
        tools = LangGraphToolBuilder.bind([async_lookup])
        assert len(tools) == 1
        assert isinstance(tools[0], StructuredTool)

    def test_async_tool_name(self):
        [tool] = LangGraphToolBuilder.bind([async_lookup])
        assert tool.name == "async_lookup"

    def test_async_tool_description(self):
        [tool] = LangGraphToolBuilder.bind([async_lookup])
        assert tool.description == "Asynchronously look up a name."

    def test_async_tool_has_coroutine(self):
        [tool] = LangGraphToolBuilder.bind([async_lookup])
        assert tool.coroutine is not None

    def test_async_tool_args_schema(self):
        [tool] = LangGraphToolBuilder.bind([async_multiply])
        schema = tool.args_schema.model_json_schema()
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]

    @pytest.mark.asyncio
    async def test_ainvoke_single_param(self):
        [tool] = LangGraphToolBuilder.bind([async_lookup])
        result = await tool.ainvoke({"name": "Alice"})
        assert result == "Found: Alice"

    @pytest.mark.asyncio
    async def test_ainvoke_multiple_params(self):
        [tool] = LangGraphToolBuilder.bind([async_multiply])
        result = await tool.ainvoke({"x": 3, "y": 7})
        assert result == 21


# Sync tool should not have coroutine, async tool should
class TestSyncAsyncDistinction:

    def test_sync_tool_coroutine_is_none(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        assert tool.coroutine is None

    def test_async_tool_coroutine_is_set(self):
        [tool] = LangGraphToolBuilder.bind([async_lookup])
        assert tool.coroutine is not None
        assert asyncio.iscoroutinefunction(tool.coroutine)


# Mixed sync / async binding
class TestMixedBinding:

    def test_bind_mixed_sync_and_async(self):
        tools = LangGraphToolBuilder.bind([get_weather, async_lookup, add, async_multiply])
        assert len(tools) == 4
        assert all(isinstance(t, StructuredTool) for t in tools)

    def test_mixed_names_preserved(self):
        tools = LangGraphToolBuilder.bind([get_weather, async_lookup])
        names = [t.name for t in tools]
        assert names == ["get_weather", "async_lookup"]

    def test_mixed_sync_has_no_coroutine(self):
        tools = LangGraphToolBuilder.bind([get_weather, async_lookup])
        assert tools[0].coroutine is None
        assert tools[1].coroutine is not None


# Type validation – non-callable inputs
class TestTypeValidation:

    def test_bind_non_callable_string_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            LangGraphToolBuilder.bind(["not a function"])

    def test_bind_non_callable_int_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            LangGraphToolBuilder.bind([42])

    def test_bind_non_callable_none_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            LangGraphToolBuilder.bind([None])

    def test_bind_mixed_valid_and_invalid_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            LangGraphToolBuilder.bind([get_weather, "invalid"])


# Edge cases
class TestEdgeCases:

    def test_bind_lambda(self):
        my_lambda = lambda x: x + 1  # noqa: E731
        my_lambda.__doc__ = "Increment by one."
        my_lambda.__name__ = "increment"
        tools = LangGraphToolBuilder.bind([my_lambda])
        assert len(tools) == 1
        assert tools[0].name == "increment"

    def test_bind_same_function_twice(self):
        tools = LangGraphToolBuilder.bind([get_weather, get_weather])
        assert len(tools) == 2
        assert tools[0].name == tools[1].name == "get_weather"

    def test_each_bind_produces_independent_tools(self):
        tools_a = LangGraphToolBuilder.bind([get_weather])
        tools_b = LangGraphToolBuilder.bind([get_weather])
        assert tools_a[0] is not tools_b[0]

    def test_tool_return_direct_defaults_false(self):
        [tool] = LangGraphToolBuilder.bind([get_weather])
        assert tool.return_direct is False
