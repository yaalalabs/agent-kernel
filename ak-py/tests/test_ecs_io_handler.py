from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentkernel.core.config import AKConfig, _ExecutionConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.containerized.ecs_io_handler import ECSIOHandler
from agentkernel.deployment.common import ThreadRunner
from agentkernel.identity import IdentityProviderFactory


def _set_mode(monkeypatch, mode, message_type=None):
    monkeypatch.setattr(ECSIOHandler, "_config", SimpleNamespace(execution=_ExecutionConfig(mode=mode, message_type=message_type)))


def _set_identity(monkeypatch, provider):
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))


@pytest.fixture(autouse=True)
def _stub_thread_runner(monkeypatch):
    """Never actually start peer threads: run_api() would call uvicorn.run()/poll loops for real."""
    monkeypatch.setattr(ThreadRunner, "run", MagicMock())


def test_rest_mode_starts_the_api_and_consumer_threads(monkeypatch):
    """Authentication is the identity dependency every REST route already carries: nothing is bound here."""
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC)
    monkeypatch.setattr("agentkernel.deployment.aws.containerized.core.api.rest_api.AWSRestAPI", MagicMock())

    ECSIOHandler.run()

    tasks = ThreadRunner.run.call_args.kwargs["tasks"]
    assert [task.thread_name for task in tasks] == ["rest-api", "output-queue-consumer"]


def test_websocket_mode_requires_an_identity_block(monkeypatch):
    """$connect authenticates through the provider, so without one the WebSocket API cannot be served."""
    _set_mode(monkeypatch, ExecutionMode.ASYNC)
    _set_identity(monkeypatch, None)

    with pytest.raises(AKConfigError, match="identity block"):
        ECSIOHandler.run()

    ThreadRunner.run.assert_not_called()


def test_async_delta_requires_an_identity_block(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.ASYNC, "delta")
    _set_identity(monkeypatch, None)

    with pytest.raises(AKConfigError, match="identity block"):
        ECSIOHandler.run()

    ThreadRunner.run.assert_not_called()


def test_websocket_mode_with_an_identity_block_serves_the_websocket_api(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.ASYNC)
    _set_identity(monkeypatch, MagicMock())
    fake_ws_api = MagicMock()
    monkeypatch.setattr("agentkernel.deployment.aws.containerized.core.api.websocket_api.AWSWebsocketAPI", fake_ws_api)
    extra = MagicMock()

    ECSIOHandler.run(handlers=[extra])
    tasks = ThreadRunner.run.call_args.kwargs["tasks"]
    tasks[0].execution_function()

    fake_ws_api.run.assert_called_once_with(handlers=[extra])


def test_rest_sync_delta_is_refused_before_any_thread_starts(monkeypatch):
    """ECSQueueRequestHandler waits for one stored record: it has no SSE route to serve chunks."""
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC, "delta")

    with pytest.raises(AKConfigError, match="rest_sync with message_type delta"):
        ECSIOHandler.run()

    ThreadRunner.run.assert_not_called()


@pytest.mark.parametrize("env", [{"AK_A2A__ENABLED": "true"}, {"AK_MCP__ENABLED": "true", "AK_MCP__EXPOSE_AGENTS": "true"}])
def test_a2a_or_agent_mcp_is_refused_before_any_thread_starts(monkeypatch, env):
    """ECS has no queue-mode A2A/MCP yet (#780 decision 2): refused here, not inside the rest-api thread."""
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    AKConfig._reset()
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC)
    try:
        with pytest.raises(AKConfigError, match="IOHandler.run"):
            ECSIOHandler.run()
    finally:
        # Leave no A2A/MCP-enabled config cached for later tests.
        for name in env:
            monkeypatch.delenv(name)
        AKConfig._reset()

    ThreadRunner.run.assert_not_called()
