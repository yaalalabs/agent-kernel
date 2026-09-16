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
from typing import Any, AsyncGenerator, Coroutine, Generator, Optional


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

    Loop handling matches run_async_sync: an open loop already on this thread is reused and
    left as it was found, and otherwise a loop is owned for the duration of the run.
    asyncio.Runner owns that one, so it is torn down exactly as asyncio.run tears down its
    own (pending tasks cancelled, async generators shut down, loop closed, thread left with
    no current loop).

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
    """Return this thread's usable event loop, or None when it has none to reuse.

    :return: The thread's open event loop, or None when there is no loop or it is closed.
    """
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
        loop.run_until_complete(loop.create_task(agen.aclose(), context=context))
