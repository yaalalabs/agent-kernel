"""
Integration tests for framework-specific tool builders.

These tests verify that tool functions with ToolContext work correctly
when invoked by actual framework agents, ensuring the context is properly
initialized with runtime, session, agent, and request information.

Note: Framework-specific tests require the respective packages to be installed.
They will be skipped if the dependencies are not available.
"""

import pytest

from agentkernel import Runtime, Session
from agentkernel.core.model import AgentRequestText
from agentkernel.core.tool import ToolContext

# Test data shared across all framework tests
test_session_id = "test-integration-session"
test_agent_name = "TestAgent"
test_prompt = "Hello, what is 5 + 3?"


def context_aware_tool(ctx: ToolContext, a: int, b: int) -> str:
    """
    A tool that uses ToolContext and validates it's properly initialized.
    Returns information about the context for test validation.
    """
    return (
        f"sum={a + b}|"
        f"session={ctx.session.id}|"
        f"agent={ctx.agent.name}|"
        f"runtime={type(ctx.runtime).__name__}|"
        f"requests={len(ctx.requests)}"
    )


def simple_tool(x: int, y: int) -> int:
    """A simple tool without context."""
    return x * y


# OpenAI Framework Tests
try:
    import agents  # noqa: F401

    from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder

    openai_available = True
except ImportError:
    openai_available = False


@pytest.mark.skipif(not openai_available, reason="OpenAI agents package not installed")
class TestOpenAIToolIntegration:
    """Tests for OpenAI framework tool integration."""

    @pytest.mark.asyncio
    async def test_openai_tool_with_context(self):
        """Test that OpenAI agents correctly invoke tools with ToolContext."""
        from agents import Agent

        from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder

        # Create runtime and session
        runtime = Runtime.current()
        session = Session(test_session_id)

        # Create tool-using agent
        test_agent = Agent(
            name=test_agent_name,
            instructions="You are a helpful assistant. Use the tools provided.",
            tools=[],  # Tools will be bound after agent creation
        )

        # Bind tools with context
        bound_tools = OpenAIToolBuilder.bind(
            [context_aware_tool, simple_tool],
            runtime=runtime,
            session=session,
            agent=None,  # Will be set after wrapping
            requests=[AgentRequestText(text=test_prompt)],
            params={"test_key": "test_value"},
        )

        # Update agent with bound tools
        test_agent.tools = bound_tools

        # Wrap in module
        module = OpenAIModule([test_agent])
        wrapped_agent = module.get_agent(test_agent_name)

        # Update bound tools with the wrapped agent
        bound_tools_with_agent = OpenAIToolBuilder.bind(
            [context_aware_tool, simple_tool],
            runtime=runtime,
            session=session,
            agent=wrapped_agent,
            requests=[AgentRequestText(text=test_prompt)],
            params={"test_key": "test_value"},
        )

        # Test direct tool invocation (simulating what the framework does)
        result = bound_tools_with_agent[0](a=5, b=3)

        # Validate the context was properly initialized
        assert "sum=8" in result
        assert f"session={test_session_id}" in result
        assert f"agent={test_agent_name}" in result
        assert "runtime=GlobalRuntime" in result
        assert "requests=1" in result

        # Test simple tool without context
        result2 = bound_tools_with_agent[1](x=5, y=3)
        assert result2 == 15

    @pytest.mark.asyncio
    async def test_openai_async_tool_with_context(self):
        """Test that OpenAI agents correctly invoke async tools with ToolContext."""
        from agents import Agent

        from agentkernel.framework.openai import OpenAIModule, OpenAIToolBuilder

        async def async_context_tool(ctx: ToolContext, value: int) -> str:
            """Async tool that uses context."""
            return f"value={value}|session={ctx.session.id}"

        runtime = Runtime.current()
        session = Session("async-test-session")

        test_agent = Agent(name="AsyncAgent", instructions="Test agent", tools=[])

        module = OpenAIModule([test_agent])
        wrapped_agent = module.get_agent("AsyncAgent")

        bound_tools = OpenAIToolBuilder.bind(
            [async_context_tool],
            runtime=runtime,
            session=session,
            agent=wrapped_agent,
            requests=[],
            params={},
        )

        # Test async tool invocation
        result = await bound_tools[0](value=42)
        assert "value=42" in result
        assert "session=async-test-session" in result


# ADK Framework Tests
try:
    import google.adk  # noqa: F401

    from agentkernel.framework.adk import ADKToolBuilder

    adk_available = True
except ImportError:
    adk_available = False


@pytest.mark.skipif(not adk_available, reason="Google ADK package not installed")
class TestADKToolIntegration:
    """Tests for Google ADK framework tool integration."""

    @pytest.mark.asyncio
    async def test_adk_tool_context_initialization(self):
        """
        Test that ADK context is properly set up before tool invocation.

        Note: This test validates the tool builder logic but cannot fully test
        ADK runtime context without running an actual ADK agent, which requires
        more complex setup.
        """
        from agentkernel.core.tool_util import needs_tool_context
        from agentkernel.framework.adk import ADKToolBuilder

        # Verify tool detection works
        assert needs_tool_context(context_aware_tool)
        assert not needs_tool_context(simple_tool)

        # Bind tools for ADK
        bound_tools = ADKToolBuilder.bind([context_aware_tool, simple_tool])

        # The first tool should be wrapped, second should not
        assert bound_tools[0] != context_aware_tool
        assert bound_tools[1] == simple_tool

        # Verify metadata is preserved
        assert bound_tools[0].__name__ == "context_aware_tool"
        assert bound_tools[0].__doc__ == context_aware_tool.__doc__


