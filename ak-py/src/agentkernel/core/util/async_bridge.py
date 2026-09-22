"""Running async work from synchronous code.

Agent Kernel has synchronous execution surfaces (the pipeline's consumer threads, the sync
ChatService entry points) that must drive async work: framework runners, platform SDK calls.
They all need the same event-loop handling, so it lives here once rather than being
re-derived per caller.

Two shapes, because a coroutine and an async generator deliver results differently: a
coroutine hands the loop exactly one value, its return value, so `run_async_sync` returns
once; an async generator hands over many, so `iterate_async_sync` pumps it one item at a
time and yields each as it is produced.
"""

import asyncio
import contextvars
import logging
import threading
import warnings
from typing import Any, AsyncGenerator, Coroutine, Generator, Optional

_log = logging.getLogger("ak.core.async_bridge")


def run_async_sync(coro: Coroutine) -> Any:
    """Run a coroutine from sync code, handling event loop state.

    Only a RuntimeError from get_event_loop() itself (no loop in this thread) falls back to
    asyncio.run: a RuntimeError raised by the coroutine must propagate as-is, not trigger a
    second await of the already-consumed coroutine.

    :param coro: Coroutine to execute.
    :return: Result of the coroutine.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def iterate_async_sync(agen: AsyncGenerator) -> Generator[Any, None, None]:
    """Consume an async generator from sync code, yielding each item as it is produced.

    The streaming counterpart of run_async_sync. Wrapping a stream in one coroutine can only
    ever deliver the whole run at once, because a coroutine returns a single value; this
    pumps the generator instead — one `__anext__` per item, driven to completion on the
    calling thread, with one loop held for the whole run — so a chunk reaches the caller as
    soon as the generator produces it. Background work the framework SDK started still gets
    loop time, because the loop runs for the whole of each await; only the caller's own
    handling of a yielded item happens with the loop stopped.

    A loop this thread already had is reused and left as it was found; otherwise a loop is
    owned for the duration of the run. asyncio.Runner owns that one, so it is torn down
    exactly as asyncio.run tears down its own (pending tasks cancelled, async generators shut
    down, loop closed, thread left with no current loop). See _open_loop for why "already had"
    is narrower than what asyncio.get_event_loop() hands back.

    :param agen: Async generator to consume.
    :return: Generator yielding each item the async generator produces.
    """
    loop = _open_loop()
    if loop is not None:
        yield from _pump(loop, agen)
        return
    with asyncio.Runner() as runner:
        yield from _pump(runner.get_loop(), agen)


def _open_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return a loop this thread already has, or None when it has none worth reusing.

    `asyncio.get_event_loop()` does not simply look one up. On a worker thread with no loop it
    raises RuntimeError, which is the answer we want. On the **main** thread it instead warns
    `There is no current event loop` and then manufactures a loop and sets it — and a loop made
    that way is not one we can reuse and leave as we found it, because nobody owns it: it is
    never closed and its async generators are never shut down, so it outlives the run and every
    later one on that thread inherits whatever the previous left behind. AWS Lambda invokes a
    handler on the main thread and reuses the container, so that is a live surface, not a
    theoretical one.

    Turning the warning into an error is what stops the manufacture: asyncio warns before it
    creates the loop, so raising there leaves the thread with no loop and sends the caller down
    the owned-loop path. The filter is scoped to the main thread because that is the only thread
    where the manufacture can happen, and because `warnings.catch_warnings()` mutates global
    state — entering it on the pipeline's consumer threads would race.

    :return: A loop this thread already had, or None when it has none or the one it has is
        closed.
    """
    if threading.current_thread() is threading.main_thread():
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            try:
                loop = asyncio.get_event_loop()
            except (RuntimeError, DeprecationWarning):
                return None
    else:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return None
    return None if loop.is_closed() else loop


def _pump(loop: asyncio.AbstractEventLoop, agen: AsyncGenerator) -> Generator[Any, None, None]:
    """Advance an async generator one item per turn on the given loop, in one context.

    Every step is its own task, and a task runs in a *fresh copy* of the current context, so a
    run that sets a contextvar while producing one item and resets it while producing another
    would reset a token belonging to a context that is already gone. `Runtime.stream` does
    exactly that — the current session and the current agent are contextvars set on entry and
    reset on exit — and the single coroutine the buffering bridge awaited gave it one context
    for free. Pinning one context here restores that: the steps enter it in turn, never
    concurrently, so the run keeps one continuous view of its context variables. It is a copy
    of the caller's, which is what a task would have taken anyway, so what the caller had set
    (an OpenTelemetry span, say) is still visible inside the run and what the run sets does
    not leak back out.

    The close in the finally is what a caller abandoning the iteration owes the generator:
    without it the run's own `finally` — storing the session, clearing the volatile cache —
    would not run until the generator was garbage collected.

    That close is also the only place a teardown failure can be reported from. A caller that
    abandons a stream does not call close() itself — it drops the generator and lets the
    interpreter finalize it — and an exception raised while finalizing a generator is printed
    to stderr as "Exception ignored in: ..." and goes no further. Logging it here is what puts
    it in front of an operator; it is re-raised so a caller that did close explicitly still
    sees it.

    :param loop: Event loop to drive each step on.
    :param agen: Async generator to consume.
    :return: Generator yielding each item the async generator produces.
    """
    context = contextvars.copy_context()
    try:
        while True:
            try:
                item = loop.run_until_complete(loop.create_task(agen.__anext__(), context=context))
            except StopAsyncIteration:
                return
            yield item
    finally:
        try:
            loop.run_until_complete(loop.create_task(agen.aclose(), context=context))
        except Exception:
            _log.exception("Streaming run failed while being torn down")
            raise
