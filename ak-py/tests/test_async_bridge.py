"""Tests for the sync/async bridge (``core/util/async_bridge.py``).

``iterate_async_sync`` is the streaming half: the point of it is *when* items arrive, so
most of what is asserted here is ordering — a produced/consumed timeline that a buffering
bridge could not produce — rather than the items themselves.
"""

import asyncio
import contextvars
import logging
import threading
import warnings

import pytest

from agentkernel.core.util.async_bridge import iterate_async_sync, run_async_sync


def _in_fresh_thread(func, timeout: float = 10.0):
    """Run func on a new thread — one with no event loop of its own — and return its result.

    The pipeline's consumers are exactly this: worker threads where ``get_event_loop()``
    raises. Running the loop-lifecycle cases here also keeps them from leaving the test
    session's own event loop state disturbed.
    """
    outcome = {}

    def _run():
        try:
            outcome["value"] = func()
        except BaseException as error:  # noqa: BLE001 - re-raised on the calling thread below
            outcome["error"] = error

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "the bridge stalled instead of finishing"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class TestIterateAsyncSync:
    def test_hands_over_each_item_before_producing_the_next(self):
        timeline = []

        async def _agen():
            for index in range(3):
                timeline.append(f"produced-{index}")
                yield index

        for item in iterate_async_sync(_agen()):
            timeline.append(f"consumed-{item}")

        assert timeline == ["produced-0", "consumed-0", "produced-1", "consumed-1", "produced-2", "consumed-2"]

    def test_yields_every_item_in_order(self):
        async def _agen():
            for index in range(5):
                yield index

        assert list(iterate_async_sync(_agen())) == [0, 1, 2, 3, 4]

    def test_empty_generator_yields_nothing(self):
        async def _agen():
            return
            yield  # pragma: no cover - unreachable, makes the function an async generator

        assert list(iterate_async_sync(_agen())) == []

    def test_exception_surfaces_after_the_items_already_handed_over(self):
        async def _agen():
            yield "first"
            raise RuntimeError("boom")

        iterator = iterate_async_sync(_agen())
        assert next(iterator) == "first"
        with pytest.raises(RuntimeError, match="boom"):
            next(iterator)

    def test_abandoning_the_iteration_closes_the_generator(self):
        cleaned_up = []

        async def _agen():
            try:
                yield 1
                yield 2  # pragma: no cover - the consumer stops before this
            finally:
                cleaned_up.append("closed")

        iterator = iterate_async_sync(_agen())
        assert next(iterator) == 1
        iterator.close()

        assert cleaned_up == ["closed"]

    def test_a_teardown_failure_is_logged_and_re_raised(self, caplog):
        """A teardown failure has nowhere else to surface.

        The consumers abandon a stream rather than closing it, and an exception raised while the
        interpreter finalizes a generator is printed to stderr as "Exception ignored in: ..." and
        reaches no logger and no caller. Logging it at the close is what puts it in front of an
        operator; the re-raise keeps it visible to a caller that did close explicitly.
        """

        async def _agen():
            try:
                yield 1
            finally:
                raise RuntimeError("session store failed during teardown")

        iterator = iterate_async_sync(_agen())
        assert next(iterator) == 1
        with caplog.at_level(logging.ERROR, logger="ak.core.async_bridge"):
            with pytest.raises(RuntimeError, match="session store failed during teardown"):
                iterator.close()

        assert "Streaming run failed while being torn down" in caplog.text
        assert "session store failed during teardown" in caplog.text

    def test_runs_on_a_thread_that_has_no_event_loop(self):
        async def _agen():
            yield "a"
            yield "b"

        def _consume():
            items = list(iterate_async_sync(_agen()))
            with pytest.raises(RuntimeError):
                asyncio.get_event_loop()
            return items

        assert _in_fresh_thread(_consume) == ["a", "b"]

    def test_reuses_an_existing_loop_and_leaves_it_open(self):
        async def _agen():
            yield "a"
            yield "b"

        def _consume():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                items = list(iterate_async_sync(_agen()))
                return items, asyncio.get_event_loop() is loop, loop.is_closed()
            finally:
                loop.close()

        assert _in_fresh_thread(_consume) == (["a", "b"], True, False)

    def test_does_not_leave_a_manufactured_loop_on_the_main_thread(self):
        """The main thread is the one place get_event_loop() creates a loop instead of raising.

        Reusing that one would leak it — nobody closes it or shuts its async generators down, so
        it outlives the run and the next run on that thread inherits whatever was left on it. AWS
        Lambda invokes a handler on the main thread of a container it reuses, so this is the
        serverless consumers' path, not a test-only one. The bridge must own its loop here too.
        """
        assert threading.current_thread() is threading.main_thread()

        async def _agen():
            yield "a"

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            assert list(iterate_async_sync(_agen())) == ["a"]

        with pytest.raises(RuntimeError):
            asyncio.get_event_loop()

    def test_replaces_a_closed_loop_rather_than_driving_it(self):
        async def _agen():
            yield "a"

        def _consume():
            closed = asyncio.new_event_loop()
            closed.close()
            asyncio.set_event_loop(closed)
            return list(iterate_async_sync(_agen()))

        assert _in_fresh_thread(_consume) == ["a"]

    def test_a_contextvar_set_on_one_item_survives_to_the_next(self):
        """Each item is pumped as its own task, and a task runs in a copy of the context, so
        without one pinned context a run that enters on one item and exits on another — which
        is exactly Runtime.stream with the current session and agent — reads back a default
        mid-run and then resets a token from a context it never belonged to.
        """
        marker = contextvars.ContextVar("ak-test-marker", default="outside")

        async def _agen():
            token = marker.set("inside")
            try:
                yield marker.get()
                yield marker.get()
            finally:
                marker.reset(token)

        assert list(iterate_async_sync(_agen())) == ["inside", "inside"]
        assert marker.get() == "outside", "the run's context leaked into the caller's"

    def test_the_callers_context_is_visible_inside_the_run(self):
        """The pinned context is a copy of the caller's, not an empty one, so ambient state a
        caller had set — a tracing span's context, for instance — still reaches the run."""
        marker = contextvars.ContextVar("ak-test-caller-marker", default="unset")
        marker.set("set-by-caller")

        async def _agen():
            yield marker.get()
            yield marker.get()

        assert list(iterate_async_sync(_agen())) == ["set-by-caller", "set-by-caller"]

    def test_background_work_keeps_running_between_items(self):
        """The shape's standing risk: an SDK's heartbeat or prefetch must still get loop time.

        It does, because the loop runs for the whole of each ``__anext__`` await — only the
        consumer's own handling of an item happens with the loop stopped.
        """
        ticks = []

        async def _agen():
            async def _heartbeat():
                while True:
                    await asyncio.sleep(0.005)
                    ticks.append(len(ticks))

            beat = asyncio.get_running_loop().create_task(_heartbeat())
            try:
                for index in range(3):
                    await asyncio.sleep(0.05)
                    yield index
            finally:
                beat.cancel()

        seen = [(item, len(ticks)) for item in iterate_async_sync(_agen())]

        assert [item for item, _ in seen] == [0, 1, 2]
        assert seen[0][1] > 0, "the heartbeat got no loop time while the first item was awaited"
        assert seen[-1][1] > seen[0][1], "the heartbeat stopped advancing once items started arriving"


class TestRunAsyncSync:
    """run_async_sync is untouched by the streaming addition; these pin that down."""

    def test_returns_the_coroutine_result(self):
        async def _coro():
            return "done"

        assert _in_fresh_thread(lambda: run_async_sync(_coro())) == "done"

    def test_propagates_a_runtime_error_raised_by_the_coroutine(self):
        async def _coro():
            raise RuntimeError("from the coroutine")

        with pytest.raises(RuntimeError, match="from the coroutine"):
            _in_fresh_thread(lambda: run_async_sync(_coro()))
