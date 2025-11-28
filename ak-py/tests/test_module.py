from typing import List

from agentkernel import Agent, Runner
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentRequestText
from agentkernel.core.module import Module
from agentkernel.core.runtime import Runtime


class DummyRunner(Runner):
    async def run(self, agent, session, prompt):
        return f"ok:{prompt}"

    async def run_multi(self, agent, session, requests):
        prompt = requests[0].text if isinstance(requests[0], AgentRequestText) else ""
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


def test_module_add_updates_agents(monkeypatch):
    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    with Runtime(SessionStoreBuilder.build()) as runtime:
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
        assert "agent1" in runtime.agents()
        assert "agent2" in runtime.agents()

        # Verify unload
        mod.unload()
        assert len(mod.agents) == 0
        assert runtime.agents() == {}

        # Verify reload
        mod.load([a1])
        assert len(mod.agents) == 1
        assert mod.agents[0].name == "agent1"
        assert runtime.agents() == {"agent1": mod.agents[0]}

        # Handle duplicates
        a3 = FrameworkAgent("agent3")

        try:
            SimpleModule([a3, a1])
        except Exception as e:
            assert "Agent with name 'agent1' is already registered." in str(e)

        # Runtime should be intact after exception
        assert len(mod.agents) == 1
        assert runtime.agents() == {"agent1": mod.agents[0]}


def test_load_modules_with_unique_agent_names():
    with Runtime(SessionStoreBuilder.build()) as runtime:
        a1 = FrameworkAgent("agent1")
        SimpleModule([a1])
        assert len(runtime.agents()) == 1
        assert "agent1" in runtime.agents().keys()

        a2 = FrameworkAgent("agent2")
        a3 = FrameworkAgent("agent3")
        SimpleModule([a2, a3])
        assert len(runtime.agents()) == 3
        assert "agent1" in runtime.agents().keys()
        assert "agent2" in runtime.agents().keys()
        assert "agent3" in runtime.agents().keys()


def test_load_modules_with_duplicate_agent_names():
    with Runtime(SessionStoreBuilder.build()) as runtime:
        a1 = FrameworkAgent("agent1")
        mod1 = SimpleModule([a1])
        assert len(runtime.agents()) == 1
        assert "agent1" in runtime.agents().keys()

        a2 = FrameworkAgent("agent2")
        a1x = FrameworkAgent("agent1")
        try:
            SimpleModule([a2, a1x])
        except Exception as e:
            assert "Agent with name 'agent1' is already registered." in str(e)

        assert len(runtime.agents()) == 1
        assert runtime.agents() == {"agent1": mod1.agents[0]}


def test_load_modules_with_duplicate_agent_names_across_runtimes():
    runtime1 = Runtime(SessionStoreBuilder.build())
    with runtime1:
        a1 = FrameworkAgent("agent1")
        mod1 = SimpleModule([a1])
        assert len(runtime1.agents()) == 1
        assert runtime1.agents() == {"agent1": mod1.agents[0]}

    runtime2 = Runtime(SessionStoreBuilder.build())
    with runtime2:
        a1x = FrameworkAgent("agent1")
        a2 = FrameworkAgent("agent2")
        mod2 = SimpleModule([a1x, a2])
        assert len(runtime2.agents()) == 2
        assert runtime2.agents() == {"agent1": mod2.agents[0], "agent2": mod2.agents[1]}
