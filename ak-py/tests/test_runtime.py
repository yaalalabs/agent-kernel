from agentkernel.core.sessions.in_memory import InMemorySessionStore
from agentkernel.core.sessions.redis import RedisSessionStore
import pytest

from agentkernel import Agent, Runner
from agentkernel.core.runtime import Runtime


class DummyRunner(Runner):
    async def run(self, agent, session, prompt):
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


def reset_runtime_singleton():
    # helper to reset the singleton between tests
    Runtime._instance = None


def test_runtime_instance_redis_when_config(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "redis"

            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    monkeypatch.setattr("agentkernel.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    # Should select REDIS memory type and initialize a session store
    assert type(rt._sessions) is RedisSessionStore
    assert rt.sessions() is not None


def test_runtime_instance_invalid_fallsback(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "not-a-real-type"

    monkeypatch.setattr("agentkernel.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    assert type(rt._sessions) is InMemorySessionStore
    # Should be able to register and list agents
    a = DummyAgent("a1")
    rt.register(a)
    assert "a1" in rt.agents()


@pytest.mark.asyncio
async def test_runtime_run_calls_runner(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    a = DummyAgent("agent")
    rt.register(a)
    sess = rt.sessions().new("s1")

    out = await rt.run(a, sess, "ping")
    assert out == "ok:ping"
