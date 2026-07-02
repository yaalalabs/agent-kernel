import logging
import sys
import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable

_log = logging.getLogger("ak.thread_runner")


class ThreadRunner:
    """
    Runs Task instances concurrently — each as task.execution_function(task.item) — and reacts to
    each completion in turn.

    Each Task gets its own threading.Thread (instead of a ThreadPoolExecutor worker), so a
    finished task's OS thread is torn down and reclaimed immediately rather than lingering
    idle until every task in the batch — including any that never finish — has completed.
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

    @staticmethod
    def run(tasks: list[Task], max_workers: int | None = None) -> None:
        if not tasks:
            return

        semaphore = threading.Semaphore(max_workers or len(tasks))
        completions: Queue = Queue() # Thread-safe mailbox every worker thread reports its completion to.

        def _target(task: "ThreadRunner.Task") -> None:
            args = () if task.item is None else (task.item,)
            with semaphore:
                try:
                    task.execution_function(*args)
                except Exception as exc:
                    completions.put((task, exc))
                else:
                    completions.put((task, None))
            # the thread ends itself once execution_function returns (or raises), and Python/the OS reclaim it.

        # daemon=True: on stop_all_on_failure, sys.exit() below only unwinds the calling thread the interpreter still waits for every non-daemon thread before 
        # actually exiting, which would hang forever behind a never-ending task. Daemon threads are abandoned instead.
        threads = [
            threading.Thread(target=_target, args=(task,), name=task.thread_name, daemon=True)
            for task in tasks
        ]
        for thread in threads:
            thread.start()

        for _ in tasks:
            task, exc = completions.get() # Pulling from a shared queue exactly len(tasks) times yields tasks in true completion order (whichever finishes first is handled first)
            if exc is not None:
                if task.stop_task_on_failure:
                    _log.exception(f"[{task.thread_name}] raised unexpectedly", exc_info=exc)
                    if task.stop_all_on_failure:
                        sys.exit(1)
                else:
                    _log.debug(f"[{task.thread_name}] raised (stop_task_on_failure=False, ignoring)")
            else:
                _log.debug(f"[{task.thread_name}] completed")
