"""The API Gateway authorizer's bypass for messaging-integration routes (#760 Q1)."""

from unittest.mock import MagicMock, patch

import pytest

from agentkernel.core.util.factory import AKConfigError
from agentkernel.deployment.aws.serverless.akauthorizer import APIGatewayAuthorizer
from agentkernel.integration.adapter.route_matcher import WebhookRouteMatcher
from agentkernel.integration.adapter.routes import WebhookRoute

ROUTER_MODULE = "agentkernel.deployment.aws.serverless.core.router.rest_lambda"


@pytest.fixture
def base_path(monkeypatch):
    monkeypatch.setenv("API_BASE_PATH", "api")
    monkeypatch.setenv("API_VERSION", "v1")
    monkeypatch.setenv("AGENT_ENDPOINT", "chat")


def _event(method: str = "POST", path: str = "/api/v1/slack/events", headers: dict | None = None, method_arn: str | None = "default") -> dict:
    event = {
        "type": "REQUEST",
        "resource": path,
        "path": path,
        "httpMethod": method,
        "headers": headers if headers is not None else {"Content-Type": "application/json"},
    }
    if method_arn == "default":
        event["methodArn"] = f"arn:aws:execute-api:us-east-1:123456789012:abc123/prod/{method}{path}"
    elif method_arn is not None:
        event["methodArn"] = method_arn
    return event


def _effect(policy: dict) -> str:
    return policy["policyDocument"]["Statement"][0]["Effect"]


class TestWebhookRouteMatcher:
    def test_a_builtin_route_matches_under_the_base_path(self, base_path):
        assert WebhookRouteMatcher.for_integrations("slack")(_event()) == "slack"

    @pytest.mark.parametrize("api_base_path, api_version", [("api", "v1"), ("svc", "v2")])
    def test_the_base_path_is_stripped_as_the_router_strips_it(self, monkeypatch, api_base_path, api_version):
        monkeypatch.setenv("API_BASE_PATH", api_base_path)
        monkeypatch.setenv("API_VERSION", api_version)
        monkeypatch.setenv("AGENT_ENDPOINT", "chat")
        path = f"/{api_base_path}/{api_version}/slack/events"

        endpoints = MagicMock()
        endpoints.get_default_endpoint_info.return_value = ("default_chat_path", "POST", None)
        endpoints.get_routes.return_value = {"default_chat_path": {"POST": lambda event, context: "chat"}}
        with patch(f"{ROUTER_MODULE}.DefaultEndpointsHandler", return_value=endpoints):
            from agentkernel.deployment.aws.serverless.core.router import RESTLambdaRouter

            router = RESTLambdaRouter()
        router.register("/slack/events", "POST")(lambda event, context: "webhook")

        # The router and the matcher must resolve the same gateway path to the same route.
        assert router.dispatch({"httpMethod": "POST", "path": path}, None) == "webhook"
        assert WebhookRouteMatcher.for_integrations("slack")(_event(path=path)) == "slack"

    def test_an_undeclared_method_does_not_match(self, base_path):
        assert WebhookRouteMatcher.for_integrations("slack")(_event(method="GET")) is None

    def test_a_trailing_slash_does_not_match(self, base_path):
        assert WebhookRouteMatcher.for_integrations("slack")(_event(path="/api/v1/slack/events/")) is None

    def test_a_challenge_route_matches_on_get(self, base_path):
        matcher = WebhookRouteMatcher.for_integrations("whatsapp")

        assert matcher(_event(method="GET", path="/api/v1/whatsapp/webhook")) == "whatsapp"
        assert matcher(_event(method="POST", path="/api/v1/whatsapp/webhook")) == "whatsapp"

    def test_without_the_base_path_variables_it_fails_closed(self, monkeypatch):
        for variable in ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"):
            monkeypatch.delenv(variable, raising=False)

        assert WebhookRouteMatcher.for_integrations("slack")(_event()) is None

    def test_an_explicit_base_path_wins_over_the_environment(self, base_path):
        matcher = WebhookRouteMatcher.for_integrations("slack", base_path="/svc/v9")

        assert matcher(_event(path="/svc/v9/slack/events")) == "slack"
        assert matcher(_event()) is None

    def test_an_unknown_name_lists_the_builtins(self):
        with pytest.raises(AKConfigError, match="slack") as excinfo:
            WebhookRouteMatcher.for_integrations("carrier-pigeon")

        assert "WebhookRoute" in str(excinfo.value)

    def test_no_name_is_refused(self):
        with pytest.raises(ValueError):
            WebhookRouteMatcher.for_integrations()

    def test_a_bring_your_own_route(self, base_path):
        matcher = WebhookRouteMatcher([WebhookRoute("byo", "/byo/hook")])

        assert matcher(_event(path="/api/v1/byo/hook")) == "byo"

    def test_a_platform_header_on_a_chat_path_changes_nothing(self, base_path):
        event = _event(path="/api/v1/chat", headers={"X-Slack-Signature": "v0=spoofed", "X-Slack-Request-Timestamp": "1"})

        assert WebhookRouteMatcher.for_integrations("slack")(event) is None


class TestAuthorizerBypass:
    """The bypass answers before the identity provider is asked; everything else still goes through it."""

    def test_a_webhook_route_is_allowed_without_consulting_the_provider(self, base_path, static_identity):
        event = _event()

        policy = APIGatewayAuthorizer(bypass=WebhookRouteMatcher.for_integrations("slack")).handle(event)

        assert _effect(policy) == "Allow"
        assert policy["principalId"] == "integration:slack"
        assert policy["policyDocument"]["Statement"][0]["Resource"] == event["methodArn"]
        assert "context" not in policy
        assert static_identity.calls == []

    def test_a_spoofed_platform_header_on_the_chat_route_is_denied(self, base_path, static_identity):
        event = _event(path="/api/v1/chat", headers={"X-Slack-Signature": "v0=spoofed"})

        policy = APIGatewayAuthorizer(bypass=WebhookRouteMatcher.for_integrations("slack")).handle(event)

        assert _effect(policy) == "Deny"
        assert static_identity.calls == []

    def test_an_undeclared_method_on_a_webhook_path_goes_to_the_provider(self, base_path, static_identity):
        event = _event(method="GET", headers={"Authorization": "Bearer alice-secret"})

        policy = APIGatewayAuthorizer(bypass=WebhookRouteMatcher.for_integrations("slack")).handle(event)

        assert len(static_identity.calls) == 1
        assert _effect(policy) == "Allow"
        assert policy["principalId"] == "alice"

    def test_a_raising_bypass_falls_through_to_the_provider(self, caplog, static_identity):
        def _broken(event):
            raise RuntimeError("matcher bug")

        policy = APIGatewayAuthorizer(bypass=_broken).handle(_event(headers={"Authorization": "Bearer alice-secret"}))

        assert len(static_identity.calls) == 1
        assert policy["principalId"] == "alice"
        assert "matcher bug" in caplog.text

    def test_a_true_predicate_gets_the_generic_principal(self, static_identity):
        policy = APIGatewayAuthorizer(bypass=lambda event: True).handle(_event())

        assert _effect(policy) == "Allow"
        assert policy["principalId"] == "integration"
        assert static_identity.calls == []

    def test_an_event_without_a_method_arn_falls_through(self, static_identity):
        policy = APIGatewayAuthorizer(bypass=lambda event: "slack").handle(_event(method_arn=None))

        assert _effect(policy) == "Deny"
        assert policy["principalId"] == "unauthorized"
