import pytest

from agentkernel import Agent, Runner
from agentkernel.core.builder import SessionStoreBuilder
from agentkernel.core.model import AgentReplyText, AgentRequestText
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.session.redis import RedisSessionStore


class DummyRunner(Runner):
    async def run(self, agent, session, requests):
        prompt = requests[0].text if isinstance(requests[0], AgentRequestText) else ""
        return AgentReplyText(text=f"ok:{prompt}")


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


def test_runtime_instance_invalid_fallback(monkeypatch):
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
    assert out.text == "ok:ping"


@pytest.mark.asyncio
async def test_runtime_current_default(monkeypatch):
    """
    Test that Runtime.current() returns GlobalRuntime by default
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    from agentkernel.core.runtime import GlobalRuntime

    current_runtime = Runtime.current()
    assert current_runtime is not None
    assert isinstance(current_runtime, Runtime)
    # Should return GlobalRuntime singleton
    assert current_runtime == GlobalRuntime.instance()


@pytest.mark.asyncio
async def test_runtime_current_context_manager(monkeypatch):
    """
    Test that Runtime.current() returns the active runtime in a context manager
    """

    class FakeCfg:
        class session:
            type = "in_memory"

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: FakeCfg))

    runtime = Runtime(SessionStoreBuilder.build())
    agent = DummyAgent("agent")

    # Before context, should get GlobalRuntime
    from agentkernel.core.runtime import GlobalRuntime

    before_runtime = Runtime.current()
    assert before_runtime == GlobalRuntime.instance()

    # Inside context, should get the specific runtime
    with runtime:
        current_runtime = Runtime.current()
        assert current_runtime is runtime
        assert current_runtime != GlobalRuntime.instance()

        # Register an agent and verify it works
        runtime.register(agent)
        assert "agent" in runtime.agents()

    # After context, should return to GlobalRuntime
    after_runtime = Runtime.current()
    assert after_runtime == GlobalRuntime.instance()
