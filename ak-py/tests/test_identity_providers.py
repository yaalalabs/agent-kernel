"""
Identity providers (spec `docs/specs/603-identity-rbac-registry/` section 4, iteration 4).

What is pinned here: the static provider resolves its credentials through the secret capability,
compares every entry in constant time and yields the `static` namespace; the role mapper is the
one producer of `Principal.roles`; and the factory selects a provider by short name or dotted path
and wraps it with the configured mapper. The OIDC family and the request authenticator arrive in
later iterations with their own cases, run through the same contract suites.
"""

import pytest
from test_secret_manager import _DictSecretProvider

from agentkernel.core.config import _IdentityConfig, _IdentityProviderConfig, _RoleMapperConfig, _StaticPrincipalConfig, _StaticProviderConfig
from agentkernel.core.model import Principal
from agentkernel.core.util.factory import AKConfigError
from agentkernel.identity import AuthenticationError, IdentityProvider, IdentityProviderFactory, RequestContext, RoleMapper
from agentkernel.identity.provider.base import ClaimPath
from agentkernel.identity.provider.roles import MappedIdentityProvider, MappingRoleMapper, RoleMapperFactory
from agentkernel.identity.provider.static import StaticIdentityProvider
from agentkernel.identity.provider.testing import IdentityProviderContract, RoleMapperContract
from agentkernel.secret import SecretManager

ALICE = {"subject": "alice", "groups": ["ops"], "roles": ["admin"], "claims": {"email": "alice@example.com"}}
REPORTER = {"subject": "reporter", "kind": "service", "claims": {"team": "finance"}}
PRINCIPALS = {"ALICE_TOKEN": ALICE, "REPORTER_TOKEN": REPORTER}
VALUES = {"ALICE_TOKEN": "alice-secret", "REPORTER_TOKEN": "reporter-secret"}


@pytest.fixture
def secrets(monkeypatch) -> SecretManager:
    """A secret manager over a seeded dict, with the environment kept out of the way."""
    for key in VALUES:
        monkeypatch.delenv(key, raising=False)
    provider = _DictSecretProvider()
    for key, value in VALUES.items():
        provider.seed(key, value)
    return SecretManager(provider=provider, cache_ttl=0)


@pytest.fixture
def current_secrets(monkeypatch, secrets):
    """What `SecretManager.current()` hands to code that does not take an explicit manager."""
    monkeypatch.setattr(SecretManager, "current", classmethod(lambda cls: secrets))
    return secrets


@pytest.fixture(autouse=True)
def _reset_factory():
    IdentityProviderFactory.reset()
    yield
    IdentityProviderFactory.reset()


def _principal(**overrides) -> Principal:
    fields = {"subject": "alice", "provider": "oidc", "namespace": "https://issuer.example"}
    fields.update(overrides)
    return Principal(**fields)


class EchoProvider(IdentityProvider):
    """A bring-your-own provider: the factory hands it the whole `identity.provider` block."""

    name = "echo"

    def __init__(self, config: _IdentityProviderConfig):
        self.config = config

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        return Principal(subject=credential, provider=self.name, namespace="echo")


class EverybodyIsReader(RoleMapper):
    """A bring-your-own mapper: receives the whole principal."""

    def __init__(self, config: _RoleMapperConfig):
        self.config = config

    def map(self, principal: Principal) -> list[str]:
        return ["reader", f"subject:{principal.subject}"]


class TestStaticProviderContract(IdentityProviderContract):
    @pytest.fixture
    def provider(self, secrets):
        return StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets)

    @pytest.fixture
    def valid_credential(self):
        return "alice-secret", {**ALICE, "namespace": "static"}

    @pytest.fixture
    def invalid_credentials(self):
        return ["", "alice-secre", "alice-secret ", "ALICE_TOKEN", "reporter-secret-x"]


