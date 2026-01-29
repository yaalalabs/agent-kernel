import json

import pytest

from agentkernel.deployment.aws import LambdaRouter

DEFAULT_PATH = "default_agent_registered_path"  # must be same as _default_agent_registered_path in LambdaRouter
DEFAULT_METHOD = "POST"  # must be same as _default_agent_registered_method in LambdaRouter


def make_event_with_stage_vars(path, method="GET", base="api", version="v1", agent_endpoint="agent"):
    return {
        "httpMethod": method,
        "path": path,
        "stageVariables": {
            "api_base_path": base,
            "api_version": version,
            "agent_endpoint": agent_endpoint,
        },
    }


def make_event_without_stage_vars(path, method="GET"):
    return {
        "httpMethod": method,
        "path": path,
        # intentionally no stageVariables
    }


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


def test_register_normalizes_and_routes_with_stage_vars(router):
    @router.register("foo/", method="get")  # normalizes to '/foo' and 'GET'
    def foo_handler(event, context):
        return {"ok": True, "path_seen": event.get("path")}

    event = make_event_with_stage_vars("/api/v1/foo", method="GET")
    resp = router.dispatch(event, context=None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ok"] is True
    assert body["path_seen"] == "/api/v1/foo"


def test_dispatch_routes_to_default_when_event_is_agent_endpoint_with_stage_vars(router, stub_default):
    # Special case: path == base/agent_endpoint and method == POST => default handler
    stub_default(status=201, payload={"routed_to": "default_handler"})

    event = make_event_with_stage_vars("/api/v1/agent", method="POST")
    resp = router.dispatch(event, context=None)

    assert resp["statusCode"] == 201
    assert json.loads(resp["body"]) == {"routed_to": "default_handler"}


def test_dispatch_default_fallback_without_stage_vars_uses_default_route(router, stub_default):
    # No stageVariables => router forces POST and uses default path
    stub_default(status=202, payload={"fallback": True})

    event = make_event_without_stage_vars("/anything/here", method="GET")
    resp = router.dispatch(event, context=None)

    assert resp["statusCode"] == 202
    assert json.loads(resp["body"]) == {"fallback": True}


def test_dispatch_raises_for_unknown_route_with_stage_vars(router):
    event = make_event_with_stage_vars("/api/v1/unknown", method="GET")

    with pytest.raises(ValueError) as ei:
        router.dispatch(event, context=None)

    msg = str(ei.value)
    assert "/api/v1/unknown" in msg
    assert "GET" in msg
