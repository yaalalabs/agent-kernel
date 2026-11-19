"""ProtocolRouteMatcher: the API Gateway authorizer's bypass for the A2A and MCP routes (#932).

Three things get past the authorizer without a token: MCP (FastMCP authenticates it itself), and the public agent card
and catalog. Every other A2A route stays behind the authorizer, because the app lets a call with no token through as the
anonymous principal.
"""

import pytest

from agentkernel.deployment.aws.serverless.akauthorizer import APIGatewayAuthorizer
from agentkernel.deployment.aws.serverless.core.protocol_paths import ProtocolRouteMatcher

CARD = "/.well-known/agent-card.json"


@pytest.fixture
def base_path(monkeypatch):
    monkeypatch.setenv("API_BASE_PATH", "api")
    monkeypatch.setenv("API_VERSION", "v1")
    monkeypatch.setenv("AGENT_ENDPOINT", "chat")


def _event(method: str = "POST", path: str = "/api/v1/mcp", headers: dict | None = None, method_arn: str | None = "default") -> dict:
    event = {
        "type": "REQUEST",
        "resource": path,
        "path": path,
        "httpMethod": method,
        "headers": headers if headers is not None else {"Content-Type": "application/json"},
    }
    if method_arn == "default":
        event["methodArn"] = f"arn:aws:execute-api:us-east-1:123456789012:abc123/agents/{method}{path}"
    elif method_arn is not None:
        event["methodArn"] = method_arn
    return event


def _effect(policy: dict) -> str:
    return policy["policyDocument"]["Statement"][0]["Effect"]


class TestMcp:
    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS"])
    def test_mcp_is_let_through_for_any_method(self, base_path, method):
        assert ProtocolRouteMatcher()(_event(method, "/api/v1/mcp")) == "mcp"

    @pytest.mark.parametrize("path", ["/api/v1/mcp", "/api/v1/mcp/", "/api/v1/mcp/session/1", "/api/v1/mcp/.well-known/x"])
    def test_everything_under_mcp_is_let_through(self, base_path, path):
        assert ProtocolRouteMatcher()(_event("POST", path)) == "mcp"

    @pytest.mark.parametrize("path", ["/api/v1/mcpx", "/api/v1/mcp-evil", "/api/v1/x/mcp", "/api/v1/mc", "/api/v1"])
    def test_a_path_that_only_starts_like_mcp_is_not(self, base_path, path):
        assert ProtocolRouteMatcher()(_event("POST", path)) is None


class TestPublicA2a:
    def test_the_catalog_is_let_through_on_get(self, base_path):
        assert ProtocolRouteMatcher()(_event("GET", "/api/v1/a2a/catalog")) == "a2a"

    @pytest.mark.parametrize("agent", ["triage", "expense-claims", "agent_2", "A1", "catalog"])
    def test_an_agents_card_is_let_through_on_get(self, base_path, agent):
        assert ProtocolRouteMatcher()(_event("GET", f"/api/v1/a2a/{agent}{CARD}")) == "a2a"

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    def test_only_get_is_public(self, base_path, method):
        matcher = ProtocolRouteMatcher()

        assert matcher(_event(method, "/api/v1/a2a/catalog")) is None
        assert matcher(_event(method, f"/api/v1/a2a/triage{CARD}")) is None


