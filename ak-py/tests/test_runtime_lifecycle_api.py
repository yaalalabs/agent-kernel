"""
The public lifecycle API of Runtime (#928): `activate` and `end_run`.

`run()` and `stream()` use them, and so does a surface that holds a session for longer than one run (a
realtime call), which is why they are public. None takes the session lock.
"""

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.model import AgentReplyText, AgentRequestText, Principal
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore

HUMAN = Principal(subject="human", provider="static", namespace="static")


class _Runner(Runner):
    async def run(self, agent, session, requests):
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class _Agent(Agent):
    def __init__(self, name="general"):
        super().__init__(name, _Runner("fake"))

    def get_description(self):
        return "fake"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


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


class TestEndRun:
    def test_unpublishes_the_principal_and_clears_the_volatile_cache(self, runtime):
        session = Session("s1")
        runtime._publish(_Agent(), session, HUMAN)
        session.get_volatile_cache().set("hook-state", 1)

        runtime.end_run(session)

        assert session.get_principal() is None
        assert session.get_volatile_cache().keys() == []

    def test_keeps_the_durable_state(self, runtime):
        session = Session("s1")
        runtime._publish(_Agent(), session, HUMAN)
        session.get_non_volatile_cache().set("kept", 1)

        runtime.end_run(session)

        assert session.get_non_volatile_cache().get("kept") == 1
        assert session.get_owner() is not None

    def test_with_nothing_published_it_is_a_no_op(self, runtime):
        runtime.end_run(Session("s1"))


class TestRunAndStreamUseThem:
    @pytest.mark.asyncio
    async def test_run_ends_with_the_run_state_gone(self, runtime):
        agent, session = _Agent(), Session("s1")

        await runtime.run(agent, session, [AgentRequestText(prompt="hi")], principal=HUMAN)

        assert session.get_principal() is None
        assert session.get_volatile_cache().keys() == []
        assert session.get_owner().subject == "human"
        assert Session.current() is None and Agent.current() is None
