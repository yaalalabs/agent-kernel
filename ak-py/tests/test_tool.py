import pytest

from agentkernel import Agent, Runtime, Session
from agentkernel.core.model import AgentRequestText
from agentkernel.core.tool import ToolContext


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


def test_tool_context_creation():
    """Test that ToolContext can be created with all required parameters."""
    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")
    requests = [AgentRequestText(text="test")]
    params = {"key": "value"}

    ctx = ToolContext(
        runtime=runtime,
        session=session,
        agent=agent,
        requests=requests,
        params=params,
    )

    assert ctx.runtime == runtime
    assert ctx.session == session
    assert ctx.agent == agent
    assert ctx.requests == requests
    assert ctx.params == params


def test_tool_context_is_immutable():
    """Test that ToolContext is immutable (frozen dataclass)."""
    runtime = Runtime.current()
    session = Session("test-session")
    agent = MockAgent("test-agent")
    requests = []
    params = {}

    ctx = ToolContext(
        runtime=runtime,
        session=session,
        agent=agent,
        requests=requests,
        params=params,
    )

    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        ctx.runtime = None


def test_tool_builder_imports():
    """Test that all tool builders can be imported."""
    # Test that the core utility functions can be imported
    from agentkernel.core.tool_util import needs_tool_context, wrap_tool_with_context

    # These should be callable
    assert callable(needs_tool_context)
    assert callable(wrap_tool_with_context)
