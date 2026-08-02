import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkernel.api.http import RESTAPI
from agentkernel.auth.handler import AuthValidator, ValidationResult
from agentkernel.core.model import BaseRequest, ExecutionMode
from agentkernel.deployment.aws.containerized.core.api.websocket_api import (
    AWSWebsocketAPI,
    ECSWebSocketRequestHandler,
    ECSWebSocketSystemRequestHandler,
)
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler

def _fake_config():
    """Minimal AKConfig stand-in exposing only what the WS handlers/register read."""
    return SimpleNamespace(
        websocket_api=SimpleNamespace(
            endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
            connection_table=SimpleNamespace(table_name="ak-connections", ttl=3600),
        ),
        execution=SimpleNamespace(mode=mode, queues=SimpleNamespace(input=SimpleNamespace(url=None))),
    )


class _FakeValidator(AuthValidator):
    def validate(self, token, context=None) -> ValidationResult:
        return ValidationResult(is_valid=True, claims={"userId": "u1"})


@pytest.fixture(autouse=True)
def _reset_ws_state(monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _fake_config()))
    AWSWebsocketAPI._ws_custom_routes = {}
    AWSWebsocketAPI._ws_auth_validator = None
    yield
    AWSWebsocketAPI._ws_custom_routes = {}
    AWSWebsocketAPI._ws_auth_validator = None


def _make_handler(custom_routes=None):
    return ECSWebSocketRequestHandler(custom_routes=custom_routes)


def _ctx(handler):
    return handler.WSRouteContext(
        message={"request_id": "r1", "foo": "bar"},
        user_id="u1",
        connection_id="c1",
        endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
    )


async def _invoke(handler, func):
    """Run ``func`` through ``_wrap_custom_route`` with a stubbed context and WS handler.

    :return: (JSONResponse, broadcast mock)
    """
    ctx = _ctx(handler)

    async def _fake_build(request):
        return ctx

    handler.build_route_context = _fake_build
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    endpoint = handler._wrap_custom_route(func)
    response = await endpoint(request=MagicMock())
    return response, ws_mock.broadcast


# Route-name validation (at decoration time)


@pytest.mark.parametrize("route", ["connect", "disconnect", "default"])
def test_register_rejects_reserved_routes(route):
    """Bare names already owned by the system routers (POST /ws/connect etc.) must be rejected —
    registering them would silently be dead code, since those routers are mounted first."""
    with pytest.raises(ValueError, match="already registered"):
        AWSWebsocketAPI.register(route)


@pytest.mark.parametrize("route", ["$connect", "$disconnect", "$default"])
def test_register_rejects_dollar_prefixed_routes_as_invalid_charset(route):
    """`$`-prefixed names aren't valid bare route names regardless of reservation."""
    with pytest.raises(ValueError, match="Invalid WebSocket route name"):
        AWSWebsocketAPI.register(route)


@pytest.mark.parametrize("route", ["foo bar", "foo!", "foo.bar", "status?x", ""])
def test_register_rejects_bad_charset(route):
    with pytest.raises(ValueError):
        AWSWebsocketAPI.register(route)


@pytest.mark.parametrize("route", ["/ws/status", "/status"])
def test_register_rejects_ws_prefixed_path(route):
    with pytest.raises(ValueError, match="bare route name"):
        AWSWebsocketAPI.register(route)


@pytest.mark.parametrize("route", ["status", "health-check", "my_route", "Route123"])
def test_register_accepts_valid_names(route):
    @AWSWebsocketAPI.register(route)
    def handler(ctx):
        return {}

    assert route in AWSWebsocketAPI._ws_custom_routes


def test_register_duplicate_warns_and_keeps_first(caplog):
    @AWSWebsocketAPI.register("status")
    def first(ctx):
        return {"which": "first"}

    with caplog.at_level("WARNING"):

        @AWSWebsocketAPI.register("status")
        def second(ctx):
            return {"which": "second"}

    assert AWSWebsocketAPI._ws_custom_routes["status"] is first
    assert any("already registered" in r.message for r in caplog.records)



# build_route_context: is_chat controls how `message` is parsed



def _fake_request(body: dict):
    request = MagicMock()
    request.headers = {ECSWebSocketRequestHandler.CONNECTION_ID_HEADER: "c1"}
    request.body = AsyncMock(return_value=json.dumps(body).encode())
    return request


@pytest.mark.asyncio
async def test_build_route_context_chat_parses_base_request():
    handler = _make_handler()
    ws_mock = MagicMock()
    ws_mock.get_user_id.return_value = "u1"
    handler.get_websocket_handler = lambda: ws_mock

    request = _fake_request({"route": "chat", "request_id": "r1", "body": {"session_id": "s1", "prompt": "hi"}})
    ctx = await handler.build_route_context(request, is_chat_request=True)

    assert isinstance(ctx.message, BaseRequest)
    assert ctx.message.request_id == "r1"
    assert ctx.message.body.session_id == "s1"


