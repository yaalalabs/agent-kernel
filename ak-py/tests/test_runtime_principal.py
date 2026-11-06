"""
Runtime's identity publication (spec `docs/specs/603-identity-rbac-registry/`, iteration 2).

Every run has a principal, anonymous when the surface established none, and Runtime is the one
place that publishes it: into the session for the duration of the run, with the agent as its
actor, and as the session's owner the first time a direct-channel principal runs. A resume is
checked against the principal that paused. The access gate's cases (levels, tool filters, session
ownership enforcement) arrive with the gate in a later iteration; here the tool filter is always
absent.
"""

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.event import MessageEnd, MessageStart, PausedInterruption, TextDelta
from agentkernel.core.hooks import PreHook
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyText,
    AgentRequestText,
    AgentResumeRequestAny,
    Principal,
    ResumeDecision,
    SessionOwner,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore


def _user(**overrides) -> Principal:
    fields = {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
    fields.update(overrides)
    return Principal(**fields)


class ObservingRunner(Runner):
    """Records what the session publishes while the run is in progress."""

    def __init__(self):
        super().__init__("observing")
        self.seen: list[tuple] = []

    def _observe(self, session: Session) -> None:
        session.get_volatile_cache().set("app-key", "set during the run")
        self.seen.append((session.get_principal(), session.get_tool_filter(), session.get_owner()))

    async def run(self, agent, session, requests):
        self._observe(session)
        return AgentReplyText(response="ok")

    async def stream(self, agent, session, requests):
        self._observe(session)
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="ok")
        yield MessageEnd(message_id="m1")


class PausingRunner(Runner):
    """Pauses on run, answers on resume; enough to drive the resume identity check."""

    supports_pause = True

    def __init__(self):
        super().__init__("pausing")
        self.resumed = False

    async def run(self, agent, session, requests):
        record = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")])
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    async def resume(self, agent, session, requests, decisions, record):
        self.resumed = True
        PausedRunState.clear(session, record.id)
        return AgentReplyText(response="resumed")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class SimpleAgent(Agent):
    def __init__(self, runner: Runner, name: str = "assistant"):
        super().__init__(name, runner)

    def get_description(self) -> str:
        return "test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


class RecordingPreHook(PreHook):
    def __init__(self):
        self.seen: list = []

    async def on_run(self, session, agent, requests):
        self.seen.append(session.get_principal())
        return requests

    def name(self) -> str:
        return "recording"


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


@pytest.fixture
def agent(runtime):
    agent = SimpleAgent(ObservingRunner())
    runtime.register(agent)
    return agent


async def _run(runtime, agent, session, principal=None):
    return await runtime.run(agent, session, [AgentRequestText(prompt="hi")], principal=principal)


async def _stream(runtime, agent, session, principal=None):
    return [chunk async for chunk in runtime.stream(agent, session, [AgentRequestText(prompt="hi")], principal=principal)]