class TestStaticProvider:
    @pytest.mark.asyncio
    async def test_every_configured_principal_authenticates_with_its_own_secret(self, secrets):
        provider = StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets)

        alice = await provider.authenticate("alice-secret")
        reporter = await provider.authenticate("reporter-secret")

        assert (alice.subject, alice.kind, alice.groups, alice.roles) == ("alice", "user", ["ops"], ["admin"])
        assert (reporter.subject, reporter.kind, reporter.claims) == ("reporter", "service", {"team": "finance"})
        assert {alice.provider, alice.namespace, reporter.provider, reporter.namespace} == {"static"}

    @pytest.mark.asyncio
    async def test_the_credential_value_comes_from_the_secret_capability_never_from_the_block(self, secrets):
        """The block names the secret key; the value is resolved at construction and the key itself never authenticates."""
        provider = StaticIdentityProvider(principals={"ALICE_TOKEN": ALICE}, secrets=secrets)

        assert secrets._provider.calls == ["ALICE_TOKEN"]
        with pytest.raises(AuthenticationError):
            await provider.authenticate("ALICE_TOKEN")

    def test_a_missing_secret_is_a_configuration_error_naming_the_key(self, secrets):
        with pytest.raises(AKConfigError, match="MISSING_TOKEN"):
            StaticIdentityProvider(principals={"MISSING_TOKEN": ALICE}, secrets=secrets)

    def test_a_malformed_secret_key_is_a_configuration_error(self, secrets):
        with pytest.raises(AKConfigError, match="not-a-key"):
            StaticIdentityProvider(principals={"not-a-key": ALICE}, secrets=secrets)

    def test_two_principals_sharing_a_credential_are_refused(self, secrets):
        secrets._provider.seed("TWIN_TOKEN", "alice-secret")
        with pytest.raises(AKConfigError, match="same credential"):
            StaticIdentityProvider(principals={"ALICE_TOKEN": ALICE, "TWIN_TOKEN": REPORTER}, secrets=secrets)

    @pytest.mark.asyncio
    async def test_every_entry_is_compared_even_after_a_match(self, secrets, monkeypatch):
        """Constant time over all entries: a timing side channel must not reveal which entry matched."""
        import agentkernel.identity.provider.static as static_module

        compared = []
        real = static_module.hmac.compare_digest
        monkeypatch.setattr(static_module.hmac, "compare_digest", lambda a, b: compared.append(a) or real(a, b))
        provider = StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets)

        await provider.authenticate("alice-secret")

        assert len(compared) == len(PRINCIPALS)

    @pytest.mark.asyncio
    async def test_from_config_builds_the_principals_from_the_static_block(self, secrets):
        config = _IdentityProviderConfig(
            type="static",
            static=_StaticProviderConfig(principals={"ALICE_TOKEN": _StaticPrincipalConfig(subject="alice", groups=["ops"])}),
        )

        provider = StaticIdentityProvider.from_config(config, secrets=secrets)

        alice = await provider.authenticate("alice-secret")
        assert (alice.subject, alice.groups, alice.roles, alice.claims, alice.kind) == ("alice", ["ops"], [], {}, "user")

    def test_the_security_scheme_is_bearer(self, secrets):
        assert StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets).security_scheme() == ("bearer", {})


class TestClaimPath:
    @pytest.mark.parametrize(
        "path, expected",
        [("sub", "alice"), ("realm_access.roles", ["a", "b"]), ("realm_access.missing", None), ("sub.deeper", None), ("missing", None)],
    )
    def test_reads_a_dotted_path_or_none(self, path, expected):
        payload = {"sub": "alice", "realm_access": {"roles": ["a", "b"]}}
        assert ClaimPath.read(payload, path) == expected

    def test_a_claim_name_containing_dots_is_one_key_first(self):
        """Auth0 namespaces its custom claims as URLs; such a name is tried whole before it is split."""
        payload = {"https://acme.com/roles": ["admin"], "a.b": 1, "a": {"b": 2}}
        assert ClaimPath.read(payload, "https://acme.com/roles") == ["admin"]
        assert ClaimPath.read(payload, "a.b") == 1
        assert ClaimPath.read({"a": {"b": 2}}, "a.b") == 2


class TestMappingRoleMapperContract(RoleMapperContract):
    @pytest.fixture
    def mapper(self):
        return MappingRoleMapper(
            mapping={"ops": ["operator", "reader"], "finance": ["fin"], "b": ["bee"], "ops2": ["reader"]}, pass_through="realm_access.roles"
        )

    @pytest.fixture
    def cases(self):
        return [
            # groups looked up in the mapping, in order of first appearance, de-duplicated
            (_principal(groups=["ops", "ops2"]), ["operator", "reader"]),
            # string and list claim values looked up in the mapping
            (_principal(claims={"department": "finance", "teams": ["a", "b"]}), ["fin", "bee"]),
            # pass_through: a string and a list at the claim path become roles as they are
            (_principal(claims={"realm_access": {"roles": "admin"}}), ["admin"]),
            (_principal(claims={"realm_access": {"roles": ["x", "y", "x"]}}), ["x", "y"]),
            # boolean and nested claim values are not mapped by the built-in mapper (Q14)
            (_principal(claims={"finance": True, "nested": {"department": "finance"}}), []),
            (_principal(), []),
        ]


