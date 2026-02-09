"""
Tests for tool builder functionality.
These tests use the shared utility functions to test the core binding logic.
"""

import asyncio

import pytest

from agentkernel import Agent, Runtime, Session
from agentkernel.core.model import AgentRequestText
from agentkernel.core.tool import ToolContext
from agentkernel.core.tool_util import needs_tool_context, wrap_tool_with_context


class MockAgent(Agent):
    def __init__(self, name):
        from agentkernel import Runner

        class MockRunner(Runner):
            async def run(self, agent, session, requests):
                pass

        super().__init__(name, MockRunner("mock"))

    def get_description(self):
        return "Mock agent"

    def get_a2a_card(self):
        return None


def test_needs_tool_context():
    """Test the needs_tool_context detection function."""

    def no_context_tool(x: int, y: int) -> int:
        return x + y

    def with_context_tool(ctx: ToolContext, x: int) -> str:
        return str(x)

    assert not needs_tool_context(no_context_tool)
    assert needs_tool_context(with_context_tool)


def test_tool_builder_no_context():
    """Test that tool builder doesn't wrap tools that don't need context."""

    def simple_tool(x: int, y: int) -> int:
        """Add two numbers."""
        return x + y

    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")

    wrapped_tool = wrap_tool_with_context(simple_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    # The tool should be the original function
    assert wrapped_tool == simple_tool
    # Test that it still works
    assert wrapped_tool(x=1, y=2) == 3


def test_tool_builder_with_context():
    """Test that tool builder wraps tools that need context."""

    def context_tool(ctx: ToolContext, x: int) -> str:
        """Tool that uses context."""
        return f"Session: {ctx.session.id}, x={x}"

    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")

    wrapped_tool = wrap_tool_with_context(context_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    # The wrapped tool should be different from the original
    assert wrapped_tool != context_tool
    # Test that it works and injects context
    result = wrapped_tool(x=42)
    assert "test-session" in result
    assert "x=42" in result


@pytest.mark.asyncio
async def test_tool_builder_async_tool():
    """Test that tool builder handles async tools correctly."""

    async def async_tool(ctx: ToolContext, value: int) -> int:
        """Async tool that uses context."""
        return value + len(ctx.session.id)

    runtime = Runtime.current()
    session = Session("test-session-123")
    agent = MockAgent("test-agent")

    wrapped_tool = wrap_tool_with_context(async_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    # Test the async wrapper
    result = await wrapped_tool(value=10)
    assert result == 10 + len("test-session-123")


def test_tool_builder_preserves_metadata():
    """Test that tool builder preserves function metadata."""

    def documented_tool(ctx: ToolContext, x: int) -> int:
        """This is a documented tool function."""
        return x

    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")

    wrapped_tool = wrap_tool_with_context(documented_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    assert wrapped_tool.__name__ == "documented_tool"
    assert wrapped_tool.__doc__ == "This is a documented tool function."


def test_tool_builder_with_all_context_fields():
    """Test that tool builder injects all context fields correctly."""

    def full_context_tool(ctx: ToolContext) -> dict:
        """Tool that uses all context fields."""
        return {
            "runtime_type": type(ctx.runtime).__name__,
            "session_id": ctx.session.id,
            "agent_name": ctx.agent.name,
            "requests_count": len(ctx.requests),
            "params": ctx.params,
        }

    runtime = Runtime.current()
    session = Session("test-session-456")
    agent = MockAgent("test-agent-xyz")
    requests = [AgentRequestText(text="test1"), AgentRequestText(text="test2")]
    params = {"key1": "value1", "key2": "value2"}

    wrapped_tool = wrap_tool_with_context(full_context_tool, runtime=runtime, session=session, agent=agent, requests=requests, params=params)

    result = wrapped_tool()
    assert result["runtime_type"] == "GlobalRuntime"
    assert result["session_id"] == "test-session-456"
    assert result["agent_name"] == "test-agent-xyz"
    assert result["requests_count"] == 2
    assert result["params"] == {"key1": "value1", "key2": "value2"}


def test_tool_builder_mixed_parameters():
    """Test tool builder with mix of regular and context parameters."""

    def mixed_tool(ctx: ToolContext, a: int, b: str, c: float = 3.14) -> str:
        """Tool with mixed parameters."""
        return f"{ctx.agent.name}: a={a}, b={b}, c={c}"

    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("mixed-agent")

    wrapped_tool = wrap_tool_with_context(mixed_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    result = wrapped_tool(a=42, b="hello", c=2.71)
    assert "mixed-agent" in result
    assert "a=42" in result
    assert "b=hello" in result
    assert "c=2.71" in result


@pytest.mark.asyncio
async def test_tool_builder_async_mixed_parameters():
    """Test async tool builder with mixed parameters."""

    async def async_mixed_tool(ctx: ToolContext, x: int, y: int) -> int:
        """Async tool with mixed parameters."""
        await asyncio.sleep(0.01)  # Simulate async work
        return x + y + len(ctx.session.id)

    runtime = Runtime.current()
    session = Session("session-789")
    agent = MockAgent("async-agent")

    wrapped_tool = wrap_tool_with_context(async_mixed_tool, runtime=runtime, session=session, agent=agent, requests=[], params={})

    result = await wrapped_tool(x=10, y=20)
    expected = 10 + 20 + len("session-789")
    assert result == expected


def test_tool_builder_different_parameter_name():
    """Test that tool builder works with parameter names other than 'ctx'."""

    def tool_with_custom_name(tool_context: ToolContext, value: int) -> str:
        """Tool with ToolContext parameter named 'tool_context'."""
        return f"{tool_context.agent.name}:{value}"

    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")

    wrapped_tool = wrap_tool_with_context(
        tool_with_custom_name,
        runtime=runtime,
        session=session,
        agent=agent,
        requests=[],
        params={},
    )

    result = wrapped_tool(value=42)
    assert "test-agent:42" in result


def test_tool_builder_context_parameter_name():
    """Test that tool builder works with 'context' as parameter name."""

    def tool_with_context_name(context: ToolContext, data: str) -> str:
        """Tool with ToolContext parameter named 'context'."""
        return f"Session {context.session.id}: {data}"

    runtime = Runtime.current()
    session = Session("custom-session")
    agent = MockAgent("custom-agent")

    wrapped_tool = wrap_tool_with_context(
        tool_with_context_name,
        runtime=runtime,
        session=session,
        agent=agent,
        requests=[],
        params={},
    )

    result = wrapped_tool(data="test-data")
    assert "Session custom-session: test-data" in result


@pytest.mark.asyncio
async def test_tool_builder_async_different_parameter_name():
    """Test that async tool builder works with different parameter names."""

    async def async_tool_custom(my_ctx: ToolContext, x: int) -> int:
        """Async tool with ToolContext parameter named 'my_ctx'."""
        await asyncio.sleep(0.01)
        return x + len(my_ctx.session.id)

    runtime = Runtime.current()
    session = Session("async-session-xyz")
    agent = MockAgent("async-agent")

    wrapped_tool = wrap_tool_with_context(async_tool_custom, runtime=runtime, session=session, agent=agent, requests=[], params={})

    result = await wrapped_tool(x=100)
    expected = 100 + len("async-session-xyz")
    assert result == expected


def test_get_tool_context_param_name():
    """Test the get_tool_context_param_name utility function."""
    from agentkernel.core.tool_util import get_tool_context_param_name

    def tool_ctx(ctx: ToolContext) -> None:
        pass

    def tool_context(context: ToolContext) -> None:
        pass

    def tool_custom(my_context: ToolContext) -> None:
        pass

    def tool_no_context(x: int) -> None:
        pass

    assert get_tool_context_param_name(tool_ctx) == "ctx"
    assert get_tool_context_param_name(tool_context) == "context"
    assert get_tool_context_param_name(tool_custom) == "my_context"
    assert get_tool_context_param_name(tool_no_context) is None
