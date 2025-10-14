import pytest

from ak import Agent, Runner
from ak.core.runtime import Runtime, _MemoryType


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
    Runtime._agents = {}
    Runtime._sessions = None
    Runtime._memory_type = None


def test_runtime_instance_redis_when_config(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "redis"

            class redis:
                url = "redis://localhost:6379"
                ttl = 60
                prefix = "ak:test:"

    monkeypatch.setattr("ak.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    # Should select REDIS memory type and initialize a session store
    assert Runtime._memory_type == _MemoryType.REDIS
    assert rt.sessions() is not None


def test_runtime_instance_invalid_fallsback(monkeypatch):
    reset_runtime_singleton()

    class FakeCfg:
        class session:
            type = "not-a-real-type"

    monkeypatch.setattr("ak.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    assert Runtime._memory_type == _MemoryType.IN_MEMORY
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

    monkeypatch.setattr("ak.core.runtime.AKConfig.get", classmethod(lambda cls: FakeCfg))

    rt = Runtime.instance()
    a = DummyAgent("agent")
    rt.register(a)
    sess = rt.sessions().new("s1")

    out = await rt.run(a, sess, "ping")
    assert out == "ok:ping"
