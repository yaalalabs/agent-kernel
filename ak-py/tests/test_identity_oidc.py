"""
The OIDC provider family (spec `docs/specs/603-identity-rbac-registry/` section 4, iteration 5).

Four providers over one validation path: a bearer JWT is checked for signature (against a cached
JWK set found through issuer discovery), issuer, audience, lifetime and required claims, then
read through the claim paths into a Principal whose namespace is the validated issuer. Every
provider is run through `IdentityProviderContract` over an RSA and an EC key served by a local
JWK set on `httpx.MockTransport`; the cache's refresh-once-with-cooldown rule and each
subclass's one extra check are pinned beside it.
"""

import asyncio
import base64
import hashlib
import hmac
import http.server
import json
import sys
import threading
import time
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from agentkernel.core.config import _CognitoProviderConfig, _EntraProviderConfig, _FirebaseProviderConfig, _IdentityConfig, _IdentityProviderConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import AuthenticationError, IdentityProviderFactory
from agentkernel.identity.provider.cognito import CognitoIdentityProvider
from agentkernel.identity.provider.entra import EntraIdentityProvider
from agentkernel.identity.provider.firebase import FirebaseIdentityProvider
from agentkernel.identity.provider.oidc import JWKSCache, OIDCIdentityProvider
from agentkernel.identity.provider.roles import MappedIdentityProvider, MappingRoleMapper
from agentkernel.identity.provider.testing import IdentityProviderContract

ISSUER = "https://issuer.example"
AUDIENCE = "agent-kernel"
DISCOVERY = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URI = f"{ISSUER}/keys"


class Keys:
    """An RSA and an EC signing key, their public JWK set, and a token signer over either."""

    def __init__(self):
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.rsa_kid, self.ec_kid = "rsa-1", "ec-1"

    def jwks(self) -> dict:
        rsa_jwk = RSAAlgorithm.to_jwk(self.rsa.public_key(), as_dict=True)
        ec_jwk = ECAlgorithm.to_jwk(self.ec.public_key(), as_dict=True)
        return {"keys": [{**rsa_jwk, "kid": self.rsa_kid, "alg": "RS256"}, {**ec_jwk, "kid": self.ec_kid, "alg": "ES256"}]}

    def token(self, claims: dict, *, key: str = "rsa", kid: str | None = None, lifetime: int = 300) -> str:
        now = int(time.time())
        payload = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + lifetime, "sub": "alice", **claims}
        payload = {k: v for k, v in payload.items() if v is not None}
        if key == "rsa":
            return jwt.encode(payload, self.rsa, algorithm="RS256", headers={"kid": kid or self.rsa_kid})
        return jwt.encode(payload, self.ec, algorithm="ES256", headers={"kid": kid or self.ec_kid})


class JWKSServer:
    """A MockTransport answering discovery and the JWK set, counting what it served."""

    def __init__(self, keys: Keys, issuer: str = ISSUER, jwks_uri: str = JWKS_URI):
        self.keys = keys
        self.issuer, self.jwks_uri = issuer, jwks_uri
        self.discovery_calls = 0
        self.jwks_calls = 0
        self.jwks_override: dict | None = None
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{self.issuer}/.well-known/openid-configuration":
            self.discovery_calls += 1
            return httpx.Response(200, json={"issuer": self.issuer, "jwks_uri": self.jwks_uri})
        if url == self.jwks_uri:
            self.jwks_calls += 1
            return httpx.Response(200, json=self.jwks_override or self.keys.jwks())
        return httpx.Response(404)


class _KeepAliveJWKSServer:
    """A real HTTP/1.1 server on localhost that keeps connections alive, serving discovery and a JWK set."""

    def __init__(self, keys: Keys):
        self.jwks = keys.jwks()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                if self.path == "/.well-known/openid-configuration":
                    body = json.dumps({"issuer": outer.issuer, "jwks_uri": f"{outer.issuer}/keys"}).encode()
                elif self.path == "/keys":
                    body = json.dumps(outer.jwks).encode()
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.issuer = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_KeepAliveJWKSServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def keys() -> Keys:
    return Keys()


@pytest.fixture
def server(keys) -> JWKSServer:
    return JWKSServer(keys)