# CrewAI Framework Tests
try:
    import crewai  # noqa: F401

    from agentkernel.framework.crewai import CrewAIToolBuilder

    crewai_available = True
except ImportError:
    crewai_available = False


@pytest.mark.skipif(not crewai_available, reason="CrewAI package not installed")
class TestCrewAIToolIntegration:
    """Tests for CrewAI framework tool integration."""

    @pytest.mark.asyncio
    async def test_crewai_tool_with_context(self):
        """Test that CrewAI tools correctly receive ToolContext."""
        from agentkernel.framework.crewai import CrewAIToolBuilder

        runtime = Runtime.current()
        session = Session("crewai-test-session")

        # Create a mock agent (simplified for testing)
        class MockCrewAIAgent:
            name = "CrewAITestAgent"

        mock_agent = MockCrewAIAgent()

        bound_tools = CrewAIToolBuilder.bind(
            [context_aware_tool, simple_tool],
            runtime=runtime,
            session=session,
            agent=mock_agent,
            requests=[AgentRequestText(text="test")],
            params={"crew_param": "value"},
        )

        # Test tool invocation
        result = bound_tools[0](a=10, b=5)

        assert "sum=15" in result
        assert "session=crewai-test-session" in result
        assert "agent=CrewAITestAgent" in result
        assert "requests=1" in result

        # Test simple tool
        result2 = bound_tools[1](x=10, y=5)
        assert result2 == 50


# LangGraph Framework Tests
try:
    import langgraph  # noqa: F401

    from agentkernel.framework.langgraph import LangGraphToolBuilder

    langgraph_available = True
except ImportError:
    langgraph_available = False


@pytest.mark.skipif(not langgraph_available, reason="LangGraph package not installed")
class TestLangGraphToolIntegration:
    """Tests for LangGraph framework tool integration."""

    @pytest.mark.asyncio
    async def test_langgraph_tool_with_context(self):
        """Test that LangGraph tools correctly receive ToolContext."""
        from agentkernel.framework.langgraph import LangGraphToolBuilder

        runtime = Runtime.current()
        session = Session("langgraph-test-session")

        # Create a mock agent
        class MockLangGraphAgent:
            name = "LangGraphTestAgent"

        mock_agent = MockLangGraphAgent()

        bound_tools = LangGraphToolBuilder.bind(
            [context_aware_tool, simple_tool],
            runtime=runtime,
            session=session,
            agent=mock_agent,
            requests=[AgentRequestText(text="test"), AgentRequestText(text="test2")],
            params={"graph_param": "value"},
        )

        # Test tool invocation
        result = bound_tools[0](a=7, b=3)

        assert "sum=10" in result
        assert "session=langgraph-test-session" in result
        assert "agent=LangGraphTestAgent" in result
        assert "requests=2" in result

        # Test simple tool
        result2 = bound_tools[1](x=7, y=3)
        assert result2 == 21


# Cross-framework compatibility tests (uses only tool_util, no framework deps)
class TestCrossFrameworkCompatibility:
    """Tests to ensure tools work consistently across frameworks."""

    def test_context_aware_tool_binding_without_frameworks(self):
        """
        Verify tool binding works with mock frameworks using only tool_util.
        This test doesn't require any framework packages to be installed.
        """
        from agentkernel.core.tool_util import needs_tool_context, wrap_tool_with_context

        def universal_tool(ctx: ToolContext, data: str) -> str:
            return f"{ctx.agent.name}:{data}"

        # Verify detection is consistent
        assert needs_tool_context(universal_tool)

        # Test binding with mock agent (no framework needed)
        runtime = Runtime.current()
        session = Session("universal-session")

        class MockAgent:
            name = "UniversalAgent"

        agent = MockAgent()

        # Use the core wrap_tool_with_context function directly
        wrapped_tool = wrap_tool_with_context(
            universal_tool,
            runtime=runtime,
            session=session,
            agent=agent,
            requests=[],
            params={},
        )

        result = wrapped_tool(data="test")
        assert "UniversalAgent:test" in result

    @pytest.mark.asyncio
    async def test_context_fields_properly_set(self):
        """
        Verify all ToolContext fields are properly initialized.
        This test uses only tool_util and doesn't require framework packages.
        """
        from agentkernel.core.tool_util import wrap_tool_with_context

        def inspector_tool(ctx: ToolContext) -> dict:
            """Tool that inspects the context."""
            return {
                "has_runtime": ctx.runtime is not None,
                "has_session": ctx.session is not None,
                "has_agent": ctx.agent is not None,
                "has_requests": isinstance(ctx.requests, list),
                "has_params": isinstance(ctx.params, dict),
                "runtime_type": type(ctx.runtime).__name__,
                "session_id": ctx.session.id,
                "agent_name": ctx.agent.name,
            }

        runtime = Runtime.current()
        session = Session("inspector-session")

        class TestAgent:
            name = "InspectorAgent"

        agent = TestAgent()
        requests = [
            AgentRequestText(text="req1"),
            AgentRequestText(text="req2"),
        ]
        params = {"key1": "value1", "key2": "value2"}

        wrapped_tool = wrap_tool_with_context(
            inspector_tool,
            runtime=runtime,
            session=session,
            agent=agent,
            requests=requests,
            params=params,
        )

        result = wrapped_tool()

        # Verify all fields are set
        assert result["has_runtime"] is True
        assert result["has_session"] is True
        assert result["has_agent"] is True
        assert result["has_requests"] is True
        assert result["has_params"] is True
        assert result["runtime_type"] == "GlobalRuntime"
        assert result["session_id"] == "inspector-session"
        assert result["agent_name"] == "InspectorAgent"
