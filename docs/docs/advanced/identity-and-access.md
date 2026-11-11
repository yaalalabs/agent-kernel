---
sidebar_position: 7.5
---

# Identity and Access

Agent Kernel **authenticates every request through one configured identity provider and establishes a
`Principal` for the run**. The provider is configuration, not code: an `identity` block names it (an
OpenID Connect issuer such as Auth0, Keycloak or Okta, Amazon Cognito, Microsoft Entra ID, Firebase, a
static credential map, or your own class), and every surface the agent is reached through (REST,
WebSocket, AG-UI, MCP, A2A, the CLI, the messaging integrations) resolves the caller through it. Tools
and hooks read the same principal, threads and scheduled tasks belong to it, and a credential value is
never written in a configuration file.

```yaml
identity:
  provider:
    type: oidc
    issuer: https://login.example.com/
    audience: agent-kernel-api
```

```python
from agentkernel.core import ToolContext

def whoami() -> str:
    principal = ToolContext.get().principal
    return f"{principal.subject} in {principal.namespace} with groups {principal.groups}"
```

## Overview

| Concern | What it means |
| --- | --- |
| **Enablement** | An `identity` block selects the provider. Without one every request runs as the anonymous principal and an `Authorization` header is ignored. |
| **Provider** | One per deployment: `oidc`, `cognito`, `entra`, `firebase`, `static`, or a dotted path to an `IdentityProvider` subclass. |
| **Credential** | A bearer token on HTTP (`Authorization: Bearer <token>`), `?token=<credential>` on the WebSocket handshake, `--token` or `AK_CLI_TOKEN` on the CLI. |
| **Principal** | The subject, its namespace, groups, roles and claims, plus the agent acting on its behalf. Read it with `ToolContext.get().principal` in tools and `Session.get_principal()` in hooks. |
| **Anonymous** | With a provider configured, a request without a credential is anonymous and a credential that does not validate is a `401`. Which routes refuse the anonymous principal is each surface's rule (below). |
| **Roles** | Providers never issue roles. An optional `role_mapper` derives them from groups and claims. |
| **Extra** | `oidc`, `cognito`, `entra` and `firebase` need `agentkernel[auth]` (PyJWT, cryptography, httpx). `static` needs nothing extra. |

## Configuration

```yaml
identity:
  provider:
    type: oidc                       # oidc | cognito | entra | firebase | static | a dotted path
    issuer: https://login.example.com/   # required by oidc; derived by cognito, entra and firebase
    audience: agent-kernel-api       # required by oidc, cognito (the app client id) and entra (the application id)
    jwks_uri: null                   # optional; discovered from the issuer when omitted
    algorithms: [RS256, ES256]       # allowed signing algorithms; symmetric ones are refused
    leeway: 30                       # seconds of clock skew tolerated on exp and nbf
    required_claims: []              # claims a token must carry beyond the standard set
    claims:
      subject: sub                   # claim path of the subject
      groups: groups                 # claim path of the group list, e.g. realm_access.roles
    cognito: {region: eu-west-1, user_pool_id: eu-west-1_abc123, token_use: access}
    entra: {tenant_id: 00000000-0000-0000-0000-000000000000}
    firebase: {project_id: my-project}
    static:
      principals:
        ALICE_TOKEN:                 # a secret key, resolved through the secret capability
          subject: alice
          kind: user                 # user | agent | service
          groups: [ops]
          claims: {email: alice@example.com}
  role_mapper:                       # optional; absent means no roles
    type: mapping                    # mapping | a dotted path to a RoleMapper subclass
    mapping:
      ops: [admin]                   # group name or claim value -> roles
    pass_through: null               # a claim path whose string or list value becomes roles as it is
```

Every field has an environment form with the usual `AK_` prefix and `__` nesting:
`AK_IDENTITY__PROVIDER__TYPE=oidc`, `AK_IDENTITY__PROVIDER__ISSUER=...`,
`AK_IDENTITY__PROVIDER__AUDIENCE=...`, `AK_IDENTITY__PROVIDER__COGNITO__USER_POOL_ID=...`.

A claim path is a claim name, a namespaced name such as `https://acme.com/roles` (tried as one key
first, the way Auth0 issues custom claims), or dotted segments into a nested claim such as
`realm_access.roles`.

## Providers

