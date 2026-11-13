"""CognitoIdentityProvider: Amazon Cognito user pool tokens."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ...core.util.factory import AKConfigError
from ..errors import AuthenticationError
from .oidc import JWKSCache, OIDCIdentityProvider

if TYPE_CHECKING:
    from ...core.config import _IdentityProviderConfig


class CognitoIdentityProvider(OIDCIdentityProvider):
    """OIDC with Cognito's issuer, its ``cognito:groups`` claim and its ``token_use`` rule.

    A Cognito access token carries no ``aud``: its audience is ``client_id``, which is checked
    against the configured audience instead. An id token carries ``aud`` and is checked as any
    OIDC token is.
    """

    name = "cognito"

    def __init__(
        self,
        region: str,
        user_pool_id: str,
        audience: str,
        *,
        token_use: str = "access",
        jwks_uri: str | None = None,
        algorithms: Iterable[str] | None = None,
        leeway: int = 30,
        required_claims: Iterable[str] = (),
        subject_claim: str = "sub",
        groups_claim: str = "cognito:groups",
        jwks: JWKSCache | None = None,
    ):
        """
        :param region: The AWS region of the user pool.
        :param user_pool_id: The user pool id; with the region it forms the issuer.
        :param audience: The app client id a token must be issued for.
        :param token_use: The ``token_use`` a token must carry: ``access`` or ``id``.
        """
        super().__init__(
            f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
            audience,
            jwks_uri=jwks_uri,
            algorithms=algorithms,
            leeway=leeway,
            required_claims=required_claims,
            subject_claim=subject_claim,
            groups_claim=groups_claim,
            jwks=jwks,
        )
        if token_use not in ("access", "id"):
            raise AKConfigError(f"identity.provider.cognito.token_use must be access or id, not {token_use!r}")
        self._token_use = token_use

    @classmethod
    def from_config(cls, config: "_IdentityProviderConfig") -> "CognitoIdentityProvider":
        if config.cognito is None:
            raise AKConfigError("identity.provider.type cognito requires the identity.provider.cognito block")
        if not config.audience:
            raise AKConfigError("identity.provider.type cognito requires identity.provider.audience (the app client id)")
        return cls(
            config.cognito.region,
            config.cognito.user_pool_id,
            config.audience,
            token_use=config.cognito.token_use,
            jwks_uri=config.jwks_uri,
            algorithms=config.algorithms,
            leeway=config.leeway,
            required_claims=config.required_claims,
            subject_claim=cls._claim_path(config.claims, "subject", "sub"),
            groups_claim=cls._claim_path(config.claims, "groups", "cognito:groups"),
        )

    def _verifies_audience(self) -> bool:
        return self._token_use != "access"

    def _check(self, payload: dict[str, Any]) -> None:
        if payload.get("token_use") != self._token_use:
            raise AuthenticationError(f"token_use {payload.get('token_use')!r} is not the configured {self._token_use!r}")
        if self._token_use == "access" and payload.get("client_id") != self._audience:
            raise AuthenticationError("the access token's client_id is not the configured audience")
