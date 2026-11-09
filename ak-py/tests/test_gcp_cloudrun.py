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

from agentkernel.core.config import _ExecutionConfig, _QueuesConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.gcp import CloudRun


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
