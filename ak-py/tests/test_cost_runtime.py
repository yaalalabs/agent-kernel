"""
Runtime seams of cost management (spec `docs/specs/954-pluggable-cost-management/`, §3).

Iteration 1.5: every run carries a request id, from the request through ChatService, AgentService and Runtime,
minted when absent and published as Session.get_request_id() for the run's duration.

Iteration 1.6: Runtime asks the RunMeter before the pre-hooks; a deny ends the turn with the pre-hook halt shape and
stores nothing. RunMeterFactory always returns the no-op meter until cost management builds a real one.
"""

import re

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.chat_service import AgentHandler, ChatService
from agentkernel.core.config import AKConfig
from agentkernel.core.event import MessageEnd, MessageStart, PausedInterruption, TextDelta
from agentkernel.core.hooks import PreHook
from agentkernel.core.meter import BudgetDecision, NoOpRunMeter, RunMeter, RunMeterFactory
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyText,
    AgentRequestText,
    AgentResumeRequestAny,
    BaseRequest,
    BaseRunRequest,
    Principal,
    ResumeDecision,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.service import AgentService
from agentkernel.core.session.in_memory import InMemorySessionStore


class RequestIdRunner(Runner):
    """Records the request id the session publishes while the run is in progress."""

    def __init__(self):
        super().__init__("request-id")
        self.seen: list[str | None] = []

    async def run(self, agent, session: Session, requests):
        self.seen.append(session.get_request_id())
        return AgentReplyText(response="ok")

    async def stream(self, agent, session: Session, requests):
        self.seen.append(session.get_request_id())
        yield MessageStart(message_id="m1")
        yield TextDelta(message_id="m1", content="ok")
        yield MessageEnd(message_id="m1")


class SimpleAgent(Agent):
    def __init__(self, runner: Runner):
        super().__init__("assistant", runner)

    def get_description(self) -> str:
        return "test agent"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


@pytest.fixture
def agent(runtime):
    agent = SimpleAgent(RequestIdRunner())
    runtime.register(agent)
    return agent


_REQUESTS = [AgentRequestText(prompt="hi")]


class TestFromPayload:
    def test_an_envelope_body_takes_the_envelope_id(self):
        envelope = BaseRequest.from_payload({"request_id": "env-1", "body": {"prompt": "hi"}})
        assert envelope.request_id == envelope.body.request_id == "env-1"

    def test_a_flat_payload_keeps_the_client_id(self):
        envelope = BaseRequest.from_payload({"request_id": "client-1", "prompt": "hi"})
        assert envelope.request_id == envelope.body.request_id == "client-1"

    def test_an_id_is_minted_once_for_both(self):
        envelope = BaseRequest.from_payload({"prompt": "hi"})
        assert envelope.request_id and envelope.body.request_id == envelope.request_id

    def test_a_bare_run_request_keeps_its_own_id(self):
        envelope = BaseRequest.from_payload(BaseRunRequest(prompt="hi", request_id="body-1"))
        assert envelope.request_id == envelope.body.request_id == "body-1"

    def test_a_bare_run_request_without_an_id_gets_the_envelope_id(self):
        envelope = BaseRequest.from_payload(BaseRunRequest(prompt="hi"))
        assert envelope.request_id and envelope.body.request_id == envelope.request_id

    def test_a_prebuilt_envelope_hands_its_id_to_the_body(self):
        envelope = BaseRequest.from_payload(BaseRequest(request_id="env-1", body=BaseRunRequest(prompt="hi")))
        assert envelope.body.request_id == "env-1"


class TestRuntimePublication:
    @pytest.mark.asyncio
    async def test_run_publishes_the_given_id(self, runtime, agent):
        session = runtime.sessions().new("s1")
        await runtime.run(agent, session, _REQUESTS, request_id="req-1")
        assert agent.runner.seen == ["req-1"]
        assert session.get_request_id() is None

    @pytest.mark.asyncio
    async def test_stream_publishes_the_given_id(self, runtime, agent):
        session = runtime.sessions().new("s1")
        _ = [chunk async for chunk in runtime.stream(agent, session, _REQUESTS, request_id="req-1")]
        assert agent.runner.seen == ["req-1"]
        assert session.get_request_id() is None

    @pytest.mark.asyncio
    async def test_an_id_is_minted_per_run_when_absent(self, runtime, agent):
        await runtime.run(agent, runtime.sessions().new("s1"), _REQUESTS)
        _ = [chunk async for chunk in runtime.stream(agent, runtime.sessions().new("s2"), _REQUESTS)]
        first, second = agent.runner.seen
        assert re.fullmatch(r"[0-9a-f]{32}", first) and re.fullmatch(r"[0-9a-f]{32}", second)
        assert first != second


