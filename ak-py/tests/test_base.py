import logging
from types import SimpleNamespace
from typing import Any

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest, SystemTool
from agentkernel.core.tool import SystemToolFactory


class MockRunner(Runner):

    def __init__(self, name: str):
        super().__init__(name)

    @property
    def supports_streaming(self) -> bool:
        return True

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        return AgentReply(content="mock-reply")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


def test_runner_init():
    runner = MockRunner("test-runner")
    assert runner.name == "test-runner"
    assert repr(runner) == "Runner(test-runner)"


class MockAgent(Agent):

    def __init__(self, name: str, runner: Runner):
        super().__init__(name, runner)

    def get_description(self) -> str:
        return "Mock Agent"

    def get_a2a_card(self) -> Any:
        return "Mock A2A Card"

    def override_system_prompt(self, prompt: str) -> None:
        pass

    def attach_tool(self, tool: Any) -> None:
        pass


def test_agent_init():
    runner = MockRunner("test-runner")
    agent = MockAgent("test-agent", runner)
    assert agent.name == "test-agent"
    assert agent.runner == runner
    assert repr(agent) == "Agent(test-agent)"
    assert agent.get_description() == "Mock Agent"
    assert agent.get_a2a_card() == "Mock A2A Card"


def test_agent_hooks():
    runner = MockRunner("test-runner")
    agent = MockAgent("test-agent", runner)

    pre_hook_1 = lambda req: req
    pre_hook_2 = lambda req: req
    post_hook_1 = lambda rep: rep
    post_hook_2 = lambda rep: rep

    agent.pre_hooks.extend([pre_hook_1, pre_hook_2])
    agent.post_hooks.extend([post_hook_1, post_hook_2])

    assert pre_hook_1 in agent.pre_hooks
    assert pre_hook_2 in agent.pre_hooks
    assert post_hook_1 in agent.post_hooks
    assert post_hook_2 in agent.post_hooks


def test_agent_current_default_none():
    assert Agent.current() is None


def test_agent_activate_sets_and_resets_current():
    agent = MockAgent("test-agent", MockRunner("test-runner"))
    assert Agent.current() is None
    with agent._activate():
        assert Agent.current() is agent
    assert Agent.current() is None


def test_agent_activate_resets_on_exception():
    agent = MockAgent("test-agent", MockRunner("test-runner"))
    try:
        with agent._activate():
            raise ValueError("boom")
    except ValueError:
        pass
    assert Agent.current() is None


def test_agent_activate_nested_restores_previous_agent():
    outer = MockAgent("outer-agent", MockRunner("outer-runner"))
    inner = MockAgent("inner-agent", MockRunner("inner-runner"))
    with outer._activate():
        assert Agent.current() is outer
        with inner._activate():
            assert Agent.current() is inner
        assert Agent.current() is outer
    assert Agent.current() is None


def test_get_framework_session_requires_current_agent():
    session = Session("test-session")
    with pytest.raises(RuntimeError):
        session.get_framework_session()


def test_get_framework_session_returns_none_when_not_stored():
    agent = MockAgent("test-agent", MockRunner("openai"))
    session = Session("test-session")
    with agent._activate():
        assert session.get_framework_session() is None


def test_get_framework_session_returns_value_keyed_by_runner_name():
    agent = MockAgent("test-agent", MockRunner("openai"))
    session = Session("test-session")
    session.set("openai", "native-openai-session")
    with agent._activate():
        assert session.get_framework_session() == "native-openai-session"


def test_get_framework_session_scoped_to_current_agents_runner_name():
    """A framework session stored under a different runner name is not returned."""
    agent = MockAgent("test-agent", MockRunner("langgraph"))
    session = Session("test-session")
    session.set("openai", "native-openai-session")
    with agent._activate():
        assert session.get_framework_session() is None


class ToolCarryingAgent(MockAgent):
    """An agent exposing a framework-native agent with a list-shaped `tools`, as all six adapters do."""

    def __init__(self, name: str, runner: Runner, tool_names: list):
        self._native = SimpleNamespace(tools=[SimpleNamespace(name=n) for n in tool_names])
        self.attached: list = []
        super().__init__(name, runner)

    @property
    def agent(self) -> Any:
        return self._native

    def attach_tool(self, tool: Any) -> None:
        self.attached.append(tool)


def _system_tool(name: str):
    def func():
        return name

    func.__name__ = name
    return SystemTool(name=name, description="", func=func)


class TestSystemToolNameCollisions:
    """Warn when a capability's system tool shadows one the application bound by hand (#553).

    Attaching anyway is the deliberate choice: skipping would make newly enabling a capability
    silently do nothing for that agent, which is the worse of the two failures.
    """

    def test_a_collision_warns_and_still_attaches(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            agent = ToolCarryingAgent("kb-agent", MockRunner("r"), ["read_kb", "write_kb"])
            agent._attach_system_tools()

        assert "kb-agent" in caplog.text
        assert "read_kb" in caplog.text
        assert [tool.__name__ for tool in agent.attached] == ["read_kb"]

    def test_the_warning_names_only_the_colliding_tools(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb"), _system_tool("browse_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            ToolCarryingAgent("kb-agent", MockRunner("r"), ["read_kb"])._attach_system_tools()

        assert "['read_kb']" in caplog.text

    def test_no_overlap_is_silent(self, monkeypatch, caplog):
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("browse_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            ToolCarryingAgent("kb-agent", MockRunner("r"), ["something_else"])._attach_system_tools()

        assert caplog.text == ""

    def test_an_agent_exposing_no_native_tools_attribute_warns_nothing(self, monkeypatch, caplog):
        # Entirely defensive: not every adapter exposes a list-shaped `tools`, and a missing one
        # must mean no warning, never a raise.
        monkeypatch.setattr(SystemToolFactory, "get_all", staticmethod(lambda name=None: [_system_tool("read_kb")]))

        with caplog.at_level(logging.WARNING, logger="ak.core.runner"):
            agent = MockAgent("plain-agent", MockRunner("r"))
            agent._attach_system_tools()

        assert caplog.text == ""