class TestEverythingElseStaysBehindTheAuthorizer:
    @pytest.mark.parametrize(
        "method, path",
        [
            ("POST", "/api/v1/a2a/triage/message:send"),
            ("POST", "/api/v1/a2a/triage/message:stream"),
            ("GET", "/api/v1/a2a/triage/tasks"),
            ("GET", "/api/v1/a2a/triage/tasks/123"),
            ("POST", "/api/v1/a2a/triage/tasks/123:cancel"),
            ("DELETE", "/api/v1/a2a/triage/tasks/123"),
            ("GET", "/api/v1/a2a/triage"),
            ("GET", "/api/v1/a2a"),
            ("POST", "/api/v1/a2a"),
            ("GET", "/api/v1/agent"),
            ("POST", "/api/v1/chat"),
            ("GET", "/api/v1/health"),
        ],
    )
    def test_a_message_task_chat_or_unknown_route_is_not_let_through(self, base_path, method, path):
        assert ProtocolRouteMatcher()(_event(method, path)) is None

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/a2a/catalog/",  # the request path is not normalized: only the exact catalog is public
            "/api/v1/a2a/catalog/extra",
            f"/api/v1/a2a/triage{CARD}/",
            f"/api/v1/a2a/triage/extra{CARD}",  # one segment for the agent, no more
            f"/api/v1/a2a/a/b{CARD}",
            f"/api/v1/a2a/{CARD}",  # no agent
            f"/api/v1/a2a//{CARD}",
            "/api/v1/a2a/triage/.well-known/agent-card.jsonx",
            "/api/v1/a2a/triage/.well-known/other.json",
        ],
    )
    def test_a_near_miss_of_a_public_path_is_not_let_through(self, base_path, path):
        assert ProtocolRouteMatcher()(_event("GET", path)) is None

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/mcp/../a2a/triage/message:send",
            "/api/v1/a2a/../mcp",
            f"/api/v1/a2a/../{CARD}",
            f"/api/v1/a2a/x/../triage{CARD}",
            "/api/v1/a2a/catalog/..",
            "/api/v1/mcp/..",
        ],
    )
    def test_a_path_with_a_dot_dot_segment_is_never_let_through(self, base_path, path):
        """Nothing it could reach is worth a bypass: the authorizer decides, so a traversal cannot ride a public prefix."""
        assert ProtocolRouteMatcher()(_event("POST", path)) is None
        assert ProtocolRouteMatcher()(_event("GET", path)) is None


class TestTheBasePath:
    @pytest.mark.parametrize("api_base_path, api_version", [("api", "v1"), ("svc", "v2")])
    def test_the_base_path_comes_from_the_environment_as_the_router_derives_it(self, monkeypatch, api_base_path, api_version):
        monkeypatch.setenv("API_BASE_PATH", api_base_path)
        monkeypatch.setenv("API_VERSION", api_version)
        matcher = ProtocolRouteMatcher()

        assert matcher(_event("POST", f"/{api_base_path}/{api_version}/mcp")) == "mcp"
        assert matcher(_event("GET", f"/{api_base_path}/{api_version}/a2a/catalog")) == "a2a"
        assert matcher(_event("POST", "/other/v9/mcp")) is None

    def test_an_explicit_base_path_wins_over_the_environment(self, base_path):
        matcher = ProtocolRouteMatcher(base_path="/svc/v9")

        assert matcher(_event("POST", "/svc/v9/mcp")) == "mcp"
        assert matcher(_event("POST", "/api/v1/mcp")) is None

    def test_a_longer_version_is_not_the_base_path(self, base_path):
        """``/api/v10`` must not be read as ``/api/v1`` followed by ``0``."""
        assert ProtocolRouteMatcher()(_event("POST", "/api/v10/mcp")) is None
        assert ProtocolRouteMatcher()(_event("POST", "/api/v1mcp")) is None

    @pytest.mark.parametrize("method, path", [("POST", "/api/v1/mcp"), ("GET", "/api/v1/a2a/catalog"), ("GET", f"/api/v1/a2a/triage{CARD}")])
    def test_without_the_base_path_variables_it_fails_closed(self, monkeypatch, method, path):
        for variable in ("API_BASE_PATH", "API_VERSION", "AGENT_ENDPOINT"):
            monkeypatch.delenv(variable, raising=False)

        assert ProtocolRouteMatcher()(_event(method, path)) is None


