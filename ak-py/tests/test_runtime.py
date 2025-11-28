import pytest

from agentkernel import Agent, Runner
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.session.redis import RedisSessionStore


class DummyRunner(Runner):
    async def run(self, agent, session, prompt):
        return f"ok:{prompt}"

    async def run_multi(self, agent, session, requests):
        prompt = requests[0].text if isinstance(requests[0], AgentRequestText) else ""
        return f"ok:{prompt}"


class DummyAgent(Agent):

    def __init__(self, name):
        runner = DummyRunner("DummyRunner")
        super().__init__(name, runner)
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


def test_runtime_instance_redis_when_config(monkeypatch):
    class FakeCfg:
        class session:
            type = "redis"

            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    # Should select REDIS memory type and initialize a session store
    assert runtime.sessions() is not None
    assert type(runtime.sessions()) is RedisSessionStore


def test_runtime_instance_invalid_fallsback(monkeypatch):
    class FakeCfg:
        class session:
            type = "not-a-real-type"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    assert runtime.sessions() is not None
    assert type(runtime.sessions()) is InMemorySessionStore

    # Should be able to register and list agents
    agent = DummyAgent("a1")
    runtime.register(agent)
    assert "a1" in runtime.agents()


@pytest.mark.asyncio
async def test_runtime_run_calls_runner(monkeypatch):
    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    agent = DummyAgent("agent")
    runtime.register(agent)
    session = runtime.sessions().new("s1")

    out = await runtime.run(agent, session, [AgentRequestText(text="ping")])
    assert out == "ok:ping"
