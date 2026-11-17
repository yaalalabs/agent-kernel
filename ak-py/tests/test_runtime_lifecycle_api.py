"""
The lifecycle steps of Runtime that every run takes (#928): `activate` (public).

`run()` and `stream()` use them, and so does a surface that holds a session for longer than one run (a realtime
call). `activate` only sets context variables and takes no session lock.
"""

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.event import TextDelta
from agentkernel.core.hooks import PostHook, PreHook, StreamHalt
from agentkernel.core.model import AgentReplyText, AgentRequestText, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore
from agentkernel.core.util.key_value_cache import KeyValueCache

HUMAN = Principal(subject="human", provider="static", namespace="static")


class _Runner(Runner):
    def __init__(self, fail: bool = False):
        super().__init__("fake")
        self._fail = fail

    async def run(self, agent, session, requests):
        if self._fail:
            raise RuntimeError("boom")
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        if self._fail:
            raise RuntimeError("boom")
        yield TextDelta(content="ok", message_id="m1")


class _Agent(Agent):
    def __init__(self, name="general", fail=False):
        super().__init__(name, _Runner(fail))

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class _HaltingPreHook(PreHook):
    async def on_run(self, session, agent, requests):
        return AgentReplyText(response="halted by a pre-hook")

    def name(self):
        return "halting"


class _HaltingPostHook(PostHook):
    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        raise StreamHalt("stop")

    def name(self):
        return "halting"


@pytest.fixture(autouse=True)
def no_system_hooks():
    # The system hook chains are built from config at first use; pin them empty so only the agent's own hooks run.
    Runtime._system_pre_hooks = []
    Runtime._system_post_hooks = []
    yield
    Runtime._system_pre_hooks = None
    Runtime._system_post_hooks = None


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


@pytest.fixture
def calls(runtime, monkeypatch):
    """Records every `activate` call the runtime makes and the clearing of the volatile cache that ends a run, still running the real ones."""
    seen: list[str] = []
    real_activate, real_clear = runtime.activate, KeyValueCache._clear_all

    def activate(agent, session):
        seen.append("activate")
        return real_activate(agent, session)

    def clear_all(cache):
        seen.append("clear_cache")
        real_clear(cache)

    monkeypatch.setattr(runtime, "activate", activate)
    monkeypatch.setattr(KeyValueCache, "_clear_all", clear_all)
    return seen


class TestActivate:
    def test_the_session_and_agent_are_current_inside_and_restored_after(self, runtime):
        session, agent = Session("s1"), _Agent()
        assert Session.current() is None and Agent.current() is None

        with runtime.activate(agent, session):
            assert Session.current() is session
            assert Agent.current() is agent

        assert Session.current() is None and Agent.current() is None

    def test_nested_activations_restore_the_outer_one(self, runtime):
        outer_session, outer_agent = Session("outer"), _Agent("outer")
        inner_session, inner_agent = Session("inner"), _Agent("inner")

        with runtime.activate(outer_agent, outer_session):
            with runtime.activate(inner_agent, inner_session):
                assert Agent.current() is inner_agent
            assert Session.current() is outer_session
            assert Agent.current() is outer_agent

    def test_restores_after_an_exception(self, runtime):
        with pytest.raises(RuntimeError):
            with runtime.activate(_Agent(), Session("s1")):
                raise RuntimeError("boom")

        assert Session.current() is None and Agent.current() is None

    def test_takes_no_session_lock(self, runtime):
        session = Session("s1")

        with runtime.activate(_Agent(), session):
            assert not session._lock.locked()

    def test_publishes_nothing(self, runtime):
        session = Session("s1")

        with runtime.activate(_Agent(), session):
            assert session.get_principal() is None


class TestRunUsesThem:
    @pytest.mark.asyncio
    async def test_run_ends_with_the_run_state_gone(self, runtime):
        agent, session = _Agent(), Session("s1")

        await runtime.run(agent, session, [AgentRequestText(prompt="hi")], principal=HUMAN)

        assert session.get_principal() is None
        assert session.get_volatile_cache().keys() == []
        assert session.get_owner().subject == "human"
        assert Session.current() is None and Agent.current() is None

    @pytest.mark.asyncio
    async def test_on_success(self, runtime, calls):
        await runtime.run(_Agent(), Session("s1"), [AgentRequestText(prompt="hi")], principal=HUMAN)

        assert calls == ["activate", "clear_cache"]

    @pytest.mark.asyncio
    async def test_on_a_pre_hook_halt(self, runtime, calls):
        agent = _Agent()
        agent.pre_hooks.append(_HaltingPreHook())

        reply = await runtime.run(agent, Session("s1"), [AgentRequestText(prompt="hi")], principal=HUMAN)

        assert reply.response == "halted by a pre-hook"
        assert calls == ["activate", "clear_cache"]

    @pytest.mark.asyncio
    async def test_on_an_exception(self, runtime, calls):
        with pytest.raises(RuntimeError):
            await runtime.run(_Agent(fail=True), Session("s1"), [AgentRequestText(prompt="hi")], principal=HUMAN)

        assert calls == ["activate", "clear_cache"]


class TestStreamUsesThem:
    @staticmethod
    async def _drain(runtime, agent, session):
        return [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="hi")], principal=HUMAN)]

    @pytest.mark.asyncio
    async def test_on_a_normal_end(self, runtime, calls):
        session = Session("s1")

        await self._drain(runtime, _Agent(), session)

        assert calls == ["activate", "clear_cache"]
        assert session.get_principal() is None
        assert session.get_volatile_cache().keys() == []

    @pytest.mark.asyncio
    async def test_on_a_stream_halt(self, runtime, calls):
        agent = _Agent()
        agent.post_hooks.append(_HaltingPostHook())

        chunks = await self._drain(runtime, agent, Session("s1"))

        assert chunks[-1].error == "stop"
        assert calls == ["activate", "clear_cache"]

    @pytest.mark.asyncio
    async def test_on_an_exception(self, runtime, calls):
        with pytest.raises(RuntimeError):
            await self._drain(runtime, _Agent(fail=True), Session("s1"))

        assert calls == ["activate", "clear_cache"]