def _oidc(server: JWKSServer, **overrides) -> OIDCIdentityProvider:
    fields = {"issuer": ISSUER, "audience": AUDIENCE, "jwks": JWKSCache(ISSUER, transport=server.transport)}
    fields.update(overrides)
    return OIDCIdentityProvider(**fields)


def _tampered(token: str) -> str:
    head, payload, signature = token.split(".")
    return f"{head}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _forge(header: dict, payload: dict, sign) -> str:
    """A compact JWS whose signature ``sign(signing_input)`` produces, for tokens PyJWT will not encode."""
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}"
    return f"{signing_input}.{_b64(sign(signing_input.encode()))}"


class _OIDCFamilyContract(IdentityProviderContract):
    """The shared cases, parametrized over the RSA and the EC key by the `key` fixture."""

    @pytest.fixture(params=["rsa", "ec"])
    def key(self, request):
        return request.param

    def claims(self) -> dict:
        return {"groups": ["ops", "dev"], "email": "alice@example.com"}

    def expected(self) -> dict:
        return {"subject": "alice", "namespace": ISSUER, "groups": ["ops", "dev"]}

    def issuer(self) -> str:
        return ISSUER

    @pytest.fixture
    def valid_credential(self, keys, key):
        token = keys.token(self.claims(), key=key)
        expected = self.expected()
        expected["claims"] = {k: v for k, v in jwt.decode(token, options={"verify_signature": False}).items() if k not in self.claim_keys_removed()}
        return token, expected

    def claim_keys_removed(self) -> tuple[str, ...]:
        """The subject claim alone: the groups claim stays in ``claims`` beside its projection, for a role mapper's ``pass_through``."""
        return ("sub",)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "case",
        ["hs256_with_the_rsa_public_key", "alg_none", "alg_outside_the_allow_list", "alg_disagreeing_with_the_key", "no_exp", "non_string_kid"],
    )
    async def test_forged_and_malformed_tokens_are_refused(self, provider, keys, key, case):
        """Refused today by PyJWT's key-bound algorithms; pinned so an upgrade or a key-selection change cannot regress silently."""
        payload = jwt.decode(keys.token(self.claims(), key=key), options={"verify_signature": False})
        if case == "hs256_with_the_rsa_public_key":
            secret = keys.rsa.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            token = _forge({"alg": "HS256", "kid": keys.rsa_kid, "typ": "JWT"}, payload, lambda data: hmac.new(secret, data, hashlib.sha256).digest())
        elif case == "alg_none":
            token = _forge({"alg": "none", "kid": keys.rsa_kid, "typ": "JWT"}, payload, lambda data: b"")
        elif case == "alg_outside_the_allow_list":
            token = jwt.encode(payload, keys.rsa, algorithm="RS384", headers={"kid": keys.rsa_kid})
        elif case == "alg_disagreeing_with_the_key":
            # Signed with the EC key but naming the RSA key's kid.
            token = jwt.encode(payload, keys.ec, algorithm="ES256", headers={"kid": keys.rsa_kid})
        elif case == "no_exp":
            token = keys.token({**self.claims(), "exp": None}, key=key)
        else:  # PyJWT will not encode a non-string kid, so the RS256 signature is made by hand
            token = _forge({"alg": "RS256", "kid": 123, "typ": "JWT"}, payload, lambda data: keys.rsa.sign(data, padding.PKCS1v15(), hashes.SHA256()))
        with pytest.raises(AuthenticationError):
            await provider.authenticate(token)

    @pytest.fixture
    def invalid_credentials(self, keys, key):
        base = self.claims()
        return [
            keys.token(base, key=key, lifetime=-120),  # expired
            keys.token({**base, "aud": "someone-else"}, key=key),  # wrong audience
            keys.token({**base, "iss": "https://other.example"}, key=key),  # wrong issuer
            keys.token(base, key=key, kid="unknown-kid"),  # unknown key id
            _tampered(keys.token(base, key=key)),  # tampered signature
            keys.token({**base, "sub": None}, key=key),  # missing subject
            "not-a-jwt",
        ]


class TestOIDCProviderContract(_OIDCFamilyContract):
    @pytest.fixture
    def provider(self, server):
        return _oidc(server)


