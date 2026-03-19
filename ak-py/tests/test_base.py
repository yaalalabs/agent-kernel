from typing import Any

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReply, AgentRequest


class MockRunner(Runner):

    def __init__(self, name: str):
        super().__init__(name)

    async def run(self, agent: Any, session: Session, requests: list[AgentRequest]) -> AgentReply:
        return AgentReply(content="mock-reply")


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
