"""
Runtime dispatch for a resume (spec `docs/specs/606-human-in-the-loop/`, iteration 4).

Driven by a DummyRunner that pauses, so the whole path works before any adapter does. The four
failure modes are the substance: each is raised in Runtime, before the branch, because an adapter
wraps its body in one `except Exception` that would turn any of them into a generic error.
"""

import pytest

from agentkernel.core.base import Agent, Runner, Session
from agentkernel.core.event import PausedInterruption
from agentkernel.core.model import (
    AgentPausedReplyAny,
    AgentReplyText,
    AgentRequestText,
    AgentResumeRequestAny,
    ResumeDecision,
)
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore


class PausingRunner(Runner):
    """Pauses on the first run, then answers on resume. The seam every adapter will fill in."""

    supports_pause = True

    def __init__(self, name="pausing", pause_again=False, kind="tool_call"):
        super().__init__(name)
        self.pause_again = pause_again
        self.kind = kind
        self.resumed_with = None
        self.resumed_requests = None
        self._paused = 0

    async def run(self, agent, session, requests):
        self._paused += 1
        record = PausedRunState.add(
            session,
            agent=agent.name,
            interruptions=[PausedInterruption(id=f"i{self._paused}", kind=self.kind, tool_name="refund")],
            payload={"state": "blob"},
        )
        return AgentPausedReplyAny(run_id=record.id, session_id=session.id, agent=agent.name, interruptions=record.interruptions)

    async def resume(self, agent, session, requests, decisions, record):
        self.resumed_with = decisions
        self.resumed_requests = requests
        if self.pause_again:
            # Clear-or-replace is the adapter's, not Runtime's: only the adapter knows whether the
            # framework can still resume the earlier run.
            PausedRunState.clear(session, record.id)
            again = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="resumed-again", kind="tool_call")])
            return AgentPausedReplyAny(run_id=again.id, session_id=session.id, agent=agent.name, interruptions=again.interruptions)
        PausedRunState.clear(session, record.id)
        return AgentReplyText(response=f"resumed:{decisions[0].status}")

    async def stream(self, agent, session, requests):
        raise NotImplementedError()
        yield


class PausingAgent(Agent):
    def __init__(self, name="refunds", runner=None):
        super().__init__(name, runner or PausingRunner())

    def get_description(self) -> str:
        return "pauses"

    def get_a2a_card(self):
        return None

    def override_system_prompt(self, prompt):
        pass

    def attach_tool(self, tool):
        pass


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


def _decisions(*ids, status="approved"):
    return [ResumeDecision(id=i, status=status) for i in ids]


def _resume_requests(*ids, run_id=None, status="approved"):
    return [AgentResumeRequestAny(run_id=run_id, decisions=_decisions(*ids, status=status))]


async def _pause(runtime, agent, session):
    return await runtime.run(agent, session, [AgentRequestText(prompt="refund it")])