| `type` | What it validates | Settings | Notes |
| --- | --- | --- | --- |
| `oidc` | A signed JWT from any OpenID Connect issuer: signature against the issuer's JWK set, `iss`, `aud`, `exp` and `nbf` | `issuer`, `audience`; optional `jwks_uri`, `claims` | Auth0, Keycloak, Okta and any other issuer. `namespace` is the issuer. |
| `cognito` | An Amazon Cognito user pool token | `cognito.region`, `cognito.user_pool_id`, `audience` (the app client id); `cognito.token_use` `access` (default) or `id` | Groups come from `cognito:groups`. |
| `entra` | A Microsoft Entra ID (v2.0) token | `entra.tenant_id`, `audience` (the application id) | The subject is `oid`; the `tid` claim must match the tenant. `roles` and `wids` stay in `claims`. |
| `firebase` | A Firebase Authentication id token | `firebase.project_id` | Issuer, audience and Google's JWK set are derived from the project. Groups default to the application's `roles` custom claim. |
| `static` | A credential from a configured map | `static.principals` | For development, tests and the CLI. The keys name secrets; see below. |
| a dotted path | Whatever your class accepts | The whole `identity.provider` block | See bring your own provider. |

### Any OpenID Connect issuer (`oidc`)

The provider reads `<issuer>/.well-known/openid-configuration` once to find the JWK set (or uses
`jwks_uri` directly), caches the keys, and refreshes them once when a token names an unknown key,
rate-limited so a flood of bad tokens cannot turn into a flood of fetches. A token must carry `exp`,
`iss` and `aud`; `aud` must contain the configured `audience`. The principal's `subject` is the
`claims.subject` path (`sub` by default), its `namespace` is the issuer, its `groups` the
`claims.groups` path, and every other claim arrives in `claims` for the role mapper and the tools.

**Auth0** is served by this provider. Use the tenant's issuer (or the custom domain) with the trailing
slash as Auth0 issues it, the API identifier as the audience, and the namespaced claim an Auth0 Action
sets as the groups path:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<tenant>.<region>.auth0.com/   # or the custom domain; trailing slash included, as Auth0 issues it
    audience: <the API identifier of your Auth0 API>
    claims:
      groups: https://<your namespace>/roles       # the namespaced claim an Auth0 Action sets; omit if you set none
```

`permissions`, `org_id` and the other Auth0 claims reach the role mapper and the tools through
`claims`. A token to test with comes from the tenant's `/oauth/token` endpoint, for example through
the client-credentials flow of a machine-to-machine application authorised for the API.

**Keycloak**: the realm is the issuer, the client id is the audience (give the client an audience
mapper), and realm roles sit in a nested claim:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<host>/realms/<realm>
    audience: <client id>
    claims:
      groups: realm_access.roles
```

**Okta**: the authorization server is the issuer and its custom audience the audience; a `groups`
claim configured on the server fills the groups:

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<domain>/oauth2/<authorization server id>
    audience: <the audience of the authorization server>
    claims:
      groups: groups
```

### Amazon Cognito (`cognito`)

```yaml
identity:
  provider:
    type: cognito
    audience: <app client id>
    cognito:
      region: eu-west-1
      user_pool_id: eu-west-1_abc123
      token_use: access              # or id
```

The issuer is derived from the region and the pool. A Cognito access token carries no `aud`: its
audience is `client_id`, which is checked against the configured audience; an id token carries `aud`
and is checked as any other. Groups come from `cognito:groups`.

### Microsoft Entra ID (`entra`)

```yaml
identity:
  provider:
    type: entra
    audience: <application id>
    entra:
      tenant_id: <tenant id>
```

The issuer is derived from the tenant and the token's `tid` must match it. The subject is `oid`, the
groups claim is `groups`, and `roles` and `wids` stay in `claims` for the role mapper. A token carrying
the groups-overage marker (more groups than fit in a token) yields no groups, with one warning per
process: resolving them needs a Graph call this provider does not make.

### Firebase Authentication (`firebase`)

```yaml
identity:
  provider:
    type: firebase
    firebase:
      project_id: <project id>
```

The issuer, the audience and Google's JWK set are derived from the project. Firebase has no built-in
role claim, so the groups path defaults to the application's `roles` custom claim; every custom claim
stays in `claims`. A boolean flag such as `admin: true` needs a role mapper of your own.

### Static credentials (`static`)

```yaml
identity:
  provider:
    type: static
    static:
      principals:
        ALICE_TOKEN:
          subject: alice
          groups: [ops]
        BOB_TOKEN:
          subject: bob
          kind: service
          claims: {team: finance}
