# Identity providers, agent identity and delegation: landscape survey

Survey date: 2026-09-28. Supports the identity-provider part of issues #441 and #521 and the agent
identity part of #658.

Three things the identity layer has to cover: (1) pluggable *human* identity providers behind one
adapter (validate an inbound credential, produce a `Principal` with subject, groups, roles and raw
claims); (2) *agent identity*, the agent as a principal distinct from the human it acts for; (3)
delegation from user to agent to tool, so a downstream call can be authorized on both.

Verification legend: **[V]** primary page fetched and read; **[U]** search snippet or secondary
source only. Re-verify [U] claims before designing against them.

## A. Human identity providers

### A.1 Validating OIDC/OAuth2 JWTs in Python

- **Discovery.** OIDC Discovery appends `/.well-known/openid-configuration` to the issuer; `jwks_uri`
  names the key set; the document's `issuer` must equal the URL prefix used and the token's `iss`
  [V]. https://openid.net/specs/openid-connect-discovery-1_0.html
- **PyJWT** 2.15.0 (2026-09-23), Python 3.9+ [V]. `PyJWKClient(uri, cache_keys, max_cached_keys,
  cache_jwk_set, lifespan=300, headers, timeout, ssl_context, cooldown_duration)`;
  `get_signing_key_from_jwt(token)` reads `kid` from the unverified header and refreshes the JWKS
  once when the `kid` is unknown; `jwt.decode(..., audience=, issuer=, algorithms=, leeway=,
  options={require, verify_aud, strict_aud, ...})` [V]. `PyJWKClient` is synchronous (urllib); no
  async API in the docs [V]. https://pyjwt.readthedocs.io/en/stable/api.html ,
  https://pyjwt.readthedocs.io/en/stable/usage.html . A third-party `pyjwt-key-fetcher` offers an
  `AsyncKeyFetcher` [U]. AK already depends on `PyJWT>=2.13.0` through the `auth` extra
  (`ak-py/pyproject.toml:24-26`), so a JWKS-backed OIDC provider adds no new dependency.
- **joserfc** 1.7.5 (2026-08-29), Python 3.10 to 3.14 [V]; it does not fetch JWKS, the caller fetches
  with any HTTP client and calls `KeySet.import_key_set(json)`, so async is trivial [V].
  https://pypi.org/project/joserfc/ , https://jose.authlib.org/en/guide/jwk/
- **Authlib** 1.8.0; its `authlib.jose` module is deprecated in favour of joserfc and removed in 1.8
  [V]. Authlib remains the async OAuth *client* library (`AsyncOAuth2Client`) [V].
  https://docs.authlib.org/en/latest/jose/index.html
- **python-jose** last released 3.5.0 on 2025-05-28 [V]; joserfc's migration guide notes it supports
  only compact serialization and JWS-only JWTs [V]. Treat as legacy. https://pypi.org/project/python-jose/

### A.2 Provider claim conventions the adapter must normalise