class TestOIDCProvider:
    @pytest.mark.asyncio
    async def test_discovery_and_the_key_set_are_fetched_once(self, keys, server):
        provider = _oidc(server)
        for _ in range(3):
            await provider.authenticate(keys.token({}))
            await provider.authenticate(keys.token({}, key="ec"))
        assert (server.discovery_calls, server.jwks_calls) == (1, 1)

    @pytest.mark.asyncio
    async def test_a_configured_jwks_uri_skips_discovery(self, keys, server):
        provider = _oidc(server, jwks=JWKSCache(ISSUER, jwks_uri=JWKS_URI, transport=server.transport))
        await provider.authenticate(keys.token({}))
        assert (server.discovery_calls, server.jwks_calls) == (0, 1)

    @pytest.mark.asyncio
    async def test_an_unknown_kid_refreshes_the_key_set_once_and_then_cools_down(self, keys, server):
        clock = [1000.0]
        cache = JWKSCache(ISSUER, transport=server.transport, refresh_cooldown=30.0, clock=lambda: clock[0])
        provider = _oidc(server, jwks=cache)
        await provider.authenticate(keys.token({}))
        assert server.jwks_calls == 1

        # A rotated key: the set served now carries it, so one refresh finds it.
        rotated = Keys()
        rotated.rsa_kid = "rsa-2"
        server.jwks_override = {"keys": keys.jwks()["keys"] + rotated.jwks()["keys"][:1]}
        principal = await provider.authenticate(rotated.token({}, kid="rsa-2"))
        assert principal.subject == "alice" and server.jwks_calls == 2

        # Another unknown kid inside the cooldown: refused without another fetch.
        with pytest.raises(AuthenticationError):
            await provider.authenticate(keys.token({}, kid="rsa-3"))
        assert server.jwks_calls == 2

        # After the cooldown the next unknown kid refreshes again.
        clock[0] += 31
        with pytest.raises(AuthenticationError):
            await provider.authenticate(keys.token({}, kid="rsa-3"))
        assert server.jwks_calls == 3

    @pytest.mark.asyncio
    async def test_an_unreachable_key_set_keeps_the_previous_keys(self, keys, server):
        provider = _oidc(server)
        await provider.authenticate(keys.token({}))
        server.transport = httpx.MockTransport(lambda request: httpx.Response(503))
        # The cache holds its own client; the keys it already has stay usable.
        assert (await provider.authenticate(keys.token({}))).subject == "alice"

    @pytest.mark.asyncio
    async def test_an_unreachable_issuer_is_an_authentication_error_not_a_crash(self, keys):
        down = JWKSCache(ISSUER, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        with pytest.raises(AuthenticationError, match="JWK set"):
            await OIDCIdentityProvider(issuer=ISSUER, audience=AUDIENCE, jwks=down).authenticate(keys.token({}))

    @pytest.mark.asyncio
    async def test_a_failed_first_load_is_throttled(self, keys):
        """An issuer down at start is asked once per failure cooldown, however many tokens arrive."""
        clock, calls = [1000.0], []

        def refuse(request):
            calls.append(str(request.url))
            return httpx.Response(503)

        cache = JWKSCache(ISSUER, jwks_uri=JWKS_URI, transport=httpx.MockTransport(refuse), failure_cooldown=5.0, clock=lambda: clock[0])
        provider = OIDCIdentityProvider(issuer=ISSUER, audience=AUDIENCE, jwks=cache)
        for _ in range(5):
            with pytest.raises(AuthenticationError, match="JWK set"):
                await provider.authenticate(keys.token({}))
        assert len(calls) == 1

        clock[0] += 6
        with pytest.raises(AuthenticationError):
            await provider.authenticate(keys.token({}))
        assert len(calls) == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [[], "x", 7])
    async def test_a_key_set_body_that_is_not_an_object_is_an_authentication_error(self, keys, body):
        cache = JWKSCache(ISSUER, jwks_uri=JWKS_URI, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
        with pytest.raises(AuthenticationError, match="JWK set"):
            await OIDCIdentityProvider(issuer=ISSUER, audience=AUDIENCE, jwks=cache).authenticate(keys.token({}))

    @pytest.mark.asyncio
    async def test_a_known_key_does_not_wait_behind_a_slow_refresh(self, keys, server):
        """Selecting a cached key takes no lock, so one unknown kid against a slow key-set URL stalls only itself."""
        release = threading.Event()
        first = []

        def handle(request):
            if first:  # every fetch after the first load hangs until released
                release.wait(5)
            first.append(True)
            return server._handle(request)

        provider = _oidc(server, jwks=JWKSCache(ISSUER, jwks_uri=JWKS_URI, transport=httpx.MockTransport(handle)))
        await provider.authenticate(keys.token({}))

        # Timed from before the refresh starts: a refresh that blocks the loop stalls this test too.
        started = time.monotonic()
        stuck = asyncio.create_task(provider.authenticate(keys.token({}, kid="rsa-unknown")))
        await asyncio.sleep(0.05)
        try:
            principal = await provider.authenticate(keys.token({}))
            elapsed = time.monotonic() - started
        finally:
            release.set()
        assert principal.subject == "alice"
        assert elapsed < 1.0, f"the known key waited {elapsed:.1f}s behind the refresh"
        with pytest.raises(AuthenticationError):
            await stuck

    def test_one_provider_serves_threads_that_each_run_their_own_event_loop(self, keys):
        """Azure runs sync functions on a thread pool, where each call gets a fresh loop (#603 review)."""
        jwks = keys.jwks()

        def slow(request):
            time.sleep(0.2)  # long enough for both cold starts to overlap
            return httpx.Response(200, json=jwks)

        provider = OIDCIdentityProvider(
            issuer=ISSUER, audience=AUDIENCE, jwks=JWKSCache(ISSUER, jwks_uri=JWKS_URI, transport=httpx.MockTransport(slow))
        )
        results: list = []

        def call():
            try:
                results.append(asyncio.run(provider.authenticate(keys.token({}))).subject)
            except Exception as exc:  # recorded so the assertion shows what went wrong
                results.append(exc)

        threads = [threading.Thread(target=call, daemon=True) for _ in range(2)]  # daemon: a hung caller cannot hold pytest open
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads), "a cold-start caller never woke up"
        assert results == ["alice", "alice"]

    def test_a_rotated_key_is_fetched_on_a_later_event_loop(self, keys):
        """Against a real keep-alive server: a connection pooled on a closed loop must not break the refresh."""
        with _KeepAliveJWKSServer(keys) as live:
            provider = OIDCIdentityProvider(issuer=live.issuer, audience=AUDIENCE)
            assert asyncio.run(provider.authenticate(keys.token({"iss": live.issuer}))).subject == "alice"

            rotated = Keys()
            rotated.rsa_kid = "rsa-2"
            live.jwks = {"keys": keys.jwks()["keys"] + rotated.jwks()["keys"][:1]}
            principal = asyncio.run(provider.authenticate(rotated.token({"iss": live.issuer}, kid="rsa-2")))
            assert principal.subject == "alice"
            asyncio.run(provider.close())

    @pytest.mark.parametrize("algorithms", [["RS265"], [], ["none"], ["RS256", "None"]])
    def test_unusable_algorithms_are_refused_at_construction(self, server, algorithms):
        """A misspelled, empty or unsigned list would build and then refuse every token at request time."""
        with pytest.raises(AKConfigError, match="algorithm"):
            _oidc(server, algorithms=algorithms)

    def test_symmetric_algorithms_are_refused_at_construction(self, server):
        with pytest.raises(AKConfigError, match="HS256"):
            _oidc(server, algorithms=["RS256", "HS256"])

    @pytest.mark.asyncio
    async def test_required_claims_must_be_present(self, keys, server):
        provider = _oidc(server, required_claims=["email_verified"])
        with pytest.raises(AuthenticationError, match="email_verified"):
            await provider.authenticate(keys.token({}))
        assert (await provider.authenticate(keys.token({"email_verified": True}))).claims["email_verified"] is True

    @pytest.mark.asyncio
    async def test_claim_paths_are_dotted_and_a_string_group_becomes_a_list(self, keys, server):
        provider = _oidc(server, subject_claim="user.id", groups_claim="realm_access.roles")
        token = keys.token({"sub": None, "user": {"id": "u-42"}, "realm_access": {"roles": "admin"}})
        principal = await provider.authenticate(token)
        assert (principal.subject, principal.groups) == ("u-42", ["admin"])
        assert principal.claims["user"] == {"id": "u-42"}

    @pytest.mark.asyncio
    async def test_a_missing_groups_claim_yields_no_groups_and_roles_are_never_written(self, keys, server):
        principal = await _oidc(server).authenticate(keys.token({}))
        assert principal.groups == [] and principal.roles == []

    @pytest.mark.asyncio
    async def test_nbf_in_the_future_is_refused_beyond_the_leeway(self, keys, server):
        soon = keys.token({"nbf": int(time.time()) + 10})
        assert (await _oidc(server, leeway=30).authenticate(soon)).subject == "alice"
        with pytest.raises(AuthenticationError):
            await _oidc(server, leeway=0).authenticate(soon)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("configured", ["https://tenant.eu.auth0.com/", "https://tenant.eu.auth0.com"])
    async def test_a_trailing_slash_on_the_issuer_is_tolerated_either_way(self, keys, configured):
        """Auth0 issuers carry a trailing slash in `iss`; the configured value may have it or not."""
        issuer = "https://tenant.eu.auth0.com/"
        server = JWKSServer(keys, issuer=issuer.rstrip("/"), jwks_uri=f"{issuer}.well-known/jwks.json")
        provider = OIDCIdentityProvider(configured, AUDIENCE, jwks=JWKSCache(configured, transport=server.transport))

        principal = await provider.authenticate(keys.token({"iss": issuer}))

        assert principal.namespace == issuer
        assert provider.security_scheme() == ("openIdConnect", {"url": "https://tenant.eu.auth0.com/.well-known/openid-configuration"})
        with pytest.raises(AuthenticationError):
            await provider.authenticate(keys.token({"iss": "https://other.eu.auth0.com/"}))

    @pytest.mark.asyncio
    async def test_an_auth0_token_authenticates_through_the_oidc_type(self, keys):
        """Auth0 is an `oidc` configuration: the API identifier as audience, roles in a namespaced claim."""
        issuer = "https://acme.eu.auth0.com/"
        server = JWKSServer(keys, issuer=issuer.rstrip("/"), jwks_uri=f"{issuer}.well-known/jwks.json")
        provider = OIDCIdentityProvider(
            issuer, "https://api.acme.com", groups_claim="https://acme.com/roles", jwks=JWKSCache(issuer, transport=server.transport)
        )
        token = keys.token(
            {
                "iss": issuer,
                "aud": ["https://api.acme.com", f"{issuer}userinfo"],
                "sub": "auth0|64f1c2",
                "https://acme.com/roles": ["admin"],
                "permissions": ["read:reports"],
                "org_id": "org_123",
            }
        )

        principal = await provider.authenticate(token)

        assert (principal.subject, principal.namespace, principal.groups) == ("auth0|64f1c2", issuer, ["admin"])
        assert principal.claims["permissions"] == ["read:reports"] and principal.claims["org_id"] == "org_123"
        assert principal.claims["https://acme.com/roles"] == ["admin"]

    def test_the_security_scheme_is_openid_connect_with_the_discovery_url(self, server):
        assert _oidc(server).security_scheme() == ("openIdConnect", {"url": DISCOVERY})

    @pytest.mark.asyncio
    async def test_close_releases_the_client(self, server):
        provider = _oidc(server)
        await provider.close()
        await provider.close()

    def test_from_config_builds_the_provider_from_the_block(self, server):
        config = _IdentityProviderConfig(issuer=ISSUER, audience=AUDIENCE, jwks_uri=JWKS_URI, leeway=5, required_claims=["email"])
        provider = OIDCIdentityProvider.from_config(config)
        assert isinstance(provider, OIDCIdentityProvider)
        assert provider.security_scheme() == ("openIdConnect", {"url": DISCOVERY})


