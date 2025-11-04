from typing import List

from agentkernel import Agent, Runner
from agentkernel.core.module import Module
from agentkernel.core.runtime import Runtime


class DummyRunner(Runner):
    async def run(self, agent, session, prompt):
        return f"ok:{prompt}"


class FrameworkAgent:
    def __init__(self, name: str = None):
        self.name = name


class KernelWrappedAgent(Agent):

    def __init__(self, name, agent: FrameworkAgent = None):
        runner = DummyRunner("DummyRunner")
        super().__init__(name, runner)
        self._agent = agent
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def runner(self):
        return self._runner

    def get_a2a_card(self):
        pass

    def get_description(self):
        pass


class SimpleModule(Module):

    def __init__(self, agents: list[FrameworkAgent]):
        super().__init__()
        self.load(agents)

    def _wrap(self, agent: FrameworkAgent, agents: List[FrameworkAgent]) -> Agent:
        return KernelWrappedAgent(agent.name, agent)

    def load(self, agents: list[FrameworkAgent]):
        super().load(agents)


def reset_runtime_singleton():
    Runtime._instance = None
    Runtime._agents = {}
    Runtime._sessions = None
    Runtime._memory_type = None


def test_module_add_updates_agents(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    # Initialize with one agent
    a1 = FrameworkAgent("agent1")
    mod = SimpleModule([a1])

    assert len(mod.agents) == 1
    assert mod.agents[0].name == "agent1"

    # Add a second agent and verify it appears in the module.agents list
    a2 = FrameworkAgent("agent2")
    mod.load([a1, a2])

    assert len(mod.agents) == 2
    assert mod.agents[-1].name == "agent2"
    assert {a.name for a in mod.agents} == {"agent1", "agent2"}

    # Verify runtime registration reflects the newly added agent
    rt = Runtime.instance()
    assert "agent1" in rt.agents()
    assert "agent2" in rt.agents()

    # Verify unload
    mod.unload()
    assert len(mod.agents) == 0
    assert rt.agents() == {}

    # Verify reload
    mod.load([a1])
    assert len(mod.agents) == 1
    assert mod.agents[0].name == "agent1"
    assert rt.agents() == {"agent1": mod.agents[0]}

    # Handle duplicates
    a3 = FrameworkAgent("agent3")

    try:
        SimpleModule([a3, a1])
    except Exception as e:
        assert "Agent with name 'agent1' is already registered." in str(e)

    # Runtime should be intact after exception
    assert len(mod.agents) == 1
    assert rt.agents() == {"agent1": mod.agents[0]}
