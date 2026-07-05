import threading
import time

import pytest

from agentkernel.deployment.common.thread_runner import ThreadRunner


class TestTaskValidation:
    def test_stop_all_on_failure_requires_stop_task_on_failure(self):
        with pytest.raises(ValueError):
            ThreadRunner.Task(
                execution_function=lambda: None,
                thread_name="t",
                stop_task_on_failure=False,
                stop_all_on_failure=True,
            )

    def test_default_flags(self):
        task = ThreadRunner.Task(execution_function=lambda: None, thread_name="t")
        assert task.stop_task_on_failure is True
        assert task.stop_all_on_failure is False


class TestRun:
    def test_empty_task_list_returns_immediately(self):
        ThreadRunner.run([])  # should not raise or block

    def test_runs_all_tasks_to_completion(self):
        results = []
        lock = threading.Lock()

        def make_fn(value):
            def fn():
                with lock:
                    results.append(value)

            return fn

        tasks = [ThreadRunner.Task(execution_function=make_fn(i), thread_name=f"t{i}") for i in range(5)]
        ThreadRunner.run(tasks)
        assert sorted(results) == [0, 1, 2, 3, 4]

    def test_passes_item_to_execution_function(self):
        seen = []
        task = ThreadRunner.Task(
            execution_function=lambda item: seen.append(item),
            thread_name="t",
            item="hello",
        )
        ThreadRunner.run([task])
        assert seen == ["hello"]

    def test_thread_name_is_set_on_os_thread(self):
        captured = {}

        def fn():
            captured["name"] = threading.current_thread().name

        task = ThreadRunner.Task(execution_function=fn, thread_name="my-thread")
        ThreadRunner.run([task])
        assert captured["name"] == "my-thread"

    def test_task_thread_is_daemon(self):
        """Task threads must be daemon so a never-ending one can't block process/interpreter
        shutdown when sys.exit(1) is raised elsewhere on stop_all_on_failure."""
        captured = {}

        def fn():
            captured["is_daemon"] = threading.current_thread().daemon

        task = ThreadRunner.Task(execution_function=fn, thread_name="t")
        ThreadRunner.run([task])
        assert captured["is_daemon"] is True

    def test_finished_task_thread_does_not_linger_alive(self):
        """A finished task's thread must not still be alive once run() has processed
        its completion, even while another task is still running indefinitely."""
        finished_thread_name = {}
        never_finishes = threading.Event()

        def fast_fn():
            finished_thread_name["name"] = threading.current_thread().name

        def slow_fn():
            never_finishes.wait(timeout=5)

        tasks = [
            ThreadRunner.Task(execution_function=fast_fn, thread_name="fast"),
            ThreadRunner.Task(execution_function=slow_fn, thread_name="slow"),
        ]

        result_holder = {}

        def run_in_background():
            ThreadRunner.run(tasks)
            result_holder["done"] = True

        runner_thread = threading.Thread(target=run_in_background)
        runner_thread.start()

        # Give the fast task time to complete and be reclaimed while the slow task
        # is still running (run() itself is still blocked on the slow task).
        deadline = time.time() + 5
        while "name" not in finished_thread_name and time.time() < deadline:
            time.sleep(0.01)

        # Poll until the fast thread is no longer alive — it should be reclaimed
        # promptly, independent of the still-running slow task.
        fast_name = finished_thread_name["name"]
        deadline = time.time() + 5
        fast_still_alive = True
        while time.time() < deadline:
            fast_still_alive = any(t.name == fast_name and t.is_alive() for t in threading.enumerate())
            if not fast_still_alive:
                break
            time.sleep(0.01)

        assert not fast_still_alive, "fast task's thread lingered after completion"
        assert "done" not in result_holder, "run() should still be blocked on the slow task"

        never_finishes.set()
        runner_thread.join(timeout=5)
        assert result_holder.get("done") is True

    def test_stop_all_on_failure_exits_immediately_without_waiting_on_never_ending_task(self, monkeypatch):
        exit_called = threading.Event()
        exit_code = {}

        def fake_exit(code):
            exit_code["code"] = code
            exit_called.set()

        monkeypatch.setattr("agentkernel.deployment.common.thread_runner.os._exit", fake_exit)

        never_finishes = threading.Event()

        def slow_fn():
            never_finishes.wait(timeout=10)

        def crashing_fn():
            time.sleep(0.05)
            raise RuntimeError("boom")

        tasks = [
            ThreadRunner.Task(execution_function=slow_fn, thread_name="slow"),
            ThreadRunner.Task(
                execution_function=crashing_fn,
                thread_name="crasher",
                stop_task_on_failure=True,
                stop_all_on_failure=True,
            ),
        ]

        runner_thread = threading.Thread(target=ThreadRunner.run, args=(tasks,))
        runner_thread.start()

        assert exit_called.wait(timeout=5), "sys.exit was not called promptly on crash"
        assert exit_code["code"] == 1

        never_finishes.set()
        runner_thread.join(timeout=5)

    def test_stop_task_on_failure_false_ignores_exception(self):
        def crashing_fn():
            raise RuntimeError("boom")

        task = ThreadRunner.Task(
            execution_function=crashing_fn,
            thread_name="t",
            stop_task_on_failure=False,
        )
        ThreadRunner.run([task])  # should not raise