```

Each key names a **secret**, not a value: `ALICE_TOKEN` is resolved through the
[secret capability](./secrets.md) when the provider is built (the process environment first, then the
configured secret provider), so the credential a client sends lives in an environment variable, an SSM
parameter or a mounted Kubernetes Secret, never in the file. A key with no secret is a configuration
error at startup; two keys resolving to the same value are refused. Authentication compares the
presented credential against every resolved value in constant time, and the principal's `namespace`
is `static`. This is the provider the examples and the CLI run on.

### Bring your own provider

Set `identity.provider.type` to a dotted path to an `IdentityProvider` subclass. The class receives
the whole `identity.provider` block, and the configured role mapper wraps it like any built-in:

```python
from agentkernel.identity import AuthenticationError, IdentityProvider, RequestContext
from agentkernel.core.model import Principal


class ApiKeyProvider(IdentityProvider):
    name = "api_key"   # the value of Principal.provider

    def __init__(self, config):          # the identity.provider block
        self._keys = load_keys(config)

    async def authenticate(self, credential: str, context: RequestContext | None = None) -> Principal:
        key = self._keys.get(credential)
        if key is None:
            raise AuthenticationError("unknown api key")   # logged, never returned to the caller
        return Principal(subject=key.id, kind="service", provider=self.name, namespace="acme", claims={"tier": key.tier})

    def security_scheme(self):
        return ("apiKey", {"in": "header"})
```

```yaml
identity:
  provider:
    type: myapp.identity.ApiKeyProvider
```

A provider returns the facts it can vouch for (subject, groups, claims, the namespace the subject is
unique within) and never writes `roles`; `context` carries the request path, method and headers when
the surface knows them. `agentkernel.identity.provider.testing.IdentityProviderContract` and
`RoleMapperContract` are reusable pytest contract suites for provider and mapper implementations.

### Role mapper

Providers assert groups and claims; the `role_mapper` turns them into Agent Kernel roles. The built-in
`mapping` type looks every group name and every string claim value (list items included) up in
`mapping` and appends the roles found, then appends the `pass_through` claim's string or list value as
roles as it is. Boolean flags and nested claim objects are not mapped; bring a `RoleMapper` subclass by
dotted path for those.

```yaml
identity:
  provider:
    type: oidc
    issuer: https://<host>/realms/<realm>
    audience: <client id>
    claims:
      groups: realm_access.roles
  role_mapper:
    type: mapping
    mapping:
      ops: [admin]
      finance: [reader]
    pass_through: https://acme.com/roles
```

## The principal

`Principal` (`agentkernel.core.model`) is who a run acts as:

| Field | Meaning |
| --- | --- |
| `subject` | The stable identifier the provider resolved: an OIDC `sub`, Entra's `oid`, a static entry's subject, a messaging platform's user id. |
| `kind` | `user` (default), `agent` or `service`. |
| `provider` | The provider's short name (`oidc`, `static`, ...), or `messaging:<platform>` and `realtime:<gateway>` for the integrations. |
| `namespace` | The scope the subject is unique within: the OIDC issuer, `static`, a Slack workspace id. |
| `groups` | The memberships the provider asserted. |
| `roles` | What the role mapper derived; empty without one. |
| `claims` | Every other fact the provider kept, for the role mapper and the tools. |
| `actor` | The party acting on the subject's behalf: the agent principal (`kind: agent`, `provider: agentkernel`) the runtime attaches while a run executes. |

`Principal.anonymous()` is the principal of a request nobody authenticated; `principal.is_anonymous`
tells the two apart.

The runtime publishes the principal for the duration of a run. Tools read it with
`ToolContext.get().principal`, hooks and any code running inside the session with
`Session.get_principal()`, and `Session.get_owner()` returns a `SessionOwner` (`subject`, `provider`,
`namespace`): the principal a session was first used by, which threads and scheduled tasks are
checked against:

```python
from agentkernel.core import AgentReplyText, PreHook, Session

class OpsOnly(PreHook):
    async def on_run(self, session: Session, agent, requests):
        principal = session.get_principal()
        if "ops" not in principal.groups:
            return AgentReplyText(response="This agent serves the ops group only.")  # replies without running the agent
        return requests
