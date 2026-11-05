from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentkernel.core.config import AKConfig, _ExecutionConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.containerized.ecs_io_handler import ECSIOHandler
from agentkernel.deployment.common import ThreadRunner


def _set_mode(monkeypatch, mode, message_type=None):
    monkeypatch.setattr(ECSIOHandler, "_config", SimpleNamespace(execution=_ExecutionConfig(mode=mode, message_type=message_type)))


@pytest.fixture(autouse=True)
def _stub_thread_runner(monkeypatch):
    """Never actually start peer threads: run_api() would call uvicorn.run()/poll loops for real."""
    monkeypatch.setattr(ThreadRunner, "run", MagicMock())


def test_rest_mode_with_auth_validator_binds_it_via_add_auth_handlers(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC)
    fake_rest_api = MagicMock()
    monkeypatch.setattr("agentkernel.deployment.aws.containerized.core.api.rest_api.AWSRestAPI", fake_rest_api)

    validator = MagicMock()
    ECSIOHandler.run(auth_validator=validator)

    fake_rest_api.add_auth_handlers.assert_called_once_with(auth_validators=[validator])


def test_rest_mode_without_auth_validator_skips_binding(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC)
    fake_rest_api = MagicMock()
    monkeypatch.setattr("agentkernel.deployment.aws.containerized.core.api.rest_api.AWSRestAPI", fake_rest_api)

    ECSIOHandler.run()

    fake_rest_api.add_auth_handlers.assert_not_called()


def test_websocket_mode_requires_auth_validator(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.ASYNC)

    with pytest.raises(ValueError, match="auth_validator is required"):
        ECSIOHandler.run()


def test_rest_sync_delta_is_refused_before_any_thread_starts(monkeypatch):
    """ECSQueueRequestHandler waits for one stored record: it has no SSE route to serve chunks."""
    _set_mode(monkeypatch, ExecutionMode.REST_SYNC, "delta")

    with pytest.raises(AKConfigError, match="rest_sync with message_type delta"):
        ECSIOHandler.run(auth_validator=MagicMock())

    ThreadRunner.run.assert_not_called()


def test_async_delta_requires_auth_validator(monkeypatch):
    _set_mode(monkeypatch, ExecutionMode.ASYNC, "delta")

    with pytest.raises(ValueError, match="auth_validator is required"):
        ECSIOHandler.run()


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
