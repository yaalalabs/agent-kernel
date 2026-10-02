# Research: #603 Identity layer, RBAC and agent registry

Supporting investigation behind `../design.md` (written 2026-10-01). Research written 2026-09-28.
Single ticket #603 (RBAC Capability Design), into which the requirements of #441 (auth provider
support: Auth0, Cognito), #521 (RBAC capability for auth providers) and #658 (agent entity and
registry) were merged on 2026-09-28; those three issues are closed in its favour. Related:
#243 (omnichannel identity resolver) and the #494 sandbox permission boundary.

Scope of the ask: identity providers behind an adapter architecture; an authorization mechanism
that decides which agents a user may access and at what level (read, write, admin, ...) and which
tools an agent may access; and an agent registry / catalog with agent identity, bridged into one
RBAC capability.

| File | One-line takeaway | Status |
|---|---|---|
| `ak-current-state.md` | AK has an auth seam but no identity layer: no built-in provider, the REST validator's subject is discarded, the WebSocket acting user is the client-controlled frame `user_id`, MCP is mounted outside the auth dependencies, no surface authorizes agent selection per user, the registry is a name-keyed dict with no metadata, tool sets are fixed at load time with no call-time gate, and the only role model (OKF) is per agent. Two precedents to build on: the sandbox `SandboxPrincipal` / `PrincipalResolver` and the run-scoped `ACTING_USER_CACHE_KEY`. | Verified against `develop` `0a33d7d9`, every claim `path:line` |
| `identity-and-delegation.md` | PyJWT (already the `auth` extra) covers JWKS-backed OIDC; provider claim conventions differ enough to need per-provider defaults (Entra `oid`, Cognito `cognito:groups`, Keycloak `realm_access.roles`); keep IdP groups as identity facts and map to AK roles locally. Agent identity is converging on "agent as workload principal, user as subject, agent as `act`" (Entra Agent ID GA, AgentCore Identity, WIMSE AIMS draft). MCP servers must be OAuth 2.1 resource servers with RFC 9728 metadata; A2A 1.0 cards carry `securitySchemes` and per-skill `security`. Three delegation patterns: token exchange, token vault, impersonation. | Web research, verified/unverified marked per claim |
| `authorization-engines.md` | Only Casbin has the in-process "model + swappable policy adapter" shape; OpenFGA is the best ReBAC second (native `ListObjects` / `ListUsers`, first-party agent and MCP modelling docs); Cedar is an in-process policy-as-code option (unofficial Python binding); AuthZEN 1.0 (final 2026-01) gives one HTTP adapter for any PDP. List-filtering has three routes and the registry as candidate set always works. Access levels are expressible in every engine. | Web research, verified/unverified marked per claim |
| `agent-registries-and-prior-art.md` | Mature catalogs (AWS Agent Registry GA 2026-08, Microsoft Agent 365, A2A registry discussion) separate the protocol descriptor, the registry record (owner, version, tags, lifecycle, visibility) and an authorization overlay. Framework gates: OpenAI `is_enabled` + tool guardrails, Pydantic `prepare`, ADK `before_tool_callback`, CrewAI `@before_tool_call`, smolagents nothing; consensus is "filter visibility, authorize every call, deny with a message to the model". Access-level vocabularies map onto read / execute / write / admin. | Web research, verified/unverified marked per claim |
| `design-options.md` | Candidate architecture: `Principal` + `IdentityProvider` factory (oidc, cognito, entra, firebase, static), `AgentDescriptor` + `AgentRegistry` behind a `registry.type` selector, `Authorizer` factory (in_memory, casbin, openfga, cedar, authzen) with an `AccessLevel` scale, an `AccessGate` firing in `ensure_agent_available` and at tool-list and call time through each adapter's native gate. Phase 1 must fix acting-user propagation. Section 4 is the decision log: all ten questions settled in review round 1 (2026-09-28, two passes), including levels as the capability tier driven through an agent, visibility as a synthesized grant, and a descriptor `surfaces` field replacing the protocol allow-lists. | Synthesis plus decision log |

How to read: start with `ak-current-state.md` section 1 (headline findings), then
`design-options.md`; the three surveys are the evidence behind the options.
