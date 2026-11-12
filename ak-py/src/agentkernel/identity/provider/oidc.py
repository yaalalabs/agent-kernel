"""OIDCIdentityProvider: bearer JWTs from any OpenID Connect issuer, with a cached JWK set."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from ...core.model import Principal
from ...core.util.factory import AKConfigError
from ..errors import AuthenticationError
from .base import ClaimPath, IdentityProvider, RequestContext

if TYPE_CHECKING:
    from ...core.config import _ClaimPathsConfig, _IdentityProviderConfig


class JWKSCache:
    """The issuer's JWK set, fetched lazily and kept, refreshed once when a token names an unknown key.

    Discovery (``<issuer>/.well-known/openid-configuration``) runs once unless ``jwks_uri`` is given.
    An unknown ``kid`` triggers one refresh, rate-limited to one per ``refresh_cooldown`` seconds so
    a flood of bad tokens cannot turn into a flood of fetches; a fetch that fails leaves the
    previous key set in place (no cache poisoning). A first load that fails is not retried for
    ``failure_cooldown`` seconds, so an issuer that is down at start is not asked once per request.

    Nothing here is bound to an event loop, because one provider is shared by every caller in the
    process, and a sync host (Azure's thread-pooled functions) runs each call on a fresh loop. The
    key set is a dict swapped whole, so selecting a cached key takes no lock and never waits behind
    a refresh. Loads run on a worker thread (``asyncio.to_thread``) through a short-lived
    ``httpx.Client``, serialized by a ``threading.Lock`` that is only ever taken on that thread: a
    caller that waited re-checks whether another load finished meanwhile instead of fetching again.
    A test hands in a ``MockTransport``.
    """

    _log = logging.getLogger("ak.identity.provider.oidc")

    def __init__(
        self,
        issuer: str,
        jwks_uri: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        refresh_cooldown: float = 30.0,
        failure_cooldown: float = 5.0,
        timeout: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        """
        :param issuer: The issuer URL; discovery is read under it when ``jwks_uri`` is None.
        :param jwks_uri: The JWK set URL, when known; skips discovery.
        :param transport: An httpx transport for tests; None uses the network.
        :param refresh_cooldown: Seconds between two refreshes forced by an unknown ``kid``.
        :param failure_cooldown: Seconds a failed first load waits before the next attempt.
        :param timeout: Seconds a discovery or key-set fetch may take.
        :param clock: A monotonic clock, injectable for the cooldown tests.
        """
        self.issuer = issuer.rstrip("/")
        self.jwks_uri = jwks_uri
        self._transport = transport
        self._timeout = timeout
        self._refresh_cooldown = refresh_cooldown
        self._failure_cooldown = failure_cooldown
        self._clock = clock
        self._keys: dict[str | None, PyJWK] | None = None
        # Bumped by every successful load, so a caller that waited on the lock can tell.
        self._generation = 0
        self._last_forced_refresh: float | None = None
        self._failed_at: float | None = None
        self._load_lock = threading.Lock()

    @property
    def discovery_url(self) -> str:
        """Where the issuer's OpenID configuration is read from."""
        return f"{self.issuer}/.well-known/openid-configuration"

    async def signing_key(self, kid: str | None) -> PyJWK:
        """Return the key a token's header names, refreshing the set once if it is unknown.

        :param kid: The token header's ``kid``; None selects the only key of a single-key set.
        :return: The key.
        :raises AuthenticationError: If the set cannot be fetched, or holds no such key after one refresh.
        """
        if kid is not None and not isinstance(kid, str):
            raise AuthenticationError(f"the token's kid is not a string: {kid!r}")
        key = self._select(self._keys, kid)
        if key is None:
            await asyncio.to_thread(self._load_if_needed, kid, self._generation)
            key = self._select(self._keys, kid)
        if key is None:
            raise AuthenticationError(f"no signing key with kid {kid!r} in the JWK set of {self.issuer}")
        return key

    async def close(self) -> None:
        """Nothing to release: every fetch opens and closes its own client."""
        return None

    @staticmethod
    def _select(keys: dict[str | None, PyJWK] | None, kid: str | None) -> PyJWK | None:
        keys = keys or {}
        if kid is not None:
            return keys.get(kid)
        return next(iter(keys.values())) if len(keys) == 1 else None

    def _load_if_needed(self, kid: str | None, generation: int) -> None:
        """Load the key set unless another caller already did, honouring both cooldowns. Worker thread only.

        :param kid: The key the caller is missing.
        :param generation: The load generation the caller saw before it missed.
        :raises AuthenticationError: If a first load fails, or is still inside its failure cooldown.
        """
        with self._load_lock:
            if self._generation != generation:
                return  # another caller's load finished while this one waited
            now = self._clock()
            if self._keys is None:
                if self._failed_at is not None and now - self._failed_at < self._failure_cooldown:
                    raise AuthenticationError(
                        f"the JWK set of {self.issuer} is unavailable; the last fetch failed less than {self._failure_cooldown:g}s ago"
                    )
            elif self._last_forced_refresh is not None and now - self._last_forced_refresh < self._refresh_cooldown:
                return  # an unknown kid inside the cooldown: refused without a fetch
            else:
                # Stamped before the fetch so a failing endpoint is not hammered inside the cooldown either.
                self._last_forced_refresh = now
            try:
                keys = self._fetch_keys()
            except AuthenticationError:
                if self._keys is not None:
                    self._log.warning(
                        f"Refreshing the JWK set of {self.issuer} failed; keeping the {len(self._keys)} key(s) already loaded", exc_info=True
                    )
                    return
                self._failed_at = now
                raise
            self._keys = keys
            self._generation += 1
            self._failed_at = None
            self._log.info(f"Loaded {len(keys)} signing key(s) from {self.jwks_uri}")

    def _fetch_keys(self) -> dict[str | None, PyJWK]:
        with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
            if self.jwks_uri is None:
                self.jwks_uri = self._discover(client)
            data = self._get_json(client, self.jwks_uri, "the JWK set")
        if not isinstance(data, Mapping):
            raise AuthenticationError(f"the JWK set at {self.jwks_uri} is not a JSON object")
        try:
            keys = PyJWKSet.from_dict(dict(data)).keys
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"the JWK set at {self.jwks_uri} is unusable: {exc}") from exc
        return {key.key_id: key for key in keys}

    def _discover(self, client: httpx.Client) -> str:
        data = self._get_json(client, self.discovery_url, "the JWK set location")
        jwks_uri = data.get("jwks_uri") if isinstance(data, Mapping) else None
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise AuthenticationError(f"the JWK set location is missing from the discovery document at {self.discovery_url}")
        return jwks_uri

    @staticmethod
    def _get_json(client: httpx.Client, url: str, what: str) -> Any:
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - any fetch failure is a refused credential, never a 500
            raise AuthenticationError(f"{what} could not be fetched from {url}: {exc}") from exc


