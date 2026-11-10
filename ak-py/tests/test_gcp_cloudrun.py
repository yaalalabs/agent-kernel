"""CloudRun.run (spec #886 §6): the Cloud Run entry point always starts the pipeline's IOHandler.

On the default in_memory transport that is the single-process topology RESTAPI.run() booted
before; on a broker transport it is the queue-mode edge. Modes whose replies are pushed to a
specific instance are refused on a broker transport, because Cloud Run instances are not
individually addressable.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from agentkernel.core.config import _ExecutionConfig, _QueuesConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.gcp import CloudRun, CloudRunAgentRunner
from agentkernel.pipeline.agent_runner import AgentRunner, StreamAgentRunner
from agentkernel.pipeline.envelope import QueueName


@pytest.fixture
def calls(monkeypatch):
    """Record what CloudRun hands to IOHandler and RESTAPI, in order, without serving anything."""
    recorded: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "agentkernel.pipeline.io_handler.IOHandler.run",
        classmethod(lambda cls, **kwargs: recorded.append(("io_handler", kwargs))),
    )
    monkeypatch.setattr("agentkernel.api.http.RESTAPI.add", classmethod(lambda cls, router: recorded.append(("add", router))))
    # The router is class-level: give each test its own so registered routes do not leak.
    monkeypatch.setattr(CloudRun, "_router", APIRouter())
    return recorded


def _configure(monkeypatch, transport: str, mode: ExecutionMode | None = None) -> None:
    config = SimpleNamespace(execution=_ExecutionConfig(mode=mode, queues=_QueuesConfig(type=transport)))
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))


def test_in_memory_with_no_arguments_starts_the_single_process_pipeline(monkeypatch, calls):
    """Exactly what RESTAPI.run() did before: it handed this case to IOHandler.run()."""
    _configure(monkeypatch, "in_memory")

    CloudRun.run()

    assert calls == [("io_handler", {"handlers": None})]


@pytest.mark.parametrize("mode", [None, ExecutionMode.REST_SYNC, ExecutionMode.REST_ASYNC])
def test_a_broker_transport_starts_the_queue_mode_edge(monkeypatch, calls, mode):
    _configure(monkeypatch, "pubsub", mode)

    CloudRun.run()

    assert calls == [("io_handler", {"handlers": None})]


def test_handlers_are_passed_through_unchanged(monkeypatch, calls):
    _configure(monkeypatch, "pubsub")
    handlers = [object(), object()]

    CloudRun.run(handlers=handlers)

    assert calls[-1][1]["handlers"] is handlers


def test_registered_routes_are_added_before_the_server_starts(monkeypatch, calls):
    _configure(monkeypatch, "pubsub")

    @CloudRun.register("/custom", method="GET")
    def custom() -> dict[str, str]:
        return {"status": "ok"}

    CloudRun.run()

    assert [name for name, _ in calls] == ["add", "io_handler"]
    assert calls[0][1] is CloudRun._router


def test_no_registered_routes_adds_nothing(monkeypatch, calls):
    _configure(monkeypatch, "in_memory")
    CloudRun.run()
    assert [name for name, _ in calls] == ["io_handler"]


@pytest.mark.parametrize("mode", [ExecutionMode.ASYNC, ExecutionMode.REALTIME])
def test_socket_modes_are_refused_on_a_broker_transport_before_anything_starts(monkeypatch, calls, mode):
    _configure(monkeypatch, "pubsub", mode)

    with pytest.raises(AKConfigError, match=f"execution.mode {mode.value} is not supported on Cloud Run.*not individually addressable"):
        CloudRun.run()

    assert calls == []


def test_socket_modes_on_in_memory_are_left_to_io_handler(monkeypatch, calls):
    """One process holds everything there; IOHandler applies its own validator check."""
    _configure(monkeypatch, "in_memory", ExecutionMode.ASYNC)

    CloudRun.run()

    assert calls == [("io_handler", {"handlers": None})]


def test_importing_the_gcp_package_does_not_load_the_pipeline():
    """The pipeline is imported when the server starts, not when an app imports CloudRun."""
    probe = "import sys, agentkernel.gcp; print('agentkernel.pipeline.io_handler' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert result.stdout.strip().splitlines()[-1] == "False"


class TestCloudRunAgentRunner:
    """The runner side on Cloud Run: a service that Pub/Sub pushes each request to (spec #886 §6)."""

    class _Receiver:
        def __init__(self, status=204, error=None):
            self.bodies, self._status, self._error = [], status, error

        def handle(self, body):
            self.bodies.append(body)
            if self._error:
                raise self._error
            return self._status

    @pytest.mark.parametrize("status", [204, 500, 400])
    def test_the_push_route_answers_with_the_receivers_status(self, status):
        receiver = self._Receiver(status)
        client = TestClient(CloudRunAgentRunner.build_app(receiver))

        response = client.post("/pubsub/push", json={"subscription": "s", "message": {"messageId": "m1"}})

        assert response.status_code == status
        assert receiver.bodies == [{"subscription": "s", "message": {"messageId": "m1"}}]

    def test_a_receiver_error_is_answered_with_a_nack(self):
        client = TestClient(CloudRunAgentRunner.build_app(self._Receiver(error=ConnectionError("bookkeeping down"))))
        assert client.post("/pubsub/push", json={}).status_code == 500, "a nack, so Pub/Sub redelivers"

    def test_the_health_route_serves_the_startup_probe(self):
        assert TestClient(CloudRunAgentRunner.build_app(self._Receiver())).get("/health").json() == {"status": "ok"}

    @staticmethod
    def _configure_runner(monkeypatch, transport: str, mode=None, message_type=None, session_type="redis"):
        config = SimpleNamespace(
            execution=_ExecutionConfig(
                mode=mode, message_type=message_type, queues=_QueuesConfig(type=transport, pubsub={}, input={"max_receive_count": 4})
            ),
            api=SimpleNamespace(host="127.0.0.1", port=8123),
            session=SimpleNamespace(type=session_type),
        )
        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: config))

    @pytest.fixture
    def served(self, monkeypatch):
        """Capture the push receiver the runner builds and the server it would start."""
        captured: dict = {}

        class FakeTransport:
            def create_push_receiver(self, queue, process, on_permanent_failure, max_receive_count):
                captured.update(queue=queue, process=process, on_permanent_failure=on_permanent_failure, max_receive_count=max_receive_count)
                return TestCloudRunAgentRunner._Receiver()

        monkeypatch.setattr("agentkernel.pipeline.transport.base.QueueTransportFactory.create", classmethod(lambda cls, **kw: FakeTransport()))
        monkeypatch.setattr("uvicorn.run", lambda **kwargs: captured.update(server=kwargs))
        return captured

    @pytest.mark.parametrize("message_type, runner_class", [(None, AgentRunner), ("delta", StreamAgentRunner)], ids=["complete", "delta-sse"])
    def test_run_serves_the_input_queue_with_the_runner_the_mode_needs(self, monkeypatch, served, message_type, runner_class):
        self._configure_runner(monkeypatch, "pubsub", ExecutionMode.REST_SYNC, message_type)

        CloudRunAgentRunner.run()

        assert served["queue"] == QueueName.INPUT
        assert served["max_receive_count"] == 4
        assert type(served["process"].__self__) is runner_class
        assert served["on_permanent_failure"].__self__ is served["process"].__self__
        assert (served["server"]["host"], served["server"]["port"]) == ("127.0.0.1", 8123)

    def test_run_refuses_a_transport_that_does_not_push(self, monkeypatch, served):
        self._configure_runner(monkeypatch, "in_memory")
        with pytest.raises(AKConfigError, match="set it to pubsub"):
            CloudRunAgentRunner.run()
        assert served == {}

    @pytest.mark.parametrize("mode", [ExecutionMode.ASYNC, ExecutionMode.REALTIME])
    def test_run_refuses_socket_modes(self, monkeypatch, served, mode):
        self._configure_runner(monkeypatch, "pubsub", mode)
        with pytest.raises(AKConfigError, match="not individually addressable"):
            CloudRunAgentRunner.run()
        assert served == {}

    def test_run_refuses_in_memory_sessions(self, monkeypatch, served):
        self._configure_runner(monkeypatch, "pubsub", session_type="in_memory")
        with pytest.raises(AKConfigError, match="shared session store"):
            CloudRunAgentRunner.run()
        assert served == {}