class TestDispatch:
    @pytest.mark.asyncio
    async def test_a_resume_request_reaches_resume_not_run(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        reply = await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert reply.response == "resumed:approved"
        assert agent.runner.resumed_with[0].id == "i1"

    @pytest.mark.asyncio
    async def test_resume_receives_the_hook_processed_request_list(self, runtime):
        """Adapters put this list in the ToolContext, so a tool on a resumed turn sees it."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert any(isinstance(r, AgentResumeRequestAny) for r in agent.runner.resumed_requests)

    @pytest.mark.asyncio
    async def test_the_run_id_may_be_omitted(self, runtime):
        """Resolved from the interruption ids — the only thing AG-UI can do."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)

        reply = await runtime.run(agent, session, _resume_requests("i1"))

        assert reply.response == "resumed:approved"

    @pytest.mark.asyncio
    async def test_an_ordinary_turn_still_calls_run(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        reply = await _pause(runtime, agent, session)

        assert isinstance(reply, AgentPausedReplyAny)


class TestLeftoverRecordCleanup:
    @pytest.mark.asyncio
    async def test_a_successful_resume_clears_its_record(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_failed_resume_keeps_the_record_so_the_decision_can_be_retried(self, runtime):
        """A transient framework failure must not cost the human their decision."""

        class FlakyRunner(PausingRunner):
            attempts = 0

            async def resume(self, agent, session, requests, decisions, record):
                FlakyRunner.attempts += 1
                if FlakyRunner.attempts == 1:
                    # What every adapter does with a framework failure: report it as text, without
                    # reaching its own PausedRunState.clear.
                    return AgentReplyText(response="Sorry, something went wrong.")
                return await super().resume(agent, session, requests, decisions, record)

        agent = PausingAgent(runner=FlakyRunner())
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))
        assert PausedRunState.get(session, paused.run_id) is not None

        reply = await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))
        assert reply.response == "resumed:approved"
        assert PausedRunState.list(session) == []

    @pytest.mark.asyncio
    async def test_a_resume_that_pauses_again_keeps_its_new_record(self, runtime):
        """Narrowed to a non-paused reply precisely so this case is untouched."""
        agent = PausingAgent(runner=PausingRunner(pause_again=True))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        reply = await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert isinstance(reply, AgentPausedReplyAny)
        assert [r.id for r in PausedRunState.list(session)] == [reply.run_id]

    @pytest.mark.asyncio
    async def test_an_ordinary_turn_leaves_a_pending_pause_alone(self, runtime):
        """The user changed the subject; AK does not discard their pending decision for them."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        await runtime.run(agent, session, [AgentRequestText(prompt="something else")])

        assert PausedRunState.get(session, paused.run_id) is not None


class TestFailureModes:
    """Raised in Runtime, before the branch — an adapter's `except` would make them all generic."""

    @pytest.mark.asyncio
    async def test_no_paused_run_matches(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        with pytest.raises(ValueError, match="No paused run in session 's1' matches"):
            await runtime.run(agent, session, _resume_requests("i1"))

    @pytest.mark.asyncio
    async def test_an_unknown_run_id(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)

        with pytest.raises(ValueError, match="No paused run in session 's1' matches"):
            await runtime.run(agent, session, _resume_requests("i1", run_id="no-such-run"))

    @pytest.mark.asyncio
    async def test_a_decision_naming_an_unknown_interruption(self, runtime):
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        with pytest.raises(ValueError, match="unknown interruption"):
            await runtime.run(agent, session, _resume_requests("nope", run_id=paused.run_id))

    @pytest.mark.asyncio
    async def test_decisions_spanning_two_runs(self, runtime):
        """One resume addresses one run."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)
        PausedRunState.add(session, agent="refunds", interruptions=[PausedInterruption(id="i9", kind="tool_call")])

        with pytest.raises(ValueError, match="No paused run in session 's1' matches"):
            await runtime.run(agent, session, _resume_requests("i1", "i9"))

    @pytest.mark.asyncio
    async def test_an_agent_that_disagrees_with_the_record(self, runtime):
        agent = PausingAgent()
        other = PausingAgent(name="billing")
        runtime.register(agent)
        runtime.register(other)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        with pytest.raises(ValueError, match="belongs to 'refunds'"):
            await runtime.run(other, session, _resume_requests("i1", run_id=paused.run_id))

    @pytest.mark.asyncio
    async def test_a_runner_that_does_not_support_pausing(self, runtime):
        class NoPauseRunner(PausingRunner):
            supports_pause = False

        agent = PausingAgent(runner=NoPauseRunner())
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)

        with pytest.raises(ValueError, match="does not support resuming"):
            await runtime.run(agent, session, _resume_requests("i1"))


class TestStatusIsRequiredForApprovals:
    """
    An approval pause answered with no verb has no defined rendering in any adapter.

    `status` stays optional on the model because an `input_required` pause has nothing to approve —
    the frameworks take a value there, not a yes or no — so the requirement is per interruption
    kind and can only be checked once the record says which kind each decision answers.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["tool_call", "confirmation"])
    async def test_an_approval_answered_without_a_status_is_rejected(self, runtime, kind):
        agent = PausingAgent(runner=PausingRunner(kind=kind))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)

        with pytest.raises(ValueError, match="gives no status for interruption"):
            await runtime.run(agent, session, _resume_requests("i1", status=None))

    @pytest.mark.asyncio
    async def test_a_value_pause_may_omit_the_status(self, runtime):
        agent = PausingAgent(runner=PausingRunner(kind="input_required"))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        await _pause(runtime, agent, session)

        reply = await runtime.run(agent, session, _resume_requests("i1", status=None))

        assert reply.response == "resumed:None"

    @pytest.mark.asyncio
    async def test_the_check_is_per_interruption_not_per_request(self, runtime):
        """A value pause answered beside an approval pause must not excuse the missing verb."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        record = PausedRunState.add(
            session,
            agent=agent.name,
            interruptions=[
                PausedInterruption(id="ask", kind="input_required"),
                PausedInterruption(id="approve", kind="tool_call"),
            ],
        )
        decisions = [ResumeDecision(id="ask", message="two"), ResumeDecision(id="approve")]

        with pytest.raises(ValueError, match=r"awaiting approval: \['approve'\]"):
            await runtime.run(agent, session, [AgentResumeRequestAny(run_id=record.id, decisions=decisions)])


class TestTheAgentMismatchErrorIsActionable:
    """
    A resume names the agent that paused; there is no way for Runtime to relax that.

    AgentService.select has already defaulted to the first registered agent by the time Runtime
    sees the request, so "the client named the wrong agent" and "the client named none" arrive
    identically. Rejecting both is the deliberate choice — AK does not quietly rewrite what the
    client asked for — which makes the message the only thing that can tell them apart.
    """

    @pytest.mark.asyncio
    async def test_the_error_says_where_to_find_the_agent_name(self, runtime):
        agent = PausingAgent()
        other = PausingAgent(name="billing")
        runtime.register(agent)
        runtime.register(other)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        with pytest.raises(ValueError) as excinfo:
            await runtime.run(other, session, _resume_requests("i1", run_id=paused.run_id))

        assert "paused reply" in str(excinfo.value)
        assert "default agent" in str(excinfo.value)


class TestTheActivatedAgentIsTheOneThatRuns:
    """
    Runtime must not swap the agent out from under the contextvar it already activated.

    `_activate()` is entered before the resume is validated, and `Agent.current()` is what
    `session.get_framework_session()` resolves the runner key through — so an adapter's `resume()`
    reading it has to see the same agent it was handed. Validation therefore checks the record
    against the agent, rather than resolving a replacement from it.
    """

    @pytest.mark.asyncio
    async def test_a_stale_agent_reference_runs_itself_not_the_registry_entry(self, runtime):
        """`Module.unload()` then `load()` again replaces the registry entry with a new wrapper.

        A caller holding the old one is what separates "checked against the record" from "resolved
        from it": both agents are named 'refunds', so the mismatch check passes either way.
        """
        seen = {}

        class RecordingRunner(PausingRunner):
            async def resume(self, agent, session, requests, decisions, record):
                seen["passed"] = agent
                seen["current"] = Agent.current()
                return AgentReplyText(response="done")

        stale = PausingAgent(runner=RecordingRunner())
        runtime.register(stale)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, stale, session)

        runtime.deregister(stale)
        reloaded = PausingAgent(runner=RecordingRunner())
        runtime.register(reloaded)

        await runtime.run(stale, session, _resume_requests("i1", run_id=paused.run_id))

        assert seen["passed"] is stale
        assert seen["current"] is stale
        assert reloaded.runner.resumed_with is None

    @pytest.mark.asyncio
    async def test_a_record_whose_agent_was_deregistered_is_still_rejected(self, runtime):
        """The registry is checked, not used as a source — the failure mode survives the change."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)
        runtime.deregister(agent)

        with pytest.raises(ValueError, match="no longer registered"):
            await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))