class TestPublication:
    @pytest.mark.asyncio
    async def test_run_publishes_the_principal_for_the_runner(self, runtime, agent):
        await _run(runtime, agent, runtime.sessions().new("s1"), principal=_user())
        principal, tool_filter, _ = agent.runner.seen[0]
        assert (principal.subject, principal.provider, principal.namespace) == ("alice", "oidc", "https://issuer.example")
        assert tool_filter is None  # no authorization block: nothing is filtered

    @pytest.mark.asyncio
    async def test_stream_publishes_the_principal_for_the_runner(self, runtime, agent):
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), principal=_user())
        assert [chunk.error for chunk in chunks if chunk.error] == []
        principal, tool_filter, _ = agent.runner.seen[0]
        assert principal.subject == "alice"
        assert tool_filter is None

    @pytest.mark.asyncio
    async def test_a_run_without_a_principal_is_anonymous_not_none(self, runtime, agent):
        await _run(runtime, agent, runtime.sessions().new("s1"))
        principal, _, _ = agent.runner.seen[0]
        assert principal is not None and principal.is_anonymous

    @pytest.mark.asyncio
    async def test_the_agent_is_the_actor(self, runtime, agent):
        await _run(runtime, agent, runtime.sessions().new("s1"), principal=_user())
        await _run(runtime, agent, runtime.sessions().new("s2"))
        for principal, _, _ in agent.runner.seen:
            assert principal.actor == Principal(kind="agent", subject="assistant", provider="agentkernel")

    @pytest.mark.asyncio
    async def test_pre_hooks_run_with_the_principal_published(self, runtime, agent):
        hook = RecordingPreHook()
        agent.pre_hooks.append(hook)
        await _run(runtime, agent, runtime.sessions().new("s1"), principal=_user())
        assert [p.subject for p in hook.seen] == ["alice"]

    @pytest.mark.asyncio
    async def test_nothing_stays_published_after_the_run(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session, principal=_user())
        assert session.get_principal() is None
        assert session.get_tool_filter() is None
        assert session.get_volatile_cache().get("app-key") is None

    @pytest.mark.asyncio
    async def test_nothing_stays_published_after_a_stream(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await _stream(runtime, agent, session, principal=_user())
        assert session.get_principal() is None
        assert session.get_volatile_cache().get("app-key") is None

    @pytest.mark.asyncio
    async def test_the_principal_is_per_run(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session, principal=_user())
        await _run(runtime, agent, session)
        assert [p.is_anonymous for p, _, _ in agent.runner.seen] == [False, True]


class TestOwner:
    @pytest.mark.asyncio
    async def test_a_direct_channel_principal_becomes_the_owner(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session, principal=_user())
        owner = SessionOwner(subject="alice", provider="oidc", namespace="https://issuer.example")
        assert session.get_owner() == owner
        assert agent.runner.seen[0][2] == owner  # recorded before the runner, not after

    @pytest.mark.asyncio
    async def test_an_anonymous_run_records_no_owner(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session)
        assert session.get_owner() is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["messaging:slack", "realtime:livekit"])
    async def test_a_shared_channel_records_no_owner(self, runtime, agent, provider):
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session, principal=Principal(subject="U1", provider=provider, namespace="T1"))
        assert session.get_owner() is None

    @pytest.mark.asyncio
    async def test_the_first_owner_is_kept(self, runtime, agent):
        """Recording only; whether a second principal may run here is the gate's call."""
        session = runtime.sessions().new("s1")
        await _run(runtime, agent, session, principal=_user())
        await _run(runtime, agent, session, principal=_user(subject="bob"))
        assert session.get_owner().subject == "alice"
        assert [p.subject for p, _, _ in agent.runner.seen] == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_the_owner_is_stored_with_the_session(self, runtime, agent):
        await _run(runtime, agent, runtime.sessions().new("s1"), principal=_user())
        assert runtime.sessions().load("s1").get_owner().subject == "alice"


class TestResumeIdentity:
    def _decision(self, run_id=None):
        return [AgentResumeRequestAny(run_id=run_id, decisions=[ResumeDecision(id="i1", status="approved")])]

    @pytest.fixture
    def pausing(self, runtime):
        agent = SimpleAgent(PausingRunner(), name="refunds")
        runtime.register(agent)
        return agent

    @pytest.mark.asyncio
    async def test_the_pausing_principal_may_resume(self, runtime, pausing):
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session, principal=_user())
        reply = await runtime.run(pausing, session, self._decision(paused.run_id), principal=_user())
        assert reply.response == "resumed"

    @pytest.mark.asyncio
    async def test_another_principal_is_refused_before_the_adapter(self, runtime, pausing):
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session, principal=_user())
        with pytest.raises(PermissionError, match="belongs to another principal"):
            await runtime.run(pausing, session, self._decision(paused.run_id), principal=_user(subject="bob"))
        assert pausing.runner.resumed is False
        assert PausedRunState.get(session, paused.run_id) is not None  # the record survives for its owner

    @pytest.mark.asyncio
    async def test_the_same_subject_from_another_namespace_is_refused(self, runtime, pausing):
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session, principal=_user())
        with pytest.raises(PermissionError, match="belongs to another principal"):
            await runtime.run(pausing, session, self._decision(paused.run_id), principal=_user(namespace="https://other.example"))

    @pytest.mark.asyncio
    async def test_a_record_without_a_subject_is_resumable_by_anyone(self, runtime, pausing):
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session)  # anonymous pause
        reply = await runtime.run(pausing, session, self._decision(paused.run_id), principal=_user())
        assert reply.response == "resumed"

    @pytest.mark.asyncio
    async def test_an_anonymous_resume_is_not_checked_here(self, runtime, pausing):
        """Ownership against an anonymous caller is the gate's job (it refuses the session before
        this check runs); without a gate an anonymous surface has no owner to enforce."""
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session, principal=_user())
        reply = await runtime.run(pausing, session, self._decision(paused.run_id))
        assert reply.response == "resumed"

    @pytest.mark.asyncio
    async def test_the_stream_path_refuses_too(self, runtime, pausing):
        session = runtime.sessions().new("s1")
        paused = await _run(runtime, pausing, session, principal=_user())
        with pytest.raises(PermissionError, match="belongs to another principal"):
            async for _ in runtime.stream(pausing, session, self._decision(paused.run_id), principal=_user(subject="bob")):
                pass