class OIDCIdentityProvider(IdentityProvider):
    """Validates a bearer JWT against an OpenID Connect issuer and reads the principal out of it.

    The signature is checked against the issuer's cached JWK set, then ``iss``, ``aud``, ``exp``
    and ``nbf`` (with ``leeway``) and every ``required_claims`` entry. The subject and the groups
    are read through dotted claim paths; the namespace is the validated ``iss``, so one issuer and
    subject is one identity on every direct surface. Every claim but the subject is kept in
    ``claims`` for the role mapper and the tools, the groups claim included beside its ``groups``
    projection, so a mapper's ``pass_through`` can lift it; ``roles`` is never written here.
    """

    name = "oidc"
    DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256", "ES256")

    _log = logging.getLogger("ak.identity.provider.oidc")

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        jwks_uri: str | None = None,
        algorithms: Iterable[str] | None = None,
        leeway: int = 30,
        required_claims: Iterable[str] = (),
        subject_claim: str = "sub",
        groups_claim: str = "groups",
        jwks: JWKSCache | None = None,
    ):
        """
        :param issuer: The issuer a token's ``iss`` must equal.
        :param audience: The audience a token must carry.
        :param jwks_uri: The JWK set URL; None discovers it from the issuer.
        :param algorithms: Allowed signing algorithms; symmetric ones are refused.
        :param leeway: Clock skew in seconds tolerated on ``exp`` and ``nbf``.
        :param required_claims: Claims a token must carry beyond the standard set.
        :param subject_claim: Dotted claim path of the subject.
        :param groups_claim: Dotted claim path of the groups.
        :param jwks: A prepared key cache (tests); None builds one over the network.
        :raises AKConfigError: If an algorithm is symmetric.
        """
        # Kept as configured for the `iss` comparison: an Auth0 issuer ends with a slash and its
        # tokens carry it. The slash-less and slashed spellings are both accepted, so a configured
        # value written either way matches; the namespace is the token's `iss` verbatim.
        self._issuer = issuer
        stripped = issuer.rstrip("/")
        self._accepted_issuers = list(dict.fromkeys([issuer, stripped, f"{stripped}/"]))
        self._audience = audience
        self._algorithms = list(algorithms) if algorithms is not None else list(self.DEFAULT_ALGORITHMS)
        self._check_algorithms(self._algorithms)
        self._leeway = leeway
        self._required_claims = list(required_claims)
        self._subject_claim = subject_claim
        self._groups_claim = groups_claim
        self.jwks = jwks if jwks is not None else JWKSCache(stripped, jwks_uri)

    @classmethod
    def from_config(cls, config: "_IdentityProviderConfig") -> "OIDCIdentityProvider":
        """Build the provider from an ``identity.provider`` block of type ``oidc``.

        :param config: The block; ``issuer`` and ``audience`` are required by the config validator.
        :return: The provider.
        :raises AKConfigError: If an algorithm is symmetric, or issuer or audience is missing.
        """
        if not config.issuer or not config.audience:
            raise AKConfigError("identity.provider.type oidc requires identity.provider.issuer and identity.provider.audience")
        return cls(
            config.issuer,
            config.audience,
            jwks_uri=config.jwks_uri,
            algorithms=config.algorithms,
            leeway=config.leeway,
            required_claims=config.required_claims,
            subject_claim=config.claims.subject,
            groups_claim=config.claims.groups,
        )

    @staticmethod
    def _claim_path(claims: "_ClaimPathsConfig", field: str, default: str) -> str:
        """The configured claim path when the block set it, else the subclass's own default."""
        return getattr(claims, field) if field in claims.model_fields_set else default

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        try:
            header = jwt.get_unverified_header(credential)
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"malformed token: {exc}") from exc
        key = await self.jwks.signing_key(header.get("kid"))
        verify_audience = self._verifies_audience()
        try:
            payload = jwt.decode(
                credential,
                key,
                algorithms=self._algorithms,
                audience=self._audience if verify_audience else None,
                issuer=self._accepted_issuers,
                leeway=self._leeway,
                options={"require": ["exp", "iss", *(["aud"] if verify_audience else [])], "verify_aud": verify_audience},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(str(exc)) from exc
        self._check(payload)
        for claim in self._required_claims:
            if ClaimPath.read(payload, claim) is None:
                raise AuthenticationError(f"required claim '{claim}' is missing")
        subject = ClaimPath.read(payload, self._subject_claim)
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError(f"subject claim '{self._subject_claim}' is missing")
        claims = {name: value for name, value in payload.items() if name != self._subject_claim}
        return Principal(subject=subject, provider=self.name, namespace=payload["iss"], groups=self._groups(payload), claims=claims)

    @staticmethod
    def _check_algorithms(algorithms: list[str]) -> None:
        """Refuse a list that would build and then refuse every token: empty, unsigned, unknown or symmetric.

        :raises AKConfigError: Naming the first unusable entry.
        """
        if not algorithms:
            raise AKConfigError("identity.provider.algorithms is empty; name at least one asymmetric algorithm, e.g. RS256")
        known = jwt.algorithms.get_default_algorithms()
        for algorithm in algorithms:
            if algorithm.lower() == "none":
                raise AKConfigError("identity.provider.algorithms: none accepts unsigned tokens; name an asymmetric algorithm such as RS256")
            if algorithm.upper().startswith("HS"):
                raise AKConfigError(
                    f"identity.provider.algorithms: {algorithm} is symmetric; the OIDC provider family validates asymmetric signatures only"
                )
            if algorithm not in known:
                raise AKConfigError(
                    f"identity.provider.algorithms: unknown algorithm {algorithm!r}; expected one of {sorted(name for name in known if name != 'none')}"
                )

    def _verifies_audience(self) -> bool:
        """Whether ``aud`` is checked by the decoder; a subclass with another audience claim says no and checks itself."""
        return True

    def _check(self, payload: dict[str, Any]) -> None:
        """A subclass's one extra check on the validated payload.

        :raises AuthenticationError: If the payload fails it.
        """
        return None

    def _groups(self, payload: dict[str, Any]) -> list[str]:
        """The groups at the configured claim path: a string is one group, a missing claim is none."""
        value = ClaimPath.read(payload, self._groups_claim)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    def security_scheme(self) -> tuple[str, dict[str, Any]]:
        return ("openIdConnect", {"url": self.jwks.discovery_url})

    async def close(self) -> None:
        await self.jwks.close()
