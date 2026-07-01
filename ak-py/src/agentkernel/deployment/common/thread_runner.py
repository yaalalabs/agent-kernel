import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger("ak.thread_runner")


class ThreadRunner:
    """
    Runs Task instances concurrently — each as task.execution_function(task.item) — and reacts to
    each completion in turn.
    """

    @dataclass
    class Task:
        execution_function: Callable
        thread_name: str
        item: Any = None
        stop_task_on_failure: bool = True
        stop_all_on_failure: bool = False

        def __post_init__(self) -> None:
            if self.stop_all_on_failure and not self.stop_task_on_failure:
                raise ValueError("stop_all_on_failure=True requires stop_task_on_failure=True")

        def _submit(self, executor: ThreadPoolExecutor):
            args = () if self.item is None else (self.item,)
            return executor.submit(self.execution_function, *args)

    @staticmethod
    def run(tasks: list[Task], max_workers: int | None = None) -> None:
        if not tasks:
            return

        with ThreadPoolExecutor(max_workers=max_workers or len(tasks)) as executor:
            futures = {task._submit(executor): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                exc = future.exception()
                if exc is not None:
                    if task.stop_task_on_failure:
                        _log.exception(f"[{task.thread_name}] raised unexpectedly", exc_info=exc)
                        if task.stop_all_on_failure:
                            os._exit(1)  # stops the entire container
                    else:
                        _log.debug(f"[{task.thread_name}] raised (stop_task_on_failure=False, ignoring)")
                else:
                    _log.debug(f"[{task.thread_name}] completed")
