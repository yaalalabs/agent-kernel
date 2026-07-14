"""Tests for containerized WebSocket custom-route support.

Covers the ``@AWSWebsocketAPI.register`` decorator (route-name validation and duplicate handling),
``ECSWebSocketRequestHandler._wrap_custom_route`` behavior (dict/None returns, WSRouteError, generic
exceptions, sync + async functions), ``get_router`` emitting ``POST /ws/<route>`` per route, and
``run``/``get_default_handlers`` assembling exactly two handlers.

``AWSWebsocketAPI._ws_custom_routes`` is process-wide class state, so an autouse fixture resets it
between cases (and monkeypatches ``AKConfig.get`` — the register/handler code reads config).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentkernel.api.http import RESTAPI
from agentkernel.auth.handler import AuthValidator, ValidationResult
from agentkernel.deployment.aws.containerized.core.api.websocket_api import (
    AWSWebsocketAPI,
    ECSWebSocketRequestHandler,
    ECSWebSocketSystemRequestHandler,
)
from agentkernel.deployment.aws.core.websocket_service import AWSWebSocketHandler

CHAT_ROUTE = "chat"


def _fake_config():
    """Minimal AKConfig stand-in exposing only what the WS handlers/register read."""
    return SimpleNamespace(
        websocket_api=SimpleNamespace(
            endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
            chat_route=CHAT_ROUTE,
            connection_table=SimpleNamespace(table_name="ak-connections", ttl=3600),
        ),
        execution=SimpleNamespace(queues=SimpleNamespace(input=SimpleNamespace(url=None))),
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
        request=SimpleNamespace(body=None, request_id="r1"),
        user_id="u1",
        connection_id="c1",
        endpoint_url="https://abc.execute-api.us-east-1.amazonaws.com/prod",
    )


async def _invoke(handler, func):
    """Wire ``func`` through ``_wrap_custom_route`` with a stubbed context + WS handler, returning
    (JSONResponse, broadcast mock)."""
    ctx = _ctx(handler)

    async def _fake_build(request):
        return ctx

    handler.build_route_context = _fake_build
    ws_mock = MagicMock()
    handler.get_websocket_handler = lambda: ws_mock

    endpoint = handler._wrap_custom_route(func)
    response = await endpoint(request=MagicMock())
    return response, ws_mock.broadcast


# --------------------------------------------------------------------------------------------------
# Route-name validation (at decoration time)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["$connect", "$disconnect", "$default"])
def test_register_rejects_reserved_routes(route):
    with pytest.raises(ValueError, match="reserved"):
        AWSWebsocketAPI.register(route)


def test_register_rejects_chat_route_collision():
    with pytest.raises(ValueError, match="chat_route"):
        AWSWebsocketAPI.register(CHAT_ROUTE)


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


# --------------------------------------------------------------------------------------------------
# _wrap_custom_route behavior
# --------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_dict_return_broadcasts_and_200():
    handler = _make_handler()

    def func(ctx):
        return {"status": "OK", "user_id": ctx.user_id}

    response, broadcast = await _invoke(handler, func)

    assert response.status_code == 200
    broadcast.assert_called_once()
    kwargs = broadcast.call_args.kwargs
    assert kwargs["message"] == {"status": "OK", "user_id": "u1"}
    assert kwargs["user_id"] == "u1"
    assert kwargs["message_type"] == AWSWebSocketHandler.MessageType.SYSTEM_RESPONSE


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


# --------------------------------------------------------------------------------------------------
# get_router / handler assembly
# --------------------------------------------------------------------------------------------------


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
