"""Public testing helpers for identity providers and role mappers. Imports pytest, so import from test code only."""

from typing import Any

import pytest

from ...core.model import Principal
from ..errors import AuthenticationError
from .base import IdentityProvider, RequestContext
from .roles import RoleMapper


class IdentityProviderContract:
    """Conformance suite every IdentityProvider subclasses. Override the three fixtures.

    Not prefixed ``Test`` so pytest does not collect it on its own. The token-shaped failures
    (expired, wrong audience, wrong issuer, unknown key, tampered signature, missing subject) are
    what an OIDC-family subclass lists in ``invalid_credentials``; a provider with other failure
    modes lists those.
    """

    @pytest.fixture
    def provider(self) -> IdentityProvider:
        """The provider under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `provider` fixture")

    @pytest.fixture
    def valid_credential(self) -> tuple[str, dict[str, Any]]:
        """A credential the provider accepts and the principal fields it must yield.

        The fields are ``subject`` and ``namespace`` at least, plus ``groups``, ``claims``, ``kind``
        and ``roles`` when the provider asserts them (``roles`` defaults to empty: only a provider
        that issues roles itself lists any).
        """
        raise NotImplementedError("subclasses must override the `valid_credential` fixture")

    @pytest.fixture
    def invalid_credentials(self) -> list[str]:
        """Credentials the provider must refuse; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `invalid_credentials` fixture")

    def test_contract_name_is_declared(self, provider):
        assert isinstance(provider.name, str) and provider.name

    @pytest.mark.asyncio
    async def test_contract_a_valid_credential_yields_the_expected_principal(self, provider, valid_credential):
        credential, expected = valid_credential

        principal = await provider.authenticate(credential)

        assert principal.subject == expected["subject"]
        assert principal.namespace == expected["namespace"]
        assert principal.provider == provider.name
        assert principal.kind == expected.get("kind", "user")
        assert principal.groups == expected.get("groups", [])
        assert principal.roles == expected.get("roles", [])
        assert principal.claims == expected.get("claims", {})
        assert not principal.is_anonymous

    @pytest.mark.asyncio
    async def test_contract_the_provider_sets_neither_actor_nor_credential_ref(self, provider, valid_credential):
        """The actor is Runtime's to set and the credential handle the authenticator's."""
        principal = await provider.authenticate(valid_credential[0])
        assert principal.actor is None and principal.credential_ref is None

    @pytest.mark.asyncio
    async def test_contract_the_request_context_is_optional_and_changes_nothing(self, provider, valid_credential):
        credential, _ = valid_credential
        bare = await provider.authenticate(credential)
        with_context = await provider.authenticate(credential, RequestContext(path="/api/v1/chat", http_method="POST", headers={}))
        assert with_context == bare

    @pytest.mark.asyncio
    async def test_contract_an_invalid_credential_is_an_authentication_error(self, provider, invalid_credentials):
        assert invalid_credentials, "the subclass must list at least one credential the provider refuses"
        for credential in invalid_credentials:
            with pytest.raises(AuthenticationError):
                await provider.authenticate(credential)

    def test_contract_security_scheme_has_a_name_and_settings(self, provider):
        scheme, settings = provider.security_scheme()
        assert isinstance(scheme, str) and scheme
        assert isinstance(settings, dict)

    @pytest.mark.asyncio
    async def test_contract_close_is_awaitable_and_idempotent(self, provider):
        await provider.close()
        await provider.close()


class RoleMapperContract:
    """Conformance suite every RoleMapper subclasses. Override `mapper` and `cases`.

    Not prefixed ``Test`` so pytest does not collect it on its own.
    """

    @pytest.fixture
    def mapper(self) -> RoleMapper:
        """The mapper under contract; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `mapper` fixture")

    @pytest.fixture
    def cases(self) -> list[tuple[Principal, list[str]]]:
        """Principals and the roles the mapper must derive for each; every subclass must override this fixture."""
        raise NotImplementedError("subclasses must override the `cases` fixture")

    def test_contract_each_case_maps_to_its_roles(self, mapper, cases):
        assert cases, "the subclass must list at least one case"
        for principal, expected in cases:
            assert mapper.map(principal) == expected, principal

    def test_contract_roles_are_strings_without_duplicates(self, mapper, cases):
        for principal, _ in cases:
            roles = mapper.map(principal)
            assert all(isinstance(role, str) for role in roles)
            assert len(roles) == len(set(roles))

    def test_contract_mapping_is_stable_and_leaves_the_principal_alone(self, mapper, cases):
        for principal, _ in cases:
            before = principal.model_dump()
            assert mapper.map(principal) == mapper.map(principal)
            assert principal.model_dump() == before
