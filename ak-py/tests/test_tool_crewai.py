import pytest
from crewai.tools import BaseTool

from agentkernel.framework.crewai.crewai import CrewAIToolBuilder


# Sample tool functions
def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny"


def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


def no_params() -> str:
    """A tool that takes no parameters."""
    return "done"


def multi_type_params(text: str, count: int, flag: bool = False) -> str:
    """A tool with multiple parameter types."""
    return f"{text}-{count}-{flag}"


# bind – basic behaviour
class TestCrewAIToolBuilderBind:

    def test_bind_returns_list(self):
        tools = CrewAIToolBuilder.bind([get_weather])
        assert isinstance(tools, list)

    def test_bind_returns_base_tool_instances(self):
        tools = CrewAIToolBuilder.bind([get_weather])
        assert len(tools) == 1
        assert isinstance(tools[0], BaseTool)

    def test_bind_multiple_functions(self):
        tools = CrewAIToolBuilder.bind([get_weather, add, no_params])
        assert len(tools) == 3
        assert all(isinstance(t, BaseTool) for t in tools)

    def test_bind_empty_list(self):
        tools = CrewAIToolBuilder.bind([])
        assert tools == []

    def test_bind_preserves_order(self):
        tools = CrewAIToolBuilder.bind([get_weather, add, no_params])
        assert tools[0].name == "get_weather"
        assert tools[1].name == "add"
        assert tools[2].name == "no_params"


# Tool metadata – name, description, args_schema
class TestToolMetadata:

    def test_tool_name_matches_function(self):
        [tool] = CrewAIToolBuilder.bind([get_weather])
        assert tool.name == "get_weather"

    def test_tool_description_contains_docstring(self):
        [tool] = CrewAIToolBuilder.bind([get_weather])
        assert "weather" in tool.description.lower()

    def test_tool_has_args_schema(self):
        [tool] = CrewAIToolBuilder.bind([get_weather])
        schema = tool.args_schema.model_json_schema()
        assert "properties" in schema
        assert "city" in schema["properties"]

    def test_multi_param_args_schema(self):
        [tool] = CrewAIToolBuilder.bind([add])
        schema = tool.args_schema.model_json_schema()
        assert "a" in schema["properties"]
        assert "b" in schema["properties"]

    def test_no_params_tool_name(self):
        [tool] = CrewAIToolBuilder.bind([no_params])
        assert tool.name == "no_params"

    def test_multi_type_params_schema(self):
        [tool] = CrewAIToolBuilder.bind([multi_type_params])
        schema = tool.args_schema.model_json_schema()
        assert "text" in schema["properties"]
        assert "count" in schema["properties"]
        assert "flag" in schema["properties"]


# Tool invocation via .run()
class TestToolRun:

    def test_run_single_string_param(self):
        [tool] = CrewAIToolBuilder.bind([get_weather])
        result = tool.run(city="Tokyo")
        assert result == "Weather in Tokyo: sunny"

    def test_run_multiple_params(self):
        [tool] = CrewAIToolBuilder.bind([add])
        result = tool.run(a=3, b=4)
        assert int(result) == 7

    def test_run_no_params(self):
        [tool] = CrewAIToolBuilder.bind([no_params])
        result = tool.run()
        assert result == "done"

    def test_run_with_default_params(self):
        [tool] = CrewAIToolBuilder.bind([multi_type_params])
        result = tool.run(text="hello", count=5)
        assert "hello" in result
        assert "5" in result

    def test_run_with_explicit_default_override(self):
        [tool] = CrewAIToolBuilder.bind([multi_type_params])
        result = tool.run(text="hello", count=5, flag=True)
        assert "True" in result


# Type validation – non-callable inputs
class TestTypeValidation:

    def test_bind_non_callable_string_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            CrewAIToolBuilder.bind(["not a function"])

    def test_bind_non_callable_int_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            CrewAIToolBuilder.bind([42])

    def test_bind_non_callable_none_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            CrewAIToolBuilder.bind([None])

    def test_bind_mixed_valid_and_invalid_raises(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            CrewAIToolBuilder.bind([get_weather, "invalid"])


# Edge cases
class TestEdgeCases:

    def test_bind_lambda(self):
        my_lambda = lambda x: x + 1  # noqa: E731
        my_lambda.__doc__ = "Increment by one."
        my_lambda.__name__ = "increment"
        tools = CrewAIToolBuilder.bind([my_lambda])
        assert len(tools) == 1
        assert tools[0].name == "increment"

    def test_bind_same_function_twice(self):
        tools = CrewAIToolBuilder.bind([get_weather, get_weather])
        assert len(tools) == 2
        assert tools[0].name == tools[1].name == "get_weather"

    def test_tool_has_func_attribute(self):
        [tool] = CrewAIToolBuilder.bind([get_weather])
        assert hasattr(tool, "func")

    def test_each_bind_produces_independent_tools(self):
        tools_a = CrewAIToolBuilder.bind([get_weather])
        tools_b = CrewAIToolBuilder.bind([get_weather])
        assert tools_a[0] is not tools_b[0]