class TestWhatItReads:
    def test_no_header_changes_the_answer(self, base_path):
        """The event has no body, and a header test could be spoofed onto a protected request."""
        matcher = ProtocolRouteMatcher()
        spoofs = {"X-Public": "true", "X-A2A-Public": "1", "Authorization": "Bearer anything", "Host": "localhost"}

        assert matcher(_event("POST", "/api/v1/a2a/triage/message:send", headers=spoofs)) is None
        assert matcher(_event("POST", "/api/v1/mcp", headers=spoofs)) == "mcp"
        assert matcher(_event("POST", "/api/v1/mcp", headers={})) == "mcp"

    def test_the_method_is_case_insensitive(self, base_path):
        matcher = ProtocolRouteMatcher()

        assert matcher(_event("get", "/api/v1/a2a/catalog")) == "a2a"
        assert matcher(_event("post", "/api/v1/a2a/triage/message:send")) is None

    def test_an_event_with_no_method_or_path_matches_nothing(self, base_path):
        matcher = ProtocolRouteMatcher()

        assert matcher({}) is None
        assert matcher({"path": "/api/v1/a2a/catalog"}) is None  # no method: the catalog is GET only

    def test_the_same_matcher_answers_the_same_every_time(self, base_path):
        matcher = ProtocolRouteMatcher()
        event = _event("GET", "/api/v1/a2a/catalog")

        assert [matcher(event) for _ in range(3)] == ["a2a", "a2a", "a2a"]

    def test_it_is_not_a_webhook_matcher(self):
        with pytest.raises(TypeError, match="ProtocolRouteMatcher"):
            ProtocolRouteMatcher.for_integrations("slack")


class TestAuthorizerBypass:
    """``APIGatewayAuthorizer(bypass=ProtocolRouteMatcher())``: the bypass answers before the identity provider is asked."""

    def _authorizer(self) -> APIGatewayAuthorizer:
        return APIGatewayAuthorizer(bypass=ProtocolRouteMatcher())

    def test_the_agent_card_is_allowed_with_no_token_and_the_provider_is_not_asked(self, base_path, static_identity):
        event = _event("GET", f"/api/v1/a2a/triage{CARD}", headers={})

        policy = self._authorizer().handle(event)

        assert _effect(policy) == "Allow"
        assert policy["principalId"] == "integration:a2a"
        assert policy["policyDocument"]["Statement"][0]["Resource"] == event["methodArn"]
        assert static_identity.calls == []

    def test_the_catalog_is_allowed_with_no_token(self, base_path, static_identity):
        policy = self._authorizer().handle(_event("GET", "/api/v1/a2a/catalog", headers={}))

        assert (_effect(policy), policy["principalId"]) == ("Allow", "integration:a2a")
        assert static_identity.calls == []

    @pytest.mark.parametrize("method", ["POST", "GET", "DELETE"])
    def test_mcp_is_allowed_with_no_token_because_fastmcp_refuses_a_bad_one_itself(self, base_path, static_identity, method):
        policy = self._authorizer().handle(_event(method, "/api/v1/mcp", headers={}))

        assert (_effect(policy), policy["principalId"]) == ("Allow", "integration:mcp")
        assert static_identity.calls == []

    def test_a_message_send_with_no_token_is_refused(self, base_path, static_identity):
        policy = self._authorizer().handle(_event("POST", "/api/v1/a2a/triage/message:send", headers={}))

        assert _effect(policy) == "Deny"
        assert static_identity.calls == []

    def test_a_message_send_with_a_token_takes_the_normal_path_and_runs_as_the_caller(self, base_path, static_identity):
        event = _event("POST", "/api/v1/a2a/triage/message:send", headers={"Authorization": "Bearer alice-secret"})

        policy = self._authorizer().handle(event)

        assert len(static_identity.calls) == 1
        assert (_effect(policy), policy["principalId"]) == ("Allow", "alice")

    def test_a_message_send_with_a_wrong_token_is_refused(self, base_path, static_identity):
        event = _event("POST", "/api/v1/a2a/triage/message:send", headers={"Authorization": "Bearer wrong"})

        with pytest.raises(Exception, match="Unauthorized"):
            self._authorizer().handle(event)

        assert len(static_identity.calls) == 1

    def test_a_task_route_with_no_token_is_refused(self, base_path, static_identity):
        policy = self._authorizer().handle(_event("GET", "/api/v1/a2a/triage/tasks/123", headers={}))

        assert _effect(policy) == "Deny"
        assert static_identity.calls == []

    def test_a_post_to_the_card_path_is_not_public(self, base_path, static_identity):
        policy = self._authorizer().handle(_event("POST", f"/api/v1/a2a/triage{CARD}", headers={}))

        assert _effect(policy) == "Deny"

    def test_an_event_without_a_method_arn_is_not_bypassed(self, base_path, static_identity):
        policy = self._authorizer().handle(_event("GET", "/api/v1/a2a/catalog", headers={}, method_arn=None))

        assert _effect(policy) == "Deny"
        assert static_identity.calls == []
