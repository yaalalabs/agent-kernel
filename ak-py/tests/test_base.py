from typing import Any

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest


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
