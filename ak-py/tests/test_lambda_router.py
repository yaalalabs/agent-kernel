import json
from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.config import _ExecutionConfig, _ResponseStoreConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.core.router import RESTLambdaRouter, WSLambdaRouter
from agentkernel.deployment.aws.serverless.core.router.rest_lambda import LambdaChatRejection

DEFAULT_METHOD = "POST"  # must be same as _default_agent_registered_method in LambdaRouter


# monkeypatch is a builtin fixture that allows to temporarily modify env vars, all env var changes are reverted after each test
def make_event_with_env_vars(monkeypatch, path, method="GET", base="api", version="v1", agent_endpoint="agent", **extra):
    """Set environment variables using monkeypatch and return event; extra keys (resource, pathParameters) are merged in"""
    monkeypatch.setenv("API_BASE_PATH", base)
    monkeypatch.setenv("API_VERSION", version)
    monkeypatch.setenv("AGENT_ENDPOINT", agent_endpoint)
    return {
        "httpMethod": method,
        "path": path,
        **extra,
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


def test_dispatch_routes_path_parameter_route_by_resource_template(router, monkeypatch):
    @router.register("/threads/{session_id}", method="GET")
    def get_thread(event, context):
        return (200, {"session_id": event["pathParameters"]["session_id"]})

    event = make_event_with_env_vars(
        monkeypatch,
        "/api/v1/threads/abc123",
        resource="/api/v1/threads/{session_id}",
        pathParameters={"session_id": "abc123"},
    )

    assert router.dispatch(event, context=None) == (200, {"session_id": "abc123"})


def test_dispatch_follows_the_resource_api_gateway_selected_over_a_matching_concrete_path(router, monkeypatch):
    # The concrete path is also registered, but the gateway matched the template: its choice wins.
    router.register("/thread/something1/something2", method="GET")(lambda e, c: (200, {"via": "static"}))
    router.register("/thread/something1/{param2}", method="GET")(lambda e, c: (200, {"via": "template"}))

    event = make_event_with_env_vars(
        monkeypatch,
        "/api/v1/thread/something1/something2",
        resource="/api/v1/thread/something1/{param2}",
        pathParameters={"param2": "something2"},
    )

    assert router.dispatch(event, context=None) == (200, {"via": "template"})


def test_dispatch_routes_static_route_when_resource_equals_path(router, monkeypatch):
    router.register("/threads/search", method="GET")(lambda e, c: (200, {"via": "static"}))
    router.register("/threads/{session_id}", method="GET")(lambda e, c: (200, {"via": "template"}))

    event = make_event_with_env_vars(monkeypatch, "/api/v1/threads/search", resource="/api/v1/threads/search")

    assert router.dispatch(event, context=None) == (200, {"via": "static"})


def test_dispatch_falls_back_to_concrete_path_when_resource_is_not_registered(router, monkeypatch):
    # A {proxy+} resource in front of the Lambda: its template is not a registered route.
    router.register("/foo", method="GET")(lambda e, c: (200, {"via": "path"}))

    event = make_event_with_env_vars(monkeypatch, "/api/v1/foo", resource="/api/v1/{proxy+}", pathParameters={"proxy": "foo"})

    assert router.dispatch(event, context=None) == (200, {"via": "path"})


def test_dispatch_raises_when_template_route_lacks_the_method(router, monkeypatch):
    router.register("/threads/{session_id}", method="GET")(lambda e, c: (200, {}))

    event = make_event_with_env_vars(monkeypatch, "/api/v1/threads/abc123", method="DELETE", resource="/api/v1/threads/{session_id}")

    with pytest.raises(ValueError, match="/api/v1/threads/abc123"):
        router.dispatch(event, context=None)


def test_dispatch_routes_agent_endpoint_to_default_when_resource_is_present(router, stub_default, monkeypatch):
    stub_default(status=201, payload={"routed_to": "default_handler"})

    event = make_event_with_env_vars(monkeypatch, "/api/v1/agent", method="POST", resource="/api/v1/agent")

    assert router.dispatch(event, context=None) == (201, {"routed_to": "default_handler"})


def _router_with_execution(monkeypatch, input_queue_url, **execution):
    """Build a real RESTLambdaRouter (no DefaultEndpointsHandler stub) over the given execution config."""
    module = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"
    config = MagicMock()
    config.execution = _ExecutionConfig(response_store=_ResponseStoreConfig(type="dynamodb"), **execution)
    monkeypatch.setattr(f"{module}.AKConfig.get", lambda: config)
    monkeypatch.setattr(f"{module}.ResponseStoreFactory.create", lambda: MagicMock())
    monkeypatch.setattr(f"{module}.ChatService", MagicMock())
    monkeypatch.setattr(f"{module}.SQSHandler.get_input_queue_url", lambda: input_queue_url)
    return RESTLambdaRouter()


@pytest.mark.parametrize("input_queue_url", [None, "https://sqs.us-east-1.amazonaws.com/123/input"])
def test_rest_sync_delta_is_refused_at_router_init(monkeypatch, input_queue_url):
    """The Lambda REST router does not stream responses, so SSE fails at cold start, direct or queued."""
    with pytest.raises(AKConfigError, match="rest_sync with message_type delta"):
        _router_with_execution(monkeypatch, input_queue_url, mode="rest_sync", message_type="delta")


@pytest.mark.parametrize("input_queue_url", [None, "https://sqs.us-east-1.amazonaws.com/123/input"])
def test_rest_sync_complete_builds_the_router(monkeypatch, input_queue_url):
    _router_with_execution(monkeypatch, input_queue_url, mode="rest_sync", message_type="complete")


QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123/input"
ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"


def _submit(router, monkeypatch):
    """POST a chat through the rest_async submit route; return the response and the SQS send mock."""
    send = MagicMock(return_value={"MessageId": "m1"})
    monkeypatch.setattr(f"{ROUTER_MODULE}.SQSHandler.send_message_to_input_queue", send)
    event = {
        "body": json.dumps(
            {
                "request_id": "r1",
                "user_id": "u1",
                "prompt": "hi",
                "session_id": "s1",
                "images": [{"image_data": "eA==", "name": "a.png", "mime_type": "image/png"}],
            }
        )
    }
    return router._routes["default_chat_path"]["POST"](event, None), send


def test_a_chat_enqueue_hook_adds_attributes_and_rewrites_the_body_before_it_is_dumped(monkeypatch):
    router = _router_with_execution(monkeypatch, QUEUE_URL, mode="rest_async")

    def hook(payload):
        payload.body.images = None
        payload.body.prompt = "rewritten"
        return {"thread": "1"}

    router.set_chat_enqueue_hook(hook)
    response, send = _submit(router, monkeypatch)

    assert response[0] == 200
    kwargs = send.call_args.kwargs
    assert {a.name: a.value for a in kwargs["custom_message_attributes"]} == {"thread": "1"}
    assert kwargs["message_body"]["prompt"] == "rewritten"
    assert "images" not in kwargs["message_body"]


def test_without_a_hook_the_send_carries_no_custom_attributes(monkeypatch):
    router = _router_with_execution(monkeypatch, QUEUE_URL, mode="rest_async")

    _, send = _submit(router, monkeypatch)

    assert send.call_args.kwargs["custom_message_attributes"] is None


def test_a_chat_rejection_answers_with_its_status_and_sends_nothing(monkeypatch):
    router = _router_with_execution(monkeypatch, QUEUE_URL, mode="rest_async")

    def hook(payload):
        raise LambdaChatRejection(400, {"error": "nope", "session_id": "s1"})

    router.set_chat_enqueue_hook(hook)
    response, send = _submit(router, monkeypatch)

    assert response == (400, {"error": "nope", "session_id": "s1"})
    send.assert_not_called()


def test_a_second_chat_enqueue_hook_is_rejected(monkeypatch):
    router = _router_with_execution(monkeypatch, QUEUE_URL, mode="rest_async")
    router.set_chat_enqueue_hook(lambda p: {})

    with pytest.raises(ValueError, match="already set"):
        router.set_chat_enqueue_hook(lambda p: {})


def test_a_chat_enqueue_hook_requires_queue_mode(monkeypatch):
    router = _router_with_execution(monkeypatch, None, mode="rest_sync")

    with pytest.raises(AKConfigError, match="requires queue mode"):
        router.set_chat_enqueue_hook(lambda p: {})


def test_a_chat_enqueue_hook_is_refused_in_websocket_mode(monkeypatch):
    from agentkernel.deployment.aws.serverless.aklambda import Lambda

    monkeypatch.setattr(Lambda, "_router", WSLambdaRouter.__new__(WSLambdaRouter))  # a real WebSocket router type, no init
    try:
        with pytest.raises(AKConfigError, match="WebSocket mode"):
            Lambda.set_chat_enqueue_hook(lambda p: {})
    finally:
        Lambda._router = None
