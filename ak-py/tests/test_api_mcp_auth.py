"""
MCP authentication over the configured identity provider (spec `docs/specs/603-identity-rbac-registry/` 8.6, iteration 8).

FastMCP owns the HTTP side: `AKTokenVerifier` turns a bearer token into an access token that
carries the `Principal`, FastMCP answers 401 for a token the provider refuses, and the executor
reads the principal off the request's access token onto the queued body. Without an identity
block `auth` is None and MCP stays open, every call anonymous. The per-tool visibility check
arrives with the access gate.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth.auth import RemoteAuthProvider
from mcp.server.auth.provider import AccessToken

from agentkernel.api.mcp.akmcp import MCP
from agentkernel.api.mcp.auth import PRINCIPAL_CLAIM, AKAccessToken, AKMCPAuthProvider, AKTokenVerifier
from agentkernel.core.chat_service import ResponseBuilder
from agentkernel.core.model import AgentReplyText, Principal
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory
from agentkernel.pipeline.request_handler import QueuedReply

MCP_NAME = "Agent Kernel FastMCP Instance"
ALICE = Principal(subject="alice", provider="test", namespace="test", groups=["ops"], claims={"exp": 4102444800, "email": "alice@example.com"})


class _Provider(IdentityProvider):
    name = "test"

    async def authenticate(self, credential, context=None):
        if credential == "alice-secret":
            return ALICE
        raise AuthenticationError("unknown token")


class _OIDCShaped(_Provider):
    """What the OIDC family advertises: the discovery URL under the issuer."""

    name = "oidc"

    def security_scheme(self):
        return ("openIdConnect", {"url": "https://issuer.example/.well-known/openid-configuration"})


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def request(self, body, protocol):
        self.calls.append((body, protocol))
        return self.reply


def _reply(text="hi") -> QueuedReply:
    _status, body = ResponseBuilder.build_response(200, "s1", rest_api_mode=False, result=AgentReplyText(response=text))
    return QueuedReply(request_id="r1", status_code=200, body=body)


@pytest.fixture(autouse=True)
def _mcp_state():
    saved = (MCP._fastmcp, MCP._built, dict(MCP._executors), MCP._client)
    MCP._fastmcp, MCP._built, MCP._executors = None, False, {}
    yield
    MCP._fastmcp, MCP._built, MCP._executors, MCP._client = saved


@pytest.fixture
def provider(monkeypatch):
    instance = _Provider()
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: instance))
    return instance


class TestTokenVerifier:
    @pytest.mark.asyncio
    async def test_a_valid_token_becomes_an_access_token_carrying_the_principal(self):
        token = await AKTokenVerifier(_Provider()).verify_token("alice-secret")

        assert isinstance(token, AKAccessToken) and isinstance(token, AccessToken)
        assert token.principal == ALICE
        assert (token.token, token.client_id, token.subject, token.scopes) == ("alice-secret", "alice", "alice", [])
        assert token.claims == {**ALICE.claims, PRINCIPAL_CLAIM: ALICE.model_dump(mode="json")}
        assert token.expires_at == 4102444800

    def test_the_principal_is_read_back_from_the_claim_fastmcp_keeps(self):
        """FastMCP rebuilds the verifier's token as its own AccessToken, SDK fields only; the claim is what survives."""
        rebuilt = AccessToken(token="t", client_id="alice", scopes=[], claims={"email": "a@x", PRINCIPAL_CLAIM: ALICE.model_dump(mode="json")})
        assert AKAccessToken.principal_of(rebuilt) == ALICE
        assert AKAccessToken.principal_of(AccessToken(token="t", client_id="c", scopes=[])).is_anonymous
        assert AKAccessToken.principal_of(None).is_anonymous

    @pytest.mark.asyncio
    async def test_a_refused_token_is_none_and_the_reason_is_logged(self, caplog):
        with caplog.at_level("INFO", logger="ak.api.mcp.auth"):
            assert await AKTokenVerifier(_Provider()).verify_token("nope") is None
        assert any("unknown token" in record.getMessage() for record in caplog.records if record.name == "ak.api.mcp.auth")


class TestAuthProviderSelection:
    def test_no_identity_block_means_no_auth(self, monkeypatch):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))
        assert AKMCPAuthProvider.from_config() is None

    def test_a_bearer_provider_is_served_by_the_verifier_alone(self, provider):
        auth = AKMCPAuthProvider.from_config()
        assert isinstance(auth, AKTokenVerifier) and not isinstance(auth, RemoteAuthProvider)

    def test_an_openid_provider_is_wrapped_for_the_resource_metadata(self, monkeypatch):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: _OIDCShaped()))

        class _Api:
            host = "agents.example"
            port = 8443

        class _Cfg:
            api = _Api

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

        auth = AKMCPAuthProvider.from_config()

        assert isinstance(auth, RemoteAuthProvider)
        assert [str(url) for url in auth.authorization_servers] == ["https://issuer.example/"]
        assert str(auth.base_url).rstrip("/") == "http://agents.example:8443"
        assert isinstance(auth.token_verifier, AKTokenVerifier)


