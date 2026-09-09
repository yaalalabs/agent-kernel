import pytest
from pydantic_ai import Tool

from agentkernel.framework.pydanticai.pydanticai import PydanticAIToolBuilder


# Sample tool functions used by the tests
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
class TestPydanticAIToolBuilderBind:

    def test_bind_returns_list(self):
        tools = PydanticAIToolBuilder.bind([get_weather])
        assert isinstance(tools, list)

    def test_bind_returns_tools(self):
        tools = PydanticAIToolBuilder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], Tool)

    def test_bind_multiple_functions(self):
        tools = PydanticAIToolBuilder.bind([get_weather, add, no_params])
        assert len(tools) == 3
        assert all(isinstance(t, Tool) for t in tools)

    def test_bind_empty_list(self):
        tools = PydanticAIToolBuilder.bind([])
        assert tools == []

    def test_bind_preserves_order(self):
        tools = PydanticAIToolBuilder.bind([get_weather, add, no_params])
        assert tools[0].name == "get_weather"
        assert tools[1].name == "add"
        assert tools[2].name == "no_params"


# Tool metadata – name, description, schema
class TestToolMetadata:

    def test_tool_name_matches_function(self):
        [tool] = PydanticAIToolBuilder.bind([get_weather])
        assert tool.name == "get_weather"

    def test_tool_description_from_docstring(self):
        [tool] = PydanticAIToolBuilder.bind([get_weather])
        assert "weather" in tool.description.lower()

    def test_tool_params_schema_contains_properties(self):
        [tool] = PydanticAIToolBuilder.bind([get_weather])
        schema = tool.function_schema.json_schema
        assert "properties" in schema
        assert "city" in schema["properties"]

    def test_tool_params_schema_for_multiple_params(self):
        [tool] = PydanticAIToolBuilder.bind([add])
        schema = tool.function_schema.json_schema
        assert "a" in schema["properties"]
        assert "b" in schema["properties"]

    def test_no_params_tool_schema(self):
        [tool] = PydanticAIToolBuilder.bind([no_params])
        schema = tool.function_schema.json_schema
        # Should either have empty properties or no required fields
        props = schema.get("properties", {})
        assert len(props) == 0 or all(p not in schema.get("required", []) for p in props)

    def test_multi_type_params_schema(self):
        [tool] = PydanticAIToolBuilder.bind([multi_type_params])
        schema = tool.function_schema.json_schema
        assert "text" in schema["properties"]
        assert "count" in schema["properties"]
        assert "flag" in schema["properties"]


# Sync function wrapping and invocation
class TestSyncFunctionWrapping:

    def test_sync_tool_wraps_function(self):
        [tool] = PydanticAIToolBuilder.bind([get_weather])
        assert tool.function is get_weather
        assert callable(tool.function)

    def test_sync_function_returns_correct_result(self):
        result = get_weather("Tokyo")
        assert result == "Weather in Tokyo: sunny"

    def test_sync_function_with_multiple_args(self):
        result = add(3, 4)
        assert result == 7

    def test_sync_function_with_default_params(self):
        result = multi_type_params("hello", 5)
        assert result == "hello-5-False"

        result_with_flag = multi_type_params("hello", 5, flag=True)
        assert result_with_flag == "hello-5-True"


# Async function wrapping and invocation
class TestAsyncFunctionWrapping:

    def test_bind_async_returns_tools(self):
        tools = PydanticAIToolBuilder.bind([async_lookup])
        assert len(tools) == 1
        assert isinstance(tools[0], Tool)

    def test_async_tool_name_matches(self):
        [tool] = PydanticAIToolBuilder.bind([async_lookup])
        assert tool.name == "async_lookup"

    def test_async_tool_description_from_docstring(self):
        [tool] = PydanticAIToolBuilder.bind([async_lookup])
        assert "look up" in tool.description.lower()

    def test_async_tool_params_schema(self):
        [tool] = PydanticAIToolBuilder.bind([async_multiply])
        schema = tool.function_schema.json_schema
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]

    @pytest.mark.asyncio
    async def test_async_function_returns_correct_result(self):
        result = await async_lookup("Alice")
        assert result == "Found: Alice"

    @pytest.mark.asyncio
    async def test_async_multiply_returns_correct_result(self):
        result = await async_multiply(3, 7)
        assert result == 21


# Mixed sync / async binding
class TestMixedBinding:

    def test_bind_mixed_sync_and_async(self):
        tools = PydanticAIToolBuilder.bind([get_weather, async_lookup, add, async_multiply])
        assert len(tools) == 4
        assert all(isinstance(t, Tool) for t in tools)

    def test_mixed_names_preserved(self):
        tools = PydanticAIToolBuilder.bind([get_weather, async_lookup])
        names = [t.name for t in tools]
        assert names == ["get_weather", "async_lookup"]


# Edge cases
class TestEdgeCases:

    def test_bind_same_function_twice(self):
        tools = PydanticAIToolBuilder.bind([get_weather, get_weather])
        assert len(tools) == 2
        assert tools[0].name == tools[1].name == "get_weather"

    def test_bind_non_callable_raises(self):
        with pytest.raises(TypeError):
            PydanticAIToolBuilder.bind([42])