COGNITO_ISSUER = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_abc123"


class TestCognitoProviderContract(_OIDCFamilyContract):
    def issuer(self) -> str:
        return COGNITO_ISSUER

    def claims(self) -> dict:
        return {
            "iss": COGNITO_ISSUER,
            "aud": None,
            "client_id": AUDIENCE,
            "token_use": "access",
            "cognito:groups": ["ops", "dev"],
            "username": "alice",
        }

    def expected(self) -> dict:
        return {"subject": "alice", "namespace": COGNITO_ISSUER, "groups": ["ops", "dev"]}

    def claim_keys_removed(self) -> tuple[str, ...]:
        return ("sub",)

    @pytest.fixture
    def provider(self, keys):
        server = JWKSServer(keys, issuer=COGNITO_ISSUER, jwks_uri=f"{COGNITO_ISSUER}/.well-known/jwks.json")
        return CognitoIdentityProvider(
            region="eu-west-1", user_pool_id="eu-west-1_abc123", audience=AUDIENCE, jwks=JWKSCache(COGNITO_ISSUER, transport=server.transport)
        )

    @pytest.fixture
    def invalid_credentials(self, keys, key):
        base = self.claims()
        return [
            keys.token(base, key=key, lifetime=-120),
            keys.token({**base, "client_id": "someone-else"}, key=key),  # an access token's audience is client_id
            keys.token({**base, "iss": ISSUER}, key=key),
            keys.token(base, key=key, kid="unknown-kid"),
            _tampered(keys.token(base, key=key)),
            keys.token({**base, "sub": None}, key=key),
            keys.token({**base, "token_use": "id"}, key=key),  # the wrong token_use
        ]


