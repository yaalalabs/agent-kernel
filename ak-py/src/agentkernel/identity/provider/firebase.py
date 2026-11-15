"""FirebaseIdentityProvider: Firebase Authentication id tokens."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ...core.util.factory import AKConfigError
from .oidc import JWKSCache, OIDCIdentityProvider

if TYPE_CHECKING:
    from ...core.config import _IdentityProviderConfig


class FirebaseIdentityProvider(OIDCIdentityProvider):
    """OIDC with Firebase's issuer and audience derived from the project, and Google's fixed JWK set.

    Firebase has no built-in role claim, so the groups claim path defaults to the application's
    ``roles`` custom claim (Q14); every custom claim stays in ``claims`` for the role mapper, and a
    boolean flag such as ``admin: true`` needs a dotted-path mapper.
    """

    name = "firebase"
    JWKS_URI = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"

    def __init__(
        self,
        project_id: str,
        *,
        algorithms: Iterable[str] | None = None,
        leeway: int = 30,
        required_claims: Iterable[str] = (),
        subject_claim: str = "sub",
        groups_claim: str = "roles",
        jwks: JWKSCache | None = None,
    ):
        """
        :param project_id: The Firebase project; forms the issuer and is the audience.
        """
        super().__init__(
            f"https://securetoken.google.com/{project_id}",
            project_id,
            jwks_uri=self.JWKS_URI,
            algorithms=algorithms,
            leeway=leeway,
            required_claims=required_claims,
            subject_claim=subject_claim,
            groups_claim=groups_claim,
            jwks=jwks,
        )

    @classmethod
    def from_config(cls, config: "_IdentityProviderConfig") -> "FirebaseIdentityProvider":
        if config.firebase is None:
            raise AKConfigError("identity.provider.type firebase requires the identity.provider.firebase block")
        return cls(
            config.firebase.project_id,
            algorithms=config.algorithms,
            leeway=config.leeway,
            required_claims=config.required_claims,
            subject_claim=cls._claim_path(config.claims, "subject", "sub"),
            groups_claim=cls._claim_path(config.claims, "groups", "roles"),
        )