| Provider | Subject | Groups / roles | Notes |
|---|---|---|---|
| Keycloak | `sub` | `realm_access.roles`, `resource_access.<client>.roles` [V] | Which role mappings land in the token is governed by scope mappings and the client's "Full Scope Allowed" toggle [V]. https://github.com/keycloak/keycloak/blob/main/core/src/main/java/org/keycloak/representations/AccessToken.java , https://docs.redhat.com/en/documentation/red_hat_build_of_keycloak/24.0/html/server_administration_guide/assigning_permissions_using_roles_and_groups |
| Auth0 | `sub` | `permissions` claim when "Add Permissions in the Access Token" is on (token dialect `access_token_authz` or `rfc9068_profile_authz`); `scope` is the intersection of requested and assigned permissions when RBAC is enabled [V] | Custom claims should be namespaced; `permissions`, `roles`, `groups` are reserved names and colliding custom claims are silently dropped [V]. https://auth0.com/docs/get-started/apis/enable-role-based-access-control-for-apis , https://auth0.com/docs/secure/tokens/json-web-tokens/create-custom-claims |
| Okta | `sub` | `groups` claim; the org authorization server only puts it in the ID token, a custom authorization server can put it in the access token; request the `groups` scope [V] | Custom authorization servers need the API Access Management add-on [U]. https://developer.okta.com/docs/guides/customize-tokens-groups-claim/main/ |
| Microsoft Entra ID | `oid` is stable across apps, `sub` is pairwise per app [V] | `scp` (delegated scopes, user tokens only), `roles` (app roles for users; application permissions for client-credentials tokens), `groups` (object-id GUIDs; omitted past 150 for SAML or 200 for JWT, replaced by `_claim_names` / `_claim_sources` or `hasgroups`), `wids` (directory roles), `azp` / `appid`, `tid`, `idtyp` [V] | Microsoft's validation guidance: always validate `aud` and `tid`; authorize on `sub` / `oid` or `roles` / `groups` / `wids`; never on `email`, `preferred_username`, `unique_name`, `upn`; for app-only tokens authorize on `azp` only after checking `idtyp == app` [V]. https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference , https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation |
| AWS Cognito | `sub` | access token: `cognito:groups`, `scope`, `token_use: "access"`, `client_id`, `username`, `aud` only with resource binding; ID token: `token_use: "id"`, `cognito:groups`, `cognito:roles`, `cognito:preferred_role`, `cognito:username`, `aud` = app client id [V] | The two tokens are signed with different keys and must be verified independently [V]. https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html , https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html |
| Google | `sub` | none: the ID token has no roles, groups or permissions claim [V] | Discovery at `https://accounts.google.com/.well-known/openid-configuration` [V]. https://developers.google.com/identity/openid-connect/openid-connect |
| Firebase Auth | `sub` / `user_id` | custom claims set server-side (for example `admin: true`, `roles: [...]`) and surfaced verbatim in the ID token [U] | Named in #521 as a target; verify the claim shape against the Firebase Admin SDK docs before designing |

Trivial adapters (API key with a static map, config-listed static users) need no external source;
the design point is that they emit the same `Principal` shape so everything downstream is
provider-agnostic.

### A.3 Where roles and permissions should live

- **In the token, with standard names.** RFC 9068 (JWT profile for OAuth access tokens) says an AS
  wanting to convey authorization attributes beyond `scope` SHOULD use the SCIM (RFC 7643) `groups`,
  `roles` and `entitlements` claims; `typ` is `at+jwt`; resource servers MUST check `aud` [V].
  https://www.rfc-editor.org/rfc/rfc9068.html
- **Known costs of token-borne roles.** Entra drops `groups` past 200 memberships [V]; Auth0 warns
  the `permissions` claim increases token size [V]; OpenFGA notes token-borne groups stay stale until
  the token expires [V]. https://openfga.dev/docs/modeling/token-claims-contextual-tuples
- **Local mapping (IdP group to runtime role).** Microsoft's OBO guidance: a middle tier "only uses
  delegated scopes and not application roles. Roles remain attached to the principal (the user) and
  never to the application operating on the user's behalf" [V].
  https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- **External engine.** OpenFGA recommends passing token `groups` / `roles` as *contextual tuples* at
  check time instead of syncing directories, with the caveat that contextual tuples only work with
  Check / ListObjects / ListUsers [V]. Auth0 FGA for RAG applies the same tuple model to filter
  documents per user [V]. https://auth0.com/ai/docs/intro/authorization-for-rag

Practical reading for AK: normalise the subject (prefer `oid` on Entra, `sub` elsewhere), carry the
provider's `groups` / `roles` / `permissions` verbatim in `Principal.claims`, and let a configurable
mapper (or an external engine, see `authorization-engines.md`) derive runtime roles. Issue #521's
"built-in integrations with RBAC configurations of auth providers like Cognito, Firebase auth" is
exactly this mapper: `cognito:groups` and Firebase custom claims into AK roles.

## B. Agent identity: the agent as a first-class principal

### B.1 Microsoft Entra Agent ID and Agent 365