class TestCognitoProvider:
    @pytest.mark.asyncio
    async def test_an_id_token_is_checked_on_aud_when_configured(self, keys):
        server = JWKSServer(keys, issuer=COGNITO_ISSUER, jwks_uri=f"{COGNITO_ISSUER}/.well-known/jwks.json")
        provider = CognitoIdentityProvider(
            region="eu-west-1",
            user_pool_id="eu-west-1_abc123",
            audience=AUDIENCE,
            token_use="id",
            jwks=JWKSCache(COGNITO_ISSUER, transport=server.transport),
        )
        principal = await provider.authenticate(keys.token({"iss": COGNITO_ISSUER, "token_use": "id", "cognito:groups": "admins"}))
        assert principal.groups == ["admins"]
        with pytest.raises(AuthenticationError):
            await provider.authenticate(keys.token({"iss": COGNITO_ISSUER, "token_use": "id", "aud": "other"}))

    def test_from_config_derives_the_issuer(self):
        config = _IdentityProviderConfig(
            type="cognito", audience=AUDIENCE, cognito=_CognitoProviderConfig(region="eu-west-1", user_pool_id="eu-west-1_abc123")
        )
        provider = CognitoIdentityProvider.from_config(config)
        assert provider.security_scheme() == ("openIdConnect", {"url": f"{COGNITO_ISSUER}/.well-known/openid-configuration"})

    def test_from_config_requires_an_audience(self):
        config = _IdentityProviderConfig(type="cognito", cognito=_CognitoProviderConfig(region="eu-west-1", user_pool_id="p"))
        with pytest.raises(AKConfigError, match="audience"):
            CognitoIdentityProvider.from_config(config)


