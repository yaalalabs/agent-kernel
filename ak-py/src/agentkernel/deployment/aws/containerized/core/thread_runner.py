import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable

_log = logging.getLogger("ak.thread_runner")


class ThreadRunner:
    """
    Runs multiple callables as concurrent threads.

    If a thread raises, logs the exception. When exit_on_failure=True (default),
    also calls os._exit(1) so the container restarts cleanly via ECS.
    If a thread returns normally (no exception), it is logged as an unexpected
    exit but os._exit is NOT called regardless of exit_on_failure.
    """

    @staticmethod
    def run(
        *targets: Callable,
        max_workers: int | None = None,
        thread_names: list[str] | None = None,
        exit_on_failure: bool = True,
    ) -> None:
        names = thread_names or [getattr(t, "__name__", f"thread-{i}") for i, t in enumerate(targets)]

        with ThreadPoolExecutor(max_workers=max_workers or len(targets)) as executor:
            futures = {executor.submit(t): name for t, name in zip(targets, names)}

            done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)

            failed = False
            for future in done:
                name = futures[future]
                exc = future.exception()
                if exc is not None:
                    _log.exception(f"[{name}] crashed", exc_info=exc)
                    failed = True
                else:
                    _log.error(f"[{name}] exited unexpectedly (no exception)")

            # os._exit must fire here, inside the `with` block, before
            # executor.shutdown(wait=True) blocks indefinitely on the other
            # thread (which is an infinite poll loop and never returns).
            if failed and exit_on_failure:
                os._exit(1)