@pytest.mark.asyncio
async def test_build_route_context_custom_route_keeps_raw_dict():
    handler = _make_handler()
    ws_mock = MagicMock()
    ws_mock.get_user_id.return_value = "u1"
    handler.get_websocket_handler = lambda: ws_mock

    raw_body = {"foo": "bar", "nested": {"baz": 1}}
    request = _fake_request(raw_body)
    ctx = await handler.build_route_context(request)

    assert ctx.message == raw_body
    assert not isinstance(ctx.message, BaseRequest)



# _wrap_custom_route behavior



@pytest.mark.asyncio
async def test_wrap_dict_return_broadcasts_and_200():
    handler = _make_handler()

    def func(ctx):
        return {"status": "OK", "user_id": ctx["user_id"]}

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 200
    broadcast.assert_called_once()
    kwargs = broadcast.call_args.kwargs
    assert kwargs["message"] == {"status": "OK", "user_id": "u1"}
    assert kwargs["user_id"] == "u1"
    assert kwargs["message_type"] == AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE


@pytest.mark.asyncio
async def test_wrap_func_receives_message_and_user_id_only():
    handler = _make_handler()
    received = {}

    def func(ctx):
        received.update(ctx)
        return None

    await _invoke(handler, func)

    assert received == {"message": {"request_id": "r1", "foo": "bar"}, "user_id": "u1"}
    assert "connection_id" not in received
    assert "endpoint_url" not in received


@pytest.mark.asyncio
async def test_wrap_async_function_supported():
    handler = _make_handler()

    async def func(ctx):
        return {"ok": True}

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 200
    broadcast.assert_called_once()
    assert broadcast.call_args.kwargs["message"] == {"ok": True}


@pytest.mark.asyncio
async def test_wrap_none_return_no_broadcast_still_200():
    handler = _make_handler()

    def func(ctx):
        return None

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 200
    broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_wrap_ws_route_error_maps_to_status():
    handler = _make_handler()

    def func(ctx):
        raise handler.WSRouteError(403, "forbidden")

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 403
    assert json.loads(response.body)["message"] == "forbidden"
    broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_wrap_generic_exception_broadcasts_error_and_500():
    handler = _make_handler()

    def func(ctx):
        raise RuntimeError("boom")

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 500
    broadcast.assert_called_once()
    assert broadcast.call_args.kwargs["message"]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_wrap_context_resolution_error_maps_to_status():
    handler = _make_handler()
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    async def _fake_build(request):
        raise handler.WSRouteError(401, "no user")

    handler.build_route_context = _fake_build

    def func(ctx):
        return {"never": "called"}

    endpoint = handler._wrap_custom_route(func)
    response = await endpoint(request=MagicMock())

    assert response.status_code == 401
    ws_mock.broadcast.assert_not_called()



# get_router / handler assembly



def test_get_router_emits_post_per_route():
    handler = _make_handler(custom_routes={"status": lambda ctx: {}, "ping": lambda ctx: None})
    router = handler.get_router()

    routes = {route.path: route.methods for route in router.routes}
    assert routes["/ws/chat"] == {"POST"}
    assert routes["/ws/status"] == {"POST"}
    assert routes["/ws/ping"] == {"POST"}


def test_get_router_chat_only_when_no_custom_routes():
    handler = _make_handler()
    router = handler.get_router()
    assert [route.path for route in router.routes] == ["/ws/chat"]


def test_get_default_handlers_builds_two_carrying_all_routes():
    @AWSWebsocketAPI.register("status")
    def status(ctx):
        return {}

    @AWSWebsocketAPI.register("ping")
    def ping(ctx):
        return None

    AWSWebsocketAPI.set_auth_handler(auth_validator=_FakeValidator())
    handlers = AWSWebsocketAPI.get_default_handlers()

    assert len(handlers) == 2
    system, app = handlers
    assert isinstance(system, ECSWebSocketSystemRequestHandler)
    assert isinstance(app, ECSWebSocketRequestHandler)
    assert set(app._custom_routes) == {"status", "ping"}


def test_run_builds_default_handlers(monkeypatch):
    captured = {}

    def fake_run(cls, handlers=None):
        captured["handlers"] = handlers

    monkeypatch.setattr(RESTAPI, "run", classmethod(fake_run))

    @AWSWebsocketAPI.register("status")
    def status(ctx):
        return {}

    AWSWebsocketAPI.set_auth_handler(auth_validator=_FakeValidator())
    AWSWebsocketAPI.run()

    assert len(captured["handlers"]) == 2
    _, app = captured["handlers"]
    assert isinstance(app, ECSWebSocketRequestHandler)
    assert "status" in app._custom_routes


