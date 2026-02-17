from typing import Any
from unittest.mock import MagicMock

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.tool import ToolBuilder, ToolContext


# Fixtures and helpers
class MockRunner(Runner):
    def __init__(self, name: str = "mock-runner"):
        super().__init__(name)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        return AgentReply(content="mock-reply")


class MockAgent(Agent):
    def __init__(self, name: str = "mock-agent", runner: Runner | None = None):
        super().__init__(name, runner or MockRunner())

    def get_description(self) -> str:
        return "Mock Agent"

    def get_a2a_card(self) -> Any:
        return None


@pytest.fixture
def mock_runtime():
    return MagicMock(spec=Runtime)


@pytest.fixture
def mock_agent():
    return MockAgent()


@pytest.fixture
def mock_session():
    return Session("test-session-id")


@pytest.fixture
def mock_requests():
    return [AgentRequestText(text="hello")]


@pytest.fixture
def tool_context(mock_runtime, mock_agent, mock_session, mock_requests):
    return ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)


# ToolContext property tests
class TestToolContextProperties:

    def test_id_is_non_empty_string(self, tool_context):
        assert isinstance(tool_context.id, str)
        assert len(tool_context.id) > 0

    def test_id_is_unique(self, mock_runtime, mock_agent, mock_session, mock_requests):
        ctx1 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)
        ctx2 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)
        assert ctx1.id != ctx2.id

    def test_runtime_property(self, tool_context, mock_runtime):
        assert tool_context.runtime is mock_runtime

    def test_agent_property(self, tool_context, mock_agent):
        assert tool_context.agent is mock_agent

    def test_session_property(self, tool_context, mock_session):
        assert tool_context.session is mock_session

    def test_requests_property(self, tool_context, mock_requests):
        assert tool_context.requests is mock_requests
        assert len(tool_context.requests) == 1
        assert tool_context.requests[0].text == "hello"


# ToolContext.get / .set / .reset (contextvars)
class TestToolContextGetSetReset:

    def test_get_raises_when_no_context_set(self):
        # Ensure clean state
        ToolContext._context.set(None)
        with pytest.raises(RuntimeError, match="No ToolContext is set"):
            ToolContext.get()

    def test_set_and_get(self, tool_context):
        tool_context.set()
        try:
            retrieved = ToolContext.get()
            assert retrieved is tool_context
        finally:
            tool_context.reset()

    def test_reset_clears_context(self, tool_context):
        tool_context.set()
        tool_context.reset()
        with pytest.raises(RuntimeError, match="No ToolContext is set"):
            ToolContext.get()

    def test_reset_without_set_is_noop(self, tool_context):
        # Should not raise
        tool_context.reset()

    def test_set_returns_self(self, tool_context):
        try:
            result = tool_context.set()
            assert result is tool_context
        finally:
            tool_context.reset()

    def test_nested_set_and_reset(self, mock_runtime, mock_agent, mock_session, mock_requests):
        ctx1 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)
        ctx2 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)

        ctx1.set()
        assert ToolContext.get() is ctx1

        ctx2.set()
        assert ToolContext.get() is ctx2

        ctx2.reset()
        assert ToolContext.get() is ctx1

        ctx1.reset()
        with pytest.raises(RuntimeError):
            ToolContext.get()


# ToolContext context manager (__enter__ / __exit__)
class TestToolContextContextManager:

    def test_enter_adds_to_cache(self, tool_context):
        with tool_context:
            assert tool_context.id in ToolContext._cache
            assert ToolContext._cache[tool_context.id] is tool_context

    def test_exit_removes_from_cache(self, tool_context):
        with tool_context:
            pass
        assert tool_context.id not in ToolContext._cache

    def test_enter_returns_self(self, tool_context):
        with tool_context as ctx:
            assert ctx is tool_context

    def test_multiple_contexts_in_cache(self, mock_runtime, mock_agent, mock_session, mock_requests):
        ctx1 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)
        ctx2 = ToolContext(mock_runtime, mock_agent, mock_session, mock_requests)

        with ctx1:
            with ctx2:
                assert ctx1.id in ToolContext._cache
                assert ctx2.id in ToolContext._cache
            # ctx2 exited
            assert ctx1.id in ToolContext._cache
            assert ctx2.id not in ToolContext._cache

    def test_exit_on_exception_still_cleans_up(self, tool_context):
        with pytest.raises(ValueError):
            with tool_context:
                raise ValueError("test error")
        assert tool_context.id not in ToolContext._cache


# ToolContext.fetch
class TestToolContextFetch:

    def test_fetch_returns_cached_context(self, tool_context):
        with tool_context:
            fetched = ToolContext.fetch(tool_context.id)
            assert fetched is tool_context

    def test_fetch_raises_for_unknown_id(self):
        with pytest.raises(KeyError, match="No ToolContext found for id"):
            ToolContext.fetch("nonexistent-id")

    def test_fetch_raises_after_exit(self, tool_context):
        with tool_context:
            pass
        with pytest.raises(KeyError):
            ToolContext.fetch(tool_context.id)


# ToolContext set/get combined with context manager
class TestToolContextSetGetWithContextManager:

    def test_set_inside_context_manager(self, tool_context):
        with tool_context:
            tool_context.set()
            try:
                assert ToolContext.get() is tool_context
                assert ToolContext.fetch(tool_context.id) is tool_context
            finally:
                tool_context.reset()

    def test_context_manager_does_not_affect_contextvar(self, tool_context):
        """__enter__/__exit__ manage the cache, not the contextvar."""
        ToolContext._context.set(None)
        with tool_context:
            # context manager doesn't call set(), so contextvar should still be None
            with pytest.raises(RuntimeError):
                ToolContext.get()


# ToolBuilder
class TestToolBuilder:

    def test_bind_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="bind\\(\\) must be implemented"):
            ToolBuilder.bind([lambda: None])

    def test_subclass_can_override_bind(self):
        class MyToolBuilder(ToolBuilder):
            @classmethod
            def bind(cls, funcs):
                return [f.__name__ for f in funcs]

        def my_func():
            pass

        result = MyToolBuilder.bind([my_func])
        assert result == ["my_func"]

    def test_bind_with_empty_list_raises(self):
        with pytest.raises(NotImplementedError):
            ToolBuilder.bind([])
