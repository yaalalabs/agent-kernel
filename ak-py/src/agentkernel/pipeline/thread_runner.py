import logging
import os
import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable

_log = logging.getLogger("ak.thread_runner")


class ThreadRunner:
    """
    Runs Task instances concurrently, each as task.execution_function(task.item), and reacts to
    each completion in turn.

    Each Task gets its own threading.Thread (instead of a ThreadPoolExecutor worker), so a
    finished task's OS thread is torn down and reclaimed immediately rather than lingering
    idle until every task in the batch, including any that never finish, has completed.
    """

    shutdown_event: threading.Event = threading.Event()

    @dataclass(eq=False)
    class Task:
        execution_function: Callable
        thread_name: str
        item: Any = None
        stop_task_on_failure: bool = True
        stop_all_on_failure: bool = False
        graceful: bool = False
        awaited_on_shutdown: bool = True

        def __post_init__(self) -> None:
            if self.stop_all_on_failure and not self.stop_task_on_failure:
                raise ValueError("stop_all_on_failure=True requires stop_task_on_failure=True")
            if self.graceful and not self.stop_all_on_failure:
                raise ValueError("graceful=True requires stop_all_on_failure=True")

    @staticmethod
    def run(tasks: list[Task], max_workers: int | None = None) -> dict[Task, Any]:
        if not tasks:
            return {}

        semaphore = threading.Semaphore(max_workers or len(tasks))
        completions: Queue = Queue()  # Thread-safe mailbox every worker thread reports its completion to.

        def _target(task: "ThreadRunner.Task") -> None:
            args = () if task.item is None else (task.item,)
            with semaphore:
                try:
                    result = task.execution_function(*args)
                except Exception as exc:
                    completions.put((task, None, exc))
                else:
                    completions.put((task, result, None))
            # the thread ends itself once execution_function returns (or raises), and Python/the OS reclaim it.

        # daemon=True: without this, the interpreter would wait for every non-daemon thread before
        # exiting, which would hang forever behind a never-ending task. Daemon threads are abandoned instead.
        threads = [threading.Thread(target=_target, args=(task,), name=task.thread_name, daemon=True) for task in tasks]
        for thread in threads:
            thread.start()

        results: dict[ThreadRunner.Task, Any] = {}
        pending = {task for task in tasks if task.awaited_on_shutdown}
        while pending:
            task, result, exc = completions.get()  # blocks until the next task (in true completion order) reports in
            if exc is not None:
                if task.stop_task_on_failure:
                    _log.exception(f"[{task.thread_name}] raised unexpectedly", exc_info=exc)
                    if task.stop_all_on_failure:
                        if task.graceful:
                            _log.debug(f"[{task.thread_name}] gracefully stopping all")
                            ThreadRunner.shutdown_event.set()
                        else:
                            _log.debug(f"[{task.thread_name}] stopping all processes")
                            logging.shutdown()
                            os._exit(1)
                else:
                    _log.debug(f"[{task.thread_name}] raised (stop_task_on_failure=False, ignoring)")
            else:
                results[task] = result
                _log.debug(f"[{task.thread_name}] completed")
            pending.discard(task)

        if ThreadRunner.shutdown_event.is_set():
            logging.shutdown()
            os._exit(1)

        return results
