from unittest.mock import MagicMock, patch

import pytest

from agentkernel.deployment.aws.serverless.core.router import RESTLambdaRouter

DEFAULT_METHOD = "POST"  # must be same as _default_agent_registered_method in LambdaRouter


# monkeypatch is a builtin fixture that allows to temporarily modify env vars, all env var changes are reverted after each test
def make_event_with_env_vars(monkeypatch, path, method="GET", base="api", version="v1", agent_endpoint="agent"):
    """Set environment variables using monkeypatch and return event"""
    monkeypatch.setenv("API_BASE_PATH", base)
    monkeypatch.setenv("API_VERSION", version)
    monkeypatch.setenv("AGENT_ENDPOINT", agent_endpoint)
    return {
        "httpMethod": method,
        "path": path,
    }


def make_event_without_env_vars(monkeypatch, path, method="GET"):
    """Clear environment variables using monkeypatch and return event"""
    for key in ["API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"]:
        monkeypatch.delenv(key, raising=False)
    return {
        "httpMethod": method,
        "path": path,
    }


@pytest.fixture  # what fixture does here is it enables every test function to get a new lambda router instance if they want to by just adding router as a parameter
@patch("agentkernel.deployment.aws.serverless.core.router.rest_lambda.DefaultEndpointsHandler")
@patch("agentkernel.deployment.aws.serverless.core.router.rest_lambda.SQSHandler")
def router(mock_sqs_handler, mock_default_endpoints_handler):
    # Mock SQSHandler to return None for queue URL (no queues configured)
    mock_sqs_handler.get_input_queue_url.return_value = None

    # Mock DefaultEndpointsHandler to return simple route configuration
    mock_handler_instance = MagicMock()
    mock_handler_instance.get_default_endpoint_info.return_value = ("default_chat_path", "POST", None)
    mock_handler_instance.get_routes.return_value = {"default_chat_path": {"POST": lambda e, c: (200, {"stubbed": True})}}
    mock_default_endpoints_handler.return_value = mock_handler_instance

    return RESTLambdaRouter()


@pytest.fixture
def stub_default(router):  # 'router' here this means it depends on the router fixture, this is how the dependcies are resolved in pytest
    """
    Returns a function that can stub the default handler with a chosen status/payload.
    Usage: stub_default(status=201, payload={"via": "default"})
    """

    def _register(status=200, payload=None):  # registers a function that returns the payload for the default path and method
        if payload is None:
            payload = {"stubbed": True}
        router._routes.setdefault(router._default_chat_path, {})[router._default_chat_method] = lambda e, c: (status, payload)

    return _register


def test_register_normalizes_and_routes_with_env_vars(router, monkeypatch):
    @router.register("foo/", method="get")  # normalizes to '/foo' and 'GET'
    def foo_handler(event, context):
        return (200, {"ok": True, "path_seen": event.get("path")})

    event = make_event_with_env_vars(monkeypatch, "/api/v1/foo", method="GET")
    resp = router.dispatch(event, context=None)

    assert resp[0] == 200  # status code
    assert resp[1]["ok"] is True
    assert resp[1]["path_seen"] == "/api/v1/foo"


def test_dispatch_routes_to_default_when_event_is_agent_endpoint_with_env_vars(router, stub_default, monkeypatch):
    # Special case: path == base/agent_endpoint and method == POST => default handler
    stub_default(status=201, payload={"routed_to": "default_handler"})

    event = make_event_with_env_vars(monkeypatch, "/api/v1/agent", method="POST")
    resp = router.dispatch(event, context=None)

    assert resp[0] == 201  # status code
    assert resp[1] == {"routed_to": "default_handler"}


def test_dispatch_default_fallback_without_env_vars_uses_default_route(router, stub_default, monkeypatch):
    # No environment variables => router forces POST and uses default path
    stub_default(status=202, payload={"fallback": True})

    event = make_event_without_env_vars(monkeypatch, "/anything/here", method="GET")
    resp = router.dispatch(event, context=None)

    assert resp[0] == 202  # status code
    assert resp[1] == {"fallback": True}


def test_dispatch_raises_for_unknown_route_with_env_vars(router, monkeypatch):
    event = make_event_with_env_vars(monkeypatch, "/api/v1/unknown", method="GET")

    with pytest.raises(ValueError) as ei:
        router.dispatch(event, context=None)

    msg = str(ei.value)
    assert "/api/v1/unknown" in msg
    assert "GET" in msg


def test_handle_stream_returns_400_not_raises():
    """Test that _handle_stream returns a 400 tuple instead of raising ValueError."""
    from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler

    event = {"httpMethod": "POST", "path": "/"}
    result = DefaultEndpointsHandler._handle_stream(MagicMock(), event, context=None)

    assert result == (
        400,
        {
            "error": (
                "SSE streaming requires a Lambda Function URL with InvokeMode: RESPONSE_STREAM. " "Use streaming_handler as your Lambda entry point."
            )
        },
    )


def _handle_request_with_operation(operation, request_id="req-1"):
    """Invoke DefaultEndpointsHandler._handle_request with a stubbed self.

    Uses the real _build_failure_body so the returned body is a plain dict we
    can assert on, while _parse_body is stubbed to yield a request_id.
    """
    from agentkernel.deployment.aws.serverless.core.router.rest_lambda import DefaultEndpointsHandler

    mock_self = MagicMock()
    mock_self._parse_body.return_value = MagicMock(request_id=request_id)
    mock_self._build_failure_body.side_effect = lambda *a, **kw: DefaultEndpointsHandler._build_failure_body(mock_self, *a, **kw)

    return DefaultEndpointsHandler._handle_request(mock_self, {"body": "{}"}, operation)


def test_handle_request_maps_client_value_error_to_400():
    """A missing/invalid field (ValueError, e.g. session_id) is a client error → 400.

    Also guards the readiness probe: a generic body without session_id must get a
    4xx ("reachable") rather than a 5xx that the probe would keep retrying.
    """

    def operation(_request):
        raise ValueError("session_id is required")

    status, body = _handle_request_with_operation(operation)

    assert status == 400
    assert body["error"] == "session_id is required"
    assert body["request_id"] == "req-1"


def test_handle_request_maps_unexpected_error_to_500():
    """Non-ValueError failures remain hidden behind a generic 500."""

    def operation(_request):
        raise RuntimeError("boom")

    status, body = _handle_request_with_operation(operation, request_id="req-2")

    assert status == 500
    assert body["request_id"] == "req-2"
    # The internal error message must not leak into the 500 body.
    assert body["error"] == "An unexpected error occurred"
