"""Tests for ClaudeToolBuilder: plain functions bound into Claude Agent SDK in-process tools."""

import pytest
from claude_agent_sdk import SdkMcpTool, ToolAnnotations
from pydantic import BaseModel

from agentkernel.core.tool import ToolContext
from agentkernel.framework.claude.claude import ClaudeToolBuilder


def get_weather(city: str, unit: str = "celsius") -> str:
    """
    Get the current weather for a city.

    Uses the forecast service.
    :param city: The city name.
    :param unit: celsius or fahrenheit.
    :return: The weather report.
    """
    return f"sunny in {city} ({unit})"


async def lookup(term: str) -> dict:
    """Look a term up."""
    return {"term": term, "hits": 2}


class Point(BaseModel):
    x: int
    y: int


def distance(a: Point, b: Point) -> float:
    """Distance between two points."""
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def undocumented(n):
    return n


class TestSchema:
    def test_required_and_optional_come_from_the_signature_and_the_description_from_the_docstring(self):
        [tool] = ClaudeToolBuilder.bind([get_weather])

        assert isinstance(tool, SdkMcpTool)
        assert tool.name == "get_weather"
        assert tool.description.startswith("Get the current weather for a city.\n\nUses the forecast service.")
        assert ":param city: The city name." in tool.description
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema["required"] == ["city"]
        assert schema["properties"]["city"] == {"title": "City", "type": "string"}
        assert schema["properties"]["unit"]["default"] == "celsius"

    def test_a_function_without_a_docstring_or_annotations_still_binds(self):
        [tool] = ClaudeToolBuilder.bind([undocumented])

        assert tool.description == "undocumented"
        assert tool.input_schema["required"] == ["n"]

    def test_pydantic_parameters_produce_nested_schemas(self):
        [tool] = ClaudeToolBuilder.bind([distance])

        assert set(tool.input_schema["required"]) == {"a", "b"}
        assert "Point" in tool.input_schema["$defs"]

    def test_options_become_tool_annotations(self):
        [tool] = ClaudeToolBuilder.bind([get_weather], readOnlyHint=True, maxResultSizeChars=1000)

        assert isinstance(tool.annotations, ToolAnnotations)
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.maxResultSizeChars == 1000

    def test_no_options_means_no_annotations(self):
        [tool] = ClaudeToolBuilder.bind([get_weather])
        assert tool.annotations is None

    def test_a_non_callable_is_rejected(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            ClaudeToolBuilder.bind(["nope"])

    def test_variadic_parameters_are_rejected_at_bind_time(self):
        def unsupported(*values: str) -> str:
            return ",".join(values)

        with pytest.raises(TypeError, match="variadic parameter 'values'"):
            ClaudeToolBuilder.bind([unsupported])

    def test_unresolvable_annotations_fail_at_bind_time(self):
        def unsupported(value: "MissingType") -> str:
            return value

        with pytest.raises(NameError, match="MissingType"):
            ClaudeToolBuilder.bind([unsupported])


class TestHandler:
    @pytest.mark.asyncio
    async def test_positional_only_parameters_are_passed_positionally(self):
        def greet(name: str, /, punctuation: str = "!") -> str:
            return f"Hello {name}{punctuation}"

        [tool] = ClaudeToolBuilder.bind([greet])

        assert await tool.handler({"name": "Ada"}) == {"content": [{"type": "text", "text": "Hello Ada!"}]}

    @pytest.mark.asyncio
    async def test_a_sync_function_returns_text_content(self):
        [tool] = ClaudeToolBuilder.bind([get_weather])

        assert await tool.handler({"city": "Colombo"}) == {"content": [{"type": "text", "text": "sunny in Colombo (celsius)"}]}

    @pytest.mark.asyncio
    async def test_an_async_function_returning_a_dict_is_json_encoded(self):
        [tool] = ClaudeToolBuilder.bind([lookup])

        assert await tool.handler({"term": "ak"}) == {"content": [{"type": "text", "text": '{"term": "ak", "hits": 2}'}]}

    @pytest.mark.asyncio
    async def test_arguments_are_validated_into_pydantic_models(self):
        [tool] = ClaudeToolBuilder.bind([distance])

        result = await tool.handler({"a": {"x": 0, "y": 0}, "b": {"x": 3, "y": 4}})

        assert result["content"][0]["text"] == "5.0"

    @pytest.mark.asyncio
    async def test_a_sync_tool_sees_the_tool_context_on_its_worker_thread(self):
        def whoami() -> str:
            """Name the session."""
            return ToolContext.get().session.id

        class _Session:
            id = "ctx-session"

        [tool] = ClaudeToolBuilder.bind([whoami])
        context = ToolContext(None, None, _Session(), []).set()
        try:
            result = await tool.handler({})
        finally:
            context.reset()

        assert result["content"][0]["text"] == "ctx-session"


class TestNames:
    def test_mcp_tool_name(self):
        assert ClaudeToolBuilder.MCP_SERVER == "ak"
        assert ClaudeToolBuilder.mcp_tool_name("double") == "mcp__ak__double"

    def test_ak_tool_name_strips_the_prefix(self):
        assert ClaudeToolBuilder.ak_tool_name("mcp__ak__double") == "double"

    def test_ak_tool_name_leaves_other_names_alone(self):
        assert ClaudeToolBuilder.ak_tool_name("Bash") == "Bash"
        assert ClaudeToolBuilder.ak_tool_name("mcp__other__double") == "mcp__other__double"


class TestNeedsApproval:
    def test_defaults_to_false(self):
        [tool] = ClaudeToolBuilder.bind([get_weather])
        assert tool.ak_needs_approval is False

    def test_can_be_set_true(self):
        [tool] = ClaudeToolBuilder.bind([get_weather], needs_approval=True)
        assert tool.ak_needs_approval is True

    def test_applies_to_every_function_in_the_call(self):
        tools = ClaudeToolBuilder.bind([get_weather, lookup], needs_approval=True)
        assert all(tool.ak_needs_approval for tool in tools)

    def test_is_not_a_declared_sdkmcptool_field(self):
        """Must stay adapter-side bookkeeping: an extra instance attribute, invisible to the SDK's own dataclass fields."""
        import dataclasses

        [tool] = ClaudeToolBuilder.bind([get_weather], needs_approval=True)
        assert "ak_needs_approval" not in {f.name for f in dataclasses.fields(tool)}
        assert tool.ak_needs_approval is True
