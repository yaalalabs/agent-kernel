import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from agentkernel.core.config import _ExecutionConfig
from agentkernel.core.model import ExecutionMode
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.core import stream_server
from agentkernel.deployment.aws.serverless.core.paths import LambdaPaths
from agentkernel.deployment.aws.serverless.core.stream_server import (
    LambdaChatPathMiddleware,
    LambdaStreamGuard,
    LambdaStreamServer,
)

ENV = {"API_BASE_PATH": "api", "API_VERSION": "v1", "AGENT_ENDPOINT": "chat"}


def _config(mode=ExecutionMode.REST_SYNC, message_type="delta"):
    config = MagicMock()
    config.execution = _ExecutionConfig(mode=mode, message_type=message_type)
    return config


@pytest.fixture
def env(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def sqs_transport():
    with patch.object(stream_server.QueueTransportFactory, "resolve_type", return_value="sqs"):
        yield


@pytest.fixture
def deployment_ok():
    with patch.object(stream_server.IOHandler, "check_deployment") as check:
        yield check


class TestLambdaPaths:
    def test_from_env_builds_the_prefix_and_chat_path(self, env):
        paths = LambdaPaths.from_env()

        assert (paths.base_path, paths.chat_path) == ("/api/v1", "/api/v1/chat")

    def test_from_env_is_none_when_a_name_is_unset(self, env, monkeypatch):
        monkeypatch.delenv("AGENT_ENDPOINT")

        assert LambdaPaths.from_env() is None
        assert LambdaPaths.missing_env() == ["AGENT_ENDPOINT"]


class TestLambdaStreamGuard:
    @pytest.mark.parametrize(
        "mode, message_type",
        [(ExecutionMode.REST_SYNC, "complete"), (ExecutionMode.ASYNC, "delta"), (ExecutionMode.REST_ASYNC, "complete")],
    )
    def test_refuses_a_mode_that_is_not_sse(self, mode, message_type, env, sqs_transport, deployment_ok):
        with pytest.raises(AKConfigError, match="SSE"):
            LambdaStreamGuard().check(_config(mode, message_type))

    def test_refuses_a_transport_that_is_not_sqs(self, env, deployment_ok):
        with patch.object(stream_server.QueueTransportFactory, "resolve_type", return_value="in_memory"):
            with pytest.raises(AKConfigError, match="sqs queue transport"):
                LambdaStreamGuard().check(_config())

    @pytest.mark.parametrize("name", list(ENV))
    def test_refuses_a_missing_base_path_name(self, name, env, monkeypatch, sqs_transport, deployment_ok):
        monkeypatch.delenv(name)

        with pytest.raises(AKConfigError, match=name):
            LambdaStreamGuard().check(_config())

    def test_the_mode_error_wins_over_a_later_one(self, sqs_transport, deployment_ok):
        with pytest.raises(AKConfigError, match="SSE"):
            LambdaStreamGuard().check(_config(ExecutionMode.REST_SYNC, "complete"))

    def test_runs_the_shared_topology_checks_without_pod_push(self, env, sqs_transport, deployment_ok):
        config = _config()

        paths = LambdaStreamGuard().check(config)

        deployment_ok.assert_called_once_with("sqs", config, pod_push=False)
        assert paths.chat_path == "/api/v1/chat"


class TestLambdaChatPathMiddleware:
    @pytest.fixture
    def client(self):
        async def echo(request: Request):
            return PlainTextResponse(request.scope["path"])

        paths = ["/api/v1/chat", "/api/v1/agents", "/health", "/api/v1/a2a/x", "/v2/api/talk"]
        app = Starlette(routes=[Route(path, echo, methods=["GET", "POST"]) for path in paths])
        wrapped = LambdaChatPathMiddleware(app, LambdaPaths("/v2/api", "/v2/api/talk"))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://t")

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/v2/api/talk", "/api/v1/chat"),
            ("/v2/api/talk/", "/api/v1/chat"),
            ("/api/v1/agents", "/api/v1/agents"),
            ("/health", "/health"),
            ("/api/v1/a2a/x", "/api/v1/a2a/x"),
        ],
    )
    @pytest.mark.asyncio
    async def test_only_the_chat_path_is_rewritten(self, client, path, expected):
        response = await client.post(path)

        assert response.text == expected

    @pytest.mark.asyncio
    async def test_a_non_http_scope_passes_unchanged(self):
        seen = {}

        async def app(scope, receive, send):
            seen.update(scope)

        wrapped = LambdaChatPathMiddleware(app, LambdaPaths("/api/v1", "/api/v1/chat"))
        await wrapped({"type": "lifespan"}, None, None)

        assert seen == {"type": "lifespan"}


class TestLambdaStreamServer:
    def test_the_guard_runs_before_the_app_is_built(self):
        with (
            patch.object(stream_server.AKConfig, "get"),
            patch.object(LambdaStreamGuard, "check", side_effect=AKConfigError("refused")),
            patch.object(stream_server.RESTAPI, "build_app", side_effect=AssertionError("built")),
        ):
            with pytest.raises(AKConfigError, match="refused"):
                LambdaStreamServer.build_app()

    def test_handlers_join_the_request_handler(self):
        extra = MagicMock()
        with (
            patch.object(stream_server.AKConfig, "get"),
            patch.object(LambdaStreamGuard, "check", return_value=LambdaPaths("/api/v1", "/api/v1/chat")),
            patch.object(stream_server.RESTAPI, "build_app") as build,
        ):
            app = LambdaStreamServer.build_app([extra])

        handlers = build.call_args.kwargs["handlers"]
        assert isinstance(handlers[0], stream_server.RequestHandler)
        assert handlers[1] is extra
        assert isinstance(app, LambdaChatPathMiddleware)

    def test_run_logs_a_guard_failure_and_re_raises_without_serving(self, caplog):
        with (
            patch.object(stream_server.AKConfig, "get"),
            patch.object(LambdaStreamGuard, "check", side_effect=AKConfigError("refused")),
            patch.object(stream_server.uvicorn, "Server") as server,
        ):
            with caplog.at_level(logging.ERROR, logger="ak.aws.lambda.stream"):
                with pytest.raises(AKConfigError):
                    LambdaStreamServer.run()

        assert "refused to start" in caplog.text
        server.assert_not_called()

    def test_run_serves_the_app_on_the_configured_port(self):
        config = MagicMock()
        config.api.host, config.api.port = "0.0.0.0", 8000
        with (
            patch.object(stream_server.AKConfig, "get", return_value=config),
            patch.object(LambdaStreamServer, "build_app", return_value="app"),
            patch.object(stream_server.uvicorn, "Config") as uv_config,
            patch.object(stream_server.uvicorn, "Server") as server,
        ):
            LambdaStreamServer.run()

        uv_config.assert_called_once_with(app="app", host="0.0.0.0", port=8000)
        server.return_value.run.assert_called_once()
