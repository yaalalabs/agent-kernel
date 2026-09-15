"""Running a coroutine from synchronous code.

Agent Kernel has synchronous execution surfaces (the pipeline's consumer threads, the sync
ChatService entry points) that must drive async work: framework runners, platform SDK calls.
They all need the same event-loop handling, so it lives here once rather than being
re-derived per caller.
"""

import asyncio
from typing import Any, Coroutine


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
