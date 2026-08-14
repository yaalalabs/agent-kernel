import logging
import os
import signal
import threading
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable, Optional

_log = logging.getLogger("ak.pipeline.thread_runner")


class ThreadRunner:
    """
    Runs Task instances concurrently, each as task.execution_function(task.item), and reacts to
    each completion in turn.

    Each Task gets its own threading.Thread (instead of a ThreadPoolExecutor worker), so a
    finished task's OS thread is torn down and reclaimed immediately rather than lingering
    idle until every task in the batch, including any that never finish, has completed.
    """

    shutdown_event: threading.Event = threading.Event()
    # Exit code used when a graceful drain completes. Failure-initiated shutdowns leave it at 1;
    # an orchestrated stop (the SIGTERM/SIGINT handler below) sets it to 0 first.
    shutdown_exit_code: int = 1

    @classmethod
    def install_shutdown_signal_handlers(cls, logger: logging.Logger, on_shutdown_signal: Optional[Callable[[], None]] = None) -> None:
        """Install SIGTERM/SIGINT handlers that start a graceful drain with exit code 0.

        Required for any pipeline process that runs as a container's PID 1: the kernel drops
        default-disposition signals to PID 1, so without a handler the process never receives
        SIGTERM at all and `docker stop`/pod termination hangs until SIGKILL. The handler sets
        ``shutdown_event`` (consumer loops finish their in-flight work and return) and marks the
        drain exit code 0: an orchestrated stop is not a failure.

        :param logger: Logger the installing component owns; signals are logged on it.
        :param on_shutdown_signal: Optional extra shutdown step run inside the handler (e.g.
            stopping an embedded uvicorn server via ``should_exit``).

        Installation is skipped (with a warning) off the main thread: Python only allows signal
        handler registration on the main thread.
        """
        if threading.current_thread() is not threading.main_thread():
            logger.warning("Not running on the main thread; skipping shutdown signal handlers")
            return

        def _handle_shutdown_signal(signum: int, frame) -> None:
            logger.info(f"Received signal {signum}: shutting down gracefully")
            cls.shutdown_exit_code = 0
            cls.shutdown_event.set()
            if on_shutdown_signal is not None:
                on_shutdown_signal()

        for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(shutdown_signal, _handle_shutdown_signal)

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
    def run(tasks: list[Task], max_workers: int | None = None, exit_on_shutdown: bool = True) -> dict[Task, Any]:
        """
        :param exit_on_shutdown: When True (default), a completed drain with shutdown_event set
            exits the process (os._exit with shutdown_exit_code). Nested runners (a ConsumerLoop
            running inside an IOHandler task) pass False so they return after draining and only
            the outermost runner ends the process, once every nested loop has finished its
            in-flight work.
        """
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

        if ThreadRunner.shutdown_event.is_set() and exit_on_shutdown:
            logging.shutdown()
            os._exit(ThreadRunner.shutdown_exit_code)

        return results
