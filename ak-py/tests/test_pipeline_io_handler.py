import os
import signal
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest

from agentkernel.core.config import AKConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.io_handler import IOHandler
from agentkernel.pipeline.thread_runner import ThreadRunner


@pytest.fixture(autouse=True)
def _restore_signals_and_shutdown_state():
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for sig, handler in previous.items():
        signal.signal(sig, handler)
    ThreadRunner.shutdown_event.clear()
    ThreadRunner.shutdown_exit_code = 1
    AKConfig._reset()


def _cfg(mode=None, response_store_type=None, push_auth_token=None):
    class _ResponseStore:
        type = response_store_type

    class _WebSocketAPI:
        pass

    _WebSocketAPI.push_auth_token = push_auth_token

    class _Cfg:
        websocket_api = _WebSocketAPI

        class execution:
            response_store = _ResponseStore() if response_store_type is not None else None

        class api:
            host = "127.0.0.1"
            port = 8000
            max_file_size = 10 * 1024 * 1024

    _Cfg.execution.mode = mode
    return _Cfg


class TestTopologyValidation:
    def test_async_on_in_memory_without_validator_rejected(self):
        """The in_memory transport co-hosts the gateway here, so ASYNC needs the validator."""
        with pytest.raises(AKConfigError, match="ASYNC.*auth_validator"):
            IOHandler._validate_topology(ExecutionMode.ASYNC, "in_memory", _cfg(ExecutionMode.ASYNC))

    def test_async_on_in_memory_with_validator_passes(self):
        IOHandler._validate_topology(ExecutionMode.ASYNC, "in_memory", _cfg(ExecutionMode.ASYNC), auth_validator=MagicMock())

    def test_websocket_modes_over_broker_need_no_validator_here(self):
        """On broker transports the gateway is its own process: the IO handler only pushes."""
        IOHandler._validate_topology(ExecutionMode.ASYNC, "kafka", _cfg(ExecutionMode.ASYNC, response_store_type="redis", push_auth_token="s3cret"))
        IOHandler._validate_topology(ExecutionMode.STREAM, "nats", _cfg(ExecutionMode.STREAM, response_store_type="redis", push_auth_token="s3cret"))

    def test_websocket_modes_over_broker_without_push_token_rejected(self):
        with pytest.raises(AKConfigError, match="push_auth_token"):
            IOHandler._validate_topology(ExecutionMode.ASYNC, "kafka", _cfg(ExecutionMode.ASYNC, response_store_type="redis"))

    def test_broker_without_shared_response_store_rejected(self):
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology(ExecutionMode.REST_SYNC, "sqs", _cfg(ExecutionMode.REST_SYNC))

    def test_broker_default_mode_without_shared_response_store_rejected(self):
        """Unset mode is REST_SYNC, so the REST-scoped store requirement applies."""
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology(None, "sqs", _cfg())

    def test_broker_with_shared_response_store_passes(self):
        IOHandler._validate_topology(ExecutionMode.REST_SYNC, "sqs", _cfg(ExecutionMode.REST_SYNC, response_store_type="redis"))

    def test_websocket_modes_over_broker_need_no_response_store(self):
        """The store requirement is REST-scoped (spec §10): WS replies push to the gateway pods."""
        IOHandler._validate_topology(ExecutionMode.ASYNC, "kafka", _cfg(ExecutionMode.ASYNC, push_auth_token="s3cret"))
        IOHandler._validate_topology(
            ExecutionMode.STREAM, "nats", _cfg(ExecutionMode.STREAM, response_store_type="in_memory", push_auth_token="s3cret")
        )

    def test_in_memory_topology_passes(self):
        IOHandler._validate_topology(ExecutionMode.STREAM, "in_memory", _cfg(ExecutionMode.STREAM))


class TestSignalHandlers:
    def test_handlers_installed_and_trigger_graceful_shutdown(self):
        server = MagicMock()
        server.should_exit = False
        IOHandler._install_signal_handlers(server)

        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        assert signal.getsignal(signal.SIGINT) is handler

        handler(signal.SIGTERM, None)
        assert ThreadRunner.shutdown_event.is_set()
        assert ThreadRunner.shutdown_exit_code == 0
        assert server.should_exit is True

    def test_installation_is_skipped_off_the_main_thread(self):
        before = signal.getsignal(signal.SIGTERM)
        thread = threading.Thread(target=lambda: IOHandler._install_signal_handlers(MagicMock()))
        thread.start()
        thread.join()
        assert signal.getsignal(signal.SIGTERM) is before


