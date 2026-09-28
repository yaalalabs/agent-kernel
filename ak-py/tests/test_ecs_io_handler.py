from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentkernel.core.model import ExecutionMode
from agentkernel.deployment.aws.containerized.ecs_io_handler import ECSIOHandler
from agentkernel.deployment.common import ThreadRunner


def _set_mode(monkeypatch, mode):
    monkeypatch.setattr(ECSIOHandler, "_config", SimpleNamespace(execution=SimpleNamespace(mode=mode)))


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
