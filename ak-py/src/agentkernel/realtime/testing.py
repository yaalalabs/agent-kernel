"""Reusable conformance suite for :class:`RealtimeRunner` implementations.

Mirrors ``pipeline/testing.py``'s ``QueueTransportContract`` and ``sandbox/testing.py``'s
``SandboxProviderContract``: subclass :class:`RealtimeRunnerContract` in a test file, implement the hooks that
build a runner over a fake native session, and pytest collects the contract tests against it. No real model is
needed. The contract asserts the rules in :meth:`RealtimeRunner.connect` and :meth:`RealtimeRunner.disconnect`
that the pool relies on: events reach the callback in order and one at a time, a ``disconnect`` is safe whenever it
comes and is not reported as a failure, a failure while connected is reported as ``error``, and a call the live
path cannot run is rejected before anything opens.

A rule a runner cannot show without a hook the subclass does not provide is skipped, not passed.
"""

import asyncio
import base64

import pytest

from .base import RealtimeRunner


class RecordedEvents:
    """The callback a test hands to ``connect``: it records every event, and checks the callbacks never overlap."""

    def __init__(self, delay: float = 0.0):
        """
        :param delay: Seconds each callback takes, so an adapter that does not await its callbacks is caught overlapping them.
        """
        self.events: list[tuple[str, dict]] = []
        self.max_concurrent = 0
        self._delay = delay
        self._running = 0
        self._changed = asyncio.Event()

    async def __call__(self, kind: str, data: dict) -> None:
        self._running += 1
        self.max_concurrent = max(self.max_concurrent, self._running)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            self.events.append((str(kind), data))
            self._changed.set()
        finally:
            self._running -= 1

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]

    def of(self, kind: str) -> list[dict]:
        return [data for k, data in self.events if k == kind]

    async def until(self, kind: str, timeout: float = 5.0) -> None:
        """Wait until an event of ``kind`` has been reported."""

        async def wait() -> None:
            while not self.of(kind):
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(wait(), timeout)


class RealtimeRunnerContract:
    """Runner conformance tests. Subclass per runner and implement the required hooks.

    Required hooks: :meth:`make_runner`, :meth:`start_call`, :meth:`speak`. The others are optional; a test whose
    hook is not implemented is skipped.
    """

    # How long a test waits for the fake native session to report an event before it fails.
    event_timeout: float = 5.0

    # -- required hooks -------------------------------------------------------------------------

    def make_runner(self) -> RealtimeRunner:
        """A new runner, not yet connected."""
        raise NotImplementedError

    async def start_call(self, runner: RealtimeRunner, callback) -> None:
        """Connect ``runner`` to a fake native session with a valid agent, reporting to ``callback``."""
        raise NotImplementedError

    async def speak(self, runner: RealtimeRunner) -> None:
        """Make the fake native session produce one model turn: at least one audio chunk and one transcript delta, then the turn's end."""
        raise NotImplementedError

    # -- optional hooks -------------------------------------------------------------------------

    async def start_invalid_call(self, runner: RealtimeRunner, callback) -> None:
        """Try to connect an agent or option the live path cannot run; ``connect`` must raise ``TypeError`` or ``ValueError``."""
        pytest.skip("start_invalid_call is not implemented")

    async def start_failing_call(self, runner: RealtimeRunner, callback) -> None:
        """Connect a valid agent whose native session fails to open; ``connect`` must raise."""
        pytest.skip("start_failing_call is not implemented")

    async def fail_native_session(self, runner: RealtimeRunner) -> None:
        """Make the connected native session fail on its own (not through ``disconnect``)."""
        pytest.skip("fail_native_session is not implemented")

    def nothing_opened(self, runner: RealtimeRunner) -> bool:
        """True when no native session, task or connection of ``runner`` is left open."""
        pytest.skip("nothing_opened is not implemented")

    # -- disconnect -------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_disconnect_before_connect_is_safe(self):
        runner = self.make_runner()
        await runner.disconnect()
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_can_repeat_and_is_not_reported_as_a_failure(self):
        runner, events = self.make_runner(), RecordedEvents()
        await self.start_call(runner, events)
        await runner.disconnect()
        await runner.disconnect()
        await asyncio.sleep(0.05)
        assert "error" not in events.kinds()

    # -- events -----------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_a_turn_reports_audio_and_transcript_before_its_done(self):
        runner, events = self.make_runner(), RecordedEvents()
        await self.start_call(runner, events)
        try:
            await self.speak(runner)
            await events.until(RealtimeRunner.Event.DONE, self.event_timeout)
        finally:
            await runner.disconnect()

        kinds = events.kinds()
        assert RealtimeRunner.Event.AUDIO_DELTA in kinds and RealtimeRunner.Event.TRANSCRIPT_DELTA in kinds
        assert kinds.index(RealtimeRunner.Event.DONE) > max(
            kinds.index(RealtimeRunner.Event.AUDIO_DELTA), kinds.index(RealtimeRunner.Event.TRANSCRIPT_DELTA)
        )

    @pytest.mark.asyncio
    async def test_event_payloads_follow_the_contract(self):
        runner, events = self.make_runner(), RecordedEvents()
        await self.start_call(runner, events)
        try:
            await self.speak(runner)
            await events.until(RealtimeRunner.Event.DONE, self.event_timeout)
        finally:
            await runner.disconnect()

        known = {str(member) for member in RealtimeRunner.Event}
        assert set(events.kinds()) <= known
        for data in events.of(RealtimeRunner.Event.AUDIO_DELTA):
            assert isinstance(data["message_id"], str)
            assert base64.b64decode(data["delta"], validate=True)
        for data in events.of(RealtimeRunner.Event.TRANSCRIPT_DELTA):
            assert isinstance(data["delta"], str) and isinstance(data["message_id"], str)
        for data in events.of(RealtimeRunner.Event.AGENT_CHANGED):
            assert isinstance(data["agent"], str)

    @pytest.mark.asyncio
    async def test_every_callback_is_awaited_and_events_do_not_overlap(self):
        runner, events = self.make_runner(), RecordedEvents(delay=0.01)
        await self.start_call(runner, events)
        try:
            await self.speak(runner)
            await events.until(RealtimeRunner.Event.DONE, self.event_timeout)
        finally:
            await runner.disconnect()

        assert events.max_concurrent == 1
        assert events.kinds()[-1] == RealtimeRunner.Event.DONE

    @pytest.mark.asyncio
    async def test_a_failure_while_connected_is_reported_as_an_error_event(self):
        runner, events = self.make_runner(), RecordedEvents()
        await self.start_call(runner, events)
        try:
            await self.fail_native_session(runner)
            await events.until(RealtimeRunner.Event.ERROR, self.event_timeout)
        finally:
            await runner.disconnect()

        assert isinstance(events.of(RealtimeRunner.Event.ERROR)[0]["message"], str)

    # -- connect ----------------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_an_agent_or_option_the_live_path_cannot_run_is_rejected_before_anything_opens(self):
        runner, events = self.make_runner(), RecordedEvents()
        with pytest.raises((TypeError, ValueError)):
            await self.start_invalid_call(runner, events)
        assert self.nothing_opened(runner)
        await runner.disconnect()

    @pytest.mark.asyncio
    async def test_a_failed_connect_closes_what_it_opened_and_disconnect_stays_safe(self):
        runner, events = self.make_runner(), RecordedEvents()
        with pytest.raises(Exception):
            await self.start_failing_call(runner, events)
        assert self.nothing_opened(runner)
        await runner.disconnect()