TENANT = "11111111-2222-3333-4444-555555555555"
ENTRA_ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"


class TestEntraProviderContract(_OIDCFamilyContract):
    def issuer(self) -> str:
        return ENTRA_ISSUER

    def claims(self) -> dict:
        return {"iss": ENTRA_ISSUER, "oid": "oid-alice", "tid": TENANT, "groups": ["ops", "dev"], "roles": ["Reader"], "wids": ["w1"]}

    def expected(self) -> dict:
        return {"subject": "oid-alice", "namespace": ENTRA_ISSUER, "groups": ["ops", "dev"]}

    def claim_keys_removed(self) -> tuple[str, ...]:
        return ("oid",)

    @pytest.fixture
    def provider(self, keys):
        server = JWKSServer(keys, issuer=ENTRA_ISSUER, jwks_uri=f"{ENTRA_ISSUER}/keys")
        return EntraIdentityProvider(tenant_id=TENANT, audience=AUDIENCE, jwks=JWKSCache(ENTRA_ISSUER, transport=server.transport))

    @pytest.fixture
    def invalid_credentials(self, keys, key):
        base = self.claims()
        return [
            keys.token(base, key=key, lifetime=-120),
            keys.token({**base, "aud": "someone-else"}, key=key),
            keys.token({**base, "iss": ISSUER}, key=key),
            keys.token(base, key=key, kid="unknown-kid"),
            _tampered(keys.token(base, key=key)),
            keys.token({**base, "oid": None}, key=key),  # the subject is oid
            keys.token({**base, "tid": "other-tenant"}, key=key),
        ]


