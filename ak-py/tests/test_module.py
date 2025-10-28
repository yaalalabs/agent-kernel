from agentkernel import Agent, Runner
from agentkernel.core.module import Module
from agentkernel.core.runtime import Runtime


class DummyRunner(Runner):
    async def run(self, agent, session, prompt):
        return f"ok:{prompt}"


class CustomAgent:
    def __init__(self, name: str = None):
        self.name = name


class DummyAgent(Agent):

    def __init__(self, name, agent: CustomAgent = None):
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
    def add(self, agent: CustomAgent):
        ak_agent = DummyAgent(name=agent.name, agent=agent)
        super().add(ak_agent)
        Runtime.instance().register(ak_agent)


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
    a1 = DummyAgent("agent1")
    mod = SimpleModule([a1])

    assert len(mod.agents) == 1
    assert mod.agents[0].name == "agent1"

    # Add a second agent and verify it appears in the module.agents list
    a2 = CustomAgent("agent2")
    mod.add(a2)

    assert len(mod.agents) == 2
    assert mod.agents[-1].name is "agent2"
    assert {a.name for a in mod.agents} == {"agent1", "agent2"}

    # Also verify runtime registration reflects the newly added agent
    rt = Runtime.instance()
    assert "agent1" in rt.agents()
    assert "agent2" in rt.agents()
