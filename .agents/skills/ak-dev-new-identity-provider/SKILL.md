---
name: ak-dev-new-identity-provider
description: >
  Step-by-step guide for adding a new built-in identity provider to Agent Kernel's identity layer
  (beyond oidc, cognito, entra, firebase and static). Use this skill when a credential type or
  issuer needs a short `identity.provider.type` name of its own. It starts with the check that
  most issuers (Auth0, Keycloak, Okta, Google) are an `oidc` configuration, not a subclass. Covers
  the IdentityProvider contract, deriving from the OIDC family, the config sub-block, factory
  registration behind the `auth` extra, the dotted-path bring-your-own path, the role mapper, the
  IdentityProviderContract test suite, and docs.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Identity Provider

This guide walks through adding a built-in provider to the identity layer
(`ak-py/src/agentkernel/identity/provider/`). Use `CognitoIdentityProvider`
(`identity/provider/cognito.py`) as the reference for a token issuer, since it derives from the
OIDC family and changes only what Cognito does differently. Use `StaticIdentityProvider`
(`identity/provider/static.py`) as the reference for a credential that is not a JWT. The
`ak-dev-architecture` skill's *Identity and Access* section covers the principal, the
`RequestAuthenticator` and the surfaces this guide builds on.

## Existing Providers

| Provider | `type` value | Validates | Extra |
|---|---|---|---|
| Any OpenID Connect issuer | `oidc` | signature against the issuer's JWKS, `iss`, `aud`, `exp`, `nbf`, `required_claims` | `agentkernel[auth]` |
| Amazon Cognito | `cognito` | OIDC with the pool's issuer, `cognito:groups`, `token_use`, `client_id` as the access token's audience | `agentkernel[auth]` |
| Microsoft Entra ID | `entra` | OIDC with the tenant's issuer and a matching `tid` | `agentkernel[auth]` |
| Firebase Authentication | `firebase` | OIDC with the project's issuer and audience | `agentkernel[auth]` |
| Static credentials | `static` | a credential equal to a secret the secret capability resolves | none |
| Bring-your-own | dotted path, e.g. `myapp.identity.ApiKeyProvider` | whatever the subclass implements | the user's own |

## Do You Need a Built-in?

Answer this before writing code: **an OpenID Connect issuer is a configuration before it is a
subclass.** Auth0, Keycloak, Okta and Google are served by `oidc` with their issuer, audience and
claim paths. Auth0, for example:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<tenant>.<region>.auth0.com/   # or the custom domain; trailing slash as Auth0 issues it
    audience: <the API identifier of your Auth0 API>
    claims:
      groups: https://<your namespace>/roles       # the namespaced claim an Auth0 Action sets; omit if none