class TestChatServiceThreading:
    @pytest.mark.asyncio
    async def test_the_request_id_reaches_the_run(self, runtime, agent, monkeypatch):
        service = AgentService()
        service._runtime, service._agent, service._session = runtime, agent, runtime.sessions().new("s1")
        handler = AgentHandler()
        handler.service = service
        monkeypatch.setattr(ChatService, "prepare_agent_handler", lambda self, session_id, agent_name: handler)

        await ChatService().execute(BaseRunRequest(prompt="hi", session_id="s1", request_id="abc"))

        assert agent.runner.seen == ["abc"]


# Iteration 1.6: the RunMeter seam


class FakeMeter(RunMeter):
    """Returns a fixed decision and records what the session publishes when it is asked."""

    def __init__(self, decision: BudgetDecision):
        self.decision = decision
        self.seen: list[tuple] = []

    async def check(self, session, agent):
        self.seen.append((session.get_principal(), session.get_request_id()))
        return self.decision

    def is_budget_refusal(self, error):
        return False


class RecordingPreHook(PreHook):
    def __init__(self):
        self.calls = 0

    async def on_run(self, session, agent, requests):
        self.calls += 1
        return requests

    def name(self) -> str:
        return "recording"


class PausingRunner(Runner):
    """Pauses on run, answers on resume."""

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


@pytest.fixture
def meter(monkeypatch):
    """Installs a meter for the test; monkeypatch puts the factory back afterwards."""

    def install(decision: BudgetDecision) -> FakeMeter:
        fake = FakeMeter(decision)
        monkeypatch.setattr(RunMeterFactory, "_instance", fake)
        return fake

    return install


@pytest.fixture
def stored(runtime, monkeypatch):
    calls: list = []
    monkeypatch.setattr(runtime.sessions(), "store", lambda session: calls.append(session))
    return calls


class TestRunMeterFactory:
    def test_get_builds_one_no_op_meter(self, monkeypatch):
        monkeypatch.setattr(RunMeterFactory, "_instance", None)
        first = RunMeterFactory.get()
        assert isinstance(first, NoOpRunMeter)
        assert RunMeterFactory.get() is first

    def test_peek_never_builds(self, monkeypatch):
        monkeypatch.setattr(RunMeterFactory, "_instance", None)
        assert isinstance(RunMeterFactory.peek(), NoOpRunMeter)
        assert RunMeterFactory._instance is None

    def test_reset_forgets_the_meter(self, monkeypatch):
        monkeypatch.setattr(RunMeterFactory, "_instance", NoOpRunMeter())
        RunMeterFactory.reset()
        assert RunMeterFactory._instance is None

    def test_a_cost_block_still_gets_the_no_op_meter(self, monkeypatch):
        monkeypatch.setattr(RunMeterFactory, "_instance", None)
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_COST__GATEWAY__TYPE", "litellm")
        monkeypatch.setenv("AK_COST__GATEWAY__BASE_URL", "http://litellm:4000")
        AKConfig._reset()
        try:
            assert AKConfig.get().cost is not None
            assert isinstance(RunMeterFactory.get(), NoOpRunMeter)
        finally:
            AKConfig._reset()

    @pytest.mark.asyncio
    async def test_the_no_op_meter_allows_and_recognises_nothing(self):
        meter = NoOpRunMeter()
        assert await meter.check(Session("s1"), None) == BudgetDecision.allow()
        assert meter.is_budget_refusal(Exception("budget exceeded")) is False

    def test_budget_decision_is_re_exported_by_cost(self):
        import agentkernel.cost as cost

        assert cost.BudgetDecision is BudgetDecision