class TestGracefulDrainExitCode:
    def test_drain_exit_uses_shutdown_exit_code(self, monkeypatch):
        exit_codes = []
        exit_called = threading.Event()

        def fake_exit(code):
            exit_codes.append(code)
            exit_called.set()

        monkeypatch.setattr("agentkernel.pipeline.thread_runner.os._exit", fake_exit)

        # A signal-initiated stop: exit code set to 0 and the event set before the drain ends.
        ThreadRunner.shutdown_exit_code = 0
        ThreadRunner.shutdown_event.set()
        ThreadRunner.run(tasks=[ThreadRunner.Task(execution_function=lambda: None, thread_name="noop")])

        assert exit_called.wait(timeout=5)
        assert exit_codes == [0]


_SIGTERM_SCRIPT = "from agentkernel.pipeline.io_handler import IOHandler; IOHandler.run()"


class TestSigtermEndToEnd:
    def test_sigterm_stops_the_single_process_pipeline_with_exit_zero(self):
        """The container regression test: SIGTERM must terminate the whole pipeline process
        promptly and cleanly (exit code 0), the way uvicorn-on-main-thread used to."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        env = {
            **os.environ,
            "AK_CONFIG_PATH_OVERRIDE": "/nonexistent/config.yaml",
            "AK_API__PORT": str(port),
        }
        proc = subprocess.Popen([sys.executable, "-c", _SIGTERM_SCRIPT], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail(f"pipeline process died during startup:\n{proc.stdout.read()}")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                pytest.fail("pipeline REST API never became healthy")

            proc.send_signal(signal.SIGTERM)
            return_code = proc.wait(timeout=15)
            assert return_code == 0, f"expected clean exit 0 on SIGTERM, got {return_code}:\n{proc.stdout.read()}"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


class TestPollerCoHosting:
    """Where an integration poller runs, per transport (spec #524 §7)."""

    @staticmethod
    def _capture_tasks(monkeypatch, transport_type):
        """Run IOHandler.run far enough to see the task list, without serving anything."""
        captured = {}

        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        if transport_type != "in_memory":
            # A real broker topology: its own queues block and a shared response store.
            monkeypatch.setenv("AK_EXECUTION__QUEUES__TYPE", transport_type)
            monkeypatch.setenv("AK_EXECUTION__QUEUES__INPUT__URL", "https://sqs.local/input")
            monkeypatch.setenv("AK_EXECUTION__QUEUES__OUTPUT__URL", "https://sqs.local/output")
            monkeypatch.setenv("AK_EXECUTION__RESPONSE_STORE__TYPE", "redis")
        AKConfig._reset()

        monkeypatch.setattr("agentkernel.api.http.RESTAPI.build_app", classmethod(lambda cls, handlers=None: MagicMock()))
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Server", MagicMock())
        monkeypatch.setattr(IOHandler, "_install_signal_handlers", classmethod(lambda cls, server: None))
        monkeypatch.setattr(ThreadRunner, "run", staticmethod(lambda tasks, max_workers=None, exit_on_shutdown=True: captured.update(tasks=tasks)))
        return captured

    def _poller(self):
        poller = MagicMock()
        poller.adapter.name = "gmail"
        return poller

    def test_a_poller_is_co_hosted_on_the_in_memory_transport(self, monkeypatch):
        captured = self._capture_tasks(monkeypatch, "in_memory")
        poller = self._poller()

        IOHandler.run(pollers=[poller])

        names = [task.thread_name for task in captured["tasks"]]
        assert "poller-gmail" in names
        [task] = [task for task in captured["tasks"] if task.thread_name == "poller-gmail"]
        task.execution_function()
        # exit_on_shutdown=False: the outer runner owns the process exit, as for every peer loop.
        poller.start.assert_called_once_with(exit_on_shutdown=False)

    def test_pollers_are_not_started_on_a_broker_transport(self, monkeypatch, caplog):
        captured = self._capture_tasks(monkeypatch, "sqs")

        with caplog.at_level("WARNING"):
            IOHandler.run(pollers=[self._poller()])

        assert not [task for task in captured["tasks"] if task.thread_name.startswith("poller-")]
        # Poller lifetime must not track this request-bound tier's replica count.
        assert "PollerRunner.run" in caplog.text


class TestNestedDrainCoordination:
    def test_thread_runner_returns_instead_of_exiting_when_exit_on_shutdown_false(self, monkeypatch):
        exit_called = threading.Event()
        monkeypatch.setattr("agentkernel.pipeline.thread_runner.os._exit", lambda code: exit_called.set())

        ThreadRunner.shutdown_event.set()
        results = ThreadRunner.run(
            tasks=[ThreadRunner.Task(execution_function=lambda: "done", thread_name="noop")],
            exit_on_shutdown=False,
        )

        assert not exit_called.is_set(), "a nested runner must return, not end the process"
        assert list(results.values()) == ["done"]