```

A namespaced claim with dots in it works because `ClaimPath.read` (`identity/provider/base.py`)
tries the whole path as one key before splitting it, and a nested one such as Keycloak's
`realm_access.roles` works because it then walks the segments. Document a new issuer as a named
`oidc` configuration in `docs/docs/advanced/identity-and-access.md` and stop there.

Subclass the OIDC family only when the issuer breaks a rule `oidc` enforces: an issuer derived
from settings (Cognito's region and pool, Entra's tenant, Firebase's project), a non-standard
audience claim (Cognito access tokens carry `client_id`, not `aud`), or an extra claim check
(Entra's `tid`, Cognito's `token_use`). Write a provider from the ABC only for a credential that is
not a JWT at all (API keys, mTLS identities, a platform signature).

A user who needs any of this once can already plug in a subclass by dotted path with no core
change. Add a built-in only when the provider is broadly useful and deserves a short name, tests
and docs.

## The Contract

`IdentityProvider` (`identity/provider/base.py`) is small. The rules around it are what matter:

- **`name: ClassVar[str]`**: the short name the factory selects it by, and the value every
  principal it returns carries in `Principal.provider`.
- **`async authenticate(credential, context=None) -> Principal`**: return a non-anonymous
  principal with `subject`, `namespace` (the scope the subject is unique within: the issuer for a
  token, `static` for the static provider) and `provider` set, plus `groups`, `claims` and `kind`
  when the provider can vouch for them. Raise `AuthenticationError` (`identity/errors.py`) to
  refuse. The message is the operator's reason and goes to the log only; the caller sees
  `public_detail`, `Unauthorized` unless you pass another one. Never return `None` for a refusal.
- **Never write `roles`.** The configured role mapper is their one producer: when a `role_mapper`
  block exists the factory wraps the provider in `MappedIdentityProvider` (`identity/provider/roles.py`),
  which replaces whatever roles the provider set. (The `static` provider is the one built-in that
  sets them, from roles an operator listed in its entries; a mapper replaces those too.) A provider
  that issues roles natively puts the raw values in `claims` and lets `role_mapper.pass_through` lift
  them, or a deployment lists that claim path in `role_mapper.claims` so `mapping` translates its
  values. `MappingRoleMapper` looks up only `principal.groups` by default, because a user sets many
  of their own claims (a display name, a sign-up username, an email) and matching every claim value
  would let one of them grant a role; keep groups in `groups`, not only in a claim.
- **Never set `actor` or `credential_ref`.** `Runtime` attaches the actor when a run starts and the
  authenticator owns the credential handle. The contract suite asserts both stay `None`.
- **`context` is optional and changes nothing by default.** `RequestContext` carries `path`,
  `http_method` and `headers` for a provider that scopes per route; the contract suite asserts the
  same credential authenticates the same way with and without it.
- **`security_scheme() -> (name, settings)`**: what an agent card advertises. The default is
  `("bearer", {})`; the OIDC family returns `("openIdConnect", {"url": <discovery url>})`.
- **`async close()`**: release any client the provider opened, idempotently.
- **No configuration reads in methods.** `from_config(cls, config: _IdentityProviderConfig)`
  turns the provider block into constructor arguments, and the constructor raises `AKConfigError`
  (`core/util/factory.py`) on unusable values, so misconfiguration fails when the provider is
  built, not on the first request. The built-ins do this: `OIDCIdentityProvider._check_algorithms`
  refuses an empty `algorithms` list, `none`, a name PyJWT does not know and any `HS*` entry;
  `CognitoIdentityProvider` refuses a `token_use` other than `access` or `id`; and
  `StaticIdentityProvider` refuses an empty `principals` map.

## Step-by-Step

### 1. Create the Provider File

`identity/provider/<name>.py`. For a token issuer, derive from `OIDCIdentityProvider` and pass the
derived issuer, the default claim paths and any extra checks to `super().__init__`, the way
`CognitoIdentityProvider` builds `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}` and
defaults `groups_claim` to `cognito:groups`. Keep the `jwks: JWKSCache | None = None` keyword so
tests can inject a cache on a fake transport. Override `_check(payload)` for an extra claim rule
and `_verifies_audience()` when the audience is not in `aud`, and raise `AuthenticationError` from
them.

For a credential that is not a JWT, subclass `IdentityProvider` directly. Compare secrets in
constant time (`hmac.compare_digest`), and resolve any secret the provider needs through
`SecretManager` at construction, the way `StaticIdentityProvider` does, so a missing secret is an
`AKConfigError` at startup.

### 2. Configuration

In `ak-py/src/agentkernel/core/config.py`:

- Reuse the shared fields of `_IdentityProviderConfig` (`issuer`, `audience`, `jwks_uri`,
  `algorithms`, `leeway`, `required_claims`, `claims`) before adding any. A provider whose issuer
  is derived needs only the inputs it is derived from.
- Add a `_<Name>ProviderConfig(BaseModel)` with those inputs, every field with a real
  `description`, and a `<name>: _<Name>ProviderConfig | None` field on `_IdentityProviderConfig`,
  the way `cognito`, `entra` and `firebase` sit there.
- Add the name to `_check_provider_settings`, the model validator that fails at load time when
  `type` names a provider whose block is missing.
- Update the `type` field's description, which lists the built-ins and surfaces in generated docs.

### 3. Register with the Factory

In `identity/provider/factory.py`, add an `elif key == "<name>":` branch beside the others, with
the import inside `require_extra("auth", "identity.provider.type: <name>")` when the provider needs
PyJWT, cryptography or httpx, and add the name to `_BUILTIN_PROVIDERS`. The dotted-path branch
stays last: it hands a bring-your-own provider the whole provider block
(`resolve_dotted(provider_type, base=IdentityProvider)(identity_config.provider)`).
`_IdentityProviderConfig` is declared `model_config = ConfigDict(extra="allow")`, so a key the model
does not define (say `keys_table`) survives validation and the custom provider reads it from
`config.model_extra`, or ignores it. `_RoleMapperConfig` allows extras the same way for a dotted-path
`RoleMapper`. A built-in never relies on extras: its settings are declared fields.

Export the class through the lazy table in `identity/__init__.py` (`_LAZY_EXPORTS` and the
`TYPE_CHECKING` imports), so `import agentkernel.identity` stays free of optional imports.

### 4. Optional Dependency Extra

The OIDC family lives in the `auth` extra (`PyJWT`, `cryptography`, `httpx` in
`ak-py/pyproject.toml`). Reuse it for a token issuer. A provider with an SDK of its own adds that
SDK to `auth` or a new extra, matched to its `require_extra(...)` call, with the bounds develop
pins every dependency with.

### 5. Tests

- **Contract:** subclass `IdentityProviderContract` (`identity/provider/testing.py`, deliberately
  not exported from `agentkernel.identity`) and override three fixtures: `provider`,
  `valid_credential` (the credential and the principal fields it must yield: `subject` and
  `namespace` at least, plus `groups`, `claims`, `kind` and `roles` when asserted) and
  `invalid_credentials` (at least one credential the provider must refuse).
- **OIDC family:** add the provider to `ak-py/tests/test_identity_oidc.py`, subclassing its
  `_OIDCFamilyContract`, which already lists the token-shaped failures (expired, wrong audience,
  wrong issuer, unknown key, tampered signature, missing subject). Mint tokens with the file's
  `Keys` helper and serve discovery and the JWK set from `JWKSServer`, an `httpx.MockTransport`,
  through `JWKSCache(<issuer>, transport=server.transport)`. Never hit the network. Then a
  provider-specific class for the rules only it has, the way `TestCognitoProvider` covers the id
  token's `aud` check and the issuer `from_config` derives.
- **Other providers:** `ak-py/tests/test_identity_providers.py`, the way
  `TestStaticProviderContract` builds its provider on the file's `secrets` fixture (a
  `SecretManager` over a fake provider).
- **Factory and config:** for a token issuer, add it to `TestFactoryBranches` in
  `test_identity_oidc.py`, whose cases assert that each short name builds its provider, that the
  name matches whatever its case, and that a failed import names the `auth` extra
  (`require_extra`). A provider outside the OIDC family goes beside `TestIdentityProviderFactory`
  in `test_identity_providers.py`, which also holds the static, dotted-path (`model_extra`
  included), unknown-name and `role_mapper`-wraps-in-`MappedIdentityProvider` cases. Either way,
  add the name to `test_a_named_provider_needs_its_block` in `test_config.py` (a missing sub-block
  is an `AKConfigError` at config load).
  `IdentityProviderFactory` caches the provider process-wide: `test_identity_providers.py` resets it
  around each test with its autouse `_reset_factory` fixture, and a new test file that calls `get()`
  does the same (`create()` builds without caching).
- **Surfaces:** nothing new. A surface test that needs an authenticated caller uses the
  `static_identity` fixture in `ak-py/tests/conftest.py` (`alice-secret` authenticates `alice`).

### 6. Documentation

- `docs/docs/advanced/identity-and-access.md`: a row in the providers table and a subsection with
  the configuration block, what is validated, the extra and how to get a test token.
- `docs/docs/core-concepts/configuration.md`: the new sub-block and the `type` value.
- `ak-py/README.md` (its *Identity* configuration fields) and the root `README.md` (the *Identity
  and Access* bullet), which list the providers by name.
- `ak-dev-architecture/SKILL.md`, *Identity and Access*: the provider in the built-ins list and
  the factory mapping.
- The bundled skills that list the providers: `ak-add-capabilities` (its *Identity* section) and
  `ak-cloud-deploy` (*Deploying the Identity Provider*), with their `evals/evals.json` when an
  expected output names the providers.
- Landing page inventories: the **Identity & Access** card's `tags` and `description` under the
  Guard tab in `docs/src/components/FeatureExplorer/data.tsx`; a marquee tile when the provider is
  a third-party service, in the **Observability, safety & testing** row of
  `IntegrationsMarquee/data.tsx` with role `Identity` and `href: IDENTITY` (an issuer you only
  documented as an `oidc` configuration gets a tile too, its `title` saying so, as Auth0, Okta and
  Keycloak have); and the highlights of the **Identity & Access** card in `docs/src/pages/features.tsx`.
  Logo sourcing and the build check are in `ak-dev-sync-docs-from-branch`.

## Gotchas

- **Symmetric algorithms are refused.** `OIDCIdentityProvider` raises `AKConfigError` for any
  `HS*` entry in `algorithms` (and for an empty list, `none` or an unknown name): a shared-secret
  JWT would let anyone holding the secret mint any subject. A provider for HMAC-signed credentials
  is not an OIDC subclass.
- **JWKS fetching is loop-agnostic and injectable.** One provider serves every caller in the
  process, and a sync host (Azure's thread-pooled functions) runs each call on a fresh event loop,
  so nothing in `JWKSCache` is bound to a loop. A cached key is selected with no lock (the key set
  is a dict swapped whole), so it never waits behind a refresh. A load runs on a worker thread
  (`asyncio.to_thread`) through a short-lived `httpx.Client`, serialized by a `threading.Lock`; a
  failed first load is retried only after `failure_cooldown` (5 s by default), an unknown `kid`
  forces at most one refresh per `refresh_cooldown` (30 s), a failed refresh keeps the previous key
  set, and every fetch failure is an `AuthenticationError` (a 401, never a 500). Tests inject an
  `httpx.MockTransport` through `transport=`. Do not hold an `httpx.AsyncClient` on the cache (it
  binds to the loop that created it) or reach for `PyJWKClient` (its `urllib` fetch cannot be
  pointed at a test transport).
- **Claim paths try the whole name first.** Keep `ClaimPath.read` for subject and groups instead
  of indexing the payload, or namespaced Auth0 claims and nested Keycloak claims stop working.
- **A missing subject is a refusal**, not an anonymous principal. The anonymous principal belongs
  to the authenticator, for a request that carried no credential at all.
- **The static provider resolves secrets when it is built.** Its keys name secrets, its values
  never appear in config, and two keys resolving to the same value is a config error. A provider
  that keeps credentials should follow the same rule.

## Checklist

- [ ] An `oidc` configuration ruled out first (documented as a named configuration if it suffices)
- [ ] `identity/provider/<name>.py`: `name` set, `AuthenticationError` on refusal, no `roles`, `actor` or `credential_ref` written
- [ ] `from_config` builds from the block; the constructor raises `AKConfigError` on unusable settings
- [ ] Config: shared fields reused, `_<Name>ProviderConfig` and its field on `_IdentityProviderConfig`, `_check_provider_settings` updated (`core/config.py`)
- [ ] Factory branch behind `require_extra("auth", ...)`, name in `_BUILTIN_PROVIDERS`, lazy export in `identity/__init__.py`
- [ ] `IdentityProviderContract` subclass plus provider-specific tests on a fake transport (`tests/test_identity_oidc.py` or `tests/test_identity_providers.py`)
- [ ] Factory tests (`TestFactoryBranches` in `test_identity_oidc.py` for a token issuer, `TestIdentityProviderFactory` in `test_identity_providers.py` otherwise)
- [ ] Docs: `identity-and-access.md`, `configuration.md`, `ak-py/README.md`, root `README.md`, architecture skill, bundled skills and evals, landing inventories
- [ ] `cd ak-py && uv run pytest tests/test_identity_*.py` and `make lint-check-all` clean
