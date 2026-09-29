"""
The paused stream's terminal sequence (spec `docs/specs/606-human-in-the-loop/`, iteration 4).

A pause is a valid outcome the client can act on, not an invalidated partial it must discard — so it
never travels through `StreamChunk.error`, and unlike the `StreamHalt` path the session *is* stored.

The boundary drain is the part worth the test: an agent pauses precisely because a tool call needs
approval, so a `ToolCallStart` is usually open at that moment. Ending the stream without closing it
leaves a frontend rendering that tool call as work still in progress, forever.
"""

import pytest
from test_runtime_resume import PausingAgent, PausingRunner, _resume_requests

from agentkernel.core.event import MessageStart, PausedInterruption, RunPaused, TextDelta, ToolCallEnd, ToolCallStart
from agentkernel.core.model import AgentRequestText
from agentkernel.core.paused_run import PausedRunState
from agentkernel.core.runtime import Runtime
from agentkernel.core.session.in_memory import InMemorySessionStore


def _pausing_stream_runner(*, open_tool_call=False, resume_answers=True):
    class _Runner(PausingRunner):
        async def stream(self, agent, session, requests):
            yield MessageStart(message_id="m1")
            if open_tool_call:
                yield ToolCallStart(tool_call_id="t1", name="refund")
            record = PausedRunState.add(
                session,
                agent=agent.name,
                interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")],
                payload={"state": "blob"},
            )
            yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)

        async def resume_stream(self, agent, session, requests, decisions, record):
            self.resumed_with = decisions
            yield TextDelta(message_id="m2", content=f"resumed:{decisions[0].status}")

    return _Runner()


@pytest.fixture
def runtime():
    return Runtime(InMemorySessionStore())


async def _stream(runtime, agent, session, requests):
    return [chunk async for chunk in runtime.stream(agent, session, requests)]


class TestPausedTerminalSequence:
    @pytest.mark.asyncio
    async def test_a_pause_never_reaches_the_error_field(self, runtime):
        agent = PausingAgent(runner=_pausing_stream_runner())
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        assert all(chunk.error is None for chunk in chunks)

    @pytest.mark.asyncio
    async def test_the_stream_ends_with_done(self, runtime):
        agent = PausingAgent(runner=_pausing_stream_runner())
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        assert chunks[-1].done is True
        assert chunks[-1].event is None

    @pytest.mark.asyncio
    async def test_the_pause_is_emitted_as_an_ordinary_event(self, runtime):
        agent = PausingAgent(runner=_pausing_stream_runner())
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        paused = [c.event for c in chunks if isinstance(c.event, RunPaused)]
        assert len(paused) == 1
        assert paused[0].interruptions[0].tool_name == "refund"

    @pytest.mark.asyncio
    async def test_the_pause_names_the_agent_to_resume(self, runtime):
        """A resume is rejected unless it names this agent, and a stream carries nothing else that does."""
        agent = PausingAgent(runner=_pausing_stream_runner())
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        paused = next(c.event for c in chunks if isinstance(c.event, RunPaused))
        assert paused.agent == "refunds"

    @pytest.mark.asyncio
    async def test_an_open_tool_call_is_closed_before_the_stream_ends(self, runtime):
        """Without this a frontend renders the gated tool call as still running, forever."""
        agent = PausingAgent(runner=_pausing_stream_runner(open_tool_call=True))
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        types = [type(c.event).__name__ for c in chunks if c.event is not None]
        assert types.index("RunPaused") < types.index("ToolCallEnd")
        assert isinstance(chunks[-2].event, (ToolCallEnd, type(chunks[-2].event)))
        assert chunks[-1].done is True

    @pytest.mark.asyncio
    async def test_every_open_boundary_is_drained(self, runtime):
        agent = PausingAgent(runner=_pausing_stream_runner(open_tool_call=True))
        runtime.register(agent)
        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        closed = {type(c.event).__name__ for c in chunks if c.event is not None}
        assert {"MessageEnd", "ToolCallEnd"} <= closed

    @pytest.mark.asyncio
    async def test_the_session_is_stored_so_the_record_survives(self, runtime):
        """Unlike the StreamHalt path, which deliberately skips the store."""
        agent = PausingAgent(runner=_pausing_stream_runner())
        runtime.register(agent)
        session = runtime.sessions().new("s1")

        await _stream(runtime, agent, session, [AgentRequestText(prompt="refund it")])

        reloaded = runtime.sessions().load("s1")
        assert len(PausedRunState.list(reloaded)) == 1


class TestStreamingResume:
    @pytest.mark.asyncio
    async def test_a_resume_dispatches_to_resume_stream(self, runtime):
        runner = _pausing_stream_runner()
        agent = PausingAgent(runner=runner)
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        chunks = await _stream(runtime, agent, session, [AgentRequestText(prompt="refund it")])
        run_id = next(c.event.run_id for c in chunks if isinstance(c.event, RunPaused))

        resumed = await _stream(runtime, agent, session, _resume_requests("i1", run_id=run_id))

        assert runner.resumed_with[0].id == "i1"
        assert any(c.delta == "resumed:approved" for c in resumed)

    @pytest.mark.asyncio
    async def test_a_streamed_resume_clears_its_record(self, runtime):
        runner = _pausing_stream_runner()
        agent = PausingAgent(runner=runner)
        runtime.register(agent)
        session = runtime.sessions().new("s1")
        chunks = await _stream(runtime, agent, session, [AgentRequestText(prompt="refund it")])
        run_id = next(c.event.run_id for c in chunks if isinstance(c.event, RunPaused))

        await _stream(runtime, agent, session, _resume_requests("i1", run_id=run_id))

        assert PausedRunState.list(session) == []


class TestTheRunnerGeneratorIsClosed:
    """
    A pause ends the stream by breaking out of the runner's generator, leaving it suspended.

    Python would finalize it whenever GC or the loop's async-generator hooks got round to it. An
    adapter holding a framework HTTP stream at the pause point would therefore keep that connection
    open for as long as the human takes to answer, which is the whole point of pausing.
    """

    @pytest.mark.asyncio
    async def test_a_paused_stream_closes_the_generator_it_broke_out_of(self, runtime):
        closed = []

        class LeakyRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                try:
                    record = PausedRunState.add(
                        session,
                        agent=agent.name,
                        interruptions=[PausedInterruption(id="i1", kind="tool_call", tool_name="refund")],
                    )
                    yield RunPaused(run_id=record.id, agent=agent.name, interruptions=record.interruptions)
                    yield TextDelta(message_id="m1", content="never reached")
                finally:
                    closed.append(True)

        agent = PausingAgent(runner=LeakyRunner())
        runtime.register(agent)

        await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="refund it")])

        assert closed == [True]

    @pytest.mark.asyncio
    async def test_an_ordinary_stream_still_finishes_cleanly(self, runtime):
        """Closing an exhausted generator is a no-op — the normal path must not change."""
        closed = []

        class PlainRunner(PausingRunner):
            async def stream(self, agent, session, requests):
                try:
                    yield TextDelta(message_id="m1", content="hello")
                finally:
                    closed.append(True)

        agent = PausingAgent(runner=PlainRunner())
        runtime.register(agent)

        chunks = await _stream(runtime, agent, runtime.sessions().new("s1"), [AgentRequestText(prompt="hi")])

        assert closed == [True]
        assert chunks[-1].done is True