class TestAnAgentRebountToAnotherFramework:
    """
    A deploy can move an agent between frameworks while a pause is outstanding — the name survives,
    the stored state does not.

    Without the check the record reaches the new adapter, which cannot read a payload written by the
    old one, runs from scratch, and answers a decision nobody applied. Demonstrated before the fix:
    an OpenAI record went into the LangGraph adapter and came back as a fresh pause.
    """

    @pytest.mark.asyncio
    async def test_a_resume_is_refused_when_the_runner_no_longer_matches(self, runtime):
        agent = PausingAgent(runner=PausingRunner(name="openai"))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)

        runtime.deregister(agent)  # the redeploy
        rebound = PausingAgent(runner=PausingRunner(name="langgraph"))
        runtime.register(rebound)

        with pytest.raises(ValueError, match="was created by runner 'openai'"):
            await runtime.run(rebound, session, _resume_requests("i1", run_id=paused.run_id))

    @pytest.mark.asyncio
    async def test_the_message_names_both_frameworks(self, runtime):
        agent = PausingAgent(runner=PausingRunner(name="openai"))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)
        runtime.deregister(agent)
        rebound = PausingAgent(runner=PausingRunner(name="langgraph"))
        runtime.register(rebound)

        with pytest.raises(ValueError) as exc:
            await runtime.run(rebound, session, _resume_requests("i1", run_id=paused.run_id))

        assert "'openai'" in str(exc.value) and "'langgraph'" in str(exc.value)

    @pytest.mark.asyncio
    async def test_the_adapter_is_never_reached(self, runtime):
        """The point of raising in Runtime: the wrong adapter must not see the record at all."""
        agent = PausingAgent(runner=PausingRunner(name="openai"))
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)
        runtime.deregister(agent)
        rebound_runner = PausingRunner(name="langgraph")
        rebound = PausingAgent(runner=rebound_runner)
        runtime.register(rebound)

        with pytest.raises(ValueError):
            await runtime.run(rebound, session, _resume_requests("i1", run_id=paused.run_id))

        assert rebound_runner.resumed_with is None
        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_a_record_with_no_runner_is_still_resumable(self, runtime):
        """Written before the field existed, so there is nothing to compare — today's behaviour."""
        agent = PausingAgent()
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        paused = await _pause(runtime, agent, session)
        record = PausedRunState.get(session, paused.run_id)
        record.runner = None
        PausedRunState.clear(session, record.id)
        session.get_non_volatile_cache().set("ak.paused_runs", [record])

        reply = await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert reply.response == "resumed:approved"