class TestServerBuild:
    def test_the_server_is_built_with_the_configured_auth(self, provider):
        with patch("agentkernel.api.mcp.akmcp.FastMCP") as fastmcp_class, patch("agentkernel.api.mcp.akmcp.AKConfig") as config_class:
            config_class.get.return_value.mcp.enabled = True
            config_class.get.return_value.mcp.expose_agents = False
            MCP.get()

        name, kwargs = fastmcp_class.call_args.args[0], fastmcp_class.call_args.kwargs
        assert name == MCP_NAME
        assert isinstance(kwargs["auth"], AKTokenVerifier)

    def test_without_an_identity_block_the_server_stays_open(self, monkeypatch):
        monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: None))
        with patch("agentkernel.api.mcp.akmcp.FastMCP") as fastmcp_class, patch("agentkernel.api.mcp.akmcp.AKConfig") as config_class:
            config_class.get.return_value.mcp.enabled = True
            config_class.get.return_value.mcp.expose_agents = False
            MCP.get()

        fastmcp_class.assert_called_once_with(MCP_NAME, auth=None)


class TestExecutorPrincipal:
    @pytest.mark.asyncio
    async def test_the_access_tokens_principal_rides_the_body(self, monkeypatch):
        client = FakeClient(_reply())
        MCP._client = client
        token = await AKTokenVerifier(_Provider()).verify_token("alice-secret")
        monkeypatch.setattr("agentkernel.api.mcp.akmcp.get_access_token", lambda: token)

        await MCP.Executor("triage").execute("s1", "hi", AsyncMock())

        [(body, _)] = client.calls
        assert body.principal == ALICE

    @pytest.mark.asyncio
    async def test_no_access_token_is_the_anonymous_principal(self, monkeypatch):
        client = FakeClient(_reply())
        MCP._client = client
        monkeypatch.setattr("agentkernel.api.mcp.akmcp.get_access_token", lambda: None)

        await MCP.Executor("triage").execute("s1", "hi", AsyncMock())

        [(body, _)] = client.calls
        assert body.principal is not None and body.principal.is_anonymous

    @pytest.mark.asyncio
    async def test_a_foreign_access_token_is_anonymous_too(self, monkeypatch):
        """Only a token this verifier minted carries a principal; anything else authenticated nobody we know."""
        client = FakeClient(_reply())
        MCP._client = client
        monkeypatch.setattr("agentkernel.api.mcp.akmcp.get_access_token", lambda: AccessToken(token="t", client_id="c", scopes=[]))

        await MCP.Executor("triage").execute("s1", "hi", AsyncMock())

        assert client.calls[0][0].principal.is_anonymous


def _http_factory(app):
    """An MCP HTTP client factory that talks to the ASGI app in-process."""

    def factory(headers=None, timeout=None, auth=None, **kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://mcp.test",
            headers=headers,
            timeout=timeout or httpx.Timeout(30),
            auth=auth,
            **kwargs,
        )

    return factory


class TestThroughARealClient:
    """FastMCP's own HTTP layer enforces the verifier: a bearer token reaches the tool as a principal, a bad one is a 401."""

    @pytest.fixture
    def served(self):
        server = FastMCP(MCP_NAME, auth=AKTokenVerifier(_Provider()))
        server.tool(MCP.Executor("triage").execute, name="triage", description="test agent")
        client = FakeClient(_reply("done"))
        MCP._client = client
        return server.http_app(path="/"), client

    @pytest.mark.asyncio
    async def test_a_bearer_token_authenticates_the_call_and_the_principal_reaches_the_queue(self, served):
        app, queue_client = served
        async with app.router.lifespan_context(app):
            transport = StreamableHttpTransport("http://mcp.test/", auth="alice-secret", httpx_client_factory=_http_factory(app))
            async with Client(transport) as client:
                result = await client.call_tool("triage", {"session_id": "s1", "prompt": "hi"})

        assert result.content[0].text == "done"
        [(body, _)] = queue_client.calls
        assert (body.principal.subject, body.principal.groups) == ("alice", ["ops"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}])
    async def test_a_missing_or_refused_token_is_a_401_before_any_tool_runs(self, served, headers):
        app, queue_client = served
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        }
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test") as http:
                response = await http.post("/", json=initialize, headers={"Accept": "application/json, text/event-stream", **headers})

        assert response.status_code == 401
        assert "bearer" in response.headers.get("www-authenticate", "").lower()
        assert queue_client.calls == []