```

A `principal` a client puts in a request body is never trusted: the surface that authenticated the
request overwrites it.

## What each surface does

| Surface | Credential | Without a credential | Refused credential |
| --- | --- | --- | --- |
| REST chat and streaming (`/api/v1/chat`, `/api/v1/stream`) | `Authorization: Bearer` | Runs anonymous | `401` |
| Conversation threads (`/api/v1/threads`, the thread chat routes) | `Authorization: Bearer` | `401 Authentication required`: a thread belongs to its principal and listing is scoped to the caller | `401` |
| Scheduled tasks (`/api/v1/schedules`, a `schedule` block on a chat request) | `Authorization: Bearer` | `401` on the management routes; a chat request with a `schedule` block is `403` (scheduling requires an authenticated principal) | `401` |
| WebSocket gateway and AWS ECS WebSocket | `?token=<credential>` on the handshake | `401 Authentication token is required` | `401 Authentication failed` |
| AG-UI | `Authorization: Bearer` | `401`: AG-UI runs an agent on a caller's behalf | `401` |
| MCP | `Authorization: Bearer`, enforced by FastMCP | `401` once an `identity` block exists; open and anonymous without one | `401` |
| A2A | `Authorization: Bearer` | Runs anonymous | `401` |
| CLI | `--token <credential>` or `AK_CLI_TOKEN` | Runs anonymous | Exits with `Authentication failed` |
| Messaging integrations | The platform's own verification | A `messaging:<platform>` principal: the platform user id as subject, the workspace or tenant as namespace, platform facts in claims | n/a |
| LiveKit realtime | The gateway's own verification | A `realtime:<gateway>` principal | n/a |

Two consequences for request bodies: `user_id` is not a request field any more (a body carrying it is a
`400` with `user_id is not a request field; the acting user comes from the credential`), and the thread
and schedule listings take no `user_id` query parameter: they return the caller's own records. Thread
and task objects still report their owner in a `user_id` field. The thread and schedule handlers
(`AgentThreadRequestHandler`, `ThreadRequestHandler`, `ScheduleRESTRequestHandler`) and
`AGUIRequestHandler` take no arguments and refuse to construct without an `identity` block, as do the
WebSocket modes.

The sandbox's default principal resolver reads the run principal, so `sandbox.identity.mode: user`
runs code as the authenticated caller with no custom resolver; see the [sandbox guide](./sandbox.md).

## Deployments

The identity block belongs in the configuration of the **process that authenticates**, and the
credential of a static provider reaches that process as an environment variable or a mounted Secret.

- **AWS Lambda** ([guide](../deployment/aws-serverless.md)): the API Gateway authorizer Lambda is one
  line, `handler = APIGatewayAuthorizer().handle`; it authenticates the bearer token through the
  provider and returns an Allow policy whose context carries the principal, or a Deny. The
  request-handler Lambda puts that principal on the chat request; a custom route registered with
  `Lambda.register` reads it with `Lambda.principal(event)`. Webhook routes that carry their own
  verification bypass the authorizer with `APIGatewayAuthorizer(bypass=WebhookRouteMatcher.for_integrations("slack"))`.
  For WebSocket APIs the `$connect` Lambda is `handler = WebsocketConnectionHandler.handler`, which
  authenticates `?token=` and stores the principal with the connection. The authorizer module keeps
  its `handler_path` contract and the connections table its `user_id` hash key: the Terraform modules
  are unchanged.
- **AWS ECS** ([guide](../deployment/aws-containerized.md)): the REST service authenticates every
  request; in WebSocket mode the service authenticates the handshake's `?token=`, and custom WebSocket
  routes receive `{"message": ..., "principal": ...}`.
- **Azure Functions** ([guide](../deployment/azure-serverless.md)): `AzureFunctions.handler`
  authenticates the bearer header before parsing the request and answers a refused credential with
  `401` and `{"error": ..., "session_id": null}`.
- **Kubernetes** ([guide](../deployment/onprem-kubernetes.md)): the io handler and the WebSocket
  gateway build the provider, so a static credential reaches them through the chart's `extraEnv` from
  a Secret; the `secretStore` mount reaches only the agent-executing tier.
- **GCP** ([guides](../deployment/gcp-serverless.md)): the examples authenticate Google identity
  tokens at the API Gateway. An `oidc` block with `issuer: https://accounts.google.com`,
  `jwks_uri: https://www.googleapis.com/oauth2/v3/certs` and the gateway's audience makes the same
  caller visible to the application as a principal.

