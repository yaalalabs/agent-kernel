import json
import os

import pytest

from agentkernel.deployment.aws import LambdaRouter

DEFAULT_PATH = "default_agent_registered_path"  # must be same as _default_agent_registered_path in LambdaRouter
DEFAULT_METHOD = "POST"  # must be same as _default_agent_registered_method in LambdaRouter


def make_event_with_env_vars(path, method="GET", base="api", version="v1", agent_endpoint="agent"):
    """Set environment variables and return event"""
    os.environ["API_BASE_PATH"] = base
    os.environ["API_VERSION"] = version
    os.environ["AGENT_ENDPOINT"] = agent_endpoint
    return {
        "httpMethod": method,
        "path": path,
    }


def make_event_without_env_vars(path, method="GET"):
    """Clear environment variables and return event"""
    for key in ["API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"]:
        os.environ.pop(key, None)
    return {
        "httpMethod": method,
        "path": path,
    }


def cleanup_env_vars():
    """Clean up environment variables"""
    for key in ["API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"]:
        os.environ.pop(key, None)


@pytest.fixture  # what fixture does here is it enables every test function to get a new lambda router instance if they want to by just adding router as a parameter
def router():
    return LambdaRouter()


@pytest.fixture
def stub_default(router):  # 'router' here this means it depends on the router fixture, this is how the dependcies are resolved in pytest
    """
    Returns a function that can stub the default handler with a chosen status/payload.
    Usage: stub_default(status=201, payload={"via": "default"})
    """

    def _register(status=200, payload=None):  # registers a function that returns the payload for the default path and method
        if payload is None:
            payload = {"stubbed": True}
        router._routes[DEFAULT_PATH][DEFAULT_METHOD] = lambda e, c: {
            "statusCode": status,
            "body": json.dumps(payload),
        }

    return _register


def test_register_normalizes_and_routes_with_env_vars(router):
    @router.register("foo/", method="get")  # normalizes to '/foo' and 'GET'
    def foo_handler(event, context):
        return {"ok": True, "path_seen": event.get("path")}

    try:
        event = make_event_with_env_vars("/api/v1/foo", method="GET")
        resp = router.dispatch(event, context=None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["ok"] is True
        assert body["path_seen"] == "/api/v1/foo"
    finally:
        cleanup_env_vars()


def test_dispatch_routes_to_default_when_event_is_agent_endpoint_with_env_vars(router, stub_default):
    # Special case: path == base/agent_endpoint and method == POST => default handler
    stub_default(status=201, payload={"routed_to": "default_handler"})

    try:
        event = make_event_with_env_vars("/api/v1/agent", method="POST")
        resp = router.dispatch(event, context=None)

        assert resp["statusCode"] == 201
        assert json.loads(resp["body"]) == {"routed_to": "default_handler"}
    finally:
        cleanup_env_vars()


def test_dispatch_default_fallback_without_env_vars_uses_default_route(router, stub_default):
    # No environment variables => router forces POST and uses default path
    stub_default(status=202, payload={"fallback": True})

    try:
        event = make_event_without_env_vars("/anything/here", method="GET")
        resp = router.dispatch(event, context=None)

        assert resp["statusCode"] == 202
        assert json.loads(resp["body"]) == {"fallback": True}
    finally:
        cleanup_env_vars()


def test_dispatch_raises_for_unknown_route_with_env_vars(router):
    try:
        event = make_event_with_env_vars("/api/v1/unknown", method="GET")

        with pytest.raises(ValueError) as ei:
            router.dispatch(event, context=None)

        msg = str(ei.value)
        assert "/api/v1/unknown" in msg
        assert "GET" in msg
    finally:
        cleanup_env_vars()
