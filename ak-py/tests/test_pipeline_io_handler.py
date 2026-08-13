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


def _cfg(mode=None, response_store_type=None):
    class _ResponseStore:
        type = response_store_type

    class _Cfg:
        class execution:
            response_store = _ResponseStore() if response_store_type is not None else None

        class api:
            host = "127.0.0.1"
            port = 8000

    _Cfg.execution.mode = mode
    return _Cfg


class TestTopologyValidation:
    def test_async_mode_rejected(self):
        with pytest.raises(AKConfigError, match="ASYNC"):
            IOHandler._validate_topology(ExecutionMode.ASYNC, "in_memory", _cfg(ExecutionMode.ASYNC))

    def test_stream_over_broker_rejected(self):
        with pytest.raises(AKConfigError, match="STREAM"):
            IOHandler._validate_topology(ExecutionMode.STREAM, "kafka", _cfg(ExecutionMode.STREAM))

    def test_broker_without_shared_response_store_rejected(self):
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology(ExecutionMode.REST_SYNC, "sqs", _cfg(ExecutionMode.REST_SYNC))

    def test_broker_with_shared_response_store_passes(self):
        IOHandler._validate_topology(ExecutionMode.REST_SYNC, "sqs", _cfg(ExecutionMode.REST_SYNC, response_store_type="redis"))

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
