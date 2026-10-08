"""
The diagnostics around a resume (spec `docs/specs/606-human-in-the-loop/`, iteration 4).

Agent Kernel does not constrain what a hook may do to a resume: a guardrail that can stop a first
prompt can stop a decision, and that is the application's call. These warnings are the entire
mechanism that makes the consequence visible, so each one has a test — without them a dropped
decision is silent, and "resume doesn't work" has nothing in the log to explain it.

`Runtime` observes as the *caller*, not as a hook, so none of this depends on where AK's own hooks
sit in the chain — which matters, because the order is not what one would guess: pre-hooks run user
first and system last, post-hooks system first and user last.
"""

import logging

import pytest
from test_runtime_resume import PausingAgent, PausingRunner, _resume_requests

from agentkernel.core.event import PausedInterruption, RunPaused, TextDelta
from agentkernel.core.hooks import PostHook, PreHook
from agentkernel.core.model import AgentReplyText, AgentRequestText, AgentResumeRequestAny
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore


class DroppingPreHook(PreHook):
    """Filters the request list down to text, the way a normalising hook plausibly would."""

    async def on_run(self, session, agent, requests):
        return [r for r in requests if isinstance(r, AgentRequestText)] or [AgentRequestText(prompt="")]

    def name(self):
        return "dropping_hook"


class HaltingPreHook(PreHook):
    async def on_run(self, session, agent, requests):
        return AgentReplyText(response="blocked")

    def name(self):
        return "halting_hook"


class PauseSwallowingPostHook(PostHook):
    """Filters out event types it does not recognise — the plausible way a pause gets eaten."""

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        return None if isinstance(event, RunPaused) else event

    def name(self):
        return "swallowing_hook"


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


async def _paused_session(runtime, agent):
    session = runtime.sessions().new("s1")
    paused = await runtime.run(agent, session, [AgentRequestText(prompt="refund it")])
    return session, paused


class TestPreHookWarnings:
    @pytest.mark.asyncio
    async def test_a_hook_that_drops_the_decision_warns(self, runtime, caplog):
        agent = PausingAgent()
        agent.pre_hooks.append(DroppingPreHook())
        runtime.register(agent)
        session, paused = await _paused_session(runtime, agent)

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert any("dropped by the pre-hook chain" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_dropped_decision_leaves_the_pause_open(self, runtime):
        """The hook wins — but the human can still answer, which is why it is only a warning."""
        agent = PausingAgent()
        agent.pre_hooks.append(DroppingPreHook())
        runtime.register(agent)
        session, paused = await _paused_session(runtime, agent)

        await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_a_hook_that_halts_a_resume_warns(self, runtime, caplog):
        agent = PausingAgent()
        runtime.register(agent)
        session, paused = await _paused_session(runtime, agent)
        agent.pre_hooks.append(HaltingPreHook())

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            reply = await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert reply.response == "blocked"
        assert any("accepted but never delivered" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_halted_resume_leaves_the_record_intact(self, runtime):
        """The only halt with a durable consequence: every other leaves nothing behind."""
        agent = PausingAgent()
        runtime.register(agent)
        session, paused = await _paused_session(runtime, agent)
        agent.pre_hooks.append(HaltingPreHook())

        await runtime.run(agent, session, _resume_requests("i1", run_id=paused.run_id))

        assert PausedRunState.get(session, paused.run_id) is not None

    @pytest.mark.asyncio
    async def test_an_ordinary_halt_does_not_warn(self, runtime, caplog):
        agent = PausingAgent()
        agent.pre_hooks.append(HaltingPreHook())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            await runtime.run(agent, session, [AgentRequestText(prompt="hello")])

        assert not [r for r in caplog.records if "never delivered" in r.message]


class TestStreamWarning:
    @pytest.mark.asyncio
    async def test_a_post_hook_dropping_the_pause_warns(self, runtime, caplog):
        class PausingStreamRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                record = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="i1", kind="tool_call")])
                yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        agent = PausingAgent(runner=PausingStreamRunner())
        agent.post_hooks.append(PauseSwallowingPostHook())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            chunks = [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        assert any("dropped by post-hook 'swallowing_hook'" in r.message for r in caplog.records)
        assert not any(isinstance(c.event, RunPaused) for c in chunks)

    @pytest.mark.asyncio
    async def test_the_record_survives_a_swallowed_pause(self, runtime):
        """The caller was not told, but the decision is still answerable."""

        class PausingStreamRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                record = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="i1", kind="tool_call")])
                yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        agent = PausingAgent(runner=PausingStreamRunner())
        agent.post_hooks.append(PauseSwallowingPostHook())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        assert len(PausedRunState.list(session)) == 1


class SubstitutingPostHook(PostHook):
    """Replaces the pause with something else, rather than dropping it outright.

    Returning a list is how a hook emits several events in place of one, so this is the realistic
    shape of a hook that rewrites a pause into, say, a notice of its own.
    """

    async def on_run(self, session, requests, agent, agent_reply):
        return agent_reply

    async def on_stream_event(self, session, requests, agent, event):
        if isinstance(event, RunPaused):
            return [TextDelta(message_id="m-sub", content="(a pause was here)")]
        return event

    def name(self):
        return "substituting_hook"


class TestAPauseReplacedByOtherEvents:
    """
    The warning exists for a dropped pause, and a hook returning `[other_event]` drops it just as
    surely as returning `None` — the emitted list is non-empty, so a `not emitted` check misses it.
    """

    @pytest.mark.asyncio
    async def test_substituting_the_pause_warns(self, runtime, caplog):
        class PausingStreamRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                record = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="i1", kind="tool_call")])
                yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        agent = PausingAgent(runner=PausingStreamRunner())
        agent.post_hooks.append(SubstitutingPostHook())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            chunks = [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        assert any("dropped by post-hook 'substituting_hook'" in r.message for r in caplog.records)
        assert not any(isinstance(c.event, RunPaused) for c in chunks)

    @pytest.mark.asyncio
    async def test_a_hook_that_keeps_the_pause_in_its_list_does_not_warn(self, runtime, caplog):
        """The guard must not fire on a hook that adds events beside the pause rather than replacing it."""

        class AugmentingPostHook(SubstitutingPostHook):
            async def on_stream_event(self, session, requests, agent, event):
                if isinstance(event, RunPaused):
                    return [TextDelta(message_id="m-note", content="heads up"), event]
                return event

            def name(self):
                return "augmenting_hook"

        class PausingStreamRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                record = PausedRunState.add(session, agent=agent.name, interruptions=[PausedInterruption(id="i1", kind="tool_call")])
                yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        agent = PausingAgent(runner=PausingStreamRunner())
        agent.post_hooks.append(AugmentingPostHook())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        with caplog.at_level(logging.WARNING, logger="ak.runtime"):
            chunks = [c async for c in runtime.stream(agent, session, [AgentRequestText(prompt="refund it")])]

        assert not any("dropped by post-hook" in r.message for r in caplog.records)
        assert any(isinstance(c.event, RunPaused) for c in chunks)
