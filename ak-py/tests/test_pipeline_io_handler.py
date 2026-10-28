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
from fastapi import APIRouter

from agentkernel.api.handler import RESTRequestHandler
from agentkernel.core.config import AKConfig, _ExecutionConfig, _ResponseStoreConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.pipeline.io_handler import IOHandler
from agentkernel.pipeline.request_handler import RequestHandler
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


def _cfg(mode=None, response_store_type=None, push_auth_token=None, message_type=None):
    class _WebSocketAPI:
        pass

    _WebSocketAPI.push_auth_token = push_auth_token

    class _Cfg:
        websocket_api = _WebSocketAPI
        execution = _ExecutionConfig(
            mode=mode,
            message_type=message_type,
            response_store=_ResponseStoreConfig(type=response_store_type) if response_store_type is not None else None,
        )

        class api:
            host = "127.0.0.1"
            port = 8000
            max_file_size = 10 * 1024 * 1024

    return _Cfg


def _store(chunk_capable: bool) -> MagicMock:
    store = MagicMock()
    store.supports_chunk_streaming.return_value = chunk_capable
    return store


class TestTopologyValidation:
    def test_async_on_in_memory_without_validator_rejected(self):
        with pytest.raises(AKConfigError, match="auth_validator"):
            IOHandler._validate_topology("in_memory", _cfg(ExecutionMode.ASYNC))

    def test_async_delta_on_in_memory_without_validator_rejected(self):
        with pytest.raises(AKConfigError, match="auth_validator"):
            IOHandler._validate_topology("in_memory", _cfg(ExecutionMode.ASYNC, message_type="delta"))

    def test_async_on_in_memory_with_validator_passes(self):
        IOHandler._validate_topology("in_memory", _cfg(ExecutionMode.ASYNC), auth_validator=MagicMock())

    def test_websocket_modes_over_broker_need_no_validator_here(self):
        # Broker topologies authenticate at the standalone gateway, not in this process.
        IOHandler._validate_topology("kafka", _cfg(ExecutionMode.ASYNC, response_store_type="redis", push_auth_token="s3cret"))
        IOHandler._validate_topology("nats", _cfg(ExecutionMode.ASYNC, response_store_type="redis", push_auth_token="s3cret", message_type="delta"))

    def test_websocket_modes_over_broker_without_push_token_rejected(self):
        with pytest.raises(AKConfigError, match="push_auth_token"):
            IOHandler._validate_topology("kafka", _cfg(ExecutionMode.ASYNC, response_store_type="redis"))

    def test_broker_without_shared_response_store_rejected(self):
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology("sqs", _cfg(ExecutionMode.REST_SYNC))

    def test_broker_default_mode_without_shared_response_store_rejected(self):
        # An unset mode runs as REST_SYNC through the pipeline, so it needs the shared store too.
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology("sqs", _cfg())

    def test_broker_with_shared_response_store_passes(self):
        IOHandler._validate_topology("sqs", _cfg(ExecutionMode.REST_SYNC, response_store_type="redis"))

    def test_websocket_modes_over_broker_need_no_response_store(self):
        # WebSocket modes push replies to the gateway pods; the response store is never touched.
        IOHandler._validate_topology("kafka", _cfg(ExecutionMode.ASYNC, push_auth_token="s3cret"))
        IOHandler._validate_topology(
            "nats", _cfg(ExecutionMode.ASYNC, response_store_type="in_memory", push_auth_token="s3cret", message_type="delta")
        )

    def test_in_memory_topology_passes(self):
        IOHandler._validate_topology("in_memory", _cfg(ExecutionMode.REST_SYNC, message_type="delta"))

    def test_sse_over_broker_with_a_store_that_cannot_stream_chunks_rejected(self, monkeypatch):
        monkeypatch.setattr("agentkernel.pipeline.io_handler.ResponseStoreFactory.create", lambda: _store(chunk_capable=False))
        with pytest.raises(AKConfigError, match="rest_sync with message_type delta"):
            IOHandler._validate_topology("nats", _cfg(ExecutionMode.REST_SYNC, response_store_type="redis", message_type="delta"))

    def test_sse_over_broker_with_a_chunk_streaming_store_passes(self, monkeypatch):
        monkeypatch.setattr("agentkernel.pipeline.io_handler.ResponseStoreFactory.create", lambda: _store(chunk_capable=True))
        IOHandler._validate_topology("nats", _cfg(ExecutionMode.REST_SYNC, response_store_type="redis", message_type="delta"))

    def test_sse_over_broker_with_an_in_memory_store_keeps_the_shared_store_error(self):
        with pytest.raises(AKConfigError, match="shared response store"):
            IOHandler._validate_topology("nats", _cfg(ExecutionMode.REST_SYNC, response_store_type="in_memory", message_type="delta"))