- Generally available (what's-new dated 2026-05-01, updated 2026-08-13) [V].
  https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id
- An *agent identity* is a special service principal with no credentials of its own; it
  authenticates only through federated identity credentials issued by its *agent identity
  blueprint*, which holds the real credentials and acquires tokens for all its agent identities;
  Conditional Access on the blueprint applies to all its agents; an optional *agent user account*
  pairs 1:1 when a system demands a user object; sponsors, owners and managers give accountability
  [V]. https://learn.microsoft.com/en-us/entra/agent-id/agent-identities ,
  https://learn.microsoft.com/en-us/entra/agent-id/key-concepts
- Token semantics: autonomous agents use client credentials with the agent identity as `sub`;
  interactive agents called with a user token do OBO, yielding a token where "the subject of the
  token is a user, while the actor is the agent identity" [V]. Downstream APIs validate the tenant
  JWKS, `iss`, `aud` and the agent marker claim `xms_par_app_azp` (present only in agent-identity
  tokens, identifies the blueprint) [V].
  https://learn.microsoft.com/en-us/entra/agent-id/how-to-validate-agent-tokens-downstream-api
- Registry: registry experiences are converging into *Microsoft Agent 365* (a unified inventory of
  Microsoft and non-Microsoft agents); Entra keeps the identity foundation and "agent registration
  APIs remain supported" [V]. https://learn.microsoft.com/en-us/entra/agent-id/agent-registry-convergence

### B.2 Okta and Auth0

- **Auth0 for AI Agents** went GA on 2025-11-19 with User Authentication, **Token Vault**,
  **Asynchronous Authorization** (CIBA) and **FGA for RAG**; "Auth for MCP" was early access [V].
  https://auth0.com/blog/auth0-for-ai-agents-generally-available/
- **Token Vault**: the user authorises an external provider once; Auth0 stores that provider's
  access and refresh tokens per user per connection; the app exchanges an Auth0 token for the
  provider token [V]. https://auth0.com/docs/secure/tokens/token-vault
- **Async authorization**: CIBA with a `bindingMessage`, push approval, the agent polls `/token`,
  RAR `authorization_details` shown in the consent prompt [V]. https://auth0.com/ai/docs/async-authorization
- **Okta Cross App Access (XAA)** is Okta's deployment of the IETF **Identity Assertion JWT
  Authorization Grant** (ID-JAG): the client exchanges its SSO ID token at the IdP (RFC 8693) for an
  ID-JAG, then presents it to the resource app's AS (RFC 7523) for an access token; implementers
  include Okta, Ping, Keycloak, Descope (IdPs), Claude and VS Code (clients), Auth0 / Stytch / Ping
  (AS), Asana, Atlassian, Figma, Linear, Notion, Slack, Supabase (resource apps) [V].
  https://oauth.net/cross-app-access/ Draft: `draft-ietf-oauth-identity-assertion-authz-grant-04`,
  OAuth WG, 2026-05-21, token type `urn:ietf:params:oauth:token-type:id-jag` [V].
  https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-assertion-authz-grant/ **Okta Agent
  SSO** went GA 2026-08-24 and states XAA "has been formally incorporated as the official
  Enterprise-Managed Authorization extension for the Model Context Protocol" [V].
  https://www.okta.com/newsroom/press-releases/okta-brings-first-class-identity-to-ai-agents-with-agent-sso/

### B.3 AWS Bedrock AgentCore

- GA 2025-10-13 for Runtime, Gateway, Memory, Identity, Observability [V].
  https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available
- **Workload identity**: agent identities are workload identities; one is auto-created per runtime;
  the *agent access token* "contains both workload identity and user identity"; the *token vault*
  releases credentials only to "the specific agent and user combination that originally obtained
  them" [V]. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-terminology.html
- **Inbound auth**: IAM SigV4 *or* a JWT authorizer (`discoveryUrl` for `iss`, `allowedClients`,
  `allowedAudience`, `allowedScopes`, required custom claims); unauthenticated calls get `401` with
  `WWW-Authenticate: Bearer resource_metadata=...` pointing at an RFC 9728 document. **Outbound
  auth**: credential providers (OAuth 2LO/3LO, API key) via `@requires_access_token(provider_name,
  scopes, auth_flow="USER_FEDERATION"|"M2M")`; the runtime exchanges the inbound JWT for a Workload
  Access Token (`GetWorkloadAccessTokenForJWT`), and third-party tokens are vaulted keyed by workload
  identity plus the user id from the inbound JWT. A `X-Amzn-Bedrock-AgentCore-Runtime-User-Id`
  header lets a SigV4 caller assert a user id (unverified, gated by the `InvokeAgentRuntimeForUser`
  IAM action) [V]. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html
- **Gateway**: exposes APIs, Lambda and Smithy models as MCP tools, fronts A2A / HTTP targets, and
  handles ingress (IAM or JWT) and egress credential injection [V].
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html

### B.4 Google Cloud

- **Agent Identity** is SPIFFE-based: `spiffe://TRUST_DOMAIN/resources/SERVICE/RESOURCE_PATH`,
  appearing in IAM as `principal://...`; auto-provisioned X.509 certificates valid 24 hours, mTLS plus
  DPoP "double-bound" tokens; no impersonation, no long-lived keys; an *Auth Manager* vault brokers
  API keys, OAuth client credentials and delegated user tokens [V].
  https://docs.cloud.google.com/iam/docs/agent-identity-overview ,
  https://docs.cloud.google.com/agent-builder/agent-engine/agent-identity
- Status (blog 2026-05-07): Agent Identity for Agent Runtime GA; for the Gemini Enterprise Agent
  Platform preview; Auth Manager preview [V].
  https://cloud.google.com/blog/products/identity-security/whats-new-in-iam-security-governance-and-runtime-defense
- The governance trio is Agent Identity (credentials), Agent Registry (catalog of agents, tools and
  MCP servers) and Agent Gateway (policy enforcement on tool calls) [V].
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-identity-overview

### B.5 SPIFFE/SPIRE and WIMSE

- spiffe.io publishes no AI-agent guidance; vendors make the case. HashiCorp (2026-04-30): agents get
  short-lived, rotated X.509-SVIDs or JWT-SVIDs; the post does not address acting on behalf of users
  [V]. https://www.hashicorp.com/en/blog/spiffe-securing-the-identity-of-agentic-ai-and-non-human-actors
- IETF WIMSE architecture (`draft-ietf-wimse-arch-08`, 2026-07-06) has a use case "AI and ML-Based
  Intermediaries" requiring delegated and autonomous action to be distinguishable and multi-hop
  delegation to be explicitly scoped [V]. https://datatracker.ietf.org/doc/draft-ietf-wimse-arch/
- `draft-ietf-wimse-workload-creds-02` (2026-07-02): the Workload Identity Token is a JWS-signed JWT
  with `sub` = trust-domain-scoped workload URI and `cnf.jwk`; proof of possession via a WPT or HTTP
  signatures [V]. https://datatracker.ietf.org/doc/draft-ietf-wimse-workload-creds/

### B.6 IETF and standards bodies

- **RFC 8693 Token Exchange**: impersonation (the receiver "is actually dealing with B") versus
  delegation ("A is an agent for B"); `subject_token` and `actor_token`; the `act` claim nests to
  express chains and `may_act` authorises future actors [V]. https://www.rfc-editor.org/rfc/rfc8693.html
- **RFC 9396 RAR** (`authorization_details` with `type`, `locations`, `actions`, `datatypes`,
  `identifier`, `privileges`) [V]. https://www.rfc-editor.org/rfc/rfc9396.html
  **RFC 9449 DPoP** [V]. https://www.rfc-editor.org/rfc/rfc9449.html
- **`draft-ietf-wimse-aims-00`** "AI Identity Management System" (2026-09-15, WIMSE WG-adopted;
  authors from AWS, Zscaler, Ping, OpenAI, Okta): composes WIMSE and OAuth; agents are workloads with
  WIMSE identifiers and WIT/WPT credentials, act as OAuth clients, and must distinguish autonomous
  from delegated action. Replaces `draft-klrc-aiagent-auth` [V].
  https://datatracker.ietf.org/doc/draft-ietf-wimse-aims/
- **`draft-ietf-oauth-identity-chaining-17`** submitted to the IESG as Proposed Standard (token
  exchange then JWT grant across domains) [V]. https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-chaining/
  **`draft-ietf-oauth-client-id-metadata-document-02`** (2026-07-06) [V].
  https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/
- Expired or individual drafts worth knowing by name: `draft-oauth-ai-agents-on-behalf-of-user-02`
  (`requested_actor`, `actor_token`, delegation-chain claims; expired, never adopted) [V];
  `draft-araut-oauth-transaction-tokens-for-agents-02` (`sub` = principal, `act` = executing agent,
  `agentic_ctx` chain metadata; individual, 2026-05-22) [V]; `draft-aap-oauth-profile-01` (expired)
  [V]. https://datatracker.ietf.org/doc/draft-oauth-ai-agents-on-behalf-of-user/ ,
  https://datatracker.ietf.org/doc/draft-araut-oauth-transaction-tokens-for-agents/
- **OpenID Foundation AIIM Community Group** (Artificial Intelligence Identity Management):
  commissioned April 2025, whitepaper October 2025 [V].
  https://openid.net/cg/artificial-intelligence-identity-management-community-group/

### B.7 Agent naming and identity registries

- **OWASP Agent Name Service (ANS) v1.0** (2025-05-14): DNS-inspired, PKI-backed naming with an
  `ANSName` encoding protocol, capability, provider and version; adapters for A2A, MCP, ACP; no
  adoption data stated [V].
  https://genai.owasp.org/resource/agent-name-service-ans-for-secure-al-agent-discovery-v1-0/
- **AGNTCY Identity**: each agent has an ID, a 1:1 `ResolverMetadata` and 1:n *Agent Badges* (W3C
  Verifiable Credentials wrapping an OASF record or an A2A card); identifiers may be IdP accounts,
  `/.well-known/agent.json` or W3C DIDs; Apache 2.0 with an issuer CLI, node backend and Python SDK
  [V]. https://spec.identity.agntcy.org/docs/intro/ , https://github.com/agntcy/identity AGNTCY
  joined the Linux Foundation on 2025-07-29 [U].
- **W3C Agent Identity Registry Protocol CG**: launched 2026-04-24, scope includes a DID method and
  VC agent formats plus MCP / A2A / OAuth / SPIFFE profiles; no deliverables yet [V].
  https://www.w3.org/community/agent-identity/
- Verdict: none of these registries is required by MCP, A2A or the three clouds today; treat them as
  optional metadata sources for an `AgentDescriptor`, not as the registry itself.

## C. Protocol-level auth AK's surfaces must be compatible with

### C.1 MCP

- **Latest revision 2026-07-28** (RC locked 2026-05-21) [V].
  https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ Its changelog: stateless
  core (no `initialize`, no `Mcp-Session-Id`), required `Mcp-Method` / `Mcp-Name` headers; clients
  MUST validate `iss` per RFC 9207, MUST declare `application_type` in DCR, MUST key stored client
  credentials by issuer; **DCR (RFC 7591) is deprecated in favour of Client ID Metadata Documents**
  [V]. https://modelcontextprotocol.io/specification/2026-07-28/changelog
- **2025-11-25 authorization spec** (the normative core): the MCP server is an OAuth 2.1 resource
  server; it MUST publish RFC 9728 Protected Resource Metadata (via `WWW-Authenticate: Bearer
  resource_metadata=..., scope=...` on 401 or at `/.well-known/oauth-protected-resource[/path]`),
  MUST validate the token was issued for it (RFC 8707 audience), MUST NOT accept or pass through
  other tokens, and returns 403 `insufficient_scope` with a `scope` list for step-up. The client MUST
  send `Authorization: Bearer` on every request, MUST send `resource=` on authorization and token
  requests, MUST use PKCE S256, MUST support RFC 8414 and OIDC discovery, SHOULD use CIMD with
  pre-registration and DCR as fallbacks [V].
  https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- **Enterprise-Managed Authorization extension** reached stable 2026-06-18; adopters include Okta
  (IdP), Claude and VS Code (clients), Asana, Atlassian, Canva, Figma, Granola, Linear, Supabase,
  Slack [V]. Flow: the MCP AS advertises `authorization_grant_profiles_supported:
  ["urn:ietf:params:oauth:grant-profile:id-jag"]`; the client does an RFC 8693 exchange at the IdP
  with `requested_token_type=urn:ietf:params:oauth:token-type:id-jag`, `audience` = the MCP AS
  issuer, optional `resource` = the MCP server; then `grant_type=jwt-bearer` at the MCP AS, which
  validates signature, `iss`, `aud`, `sub`, `exp`, `jti`, `resource` and client auth [V].
  https://blog.modelcontextprotocol.io/posts/enterprise-managed-auth/ ,
  https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization The Python SDK
  ships `IdentityAssertionOAuthProvider` (client) and `identity_assertion_enabled=True` plus
  `exchange_identity_assertion` (server) [V]. https://py.sdk.modelcontextprotocol.io/client/identity-assertion/
- Consequence for AK: an MCP **server** AK builds (`api/mcp/`) must validate the bearer JWT
  (JWKS signature, `iss`, `aud` equal to its canonical URI, `exp`, scopes) and serve PRM; today it
  is mounted outside the REST auth dependencies and validates nothing (`ak-current-state.md`,
  section 3). An MCP **client** (an agent calling remote tools) holds per-server tokens, sends
  `resource`, does PKCE, and optionally the ID-JAG exchange for enterprise-managed servers.

### C.2 A2A

- **Version 1.0.0** is the released spec (shipped March 2026 [U]). `AgentCard.securitySchemes` (API
  key, HTTP basic/bearer, OAuth 2.0 flows, OpenID Connect, mutual TLS) plus `security` requirements;
  **per-skill** `AgentSkill.security`; `capabilities.extendedAgentCard` and the
  `GetExtendedAgentCard` operation (authenticate with a public-card scheme first); servers MUST
  reject unauthenticated requests with 401 and insufficient permissions with 403 without leaking
  resource existence; in-task auth via `TASK_STATE_AUTH_REQUIRED`; signed Agent Cards (section 8.4)
  [V]. https://a2a-protocol.org/latest/specification/
- Governance: Google donated A2A to the Linux Foundation; the TSC includes AWS, Cisco, Google, IBM
  Research, Microsoft, Salesforce, SAP, ServiceNow [V]. On 2026-08-27 A2A was accepted as a Growth
  Stage project of the Agentic AI Foundation, alongside MCP [V].
  https://a2a-protocol.org/latest/blog/2026/08/27/a-new-chapter-for-a2a-joining-the-agentic-ai-foundation/
- Consequence for AK: `A2ACardBuilder` emits no `securitySchemes` or `security`
  (`core/builder.py:38-48`), and per-skill security is where a "user may use skill X of agent A"
  grant would surface externally. The authenticated extended card is the protocol's own answer to
  "show a richer catalog entry to an authorised caller".

### C.3 AG-UI

- "AG-UI defines no credential"; auth is "a property of the binding and the application, not of the
  protocol" [V]. https://docs.ag-ui.com/spec/1.0/basic/transports AK's `AGUIRequestHandler` already
  treats it that way (bearer token via the shared `Authoriser`).

## D. The delegation chain user to agent to tool: three dominant patterns

1. **Token exchange and JWT-grant chains (identity preserved, actor recorded).** RFC 8693 delegation
   with nested `act` claims is the canonical form [V]. Vendors: Microsoft OBO
   (`grant_type=jwt-bearer`, `assertion=<inbound token>`, `requested_token_use=on_behalf_of`; the
   doc warns never to relay middle-tier tokens and notes only delegated scopes, not roles, carry
   through) [V]; Entra agent OBO yields "subject is a user, actor is the agent identity" [V]; Okta
   XAA and MCP Enterprise-Managed Authorization use ID-JAG [V]; AgentCore exchanges the inbound JWT
   for a Workload Access Token carrying both workload and user identity [V]; the transaction-tokens
   draft puts the agent in `act` [V]. Cross-domain generalisation is `draft-ietf-oauth-identity-chaining` [V].
2. **Token vault (the runtime stores per-user downstream credentials keyed by user, connection and
   often agent).** Auth0 Token Vault (per user per connection, retrieved by token exchange) [V];
   AgentCore token vault (bound to the specific agent and user combination) [V]; Google Auth Manager
   (preview, decrypted only at the gateway) [V]. This is the pattern for third-party tools that
   cannot participate in the user's IdP.
3. **Impersonation via an asserted subject.** Kubernetes `Impersonate-User`, `Impersonate-Group`,
   `Impersonate-Uid`, `Impersonate-Extra-*`, gated by the `impersonate` RBAC verb and audit-logged
   with both identities [V]
   https://kubernetes.io/docs/reference/access-authn-authz/authentication/#user-impersonation ;
   AgentCore's `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` (opaque, unverified, IAM-gated) [V];
   Google Workspace domain-wide delegation sets `sub` in the service-account JWT [V]
   https://developers.google.com/identity/protocols/oauth2/service-account . RFC 8693 calls this
   impersonation: the receiver sees only B, not A [V]. Google's Agent Identity forbids impersonation
   for agent principals [V].

AK already implements pattern 3 once, in the Kubernetes sandbox provider
(`sandbox/providers/kubernetes.py:229-248`), gated by the Helm chart's `sandboxWorker.rbac.impersonate`.

**Implication for the design.** Model the run's identity as `(subject principal, actor chain)` with
`act`-style nesting: the human (or service) the run acts for, and the agent (and any sub-agent)
doing the acting. Support pattern 1 natively through the identity-provider adapters (an OBO or
ID-JAG exchange hook per provider that has one), pattern 2 as a pluggable credential store keyed by
`(user, agent, connection)`, and pattern 3 only behind an explicit, audited capability, mirroring
Kubernetes' `impersonate` verb. Whatever the pattern, the acting user must be established from the
validated credential, never from the request body; the current `from_payload` rule
(`core/model.py:325-328`) is the opposite.