class TestRuntimeCheck:
    @pytest.mark.asyncio
    async def test_the_default_meter_lets_the_run_through(self, runtime, agent):
        reply = await runtime.run(agent, runtime.sessions().new("s1"), _REQUESTS)
        assert reply.response == "ok"

    @pytest.mark.asyncio
    async def test_the_check_sees_the_published_run(self, runtime, agent, meter):
        fake = meter(BudgetDecision.allow())
        principal = Principal(subject="alice", provider="oidc", namespace="https://issuer.example")
        await runtime.run(agent, runtime.sessions().new("s1"), _REQUESTS, principal=principal, request_id="req-1")
        [(seen_principal, seen_request_id)] = fake.seen
        assert seen_principal.subject == "alice"
        assert seen_request_id == "req-1"

    @pytest.mark.asyncio
    async def test_allow_runs_the_pre_hooks_and_stores(self, runtime, agent, meter, stored):
        meter(BudgetDecision.allow())
        hook = RecordingPreHook()
        agent.pre_hooks.append(hook)
        session = runtime.sessions().new("s1")
        stored.clear()  # new() stores the fresh session itself
        await runtime.run(agent, session, _REQUESTS)
        assert hook.calls == 1
        assert stored == [session]

    @pytest.mark.asyncio
    async def test_a_deny_ends_the_run_before_the_pre_hooks(self, runtime, agent, meter, stored):
        meter(BudgetDecision.deny("over budget"))
        hook = RecordingPreHook()
        agent.pre_hooks.append(hook)
        session = runtime.sessions().new("s1")
        stored.clear()  # new() stores the fresh session itself

        reply = await runtime.run(agent, session, _REQUESTS, request_id="req-1")

        assert reply == AgentReplyText(response="over budget")
        assert hook.calls == 0
        assert agent.runner.seen == []
        assert stored == []
        assert session.get_request_id() is None  # still unpublished

    @pytest.mark.asyncio
    async def test_a_deny_ends_the_stream_with_one_error_chunk(self, runtime, agent, meter, stored):
        meter(BudgetDecision.deny("over budget"))
        hook = RecordingPreHook()
        agent.pre_hooks.append(hook)

        session = runtime.sessions().new("s1")
        stored.clear()  # new() stores the fresh session itself

        chunks = [chunk async for chunk in runtime.stream(agent, session, _REQUESTS)]

        assert len(chunks) == 1
        assert (chunks[0].error, chunks[0].done) == ("over budget", True)
        assert hook.calls == 0
        assert agent.runner.seen == []
        assert stored == []

    @pytest.mark.asyncio
    async def test_a_warning_is_logged_and_the_reply_is_untouched(self, runtime, agent, meter, caplog):
        meter(BudgetDecision.warn("90% of budget used"))
        with caplog.at_level("WARNING", logger="ak.runtime"):
            reply = await runtime.run(agent, runtime.sessions().new("s1"), _REQUESTS)
        assert reply == AgentReplyText(response="ok")
        assert "90% of budget used" in caplog.text

    @pytest.mark.asyncio
    async def test_a_warning_leaves_the_stream_untouched(self, runtime, agent, meter, caplog):
        meter(BudgetDecision.warn("90% of budget used"))
        with caplog.at_level("WARNING", logger="ak.runtime"):
            chunks = [chunk async for chunk in runtime.stream(agent, runtime.sessions().new("s1"), _REQUESTS)]
        assert "".join(chunk.delta or "" for chunk in chunks) == "ok"
        assert not any(chunk.error for chunk in chunks)
        assert "90% of budget used" in caplog.text

    @pytest.mark.asyncio
    async def test_a_denied_resume_keeps_the_paused_run(self, runtime, meter, caplog):
        pausing = SimpleAgent(PausingRunner())
        runtime.register(pausing)
        session = runtime.sessions().new("s1")
        paused = await runtime.run(pausing, session, _REQUESTS)

        meter(BudgetDecision.deny("over budget"))
        decision = [AgentResumeRequestAny(run_id=paused.run_id, decisions=[ResumeDecision(id="i1", status="approved")])]
        with caplog.at_level("WARNING", logger="ak.runtime"):
            reply = await runtime.run(pausing, session, decision)

        assert reply == AgentReplyText(response="over budget")
        assert pausing.runner.resumed is False
        assert PausedRunState.get(session, paused.run_id) is not None
        assert "halted a resume" in caplog.text