class TestCognitoTokenUse:
    def test_a_misspelled_token_use_is_refused_by_the_config(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _CognitoProviderConfig(region="eu-west-1", user_pool_id="p", token_use="acess")

    def test_a_misspelled_token_use_is_refused_by_the_constructor(self):
        with pytest.raises(AKConfigError, match="token_use"):
            CognitoIdentityProvider(region="eu-west-1", user_pool_id="p", audience=AUDIENCE, token_use="acess")


class TestEntraProvider:
    @pytest.mark.asyncio
    async def test_a_groups_overage_yields_no_groups_and_warns_once(self, keys, caplog):
        server = JWKSServer(keys, issuer=ENTRA_ISSUER, jwks_uri=f"{ENTRA_ISSUER}/keys")
        provider = EntraIdentityProvider(tenant_id=TENANT, audience=AUDIENCE, jwks=JWKSCache(ENTRA_ISSUER, transport=server.transport))
        EntraIdentityProvider._overage_warned = False
        overage = {"iss": ENTRA_ISSUER, "oid": "oid-alice", "tid": TENANT, "_claim_names": {"groups": "src1"}}
        with caplog.at_level("WARNING", logger="ak.identity.provider.entra"):
            first = await provider.authenticate(keys.token(overage))
            second = await provider.authenticate(keys.token(overage))
        assert first.groups == [] and second.groups == []
        assert len([record for record in caplog.records if "overage" in record.getMessage()]) == 1

    @pytest.mark.asyncio
    async def test_the_overage_marker_concerns_only_the_groups_claim(self, keys):
        """With the groups path on app roles, a groups overage leaves the roles alone (#603 review)."""
        server = JWKSServer(keys, issuer=ENTRA_ISSUER, jwks_uri=f"{ENTRA_ISSUER}/keys")
        provider = EntraIdentityProvider(
            tenant_id=TENANT, audience=AUDIENCE, groups_claim="roles", jwks=JWKSCache(ENTRA_ISSUER, transport=server.transport)
        )
        token = {"iss": ENTRA_ISSUER, "oid": "oid-alice", "tid": TENANT, "roles": ["Admin"], "_claim_names": {"groups": "src1"}}
        assert (await provider.authenticate(keys.token(token))).groups == ["Admin"]

    def test_from_config_derives_the_issuer(self):
        provider = EntraIdentityProvider.from_config(
            _IdentityProviderConfig(type="entra", audience=AUDIENCE, entra=_EntraProviderConfig(tenant_id=TENANT))
        )
        assert provider.security_scheme() == ("openIdConnect", {"url": f"{ENTRA_ISSUER}/.well-known/openid-configuration"})


PROJECT = "demo-project"
FIREBASE_ISSUER = f"https://securetoken.google.com/{PROJECT}"
FIREBASE_JWKS = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"


class TestFirebaseProviderContract(_OIDCFamilyContract):
    def issuer(self) -> str:
        return FIREBASE_ISSUER

    def claims(self) -> dict:
        return {"iss": FIREBASE_ISSUER, "aud": PROJECT, "roles": ["ops", "dev"], "admin": True}

    def expected(self) -> dict:
        return {"subject": "alice", "namespace": FIREBASE_ISSUER, "groups": ["ops", "dev"]}

    def claim_keys_removed(self) -> tuple[str, ...]:
        return ("sub",)

    @pytest.fixture
    def provider(self, keys):
        server = JWKSServer(keys, issuer=FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS)
        return FirebaseIdentityProvider(project_id=PROJECT, jwks=JWKSCache(FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS, transport=server.transport))

    @pytest.fixture
    def invalid_credentials(self, keys, key):
        base = self.claims()
        return [
            keys.token(base, key=key, lifetime=-120),
            keys.token({**base, "aud": "other-project"}, key=key),
            keys.token({**base, "iss": ISSUER}, key=key),
            keys.token(base, key=key, kid="unknown-kid"),
            _tampered(keys.token(base, key=key)),
            keys.token({**base, "sub": None}, key=key),
        ]


class TestFirebaseProvider:
    def test_the_defaults_are_googles(self):
        provider = FirebaseIdentityProvider.from_config(
            _IdentityProviderConfig(type="firebase", firebase=_FirebaseProviderConfig(project_id=PROJECT))
        )
        assert provider.security_scheme() == ("openIdConnect", {"url": f"{FIREBASE_ISSUER}/.well-known/openid-configuration"})
        assert provider.jwks.jwks_uri == FIREBASE_JWKS

    @pytest.mark.asyncio
    async def test_the_roles_custom_claim_reaches_a_pass_through_mapper(self, keys):
        """``roles`` is both the default groups path and a custom claim the mapper may lift as it is."""
        server = JWKSServer(keys, issuer=FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS)
        firebase = FirebaseIdentityProvider(project_id=PROJECT, jwks=JWKSCache(FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS, transport=server.transport))
        provider = MappedIdentityProvider(firebase, MappingRoleMapper({}, pass_through="roles"))

        principal = await provider.authenticate(keys.token({"iss": FIREBASE_ISSUER, "aud": PROJECT, "roles": ["editor", "billing"]}))

        assert (principal.groups, principal.roles) == (["editor", "billing"], ["editor", "billing"])
        assert principal.claims["roles"] == ["editor", "billing"]

    @pytest.mark.asyncio
    async def test_a_boolean_custom_claim_stays_in_claims_for_a_mapper(self, keys):
        server = JWKSServer(keys, issuer=FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS)
        provider = FirebaseIdentityProvider(project_id=PROJECT, jwks=JWKSCache(FIREBASE_ISSUER, jwks_uri=FIREBASE_JWKS, transport=server.transport))
        principal = await provider.authenticate(keys.token({"iss": FIREBASE_ISSUER, "aud": PROJECT, "admin": True}))
        assert principal.claims["admin"] is True and principal.groups == []


class TestFactoryBranches:
    @pytest.mark.parametrize(
        "config, cls",
        [
            (_IdentityProviderConfig(issuer=ISSUER, audience=AUDIENCE, jwks_uri=JWKS_URI), OIDCIdentityProvider),
            (
                _IdentityProviderConfig(type="cognito", audience=AUDIENCE, cognito=_CognitoProviderConfig(region="eu-west-1", user_pool_id="p")),
                CognitoIdentityProvider,
            ),
            (_IdentityProviderConfig(type="entra", audience=AUDIENCE, entra=_EntraProviderConfig(tenant_id=TENANT)), EntraIdentityProvider),
            (_IdentityProviderConfig(type="firebase", firebase=_FirebaseProviderConfig(project_id=PROJECT)), FirebaseIdentityProvider),
        ],
    )
    def test_each_family_member_is_built_by_its_short_name(self, config, cls):
        assert isinstance(IdentityProviderFactory.create(_IdentityConfig(provider=config)), cls)

    def test_a_short_name_is_matched_whatever_its_case(self):
        config = _IdentityProviderConfig(type="OIDC", issuer=ISSUER, audience=AUDIENCE)
        assert isinstance(IdentityProviderFactory.create(_IdentityConfig(provider=config)), OIDCIdentityProvider)

    @pytest.mark.parametrize("name", ["oidc", "cognito", "entra", "firebase"])
    def test_the_missing_extra_is_named(self, monkeypatch, name):
        """Poisoning the branch's module makes its import raise ImportError, which require_extra rewrites with the install hint."""
        monkeypatch.setitem(sys.modules, f"agentkernel.identity.provider.{name}", None)
        blocks = {
            "oidc": {"issuer": ISSUER, "audience": AUDIENCE},
            "cognito": {"audience": AUDIENCE, "cognito": _CognitoProviderConfig(region="eu-west-1", user_pool_id="p")},
            "entra": {"audience": AUDIENCE, "entra": _EntraProviderConfig(tenant_id=TENANT)},
            "firebase": {"firebase": _FirebaseProviderConfig(project_id=PROJECT)},
        }
        with pytest.raises(ImportError, match=f"identity.provider.type: {name} requires the 'auth' extra") as exc:
            IdentityProviderFactory.create(_IdentityConfig(provider=_IdentityProviderConfig(type=name, **blocks[name])))
        assert 'uv add "agentkernel[auth]"' in str(exc.value)