## Migrating from `agentkernel.auth`

The `agentkernel.auth` package (`AuthValidator`, `Authoriser`, the JWT and JWKS validators) and the
handler-level hooks that took them are gone. Authentication is configuration now:

| Before | Now |
| --- | --- |
| `RESTAPI.add_auth_handlers([...])`, `WebSocketGateway.run(auth_validator=...)`, `IOHandler.run(auth_validator=...)` | An `identity` block; `WebSocketGateway.run()`, `IOHandler.run(handlers=[...])` |
| `AgentThreadRequestHandler(authoriser)`, `ThreadRequestHandler(authoriser)`, a schedule handler with an `Authoriser` | `AgentThreadRequestHandler()`, `ThreadRequestHandler()`, `ScheduleRESTRequestHandler()`; ownership is the principal's |
| `AGUIRequestHandler(authoriser)` | `AGUIRequestHandler()` |
| A JWT validator class per deployment | `type: oidc` (or `cognito`, `entra`, `firebase`) |
| A Lambda authorizer that wraps a validator | `handler = APIGatewayAuthorizer().handle` |
| `GCPAuthorizer` | Gone; the API Gateway's own JWT check, or an `oidc` block |
| `user_id` in request bodies and `?user_id=` on listings | The credential; a body carrying `user_id` is a `400` |
| `acting_user_id` on `Runtime.run` | `principal` on `Runtime.run`, `AgentService.run_multi` and `stream_multi` |
| Custom validation logic | A bring-your-own `IdentityProvider` by dotted path, or a `RoleMapper` |

Threads and scheduled tasks recorded before the change carry a user id without a namespace; recreate
or migrate them outside the system.

## Examples

Every example runs on the `static` provider with its credential read from the environment:
`ALICE_TOKEN` and `BOB_TOKEN` for the two-user API demos, `DEMO_TOKEN` for the single-user ones, and
`DEMO_AUTH_TOKEN` for the AWS and Kubernetes deployments (a sensitive `demo_auth_token` Terraform
variable, or the `demo-credentials` Secret on Kubernetes).

- [`examples/aws-serverless/openai-auth`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/openai-auth)
  : the authorizer Lambda on the static provider, with the Auth0 `oidc` configuration documented beside it.
- [`examples/api/thread-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/thread-openai)
  and [`examples/api/multimodal/thread-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/multimodal/thread-openai)
  : two users whose threads stay their own.
- [`examples/api/schedule-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/schedule-openai)
  and [`examples/aws-serverless/schedule-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/schedule-openai)
  : scheduled tasks owned by the authenticated caller; the serverless one adds an authorizer Lambda and reads the owner with `Lambda.principal`.
- [`examples/api/agui`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/agui),
  [`examples/api/hitl`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/hitl) and
  [`examples/api/a2ui-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/a2ui-openai)
  : single-user API demos, the a2ui frontend sending the bearer token.
- [`examples/aws-containerized/openai-websocket`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-websocket),
  [`openai-stream`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-stream),
  [`openai-stream-queue-mode`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-stream-queue-mode) and
  [`openai-websocket-scalable`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-websocket-scalable)
  : ECS WebSocket handshakes authenticated with `?token=`, custom routes reading the principal.
- [`examples/aws-containerized/crewai-auth`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/crewai-auth)
  and [`examples/aws-containerized/openai-schedule`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-containerized/openai-schedule)
  : ECS REST services on the static provider.
- [`examples/aws-serverless/slack-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/slack-openai)
  : the authorizer with a webhook bypass for Slack's signed deliveries.
- [`examples/aws-serverless/websocket-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/websocket-openai)
  and [`examples/aws-serverless/streaming-openai`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/aws-serverless/streaming-openai)
  : the `$connect` Lambda on `WebsocketConnectionHandler.handler`.
- [`examples/k8s/openai-queue-mode`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/k8s/openai-queue-mode)
  : the credential delivered through a Secret and `extraEnv`, sent by the WebSocket and protocol clients.
- [`examples/sandbox/identity`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/sandbox/identity)
  : sandboxed code running as the caller, with a custom resolver as the override of the default.