class TestNamespacedClaimPassThrough:
    def test_a_url_shaped_claim_name_passes_through(self):
        mapper = MappingRoleMapper(mapping={}, pass_through="https://acme.com/roles")
        assert mapper.map(_principal(claims={"https://acme.com/roles": ["admin", "reader"]})) == ["admin", "reader"]


class TestRoleMapperFactory:
    def test_mapping_is_the_built_in(self):
        mapper = RoleMapperFactory.create(_RoleMapperConfig(type="mapping", mapping={"ops": ["operator"]}, pass_through="roles"))
        assert isinstance(mapper, MappingRoleMapper)
        assert mapper.map(_principal(groups=["ops"], claims={"roles": ["x"]})) == ["operator", "x"]

    def test_a_dotted_path_receives_the_block(self):
        config = _RoleMapperConfig(type="test_identity_providers.EverybodyIsReader")
        mapper = RoleMapperFactory.create(config)
        assert isinstance(mapper, EverybodyIsReader) and mapper.config is config
        assert mapper.map(_principal()) == ["reader", "subject:alice"]

    def test_an_unknown_type_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="role_mapper"):
            RoleMapperFactory.create(_RoleMapperConfig(type="ldap"))


class TestMappedIdentityProvider:
    @pytest.mark.asyncio
    async def test_the_mapper_is_the_one_producer_of_roles(self, secrets):
        """The static block's roles are replaced, not merged: `Principal.roles` has exactly one producer."""
        inner = StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets)
        mapped = MappedIdentityProvider(inner, MappingRoleMapper(mapping={"ops": ["operator"]}))

        alice = await mapped.authenticate("alice-secret")

        assert alice.roles == ["operator"]
        assert alice.groups == ["ops"] and alice.subject == "alice"

    @pytest.mark.asyncio
    async def test_everything_else_delegates(self, secrets):
        inner = StaticIdentityProvider(principals=PRINCIPALS, secrets=secrets)
        mapped = MappedIdentityProvider(inner, MappingRoleMapper(mapping={}))

        assert mapped.name == inner.name
        assert mapped.security_scheme() == inner.security_scheme()
        await mapped.close()
        with pytest.raises(AuthenticationError):
            await mapped.authenticate("nope")


def _static_identity(role_mapper: _RoleMapperConfig | None = None) -> _IdentityConfig:
    principals = {key: _StaticPrincipalConfig(**fields) for key, fields in PRINCIPALS.items()}
    return _IdentityConfig(
        provider=_IdentityProviderConfig(type="static", static=_StaticProviderConfig(principals=principals)), role_mapper=role_mapper
    )


class TestIdentityProviderFactory:
    def test_static_is_a_built_in(self, current_secrets):
        provider = IdentityProviderFactory.create(_static_identity())
        assert isinstance(provider, StaticIdentityProvider)

    @pytest.mark.asyncio
    async def test_a_role_mapper_block_wraps_the_provider(self, current_secrets):
        provider = IdentityProviderFactory.create(_static_identity(_RoleMapperConfig(mapping={"ops": ["operator"]})))

        assert isinstance(provider, MappedIdentityProvider)
        assert (await provider.authenticate("alice-secret")).roles == ["operator"]

    def test_a_dotted_path_receives_the_provider_block(self):
        identity = _IdentityConfig(provider=_IdentityProviderConfig(type="test_identity_providers.EchoProvider"))
        provider = IdentityProviderFactory.create(identity)
        assert isinstance(provider, EchoProvider) and provider.config is identity.provider

    def test_an_unknown_short_name_is_a_configuration_error(self):
        with pytest.raises(AKConfigError, match="unknown identity provider type 'ldap'"):
            IdentityProviderFactory.create(_IdentityConfig(provider=_IdentityProviderConfig(type="ldap")))

    def test_get_is_none_without_an_identity_block(self, monkeypatch):
        class _Cfg:
            identity = None

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))
        assert IdentityProviderFactory.get() is None

    def test_get_builds_once_and_reset_drops_it(self, monkeypatch, current_secrets):
        class _Cfg:
            identity = _static_identity()

        monkeypatch.setattr("agentkernel.core.config.AKConfig.get", classmethod(lambda cls: _Cfg))

        first = IdentityProviderFactory.get()
        assert first is IdentityProviderFactory.get()
        IdentityProviderFactory.reset()
        assert IdentityProviderFactory.get() is not first


class TestExports:
    def test_the_package_exports_resolve_lazily_to_their_modules(self):
        import agentkernel.identity as identity

        assert identity.IdentityProvider is IdentityProvider
        assert identity.AuthenticationError is AuthenticationError
        assert "IdentityProviderContract" not in identity.__all__
        with pytest.raises(AttributeError):
            identity.NotAThing