# --------------------------------------------------------------------------------------------------
# STREAM mode: direct (non-queue) chat path
# --------------------------------------------------------------------------------------------------


def _make_async_gen(items):
    async def _gen(req, sse_format=False):
        for item in items:
            yield item

    return _gen


@pytest.mark.asyncio
async def test_process_chat_direct_stream_broadcasts_each_chunk():
    handler = _make_handler()
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    chunks = [
        json.dumps({"delta": "Hello", "done": False}),
        json.dumps({"delta": " world", "done": False}),
        json.dumps({"done": True}),
    ]
    mock_chat_service = MagicMock()
    mock_chat_service.process_stream_chat_async = _make_async_gen(chunks)
    handler.get_chat_service = lambda: mock_chat_service

    from agentkernel.core.model import BaseRunRequest

    body = BaseRunRequest(session_id="s1", prompt="hi")
    response = await handler._process_chat_direct_stream(body, "u1", "https://abc.execute-api.us-east-1.amazonaws.com/prod")

    assert response.status_code == 200
    assert ws_mock.broadcast.call_count == 3
    for call in ws_mock.broadcast.call_args_list:
        assert call.kwargs["message_type"] == AWSWebSocketHandler.MessageType.STREAM_CHUNK
    assert ws_mock.broadcast.call_args_list[0].kwargs["message"] == {"delta": "Hello", "done": False}


@pytest.mark.asyncio
async def test_process_chat_direct_stream_broadcasts_error_chunk_on_exception():
    handler = _make_handler()
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    async def _failing_gen(req, sse_format=False):
        yield json.dumps({"delta": "partial", "done": False})
        raise RuntimeError("boom")

    mock_chat_service = MagicMock()
    mock_chat_service.process_stream_chat_async = _failing_gen
    handler.get_chat_service = lambda: mock_chat_service

    from agentkernel.core.model import BaseRunRequest

    body = BaseRunRequest(session_id="s1", prompt="hi")
    response = await handler._process_chat_direct_stream(body, "u1", "https://abc.execute-api.us-east-1.amazonaws.com/prod")

    assert response.status_code == 500
    assert ws_mock.broadcast.call_count == 2
    error_call = ws_mock.broadcast.call_args_list[-1]
    assert error_call.kwargs["message_type"] == AWSWebSocketHandler.MessageType.STREAM_CHUNK
    assert error_call.kwargs["message"]["error"] == "boom"
    assert error_call.kwargs["message"]["done"] is True
    assert error_call.kwargs["message"]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_handle_chat_stream_mode_routes_to_direct_stream(monkeypatch):
    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _fake_config(mode=ExecutionMode.STREAM)))
    handler = _make_handler()
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    handler.build_route_context = AsyncMock(
        return_value=handler.WSRouteContext(
            message=BaseRequest.from_payload({"request_id": "r1", "body": {"session_id": "s1", "prompt": "hi"}}),
            user_id="u1",
            connection_id="c1",
            endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
        )
    )

    called = {}

    async def _fake_stream(body, user_id, endpoint_url):
        called["invoked"] = True
        return handler.build_success_http_response("ok", user_id=user_id)

    handler._process_chat_direct_stream = _fake_stream

    response = await handler._handle_chat(request=MagicMock())

    assert called.get("invoked") is True
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_handle_chat_queue_mode_unaffected_by_stream_setting(monkeypatch):
    """Regression: queue mode must still enqueue, even when execution.mode is STREAM."""

    def _fake_config_queue_stream():
        cfg = _fake_config(mode=ExecutionMode.STREAM)
        cfg.execution.queues.input.url = "https://sqs.test/input"
        return cfg

    monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _fake_config_queue_stream()))
    handler = _make_handler()

    handler.build_route_context = AsyncMock(
        return_value=handler.WSRouteContext(
            message=BaseRequest.from_payload({"request_id": "r1", "body": {"session_id": "s1", "prompt": "hi"}}),
            user_id="u1",
            connection_id="c1",
            endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
        )
    )

    stream_called = {}
    handler._process_chat_direct_stream = lambda *a, **k: stream_called.setdefault("invoked", True)

    with patch("agentkernel.deployment.aws.containerized.core.api.websocket_api.SQSHandler") as mock_sqs:
        response = await handler._handle_chat(request=MagicMock())

    mock_sqs.send_message_to_input_queue.assert_called_once()
    assert "invoked" not in stream_called
    assert response.status_code == 200