class TestRequestHandlerValidation:
    """request_handler replaces the pipeline's queue producer, so it has to be one."""

    def test_a_direct_execution_handler_is_refused(self):
        """Mounting one here would answer every chat request in-process while the runner idles."""

        class DirectHandler(RESTRequestHandler):
            def get_router(self):  # pragma: no cover: never reached, the mount is refused first
                return APIRouter()

        with pytest.raises(AKConfigError, match="DirectHandler is not a pipeline RequestHandler"):
            IOHandler._validate_request_handler(DirectHandler())

    def test_a_request_handler_and_none_are_accepted(self):
        """None keeps the pipeline's own producer; a RequestHandler subclass substitutes for it."""
        IOHandler._validate_request_handler(None)
        IOHandler._validate_request_handler(MagicMock(spec=RequestHandler))


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


class TestRealtimeWebSocket:
    def test_realtime_does_not_co_host_the_websocket_handlers(self, monkeypatch, caplog):
        """Realtime replies go to the stateful edge, never the WS push path, so a validator must not
        mount the WebSocket handlers; it is ignored with the usual warning instead."""
        from agentkernel.pipeline.ws.endpoint import PushEndpointHandler
        from agentkernel.pipeline.ws.handler import PipelineWebSocketHandler

        captured = {}
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_EXECUTION__MODE", "realtime")
        AKConfig._reset()
        monkeypatch.setattr("agentkernel.api.http.RESTAPI.build_app", classmethod(lambda cls, handlers=None: captured.update(handlers=handlers)))
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Server", MagicMock())
        monkeypatch.setattr(IOHandler, "_install_signal_handlers", classmethod(lambda cls, server: None))
        monkeypatch.setattr(ThreadRunner, "run", staticmethod(lambda tasks, max_workers=None, exit_on_shutdown=True: None))

        with caplog.at_level("WARNING"):
            IOHandler.run(auth_validator=MagicMock())

        assert not [h for h in captured["handlers"] if isinstance(h, (PipelineWebSocketHandler, PushEndpointHandler))]
        assert "auth_validator ignored" in caplog.text


class TestMessageTypeTopology:
    """Runner selection and WebSocket co-hosting under the mode / message_type pair (#641)."""

    @staticmethod
    def _run(monkeypatch, mode, message_type=None, auth_validator=None):
        captured = {}
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_EXECUTION__MODE", mode)
        if message_type:
            monkeypatch.setenv("AK_EXECUTION__MESSAGE_TYPE", message_type)
        AKConfig._reset()
        runners = {name: MagicMock(name=name) for name in ("AgentRunner", "StreamAgentRunner", "RealtimeAgentRunner")}
        for name, runner in runners.items():
            monkeypatch.setattr(f"agentkernel.pipeline.io_handler.{name}", runner)
        monkeypatch.setattr("agentkernel.api.http.RESTAPI.build_app", classmethod(lambda cls, handlers=None: captured.update(handlers=handlers)))
        monkeypatch.setattr("agentkernel.pipeline.io_handler.uvicorn.Server", MagicMock())
        monkeypatch.setattr(IOHandler, "_install_signal_handlers", classmethod(lambda cls, server: None))
        monkeypatch.setattr(ThreadRunner, "run", staticmethod(lambda tasks, max_workers=None, exit_on_shutdown=True: None))
        IOHandler.run(auth_validator=auth_validator)
        selected = [name for name, runner in runners.items() if runner.called]
        return captured["handlers"], selected

    def test_rest_sync_delta_streams_without_co_hosting_the_websocket(self, monkeypatch, caplog):
        from agentkernel.pipeline.ws.endpoint import PushEndpointHandler
        from agentkernel.pipeline.ws.handler import PipelineWebSocketHandler

        with caplog.at_level("WARNING"):
            handlers, selected = self._run(monkeypatch, "rest_sync", "delta", auth_validator=MagicMock())

        assert selected == ["StreamAgentRunner"]
        assert not [h for h in handlers if isinstance(h, (PipelineWebSocketHandler, PushEndpointHandler))]
        assert "auth_validator ignored" in caplog.text

    def test_async_delta_selects_the_stream_runner(self, monkeypatch):
        _, selected = self._run(monkeypatch, "async", "delta", auth_validator=MagicMock())
        assert selected == ["StreamAgentRunner"]

    def test_async_complete_selects_the_plain_runner(self, monkeypatch):
        _, selected = self._run(monkeypatch, "async", auth_validator=MagicMock())
        assert selected == ["AgentRunner"]

    def test_realtime_selects_the_realtime_runner_not_the_stream_runner(self, monkeypatch):
        _, selected = self._run(monkeypatch, "realtime")
        assert selected == ["RealtimeAgentRunner"]


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
