# #603: Identity layer, RBAC and agent registry: Implementation Spec

This spec details how `design.md` (the requirements source, settled through review rounds 1 and 2,
decisions Q1 to Q20) is built. One new package, `agentkernel/identity/`, holds the pluggable
identity providers, the authorizer backends, the credential store and the store-backed registry
backends; `core/` gains the models every layer shares (`Principal`, `SessionOwner`, `AccessLevel`,
`AgentDescriptor`, `ToolFilter`), the registry ABC with its in-memory backend, and the publication
of the acting principal that every surface establishes from its credential. The design idea is
unchanged: one `AccessGate` over the registry and the authorizer decides, before any state is
committed, and the acting principal is read-only to everything but `Runtime`.

Evidence is cited against `feature/603-identity-rbac-registry` at `d9d0d18bc` (a docs-only commit
over the develop merge `287ec7485`; every `.py` cited is identical in both). The change ships as a
breaking change with no compatibility window (design section 10).

Seven places where detailing refined the design are listed in [Design refinements](#design-refinements)
at the end; each is a mechanism change inside a settled decision, not a new decision, and each is
reflected in `design.md`.

## Design

### 1. Package layout

```
ak-py/src/agentkernel/
├── core/
│   ├── model.py            # + Principal, SessionOwner, AccessLevel, ToolFilter, AgentDescriptor,
│   │                       #   AgentSkillDescriptor, AgentIdentitySpec; SystemTool.tier;
│   │                       #   BaseChatRequest.principal; user_id removed
│   ├── registry.py         # NEW: AgentRegistry ABC, InMemoryAgentRegistry, AgentRegistryFactory,
│   │                       #   AgentDescriptorPage, AgentRegistrationError
│   ├── runtime.py          # principal and tool-filter publication, resume subject check
│   ├── base.py             # Session.Keys.OWNER, get_principal/get_owner/get_tool_filter,
│   │                       #   Agent.descriptor, Agent.get_tool_names
│   ├── tool.py             # ToolContext.principal / access_level / credentials
│   ├── util/key_value_cache.py   # reserved "ak." prefix
│   ├── service.py, chat_service.py, builder.py, config.py
│   └── __init__.py         # exports Principal, AccessLevel, AgentDescriptor; ACTING_USER_CACHE_KEY gone
├── identity/
│   ├── __init__.py         # PEP 562 lazy exports (the knowledgebase pattern)
│   ├── errors.py           # AuthenticationError, CredentialError
│   ├── provider/
│   │   ├── base.py         # IdentityProvider ABC, RequestContext
│   │   ├── factory.py      # IdentityProviderFactory
│   │   ├── oidc.py         # OIDCIdentityProvider, JWKSCache
│   │   ├── cognito.py, entra.py, firebase.py   # OIDC subclasses
│   │   ├── static.py       # StaticIdentityProvider
│   │   ├── roles.py        # RoleMapper ABC, MappingRoleMapper, RoleMapperFactory
│   │   ├── request.py      # RequestAuthenticator
│   │   └── testing.py      # IdentityProviderContract, RoleMapperContract (imports pytest)
│   ├── authz/
│   │   ├── base.py         # Authorizer ABC, Decision, AuthorizerCapabilities
│   │   ├── factory.py      # AuthorizerFactory
│   │   ├── static.py       # StaticAuthorizer, GrantTable, SubjectMatcher
│   │   ├── gate.py         # AccessGate
│   │   └── testing.py      # AuthorizerContract
│   ├── registry/
│   │   ├── redis_like.py   # _RedisLikeAgentRegistry
│   │   ├── redis.py, valkey.py, dynamodb.py
│   │   └── testing.py      # AgentRegistryContract
│   └── credential/
│       ├── store.py        # CredentialStore ABC, CredentialStoreFactory, CredentialCipher
│       ├── in_memory.py, redis_like.py, redis.py, valkey.py, dynamodb.py
│       ├── exchange.py     # TokenExchanger ABC, IssuedToken, PassthroughTokenExchanger,
│       │                   #   TokenExchangerFactory
│       ├── broker.py       # CredentialBroker
│       └── testing.py      # CredentialStoreContract, TokenExchangerContract
├── auth/                   # DELETED (package), and the stale shadow module auth.py DELETED
└── api/, pipeline/, integration/, framework/, deployment/, schedule/, cli/   # consumers, section 8
```

Rules that govern the package:

1. **Core consumes ABCs it owns, and reaches `identity/` only lazily inside an enabled-check.**
   `core/registry.py` owns the `AgentRegistry` ABC because `Runtime` needs a registry even when no
   `registry` block exists (the in-memory default); `AgentRegistryFactory` imports the store-backed
   backends under `identity/registry/` lazily, the way `SessionStoreBuilder` imports session
   backends (`core/builder.py:151-185`). `AccessGate.get()` and `IdentityProviderFactory.get()`
   return `None` when their block is absent, and `AgentService`, `Runtime` and `ToolContext`
   import them inside that check (the `ChatService._maybe_schedule` precedent,
   `core/chat_service.py:559-568`).
2. **Providers, authorizers, registries and stores never read `AKConfig` in methods.** Each factory
   reads its block once and passes explicit constructor parameters (the shared-driver rule,
   `core/util/driver/`).
3. **Every pluggable seam is an ABC plus a factory in the `core/util/factory.py` shape** (`if/elif`
   real imports for built-ins, `require_extra` around optional SDKs, `resolve_dotted` for a dotted
   path, `AKConfigError` otherwise; `core/util/factory.py:26-64`), with a contract suite next to
   the ABC that imports `pytest` and is kept out of the package exports.
4. **Framework adapters import `core` only.** They read the published `ToolFilter` through
   `Session.get_tool_filter()` and never import `identity/`.
5. **Nothing outside `Session` and `Runtime` spells a reserved key.** `PRINCIPAL_CACHE_KEY`,
   `TOOL_FILTER_CACHE_KEY` and `Session.Keys.OWNER` are fronted by accessors.

Module-level functions introduced by this change, each justified: none. Agent-facing tool
functions are unchanged in kind (the schedule tools keep their shape).

### 2. Core models (`core/model.py`)

Placed beside `BaseChatRequest` (`core/model.py:408`) and `ScheduleSpec` (`core/model.py:379`),
so `core/` never imports the capability.

```python
class AccessLevel(StrEnum):            # ordered: READ < WRITE < ADMIN
    READ = "read"; WRITE = "write"; ADMIN = "admin"
    def __lt__(self, other) ...        # total order over the three members only

class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    subject: str
    kind: Literal["user", "agent", "service"] = "user"
    provider: str                      # provider short name, "messaging:<platform>",
                                       # "realtime:<gateway>", or "anonymous"
    namespace: Optional[str] = None    # issuer | "static" | platform scope | None (anonymous)
    groups: list[str] = []
    roles: list[str] = []
    claims: dict[str, Any] = {}
    actor: Optional["Principal"] = None
    credential_ref: Optional[str] = None
    @classmethod
    def anonymous(cls) -> "Principal": ...     # subject="anonymous", provider="anonymous"
    @property
    def is_anonymous(self) -> bool: ...
    def with_actor(self, actor: "Principal") -> "Principal": ...   # model_copy(update=...)
    def with_credential_ref(self, ref: Optional[str]) -> "Principal": ...

class SessionOwner(BaseModel):
    subject: str
    provider: str
    namespace: Optional[str] = None

class ToolFilter(BaseModel):
    """The per-run tool decision Runtime publishes; adapters only read it."""
    model_config = ConfigDict(frozen=True)
    level: AccessLevel
    allowed: frozenset[str]
    reasons: dict[str, str] = {}       # denied tool name -> reason string
    def allows(self, name: str) -> bool: ...
    def reason(self, name: str) -> str: ...   # the reason, or a generic one for an unlisted name

class AgentSkillDescriptor(BaseModel):
    id: str; name: str; description: str = ""; tags: list[str] = []

class AgentIdentitySpec(BaseModel):
    subject: Optional[str] = None      # defaults to the descriptor id at build time
    client_id: Optional[str] = None
    client_secret_key: Optional[str] = None

class AgentDescriptor(BaseModel):
    id: str; name: str
    version: str = "0.0.0"
    description: str = ""              # catalog text; never get_description()
    owner: Optional[str] = None
    tags: list[str] = []
    visibility: Literal["private", "internal", "public"] = "private"
    surfaces: Optional[list[Literal["rest", "a2a", "mcp", "agui"]]] = None   # None = every surface
    skills: list[AgentSkillDescriptor] = []
    tools: list[str] = []
    runner: str = ""
    supports_streaming: bool = True
    identity: AgentIdentitySpec = AgentIdentitySpec()
    updated_at: Optional[str] = None   # set by store-backed registries
    def exposed_on(self, surface: str) -> bool: ...
```

- `Principal.frozen` means a hook or tool holding one cannot mutate it; `with_actor` and
  `with_credential_ref` return copies, and only `Runtime` and the surfaces call them.
- `SystemTool` (`core/model.py:357-360`) gains `tier: AccessLevel = AccessLevel.READ`. The
  declared tiers (design section 1): sandbox tools and the five schedule tools `WRITE`
  (`sandbox/tools.py:447-459`, `schedule/tools.py:370-374`); `analyze_attachments`
  (`core/multimodal/tools.py:89-101`), the OKF read tools (`knowledgebase/okf/tools.py:55`),
  `get_agui_state`, `get_forwarded_props`, `get_agui_context` (`integration/agui/state.py:198-212`)
  `READ`; `write_kb` and `update_agui_state` `WRITE`. `AnalyzeAttachmentsTool` declares it as a
  field default like its other fields.
- `BaseChatRequest` (`core/model.py:408-431`): `user_id` (line 427) is **removed**;
  `principal: Optional[Principal] = None` is **added** with the docstring rule "assigned by the
  surface after authentication; a value arriving from a client is overwritten, never read".
  `group_id`, `thread_name`, `schedule` and `resume` stay. The docstring lines 411-417 that
  say `user_id` is required for threads and schedules are rewritten to "a non-anonymous
  principal is required".
- `BaseRequest.from_payload` (`core/model.py:488-520`): the envelope `user_id` read (line 497),
  its stripping from the body (lines 503 and 505) and the "envelope is authoritative" propagation
  (lines 513-516) are deleted. A payload whose envelope or body carries a `user_id` key raises
  `ValueError("user_id is not a request field; the acting user comes from the credential")`
  (section 8.3 maps it). `BaseRequest` keeps no `user_id` extra.
- `ScheduledTask` (`schedule/model.py`) gains `principal: Optional[dict[str, Any]] = None`, the
  owner's frozen principal as JSON primitives; `user_id` stays as the owner key and equals
  `principal["subject"]` for tasks created after the change.
- `PausedRun` (`core/paused_run.py:46-71`) gains `subject: Optional[str] = None`,
  `provider: Optional[str] = None`, `namespace: Optional[str] = None`, recorded by
  `PausedRunState.add` from `Session.get_principal()` when it is non-anonymous. A record with no
  subject (written before the change, or paused by an anonymous run) is resumable by anyone, as
  today.

### 3. Session, cache and Runtime publication

**`KeyValueCache`** (`core/util/key_value_cache.py:11-132`), which today rejects only an empty
key (lines 39-40):

```python
class KeyValueCache(BaseModel):
    RESERVED_PREFIX: ClassVar[str] = "ak."
    def set(self, key, value): ...        # ValueError(f"'{key}' is reserved for Agent Kernel") on the prefix
    def delete(self, key): ...            # same refusal
    def update(self, other): ...          # refuses when any key carries the prefix; nothing written
    def __setitem__/__delitem__ ...       # delegate to set/delete, so the refusal holds
    def clear(self): ...                  # application keys only; reserved keys survive
    def _set_reserved(self, key, value): ...     # core only
    def _delete_reserved(self, key): ...
    def _clear_all(self): ...             # what Runtime's finally calls on the volatile cache
```

- `get`, `has`, `keys`, `items` and `__contains__` are unchanged: reading a reserved key stays
  open, which is what makes `ak.paused_runs` and the published principal readable by tools.
- `clear()` keeping reserved keys is what retires the "accepted risk" note at
  `core/paused_run.py:24-26`: an application clearing the non-volatile cache no longer discards
  pending HITL decisions. `Runtime.run`/`stream` (`core/runtime.py:430, 537`) switch to
  `_clear_all()` on the volatile cache; `Session.clear()` (`core/base.py:238-247`) calls
  `_clear_all()` on the non-volatile cache (an explicit reset discards the conversation, pending
  decisions included) and the application `clear()` on the volatile one, so a tool that resets
  the session mid-run keeps the run's principal and tool filter until Runtime's `finally`.
- `PausedRunState._write` (`core/paused_run.py:114-128`) and `clear` switch to `_set_reserved` /
  `_delete_reserved`; it is the only existing writer of a reserved key.

**`Session`** (`core/base.py:28-247`):

```python
class Keys(Enum):
    VOLATILE_CACHE = "v_cache"; NON_VOLATILE_CACHE = "nv_cache"; FRAMEWORK_CONTEXT = "framework_context"
    OWNER = "owner"                      # NEW durable key, SessionOwner

def get_principal(self) -> Optional[Principal]: ...     # fronts PRINCIPAL_CACHE_KEY in v_cache
def get_tool_filter(self) -> Optional[ToolFilter]: ...  # fronts TOOL_FILTER_CACHE_KEY in v_cache
def get_owner(self) -> Optional[SessionOwner]: ...      # fronts Keys.OWNER in _data
def _publish_run(self, principal: Principal, tool_filter: Optional[ToolFilter]) -> None: ...
def _unpublish_run(self) -> None: ...
def _record_owner(self, owner: SessionOwner) -> None: ...   # sets once; no-op when present
```

- The constants `PRINCIPAL_CACHE_KEY = "ak.principal"` and `TOOL_FILTER_CACHE_KEY =
  "ak.tool_filter"` live in `core/base.py` next to `Keys` and are not exported; the accessors
  above are the only spellings. `ACTING_USER_CACHE_KEY` (`core/runtime.py:40`, exported at
  `core/__init__.py:48`) is deleted.
- The owner persists with every store because the stores write `session.get_all(volatile=False)`
  (`core/session/redis.py:100`, `valkey.py:100`, `dynamodb.py:105`, `cosmosdb.py:108`,
  `firestore.py:99`); `in_memory.py:114` keeps the live object. `Session.clear()` keeps the owner
  key (it is identity, not conversation state) and `clear_framework_context()` never touched it.
- The volatile cache is never persisted (same citations), so `ak.principal` cannot be read back by
  a later run. The in-process `SessionCache` holds live objects (`redis.py:104-105`), which the
  `_unpublish_run` in Runtime's `finally` empties before the lock is released.

**`ToolContext`** (`core/tool.py:22-141`) gains three read-only properties:

```python
@property
def principal(self) -> Optional[Principal]: return self._session.get_principal()
@property
def access_level(self) -> Optional[AccessLevel]:
    f = self._session.get_tool_filter(); return f.level if f else None
@property
def credentials(self) -> "CredentialBroker": ...   # lazy import; raises CredentialError on use
                                                    # when identity.credentials is absent
```

`credentials` returns a `CredentialBroker` bound to the run principal when `identity.credentials`
is configured, else a `CredentialBroker` whose every `token_for` raises
`CredentialError("identity.credentials is not configured")`; the property itself never raises,
so a tool that only reads `principal` pays nothing.

**`Runtime`** (`core/runtime.py:109-544`):

```python
async def run(self, agent, session, requests, principal: Optional[Principal] = None) -> AgentReply
async def stream(self, agent, session, requests, principal: Optional[Principal] = None) -> AsyncGenerator[StreamChunk, None]
```

Sequence inside `async with session:` (replacing `core/runtime.py:394-430` and `455-537`):

1. `principal = principal or Principal.anonymous()`; `principal = principal.with_actor(
   Principal(kind="agent", subject=agent.descriptor.identity.subject or agent.descriptor.id,
   provider="agentkernel"))`.
2. `gate = AccessGate.get()` (lazy import; `None` without an `authorization` block).
3. With a gate: `level = gate.authorize_agent(principal, agent.descriptor.id)` (raises
   `PermissionError`); `gate.authorize_session(principal, session)` (raises `PermissionError`);
   `tool_filter = gate.tool_filter(principal, agent)`. Without a gate: `tool_filter = None`.
   `run` lets `PermissionError` propagate; `stream` yields one `StreamChunk(error=str(e),
   done=True)` and returns, storing nothing (the `StreamHalt` shape, `core/runtime.py:525-529`).
4. `session._publish_run(principal, tool_filter)`; `session._record_owner(SessionOwner(
   subject, provider, namespace))` when the principal is non-anonymous, a shared-channel
   principal included (Q17 refined: its owner binds the session to the platform scope).
5. `with agent._activate():` pre-hooks, resume validation, runner, post-hooks, store, exactly as
   today (`core/runtime.py:398-427`).
6. `finally: session._unpublish_run(); session.get_volatile_cache()._clear_all()`.

- The gate check runs before `_prepare_requests`, so an unauthorized principal never reaches a
  pre-hook or a guardrail call.
- `_validate_resume` (`core/runtime.py:273-332`) gains an eighth check after the agent-name check
  (line 314): when `record.subject` is set and the run principal is non-anonymous and
  `(record.namespace, record.subject) != (principal.namespace, principal.subject)`, raise
  `PermissionError(f"Paused run '{record.id}' belongs to another principal")`. It sits above the
  adapter's `try`, like the other checks (`docs/specs/606`'s rule).
- `register(agent)` (`core/runtime.py:204-213`) becomes `self.registry.register(
   agent.descriptor, agent)`; the bare `Exception` at line 213 becomes `AgentRegistrationError`.
  `deregister` and `agents()` delegate; `Runtime.__init__` gains `registry: Optional[AgentRegistry]
  = None`, defaulting to `AgentRegistryFactory.build()`, and a `registry` property.
- The realtime path (`pipeline/realtime_pool.py:228-252`) never calls `Runtime.run`; section 8.4
  publishes the principal there through `Runtime._publish`, the one caller outside a run allowed
  to, because it is the AK-owned entry point for a tool call.

### 4. Identity providers (`identity/provider/`)

**`RequestContext`** (`provider/base.py`): `path`, `http_method`, `headers`, the three fields of
today's `ValidationContext` (`auth/handler.py:7-10`) moved with the package.

**`IdentityProvider`** ABC (`provider/base.py`):

```python
class IdentityProvider(ABC):
    name: ClassVar[str]
    @abstractmethod
    async def authenticate(self, credential: str, context: Optional[RequestContext] = None) -> Principal: ...
    def security_scheme(self) -> tuple[str, dict[str, Any]]: ...   # ("bearer", {}) by default;
                                                                    # OIDC family returns ("openIdConnect", {"url": discovery})
    async def close(self) -> None: ...                              # no-op default
```

`AuthenticationError(reason)` (`identity/errors.py`) is the only failure; the reason is logged by
the caller, never returned to a client.

**`IdentityProviderFactory`** (`provider/factory.py`): `create(identity_config) ->
IdentityProvider`; `get()` returns the process-wide provider built from `AKConfig.get().identity`,
or `None` when the block is absent; `reset()` for tests. Branches on `identity.provider.type`:
`oidc`, `cognito`, `entra`, `firebase` (each under `require_extra("auth", "identity.provider.type:
<name>")`), `static`, else `resolve_dotted(type, base=IdentityProvider)(config)`, else
`AKConfigError`. A dotted provider receives the whole `identity.provider` block.

**`OIDCIdentityProvider`** (`provider/oidc.py`), constructed with explicit parameters
(`issuer`, `audience`, `jwks_uri`, `algorithms`, `leeway`, `required_claims`, `subject_claim`,
`groups_claim`):

- `JWKSCache` (same module): fetches discovery (`GET <issuer>/.well-known/openid-configuration`,
  once, lazily, caching `jwks_uri`; `jwks_uri` in config skips it) and the JWK set itself through
  one `httpx.AsyncClient` (an injectable transport, so tests serve both from a `MockTransport`),
  and selects the key by `kid` from `jwt.PyJWKSet.from_dict` (PyJWT 2.15, the `auth` extra,
  `ak-py/pyproject.toml:24-28`); `signing_key(kid)` is the one entry point. An unknown `kid`
  triggers one forced refresh, rate-limited to one per 30 s (`refresh_cooldown`, counted between
  forced refreshes, not from the initial load), then `AuthenticationError`; a fetch that fails
  leaves the previous key set in place and is an `AuthenticationError` too. Design refinement 6:
  `PyJWKClient` was dropped because its `urllib` fetch blocks and cannot be pointed at a test
  transport.
  PR #937 review follow-up (2026-11-12): the cache holds no event-loop-bound state, because one
  provider is shared by every caller in the process and a sync host (Azure's thread-pooled
  functions, through `run_async_sync`) runs each call on a fresh loop; the pooled `AsyncClient`
  connection and the `asyncio.Lock` broke a refresh on a later loop (`Event loop is closed`) and
  hung a concurrent cold start. The key set is a dict swapped whole and read without a lock, so a
  known `kid` never waits behind a refresh; a load runs on a worker thread (`asyncio.to_thread`)
  through a short-lived `httpx.Client` with the injectable transport, serialized by a
  `threading.Lock` taken only on that thread (never across an `await`, which would deadlock two
  coroutines on one loop) with a generation check, so a caller that waited does not fetch again.
  A failed first load is not retried for `failure_cooldown` (5 s); any fetch failure, a key-set
  body that is not an object included, is an `AuthenticationError`; a non-string `kid` is refused.
- `authenticate`: `jwt.decode(token, key, algorithms=self._algorithms, audience=self._audience,
  issuer=self._issuer, leeway=self._leeway, options={"require": ["exp", "iss", "aud", ...]})`.
  Symmetric algorithms (`HS*`) are refused at construction with `AKConfigError`, and so (PR #937
  review follow-up) are an empty list, `none` and any name `jwt.algorithms` does not know, since
  each would build and then refuse every token; Cognito's `token_use` is `Literal["access", "id"]`
  in config and checked by the constructor. Every
  `jwt.PyJWTError` becomes `AuthenticationError(str(exc))`. `required_claims` entries missing from
  the payload are an `AuthenticationError`.
- Claim paths are resolved by `ClaimPath.read(payload, path)` (a static helper in
  `provider/base.py`, shared with the role mapper's `pass_through`): the whole path is tried as
  one claim name first, then split on dots and walked, so Auth0's namespaced custom claims
  (`https://acme.com/roles`) and Keycloak's nested `realm_access.roles` both resolve: `subject`
  (default `sub`, missing is an `AuthenticationError`), `groups` (default
  `groups`, missing yields `[]`, a string yields a one-element list). `namespace` is the validated
  `iss`. Every claim but the subject lands in `Principal.claims` verbatim, the groups claim
  included beside its `groups` projection; `roles` is never written. (PR #937 review follow-up,
  2026-11-11: the groups claim was dropped from `claims`, so a `pass_through` on a top-level groups
  claim, Firebase's default `roles` among them, silently found nothing.)
- Subclasses change defaults and one check each; a subclass default for a claim path applies only
  when the block left that path unset (`model_fields_set`), so `claims.groups: groups` on a Cognito
  block is honoured and an untouched block gets `cognito:groups`:
  - `CognitoIdentityProvider`: issuer `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`,
    groups claim `cognito:groups`, requires `token_use == <configured, default "access">`, and
    for access tokens checks `client_id` against `audience` instead of `aud`.
  - `EntraIdentityProvider`: issuer `https://login.microsoftonline.com/{tenant_id}/v2.0`, subject
    claim `oid`, requires `tid == tenant_id`; a `_claim_names` key (groups overage) yields `[]`
    groups and one warning per process.
  - `FirebaseIdentityProvider`: issuer `https://securetoken.google.com/{project_id}`, audience
    `project_id`, `jwks_uri` fixed to Google's `securetoken@system.gserviceaccount.com` JWK set,
    groups claim `roles` (Q14).
- `security_scheme()` returns `("openIdConnect", {"url": f"{issuer}/.well-known/openid-configuration"})`.
- The configured `issuer` is compared verbatim and with the trailing slash added or removed (an
  Auth0 issuer is `https://<tenant>.<region>.auth0.com/` and its `iss` carries the slash);
  `namespace` is the token's `iss` as issued. Auth0 is therefore an `oidc` configuration, not a
  provider of its own: `issuer` the tenant or custom domain, `audience` the API identifier,
  `claims.groups` the namespaced claim an Action sets, with `permissions` and `org_id` arriving in
  `claims` for the role mapper and the tools.

**`StaticIdentityProvider`** (`provider/static.py`): constructed with `principals: dict[str,
dict]` (credential key to principal fields) and an optional `secrets: SecretManager` (tests pass
one; the factory's `from_config(config)` leaves it to `SecretManager.current()`). At construction
every key is resolved through `SecretManager.get(key)` (`secret/manager.py:60-76`); a
`SecretNotFoundError` or a malformed key is an `AKConfigError` naming the key, and two principals
resolving to the same credential value are refused, as is an empty `principals` map (PR #937
review follow-up: a typo such as `static: {principal: ...}` is dropped by the model and would
leave a provider that 401s every caller). `authenticate` compares the credential
against every resolved value with `hmac.compare_digest` (constant time over all entries) and
returns `Principal(subject, kind, groups, roles, claims, provider="static", namespace="static")`;
no match is an `AuthenticationError`. The static block's `roles` are the one case of a provider
issuing roles itself, since it is Agent Kernel's own dev provider; a configured role mapper
replaces them like any provider's. This is the recorded exception to the single-producer rule
(design sections 2 and 5, amended at the PR #937 review). Documented as the dev, test and CLI
provider.

**`RoleMapper`** (`provider/roles.py`):

```python
class RoleMapper(ABC):
    @abstractmethod
    def map(self, principal: Principal) -> list[str]: ...

class MappingRoleMapper(RoleMapper):
    def __init__(self, mapping: dict[str, list[str]], pass_through: Optional[str], claims: Iterable[str] = ()): ...
    # roles = union over principal.groups and the string/list values at the listed `claims`
    #         paths, looked up in `mapping`, plus the values at the pass_through claim path (str
    #         or list[str]); de-duplicated, order of first appearance

class RoleMapperFactory:
    @staticmethod
    def create(role_mapper_config) -> RoleMapper: ...   # "mapping" | dotted path | AKConfigError
```

PR #937 review follow-up (2026-11-12): `mapping` looks up the groups and, beyond them, only the
claim paths listed in `identity.role_mapper.claims` (default empty). Every top-level string claim
was looked up before, so a claim the user sets (a Firebase `name`, a Cognito `username`, an
`email`) could grant a role; design section 5's "provider group or claim value" is narrowed to
match. `_IdentityProviderConfig` and `_RoleMapperConfig` allow extra keys, which a dotted-path
provider or mapper reads from `model_extra`.

`IdentityProviderFactory.create` wraps the provider in `MappedIdentityProvider(provider, mapper)`
when `identity.role_mapper` is present, so `authenticate` returns `principal.model_copy(
update={"roles": mapper.map(principal)})`: with a mapper, `Principal.roles` has exactly one
producer, and without one only a `static` entry's own roles are set. Boolean flag claims are not
mapped by the built-in mapper (Q14); a dotted-path mapper handles them.

**`RequestAuthenticator`** (`provider/request.py`), the shared extraction over the configured
provider, replacing the three copies of header parsing (`api/http.py:223-226`,
`api/handler.py:63-69`, `pipeline/ws/handler.py:177-187`):

```python
class RequestAuthenticator:
    _current: ClassVar[contextvars.ContextVar[Optional[Principal]]]
    def __init__(self, provider: Optional[IdentityProvider], credentials: Optional["CredentialStore"], inbound_ttl: int): ...
    @classmethod
    def from_config(cls) -> "RequestAuthenticator": ...      # provider None when identity is absent
    async def authenticate_bearer(self, header: Optional[str], context: RequestContext) -> Principal
    async def authenticate_token(self, token: Optional[str], context: RequestContext) -> Principal
    def dependency(self) -> Callable                           # FastAPI Depends: principal on request.state
    @classmethod
    def current(cls) -> Optional[Principal]                   # the request's principal, for code that
                                                              # has no Request (the A2A executor)
    async def release(self, principal: Principal) -> None     # deletes the credential_ref entry
```

- Bearer parsing is `scheme, _, token = header.partition(" ")`, case-insensitive scheme, token
  stripped (the `api/handler.py:66-67` form, not the case-sensitive `replace` at `api/http.py:226`).
- No header and no provider: `Principal.anonymous()`. No header with a provider: anonymous too;
  the handlers that refuse anonymous callers say so themselves (section 8). A present header with
  no provider is ignored (anonymous) without being parsed, so a malformed or non-bearer one is
  ignored too (PR #937 review follow-up, 2026-11-11: the scheme was checked first, which answered
  `Authorization: Basic ...` with a 401 on a deployment with no identity block).
- A present but invalid credential: `AuthenticationError` is caught and re-raised as
  `HTTPException(401, detail="Unauthorized")`; the reason is logged at INFO with the path. A
  malformed scheme is `401 "Invalid authorization header"`. Both 401s carry
  `WWW-Authenticate: Bearer` (RFC 6750 section 3), as does the `AuthorisedRESTRequestHandler`
  401 for an anonymous caller (PR #937 review follow-up, 2026-11-12).
- The dependency takes Starlette's `HTTPConnection`, which FastAPI injects for HTTP and WebSocket
  scopes alike (PR #937 review follow-up): typed `Request`, it raised `TypeError` on a WebSocket
  route of a guarded router. On a WebSocket a refused credential is a `WebSocketException` with
  close code 1008 and the public detail.
- When `identity.credentials` is configured, a successful authentication mints
  `credential_ref = uuid4().hex`, stores the raw credential under it with TTL
  `min(exp - now, inbound_ttl)` (`exp` read from `claims`, else `inbound_ttl`), and returns
  `principal.with_credential_ref(ref)`. `release` deletes it; `Runtime` calls it in `finally`
  for the direct path and `AgentRunner` for the queued path (section 8.4). A ref prefixed `conn:`
  is connection-scoped: the WebSocket handlers mint it at connect through `authenticate_token`
  and delete it at disconnect, every frame's body carries it, and `release` leaves it alone. Its
  TTL is the token's `exp` when present, else `inbound_ttl` renewed per frame by the handlers
  that hold the token (pipeline and ECS gateways; the Lambda handler cannot renew); an expired
  entry makes `CredentialBroker` raise `CredentialError` until the client reconnects (design 3.1).
- `dependency()` returns an `async def identity_dependency(request: Request)` that sets
  `request.state.principal` and `RequestAuthenticator._current` for the request's task.

**`IdentityProviderContract`** (`provider/testing.py`, subclassed by every built-in): a valid
credential yields the expected subject, groups, namespace and claims with `roles == []`; expired,
wrong audience, wrong issuer, unknown `kid`, tampered signature and missing subject each raise
`AuthenticationError`; the groups path maps a string and a list. The OIDC family runs it over a
local JWKS fixture (an `httpx.MockTransport` serving a generated RSA and EC key pair).
`RoleMapperContract`: `mapping` on groups and claim values, `pass_through` on a string and a list,
de-duplication, a dotted-path mapper receiving the whole principal.

### 5. Credentials (`identity/credential/`)

**`CredentialStore`** ABC (`credential/store.py`): `put(key, value: bytes, expires_at: float)`,
`get(key) -> Optional[bytes]`, `delete(key)`, `clear()`. Values are ciphertext produced by
`CredentialCipher` (same module) over `cryptography`'s `AESGCM` (12-byte random nonce prefixed
to the ciphertext, associated data = the key), keyed by the 32-byte value of the secret named by
`identity.credentials.encryption_key`, resolved through `SecretManager.current().get(name)` and
base64url-decoded; a wrong length is `AKConfigError`. The `auth` extra gains
`cryptography>=42.0` and `httpx>=0.27.0` (section Config changes).

- `InMemoryCredentialStore` (`in_memory.py`): a class-level dict with expiry checked on read;
  the only backend that works without `encryption_key` (plaintext in process memory, one startup
  warning). `shared = False`.
- `_RedisLikeCredentialStore` (`redis_like.py`), `RedisCredentialStore`, `ValkeyCredentialStore`:
  `set` with `expire_in(ttl)` over `_RedisLikeDriver` (`core/util/driver/redis_like.py:112,380`),
  key `{prefix}{key}`, prefix default `ak:cred:`. `DynamoDBCredentialStore`: one item per key over
  `DynamoDBDriver(table_name, partition_key="credential_key", ttl=...)` with `expiry_time`.
  These three raise `AKConfigError` at construction without an `encryption_key`.
- `CredentialStoreFactory.create(credentials_config) -> CredentialStore`: `in_memory` (default),
  `redis`, `valkey`, `dynamodb` (under `require_extra("redis"|"valkey"|"aws", ...)`), dotted path,
  else `AKConfigError`.

**`TokenExchanger`** ABC (`credential/exchange.py`): `async exchange(inbound: str, audience: str,
scopes: list[str], actor: Optional[Principal]) -> IssuedToken(access_token, expires_at,
token_type)`. `PassthroughTokenExchanger` returns the inbound credential unchanged with
`expires_at` from its `exp` claim when decodable, else `now + inbound_ttl`; it logs one warning at
startup: "passthrough exchanger configured for <audience>: the inbound token is forwarded as-is;
dev only". `TokenExchangerFactory.create(exchanger_config) -> TokenExchanger`: `passthrough`,
dotted path, else `AKConfigError`; the names `rfc8693`, `entra_obo` and `id_jag` raise
`AKConfigError(f"identity.credentials.exchangers[].type: {name} is not shipped yet; use a dotted
path")` so a config written for a later release fails loudly (Q19).

**`CredentialBroker`** (`credential/broker.py`):

```python
class CredentialBroker:
    def __init__(self, principal: Principal, store: CredentialStore, cipher: CredentialCipher,
                 exchangers: dict[str, TokenExchanger], agent_id: str): ...
    async def token_for(self, audience: str, scopes: Optional[list[str]] = None) -> str: ...
```

`token_for`: cache key `cred:issued:{sha256(subject|provider|namespace|agent_id|audience|sorted
scopes)}`; a cached `IssuedToken` with `expires_at - 30 > now` is returned; else the inbound
credential is read by `principal.credential_ref` (`CredentialError("no inbound credential for this
run")` when absent or expired), the exchanger matching `audience` exactly is called
(`CredentialError("no exchanger configured for audience ...")` when none), the result is stored
with TTL `expires_at - now` and returned. Exchange failures propagate as `CredentialError`. The
broker is constructed per run by `ToolContext.credentials` and holds no state beyond its
arguments. Tools turn `CredentialError` into a tool error result (the OKF string pattern,
`knowledgebase/okf/tools.py:150-152`); nothing in the broker logs a token. Adapter MCP clients
are not wired to the broker in this change: a tool calls `token_for` itself, and the wiring
lands with the first exchange flow (design section 3.1, Q19).

**Contracts** (`credential/testing.py`): `CredentialStoreContract` (round trip, expiry, delete,
ciphertext never equals plaintext, wrong key fails to decrypt) and `TokenExchangerContract`
(issued token shape, `expires_at` in the future, `actor` forwarded) subclassed by `passthrough`
and a fake exchanger.

### 6. Registry (`core/registry.py`, `identity/registry/`)

```python
class AgentRegistrationError(Exception): ...
class AgentDescriptorPage(BaseModel): agents: list[AgentDescriptor]; next_cursor: Optional[str]

class AgentRegistry(ABC):
    @abstractmethod def register(self, descriptor: AgentDescriptor, agent: Agent) -> None   # AgentRegistrationError on a duplicate id
    @abstractmethod def deregister(self, id: str) -> None
    @abstractmethod def get(self, id: str) -> Optional[Agent]                  # process-local object
    @abstractmethod def descriptor(self, id: str) -> Optional[AgentDescriptor]
    @abstractmethod def agents(self) -> dict[str, Agent]                       # the Runtime.agents() contract
    @abstractmethod def descriptors(self) -> list[AgentDescriptor]             # every known descriptor
    def list(self, cursor: Optional[str] = None, limit: Optional[int] = None, tags: Optional[list[str]] = None) -> AgentDescriptorPage
        # concrete: descriptors() filtered by tags (every tag present), sorted by id, paged with
        # core/util/pagination.py decode_cursor / clamp_limit / paginate / encode_cursor
    def clear(self) -> None
```

- `InMemoryAgentRegistry` (`core/registry.py`): two instance dicts, `_agents` and
  `_descriptors`, replacing `Runtime._agents` (`core/runtime.py:144`). Per `Runtime` instance as
  today (`tests/test_module.py:164-179`).
- Store-backed registries (`identity/registry/`) persist descriptors only and keep the local
  `_agents` dict for `get`/`agents()`: `register` upserts `{descriptor JSON, updated_at}`;
  `descriptor(id)` and `descriptors()` read the store, so an io-handler process lists agents it
  does not host. Redis-like layout `{prefix}agent:{id}` plus `{prefix}index:all` set, re-`sadd`ed
  on every write and `srem`ed on `deregister` (the `schedule/store/redis_like.py:103-118` shape);
  DynamoDB one item per agent, partition key `agent_id`, no sort key, denormalized `updated_at`,
  listing by scan (`schedule/store/dynamodb.py:1-18`). `ttl` default 0: records never expire; a
  crashed process leaving a record is the documented boundary.
- `AgentRegistryFactory.build() -> AgentRegistry` (`core/registry.py`): `in_memory` when the
  `registry` block is absent or `registry.type == "in_memory"`; `redis`, `valkey`, `dynamodb`
  under `require_extra` with lazy imports from `identity/registry/`; dotted path; else
  `AKConfigError`. The config overlay `registry.agents.<id>` is applied inside `register`
  (section 6, descriptor sources), so every backend sees the final descriptor.
- `AgentRegistryContract` (`identity/registry/testing.py`): duplicate id, upsert on re-register,
  `descriptors()` after `deregister`, `list` paging and tag filtering, a descriptor written by one
  instance read by another over the same fake driver.

**Descriptor sources, later wins per field:**

1. `Agent.descriptor` (`core/base.py`, a property) is built once in `Agent.__init__` from
   `_build_descriptor()`: `id = name`, `name`, `tools = self.get_tool_names()`, `skills` one per
   tool (`id = name = tool name`, `description` from the native tool where the adapter has one),
   `runner = runner.name`, `supports_streaming = runner.supports_streaming`, `description = ""`.
   `Agent.get_tool_names() -> list[str]` is a new method each adapter implements (section 9 lists
   the source per adapter); the base implementation returns `[]`.
2. `Module.describe(agent, **fields) -> Self` (`core/module.py`, beside `pre_hook`, `post_hook`
   and `run_options`, resolving the wrapped agent through `_wrapped` (`core/module.py:134-145`)):
   `ValueError` for an unloaded agent and for a field `AgentDescriptor` does not declare; applies
   `descriptor.model_copy(update=fields)`.
3. The `registry.agents.<id>` overlay, applied by `AgentRegistryFactory`'s returned registry in
   `register` (the registry is constructed with the overlay dict).

**Availability** (`core/service.py:49-70`):

```python
@staticmethod
def ensure_agent_available(name: Optional[str], principal: Optional[Principal] = None) -> None
```

`registry = Runtime.current().registry`; a named agent must have `registry.descriptor(name)`
(`ValueError("No agent available")` otherwise, unchanged text); an unnamed one needs at least one
descriptor. Then, when `AccessGate.get()` is not `None` and a name is given:
`gate.authorize_agent(principal or Principal.anonymous(), name)`, which raises `PermissionError`
(no level) or `LookupError` (not visible; section 7). `select` (`core/service.py:72-101`) still
needs the local `Agent` and raises `ValueError` when the process does not host it.

**Catalog** (`api/handler.py:102-103`, `list_agents`): becomes
`GET /api/v1/agents?cursor=&limit=&tags=` returning `{"agents": [descriptor...],
"next_cursor": ...}` where the list is `AccessGate.visible_agents(principal)` narrowed to
`surfaces` containing `"rest"` (or `surfaces is None`), and each descriptor's `tools` is
replaced by `gate.tool_filter(principal, agent).allowed` when the process hosts the agent, else
the stored list filtered by `check_tool` through the authorizer (the io-handler case, Q15). With no
gate the full descriptor list is returned. `limit` is clamped by `clamp_limit(limit,
DEFAULT_PAGE_SIZE)`; a malformed cursor is 400.

**A2A card** (`core/builder.py:40-74`): `A2ACardBuilder.build(descriptor: AgentDescriptor) ->
AgentCard` replaces `build(name, description, skills)`: `name`, `description`, `version =
descriptor.version` (not `library_version`, line 69), `supported_interfaces` as today, `skills`
from `descriptor.skills` (tags defaulted to `[name]` as today, lines 90-101), and when
`IdentityProviderFactory.get()` is not `None`: `security_schemes = {"ak": SecurityScheme(
http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))}` for `static` and dotted
providers, or `SecurityScheme(open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
open_id_connect_url=<discovery url>))` for the OIDC family; `security_requirements =
[SecurityRequirement(schemes={"ak": StringList(list=[])})]`, mirrored onto every skill
(`a2a/types/a2a_pb2.pyi:188-277, 305-376` in a2a-sdk 1.2.3). Without identity, neither field is set.
Every adapter's `get_a2a_card` becomes `A2ACardBuilder.build(self.descriptor)`; ADK's `TODO`
(`framework/adk/adk.py:1519-1524`) is filled the same way.

### 7. Authorization (`identity/authz/`)

```python
class Decision(BaseModel): allowed: bool; reason: str = ""
class AuthorizerCapabilities(BaseModel): lists_resources: bool = False

class Authorizer(ABC):
    capabilities: ClassVar[AuthorizerCapabilities] = AuthorizerCapabilities()
    @abstractmethod async def agent_level(self, principal: Principal, agent_id: str) -> Optional[AccessLevel]
    @abstractmethod async def check_tool(self, principal: Principal, agent_id: str, tool: str) -> Decision
    async def filter_tools(self, principal, agent_id, tools: list[str]) -> list[str]   # default: per-tool check_tool
    async def visible_agents(self, principal, candidates: list[str]) -> list[str]     # default: those with a level
```

**`StaticAuthorizer`** (`authz/static.py`), constructed with `grants`, `tools` and a
`descriptor_lookup: Callable[[], list[AgentDescriptor]]` (the gate passes
`registry.descriptors`), its only dependency for `tag:` and tier defaults:

- `GrantTable` normalizes each grant at construction: `subjects` and `agents` coerced from a bare
  string to a one-element list; `level` parsed into `AccessLevel`; an unknown subject form or an
  empty list is `AKConfigError` naming the grant index.
- `SubjectMatcher.matches(form: str, principal) -> bool`: `*` always; `authenticated` when not
  anonymous (messaging senders included, design 5); `provider:<name>` when `principal.provider ==
  name`, or when `name` ends with `:` and `principal.provider.startswith(name)`; `user:<subject>`
  on `principal.subject` unless `principal.is_shared_channel` (design 5: an edge sender's subject
  is a platform id, never matched by a user grant); `group:<name>` on `groups`; `role:<name>` on
  `roles`.
- Agent entries: an id, `*`, or `tag:<name>` resolved at evaluation time against
  `descriptor_lookup()` (every descriptor whose `tags` contains the name; none matches nothing).
- `agent_level`: the maximum `level` over grants where any subject matches and any agent entry
  matches `agent_id`; `None` when none.
- Tool tier for `(agent_id, tool)`: the `tiers` entry of the `tools` block for that agent, else the
  tier of the `SystemTool` with that name on the hosted agent (passed in by the gate as
  `system_tiers: dict[str, AccessLevel]`), else `READ`.
- `check_tool`: `Decision(False, f"Tool '{tool}' is denied for agent '{agent_id}'")` when in
  `deny`; `Decision(False, f"Tool '{tool}' is not in the allow-list of agent '{agent_id}'")` when
  `allow` is set and the tool is absent; `Decision(False, f"Tool '{tool}' requires level {tier};
  the current principal has {level or 'none'}")` when `agent_level` is `None` or below the tier;
  else `Decision(True)`.
- With the `authorization` block present and `grants == []`, every `agent_level` is `None` and
  one startup warning names the empty block.

**`AuthorizerFactory`** (`authz/factory.py`): `create(authorization_config, descriptor_lookup)`;
`get()` returns the process-wide authorizer or `None` without the block; `reset()`. Branches:
`static`; `casbin` (`require_extra("casbin", ...)`, first engine after static, Q11), `openfga`,
`cedar`, `authzen`: each a named branch that raises `AKConfigError(f"authorization.type: {name}
is not shipped yet; use a dotted path")` until its adapter lands; a dotted path to an
`Authorizer` subclass receives the whole block; else `AKConfigError`.

**`AccessGate`** (`authz/gate.py`):

```python
class AccessGate:
    @classmethod def get(cls) -> Optional["AccessGate"]        # None without an authorization block
    @classmethod def reset(cls) -> None
    def authorize_agent(self, principal, agent_id) -> AccessLevel      # PermissionError | LookupError
    def visible(self, principal, descriptor) -> bool
    def visible_agents(self, principal) -> list[AgentDescriptor]
    def tool_filter(self, principal, agent: Agent) -> ToolFilter
    def authorize_session(self, principal, session: Session) -> None    # PermissionError
    def validate_configuration(self, agents: Iterable[Agent]) -> None   # AKConfigError
```

- Every method is synchronous at the call sites `Runtime` and `AgentService` use; the gate drives
  the async authorizer through `run_async_sync` (`core/util/async_bridge.py`) when called from a
  sync context and awaits directly inside the coroutine paths. Concretely `authorize_agent`,
  `visible_agents` and `tool_filter` have `async` twins (`authorize_agent_async`, ...) and the
  sync names wrap them; `Runtime.run`/`stream` and `ensure_agent_available`'s async callers use
  the twins so a coroutine never blocks the loop on a remote engine.
- `authorize_agent`: `descriptor = registry.descriptor(agent_id)`; `KeyError` when absent;
  `level = agent_level(...)`; when `None`: `LookupError` if `not visible(principal, descriptor)`
  (surfaces map it to 404) else `PermissionError(f"Principal '{principal.subject}' holds no level
  on agent '{agent_id}'")` (403).
- `visible`: `agent_level is not None`, or `visibility == "public"`, or `"internal"` and the
  principal is not anonymous. `visible_agents`: over `registry.descriptors()`, using
  `authorizer.visible_agents` when `capabilities.lists_resources` else the candidate walk.
- `tool_filter`: `names = agent.get_tool_names()`; `allowed = filter_tools(principal, id,
  names)`; reasons from `check_tool` for the rest; `level` from `agent_level`. One `ToolFilter`
  per run, published by `Runtime`.
- `authorize_session`: allowed when `session.get_owner()` is `None`, `(owner.namespace,
  owner.subject) == (principal.namespace, principal.subject)`, or `owner.provider.startswith(
  Principal.SHARED_CHANNEL_PREFIXES)` and `(owner.provider, owner.namespace) == (principal.provider,
  principal.namespace)` (Q17 refined: a shared session admits its platform scope, not one sender);
  otherwise `PermissionError(f"Session '{session.id}' belongs to another principal")`, for an
  anonymous principal as for any other non-owner.
- `validate_configuration(agents)`, called from `Module.load` after registration with the loaded
  agents and from the handlers' `get_router()` with the hosted agents: an `allow`, `deny` or
  `tiers` entry naming a tool a hosted agent does not have is `AKConfigError`; a grant naming an
  agent id no descriptor carries, or a `tag:` no descriptor carries, warns once; a `role:`
  subject with no `identity.role_mapper` warns once; and the Q12 refusal: for every hosted agent
  whose runner is `LangGraphRunner` or `SmolagentsRunner`, `agent.ungated_tool_names()` must be
  empty, else `AKConfigError(f"authorization is configured but agent '{id}' on {runner} has
  tools Agent Kernel cannot gate: {names}")` (section 9.5 and 9.6 define the method).

**`AuthorizerContract`** (`authz/testing.py`): level resolution across the six subject forms,
highest level wins, `*` and `tag:` agent entries, tier gating, `allow`/`deny` precedence,
anonymous handling, `provider:` prefix matching, and `visible_agents` equivalence with the
candidate walk; `StaticAuthorizer` subclasses it, and every later engine must.

### 8. Surfaces and services

#### 8.1 ChatService and AgentService

- `AgentService.run_multi` / `stream_multi` (`core/service.py:162, 180`): `acting_user_id`
  becomes `principal: Optional[Principal] = None`, forwarded to `Runtime`. `AgentService.run`
  (`core/service.py:144-160`) stays principal-less (anonymous), which is the CLI's default.
- `AgentHandler.run_sync/run_async/run_stream_sync/run_stream_async`
  (`core/chat_service.py:277-315`): same rename.
- `ChatService.execute*` (`core/chat_service.py:448-543`) pass `req.principal` (never a parameter)
  into the handler at lines 467, 485, 510 and 538. `_validate` (`core/chat_service.py:776-793`)
  adds: `"user_id" in (req.model_extra or {})` raises `ValueError("user_id is not a request field;
  the acting user comes from the credential")`.
- `RequestBuilder._attach_additional_context` (`core/chat_service.py:140-175`): the
  `known_fields` set drops `"user_id"` and adds `"principal"`, so a principal never reaches the
  agent as `AgentRequestAny`.
- `_record_trigger` (`core/chat_service.py:572-600`) forwards `req.principal` instead of
  `req.user_id`; `_maybe_schedule` is unchanged (the manager reads `req.principal`, section 8.11).
- Presentation wrappers (`core/chat_service.py:690-695, 708-713`): a `PermissionError` branch
  mapping to 403 is added before the `Exception` branch; a `LookupError` branch maps to 404. The
  streaming wrappers already deliver errors as chunks; `execute_stream` (line 500-506) lets the
  eager `PermissionError`/`LookupError` propagate to the route, which maps them the same way.
- Scheduled triggers: in `execute*`, when `req.scheduled_task_id` is set and
  `ensure_agent_available` raises `PermissionError` or `LookupError`, the service calls
  `ScheduleManager.record_trigger(task_id, principal, request_id, occurred_at, error=str(e))`
  (a new keyword the store records on the occurrence) and returns `(AgentReplyText(response=
  "scheduled task skipped: the owner no longer holds access to the agent"), session_id)` with
  status 403 through `success_status`; one warning names the task. The run never starts.

#### 8.2 REST (`api/http.py`, `api/handler.py`)

- `_get_router_dependencies()` (`api/http.py:32-37`) returns exactly
  `[Depends(RequestAuthenticator.from_config().dependency())]`: with no `identity` block the
  dependency sets `Principal.anonymous()` and costs one attribute write. `RESTAPI.add_auth_handlers`
  and `_auth_token_validators` are removed with `agentkernel.auth` (iteration 11), together with
  their callers in the deployment adapters (`ecs_io_handler.py:78`, `gcp/akauthorizer.py:29`). The A2A routers keep
  going through `include_router(..., dependencies=...)` (line 65), so the principal is on
  `request.state` for them; `/health` and `/openapi.json` stay outside (lines 60-73).
- `AgentRESTRequestHandler.run(body, request: Request)` (`api/handler.py:105-114`): sets
  `body.principal = request.state.principal` before either chat-service call. `list_agents`
  becomes the catalog of section 6 and takes `request`.
- `run_multipart` (`api/handler.py:116-145`): the `user_id: Optional[str] = Form(None)` field
  (line 121) is removed; the form carries `prompt`, `agent`, `session_id`, `group_id`,
  `thread_name`, `files`, `images`; `principal` is assigned from `request.state`. A form still
  carrying `user_id` is a 400 with `USER_ID_NOT_A_FIELD`: FastAPI drops an undeclared field
  silently, so `_reject_user_id_form(request)` reads the parsed form for it (the thread and
  pipeline multipart routes inherit the check).
- `AuthorisedRESTRequestHandler` (`api/handler.py:39-73`): the `authoriser` constructor argument
  is removed; `_resolve_user(request) -> Principal` reads `request.state.principal` and raises
  `HTTPException(401, "Authentication required")` when it is anonymous; construction raises
  `AKConfigError(f"{type(self).__name__} requires an identity block: it serves authenticated
  callers only")` when `IdentityProviderFactory.get()` is `None`. Threads, schedules and AG-UI
  inherit both.
- `RESTRequestHandler.authenticates_itself: bool = False` (PR #937 review follow-up,
  2026-11-11): `build_app` mounts the router of a handler that sets it without the identity
  dependency. `WebhookRESTRequestHandler` sets it: Teams sends its Bot Framework token in
  `Authorization`, which an application's provider refuses with a 401 before the adapter could
  verify it. The adapter's `verify` is then the delivery's one check, as behind the Lambda
  authorizer's `WebhookRouteMatcher` bypass, and the sender's principal still comes from the
  platform (section 8.4). `PipelineWebSocketHandler` (which authenticates its own `?token=`) and
  `PushEndpointHandler` (behind the shared push token) set it too (PR #937 review follow-up,
  2026-11-12): single-process async mode co-hosts both through `RESTAPI.build_app`, where the
  dependency crashed every `/ws` handshake and would have gated pod-to-pod pushes.

#### 8.3 Pipeline request handler and WebSocket (`pipeline/`)

- `RequestHandler.run_chat(body, request)` (`pipeline/request_handler.py:371-383`) and
  `RestHandler.enqueue_and_wait` (`232-284`): `body.principal = request.state.principal`, then
  `AgentService.ensure_agent_available(body.agent, body.principal)` before `_enqueue_request`
  (line 248), so an unauthorized request is answered with 403/404 and nothing is enqueued.
  `run_multipart_chat` (`476-513`) drops the `user_id` form field (line 481, 507).
- `RestHandler.request(body, protocol)` (`163-189`) requires `body.principal` to be set by the
  caller (the MCP and A2A executors) and runs the same precheck before enqueueing.
- `PipelineWebSocketHandler` (`pipeline/ws/handler.py:41-270`): `__init__` loses `auth_validator`,
  takes an optional `authenticator: RequestAuthenticator` (tests inject one; `from_config()` when
  omitted) and raises `AKConfigError("the WebSocket route requires an identity block: the
  connection is keyed by the authenticated subject")` when that authenticator has no provider. `_authenticate`
  (`175-189`) becomes `principal = await authenticator.authenticate_token(token, RequestContext(
  path=WS_PATH))`; a missing token or an `AuthenticationError` closes with 1008 ("Authentication
  token is required" / "Authentication failed"); an anonymous result (no provider) cannot occur
  here. The connection is registered under `principal.subject` (lines 144-146); the `userId` claim
  read (185-188) is deleted. `_handle_chat` (`215-255`): `body.principal = principal`, the message
  attributes stay `{REQUEST_ID, USER_ID: principal.subject}` (the WS-entered marker the Response
  Handler routes on, `pipeline/response_handler.py:279`), and a `ValueError` from
  `BaseRequest.from_payload` keeps producing the `FAILED "Invalid request: ..."` frame
  (`206-208`), which is how a frame still carrying `user_id` is refused. `_handle_custom`
  (`257-267`) passes `{"message": payload, "principal": principal}`; the `user_id` key is gone.
  The ack frame (`247-255`) carries `subject` instead of `user_id`.
- `WebSocketGateway.run()` (`pipeline/ws/gateway.py:36-67`) takes no arguments; `_validate` drops
  the validator check and adds the identity-block check with the message above.
- `IOHandler.run(handlers=None, pollers=None, gateways=None, request_handler=None)`
  (`pipeline/io_handler.py:40-48`): `auth_validator` is removed. `ws_cohosted = single_process and
  execution.is_websocket`; `_validate_topology` (`220-268`) replaces the "call
  IOHandler.run(auth_validator=...)" branch (224-228) with `AKConfigError("async (WebSocket) mode
  co-hosts the gateway here: add an identity block")` when `IdentityProviderFactory.get()` is
  `None`. The "auth_validator ignored" warning (112-117) is deleted.
- `AgentRunner` (`pipeline/agent_runner.py`): `_process_run` (69-85) passes the body through
  unchanged (the principal is on it); `_process_agui` (87-145) passes `principal=body.principal`
  at line 126; `_resolve_request_metadata` (259-285) sets `ATTR_USER_ID` from
  `body.principal.subject` on the body-fallback path (283-284) when the principal is
  non-anonymous. `StreamAgentRunner`'s `USER_ID` requirement (327-328) is unchanged. After the
  chat-service call every runner calls `RequestAuthenticator.from_config().release(body.principal)`
  in a `finally` when `credential_ref` is set (the queued-path deletion of the inbound entry;
  `release` skips a connection-scoped `conn:` ref, section 4).
- `RequestProducer` (`pipeline/producer.py:24-50`) is unchanged: the principal is part of the body
  it serializes with `exclude_none=True`.

#### 8.4 Messaging and realtime edges (`integration/adapter/`)

- `InboundRequest` (`integration/adapter/base.py:51-67`): `user_id` stays (the platform sender
  id) and gains `namespace: Optional[str] = None` and `claims: dict[str, Any] = {}`.
- `IntegrationProducer.enqueue(adapter_name, request, source=Source.WEBHOOK)`
  (`integration/adapter/producer.py:61-91`) builds the body with `principal=Principal(subject=
  request.user_id, provider=f"{prefix}{adapter_name}", namespace=request.namespace,
  claims=request.claims)` when `request.user_id` is set, where `prefix` is `"realtime:"` for
  `Source.REALTIME` and `"messaging:"` otherwise (`base.py:43-48`), and `principal=None`
  (anonymous) when it is not. `ATTR_USER_ID` stays unstamped (docstring 64-66). This keeps
  `AgentRunner` platform-agnostic (design refinement 3). Amended in iteration 9: the producer does
  not know which adapter is calling it (the webhook host and the poller hand it a name and a
  request), so the source arrives as a keyword argument; both hosts keep the default, which
  covers `WEBHOOK` and `POLLER` alike, and the stateful edge passes `self.source` from
  `_drain_requests`.
- An unverified delivery names nobody (PR #937 review follow-up, 2026-11-12): when the adapter's
  `missing_verification_settings()` is non-empty (an unset `whatsapp.app_secret`,
  `messenger.app_secret`, `instagram.app_secret` or `telegram.webhook_secret`, which makes
  `verify` a no-op), `WebhookRESTRequestHandler` logs a WARNING at construction and enqueues each
  delivery with `user_id=None`, so it runs anonymous. Before, the sender id a forger wrote became
  a `messaging:` principal the schedule tools act as and the sandbox resolver read. The producer's
  signature is unchanged, so a bring-your-own producer keeps working; `LambdaWebhookHost` still
  refuses such an adapter outright.
- Per adapter, the namespace: Slack the event's `team`, else the workspace the bot authenticated
  to (`auth_test()["team_id"]`, cached beside the bot user id); Teams `resolve_tenant(activity)`
  (`integration/teams/adapter.py:109`); Gmail the inbox address; WhatsApp `phone_number_id`
  (`integration/whatsapp/adapter.py:29`, exposed as a `_WhatsAppClient.phone_number_id`
  property); Messenger and Instagram the delivery's `recipient.id` (the page or business
  account); Telegram the bot id, the part of the token before the colon
  (`_TelegramClient.bot_id`, None for a token without one). Gmail additionally records
  `claims={"authentication_results": <header value>}` from the `format="full"` fetch
  (`integration/gmail/adapter.py:237-238`), present or absent as the message carries it. Amended
  in iteration 9: no `gmail` config field names the inbox address, and adding one would be a knob
  the API already answers, so the adapter resolves it once from the account profile
  (`users().getProfile(userId="me")["emailAddress"]`) when the first message is parsed. The
  Gmail sender id is the bare address parsed from `From`, lowercased
  (`email.utils.parseaddr(sender)[1].lower()`), so `Alice <A@X.com>` and `a@x.com` are one
  principal; the reply still goes to the raw header (PR #937 review follow-up).
- LiveKit (`integration/livekit/adapter.py`): `_stage_request(request, participant_identity)`
  and `StatefulEdgeAdapter._enqueue(request, user_id, namespace)` (`base.py:300-314`) set
  `InboundRequest(user_id=participant.identity, namespace=self._api_key)`; the greeting
  (`:249-250`), chat (`:268`) and audio (`:289-299`) paths pass the participant they already read
  (`:238-243, :255`). The API key id is the LiveKit namespace (Q20). Open (PR #937 review
  question, 2026-11-12): a room with more than one remote participant feeds every microphone into
  one session, and `RealtimeConnection.principal` is overwritten by whichever participant's frame
  arrived last, so a tool called in reply to one participant can run as another and the session
  owner is recorded from that race. Phase B keeps the behaviour; iteration 23 (tool gates), which
  keys decisions on that principal, settles which identity a multi-participant room runs as.
- `RealtimeConnectionPool.dispatch(body, request_id, user_id, attributes, chat_service)`
  (`pipeline/realtime_pool.py:520-558`): the connection stores `body.principal` on every input
  (`RealtimeConnection.principal`, None when the input named nobody); on first connect
  `chat_service.prepare_agent_handler` (line 550) runs the agent check through
  `ensure_agent_available(body.agent, body.principal)` once the gate exists (iterations 17 to
  20). `_execute_tool_and_reply` (`228-252`) wraps `adapter.execute_tool` in
  `Runtime._publish(agent, session, principal)` / `session._unpublish_run()`, so the tool sees
  the participant with the agent as actor and the session's owner is recorded as on a turn; the
  tool filter (`gate.tool_filter(principal, agent)`, `ToolFilter.allows(name)` returning the
  reason string as the tool result when denied) joins the same wrap in iteration 23. Amended in
  iteration 9: the `user_id` parameter stays. It is the `ATTR_USER_ID` WebSocket routing marker
  the output is stamped with (`_emit`, `258-259`), not an identity, so replacing it would break
  the WebSocket edge's delivery; the principal rides beside it, and the callers
  (`pipeline/agent_runner.py:391`, `deployment/aws/containerized/akagentrunner.py:329-331`) keep
  passing the attribute.

#### 8.5 AG-UI (`integration/agui/`)

- `AGUIRequestHandler.__init__()` (`integration/agui/handler.py:26-58`): the `authoriser` and
  `auth_validator` parameters and the `AuthValidatorAuthoriser` wrap (41-47) go; the
  `AuthorisedRESTRequestHandler` identity requirement (8.2) replaces the "never served
  anonymously" check with the same guarantee. `_is_exposed` (60-68) reads
  `descriptor.exposed_on("agui")` through the registry; the `agui.default_agent` validation
  (53-58) becomes "exposed on agui".
- `/agents` (140-152): `AccessGate.visible_agents(principal)` narrowed by `exposed_on("agui")` and
  `runner.supports_streaming`; names only, as today.
- `_resolve_agent` (103-127): 404 for unknown or hidden, 403 for a visible agent the principal
  holds no level on (`PermissionError` from `ensure_agent_available`), 400 for a non-streaming
  runner, unchanged order.
- `_resolve_run_inputs` (178-201) returns the `Principal`; `_events` passes
  `principal=principal` at line 280; `AGUIPipelineRequestHandler._run` (`queue_handler.py:112-151`)
  enqueues `AGUIRunRequest(..., principal=principal, ...)` instead of `user_id=user_id` (143).

#### 8.6 MCP (`api/mcp/akmcp.py`)

- `_build()` (131-150): `auth = AKMCPAuthProvider.from_config()`; `FastMCP("Agent Kernel FastMCP
  Instance", auth=auth)` (`fastmcp/server/server.py:321-329`, FastMCP 3.4.10). `AKTokenVerifier(
  fastmcp.server.auth.TokenVerifier)` (`fastmcp/server/auth/auth.py:366-412`) implements
  `verify_token(token)` by `provider.authenticate(token)` and returns `AKAccessToken(token=token,
  client_id=principal.subject, scopes=[], subject=principal.subject, claims=principal.claims,
  principal=principal)` (the SDK fields at `mcp/server/auth/provider.py:39-46` plus one
  `principal` field), or `None` on `AuthenticationError`. For the OIDC family the verifier is
  wrapped in `RemoteAuthProvider(token_verifier=..., authorization_servers=[issuer],
  base_url=<the configured public base, api host and port>)` (`auth.py:413-470`), which publishes
  the RFC 9728 metadata. With no identity block `auth=None` and MCP stays open.
  PR #937 review follow-up (2026-11-12): the metadata the 401 advertised could not be fetched and
  named the wrong resource (`http://0.0.0.0:8000/` from the bind address, served only under the
  `/mcp` mount). A new `mcp.url` field (default `http://localhost:8000/mcp`, the `a2a.url`
  pattern) is the public endpoint: `base_url` is its origin and `resource_base_url` the URL itself,
  so the resource is `<mcp.url>/` and the 401's `resource_metadata` is
  `<origin>/.well-known/oauth-protected-resource/<path>/`, which `RESTAPI.build_app` serves at the
  app root (`auth.get_well_known_routes(mcp_path="/")`), where RFC 9728 clients look it up.
- Each agent tool is registered with `cls._fastmcp.tool(execute, name=..., description=...,
  auth=visible_check)` where `visible_check: AuthCheck` (`fastmcp/utilities/authorization.py:47`)
  reads the principal off the context's access token and returns `AccessGate.visible(principal,
  descriptor) and descriptor.exposed_on("mcp")`; FastMCP hides tools whose check fails from
  `tools/list` and refuses their calls. The `mcp.agents` allow-list (140) is deleted.
- `Executor.execute` (58-106): `principal = AKAccessToken.principal_of(get_access_token())`
  (`fastmcp/server/dependencies.py:467`): the verifier stores the principal under the
  `ak.principal` claim as well as on its `principal` field, because FastMCP 3.4.10 rebuilds the
  verifier's token as its own `AccessToken` before a tool sees it, keeping only the SDK fields
  (`claims` survive, the subclass and even `subject` do not; design refinement 7); `principal_of`
  reads the field in process, the claim over HTTP, and is anonymous otherwise. `body =
  BaseRunRequest(prompt, agent, session_id, principal=principal)`; a `PermissionError`/`LookupError` from `RestHandler.request`'s precheck
  becomes `ToolError("Agent not available")`.

#### 8.7 A2A (`api/a2a/`)

- `A2ARESTRequestHandler.get_agent_routers()` (`api/a2a/handler.py:49-63`): `create_rest_routes(
  request_handler, context_builder=AKCallContextBuilder())` (`a2a/server/routes/rest_routes.py:30-35`),
  where `AKCallContextBuilder(DefaultServerCallContextBuilder)` (`a2a/server/routes/common.py:99`)
  calls the SDK's `build(request)`, keeping its state (headers, the auth scope), and adds
  `state["principal"] = request.state.principal`. The executor
  (`api/a2a/a2a.py:68-90`) reads `context.call_context.state["principal"]`, falling back to
  `RequestAuthenticator.current()` and then to anonymous, and sets it on the body (line 76).
- `_build()` (129-146): the `a2a.agents` line (137) is deleted; cards are built for every
  descriptor `exposed_on("a2a")`; `get_cards()` becomes `get_cards(principal)` filtered by
  `AccessGate.visible`; the catalog route (36-46) and the well-known card route take the request's
  principal; a hidden agent's card is 404 (the A2A 1.0 rule).

#### 8.8 CLI (`cli/cli.py`)

- `CLI.__init__(token: Optional[str] = None)`: `token or os.environ.get("AK_CLI_TOKEN")`; when set
  and a provider is configured, `principal = run_async_sync(provider.authenticate(token))` once at
  start (an `AuthenticationError` exits with the reason); the REPL's prompt path calls
  `self._service.run_multi([AgentRequestText(prompt)], principal=self._principal)` instead of
  `run(prompt)` (`cli/cli.py:119`). `ak` (`cli/ak.py`) is unchanged: it runs no agents.
  `CLI.main` parses `--token` with `allow_abbrev=False` (PR #937 review follow-up): the CLI shares
  `argv` with the script that embeds it, whose own `--to x` was read as an abbreviated `--token`.

#### 8.9 Deployment adapters

- `ECSIOHandler.run(handlers=None)` (`deployment/aws/containerized/ecs_io_handler.py`):
  `auth_validator` is removed; the WebSocket branch raises `AKConfigError` when
  `IdentityProviderFactory.get()` is `None`, before any thread starts; the REST branch binds nothing,
  since every REST route already carries the identity dependency. `AWSRestAPI.add_auth_handlers` is
  gone with the method (section 8.2).
- `AWSWebsocketAPI.set_auth_handler` and `_ws_auth_validator`
  (`deployment/aws/containerized/core/api/websocket_api.py`) are deleted.
  `ECSWebSocketSystemRequestHandler.__init__()` takes no validator: it builds
  `RequestAuthenticator.from_config()` and raises `AKConfigError("the ECS WebSocket routes require an
  identity block: ...")` when that has no provider, the `PipelineWebSocketHandler` rule of 8.3, so
  `AWSWebsocketAPI.get_default_handlers()` fails the same way (replacing the former `ValueError`;
  decided 2026-11-10). `_handle_connect` authenticates through
  `authenticate_token(token, RequestContext(path=CONNECT_PATH))`: a missing token is 401
  "Authentication token is required", a refused one 401 "Authentication failed" with the provider's
  reason logged, and the connection is stored through `AWSWebSocketHandler.on_connect(connection_id,
  principal)`; the `userId` read is deleted. `ECSWebSocketRequestHandler.build_route_context`
  resolves the connection's principal with one `get_principal` query (`WSRouteContext.principal`;
  `user_id` becomes a property returning its subject; a row without a principal is 401 "No principal
  found for connection_id"), and `_handle_chat` sets `body.principal = ctx.principal` ahead of the
  queue, direct and streaming paths. Custom routes receive `{"message", "principal"}` carrying the
  `Principal` object, the shape the pipeline's `_handle_custom` passes (8.3), not a model dump.
- The AWS `WebSocketConnectionStore` (`deployment/aws/core/websocket_service.py`):
  `add_connection(user_id, connection_id, principal=None)` writes the principal as JSON under the
  `principal` attribute when given (the `LocalConnectionRegistry` precedent for extending the ABC's
  `add_connection` with optional arguments); `get_principal(connection_id)` rebuilds it from the GSI
  row and returns `None` for an unknown connection or a row written before principals;
  `get_user_id` and `get_principal` share one `_get_connection` query. `AWSWebSocketHandler` gains
  `get_principal` beside `get_user_id`, and its `on_connect(connection_id, principal)` overrides the
  base hook's `(connection_id, user_id)` signature, keying the store by `principal.subject`: the AWS
  store is the one that keeps the whole principal.
- `LambdaWSHandler.ConnectionRoutesHandler.__init__()`
  (`deployment/aws/serverless/core/router/ws_lambda.py`) takes no validator and raises the same
  `AKConfigError` without a provider; `_handle_connect` runs the async `authenticate_token` through
  `run_async_sync` (`core/util/async_bridge.py`: the Lambda handler is synchronous) and answers the
  same 401s; the `userId` read is deleted. `WSLambdaRouter(connection_routes=False,
  system_routes=True)` loses `auth_validator` and its `ValueError`;
  `WebsocketConnectionHandler.set_auth_validator` is deleted and `_get_router` builds the router from
  configuration alone. `_parse_event_to_wsmessage` resolves `get_principal(connection_id)` (a
  `ValueError` "No principal found for connection_id" otherwise, answered as today's 500), assigns it
  to `request.body.principal`, and `WSMessageInfo` gains `principal` beside `user_id` (its subject),
  so the direct, streaming and queued chat routes all run as the connection's principal.
- `APIGatewayAuthorizer(bypass=None)` (`deployment/aws/serverless/akauthorizer.py`): the `validator`
  argument is removed, and construction raises `AKConfigError("APIGatewayAuthorizer requires an
  identity block: ...")` without a provider. `RequestAuthenticator` imports FastAPI inside
  `dependency()` only, so the authorizer and the WebSocket connection handler keep their packages
  free of it (`test_aws_lazy_exports`, found at the phase B suite run, 2026-11-10). `handle` authenticates `request.headers.Authorization`
  through `authenticate_bearer` (under `run_async_sync`) with a `RequestContext` of the path, the
  method and the `Headers` dump, and returns the Allow policy with `principalId=principal.subject` and
  `context={"principal": principal.model_dump_json()}` (API Gateway context values must be strings).
  A `ValidationError` (missing header or `methodArn`) or any unexpected exception is a Deny with
  `principalId` "unauthorized" (403). An `AuthenticationError` (a refused or expired credential, or
  a header that is not `Bearer <token>`: the former `_extract_token`, which accepted a bare token,
  is gone) raises `Exception("Unauthorized")`, which API Gateway answers with 401, the status an
  OAuth client refreshes its token on (decided 2026-11-12 at the PR #937 review; the base answered
  it with a Deny). The bypass is unchanged and answers before the provider is consulted.
  PR #937 review follow-ups (2026-11-12): `_build_request` finds the header whatever its case
  (REST v1 REQUEST events keep header names as the client sent them, and the gateway's identity
  source matches case-insensitively, so a lowercase `authorization` reached the Lambda and was
  denied); and the log carries the request line, the effect and the `principalId` only, never the
  event (its bearer header), the policy context (the whole principal) or a `ValidationError`'s
  input (only the failing field locations).
- The REST Lambda router (`deployment/aws/serverless/core/router/rest_lambda.py`):
  `DefaultEndpointsHandler._parse_body` assigns `principal_from_event(event)` to the body it parsed,
  rebuilding the principal from `event["requestContext"]["authorizer"]["principal"]` when present,
  else anonymous, so both `process_chat_request` and `_send_to_queue` receive it; a `principal` the
  client put in the body was dropped by `from_payload`. `principal_from_event` is public, and
  `Lambda.principal(event)` (`deployment/aws/serverless/aklambda.py`) wraps it for the custom
  `Lambda.register` routes, which receive the raw event (decided 2026-11-10, for the
  `aws-serverless/schedule-openai` example's management routes).
- The WebSocket Lambda router's custom routes (`ws_lambda.py`, `WSLambdaRouter._get_ws_handler_function`)
  get the connection's principal in `event["requestContext"]["authorizer"]["principal"]` before
  the route runs (PR #937 review follow-up): a WebSocket event carries no authorizer context, so
  `Lambda.principal(event)` was anonymous on every custom WebSocket route, the one surface where a
  custom route could not read its caller. The wrapper resolves only the connection's principal
  (`LambdaWSHandler._connection_principal`) and never reads the frame as a chat request, as the ECS
  and gateway custom routes already did: since develop's #765 made `BaseRunRequest` require a
  prompt, a resume or a requests list, the documented `{"route": ..., "data": ...}` frame failed
  that validation and the route answered 500 (fixed 2026-11-12, after the PR #937 review).
- `GCPAuthorizer` (`deployment/gcp/akauthorizer.py`) is deleted: `RESTAPI` installs the identity
  dependency itself. `AzureFunctions.handler` (`deployment/azure/akfunction.py`) runs
  `RequestAuthenticator.from_config().authenticate_bearer(req.headers.get("Authorization"),
  RequestContext(path=urlsplit(req.url).path, http_method=req.method, headers=dict(req.headers)))` under
  `run_async_sync` before it reads the body, answers 401 `{"error": <public detail>, "session_id":
  null}` on `AuthenticationError` (the identity error `authenticate_bearer` raises; the
  `HTTPException` the design named belongs to the FastAPI dependency), then assigns the principal to
  the body; without a header or an `identity` block the request runs anonymously. The path, not
  the URL, is also what a refusal logs (PR #937 review follow-up): under `authLevel: function` the
  query string can carry the function key (`?code=`).

#### 8.10 Threads (`integration/thread/`)

- `ThreadRecorder.pre_run` (`integration/thread/recorder.py:32-57`): the `req.user_id` check
  (47-48) becomes `principal = req.principal; if principal is None or principal.is_anonymous:
  raise PermissionError("thread support requires an authenticated principal")`, and
  `get_or_create_thread(..., user_id=principal.subject, ...)`. Ownership of an existing thread is
  checked first, `manager.get_thread(session_id, user_id=principal.subject)`, ahead of
  `store_attachments` (PR #937 review follow-up): a multimodal request naming another user's
  `session_id` stored its bytes under that session before the 403.
- `ConversationThreadManager.get_or_create_thread` (`integration/thread/manager.py:85-124`): when
  the thread exists and `thread.user_id != user_id`, raise `PermissionError(f"Thread {session_id}
  is not owned by user {user_id}")` before the rename (the check `manager.py:109-115` lacks today).
- `AgentThreadRequestHandler` (`thread_chat.py:36-218`) and `ThreadRequestHandler` (`221-309`):
  `authoriser` goes; both raise `AKConfigError` at construction without an identity block (they
  compose `ThreadRESTRequestHandler`, which requires it, 8.2); `PermissionError` maps to 403 in `_run_with_recording` (138-145) and
  `_record_user_message` (304-306) beside the `ValueError` 400; both run
  `ChatService.reject_unprocessable` before the recorder's first write, so a `user_id` extra is a
  400 with no thread written; an anonymous principal on the chat routes is 401 (8.2): the chat
  routes assign `body.principal` from the composed read handler's `_resolve_user(request)`, so
  the 401 fires before any validation or write (iteration 10). `ThreadRESTRequestHandler`
  (312-384) keeps its 403 and 404 rules with the principal's subject in place of the resolved
  user (351, 368); the listing route's `user_id` query parameter (365) is removed, since every
  listing is the caller's own and a parameter that is always overridden would only mislead
  (`group_id` stays; iteration 10).

#### 8.11 Schedules (`schedule/`)

- `ScheduleManager.create(principal: Principal, prompt, spec, agent, session_id)`
  (`schedule/manager.py:113-168`): `user_id = principal.subject`; an anonymous principal is
  `PermissionError("scheduling requires an authenticated principal")`; the task stores the owner
  without the creating run's actor chain or credential handle,
  `principal=principal.model_copy(update={"actor": None, "credential_ref": None}).model_dump(mode="json")`.
  `create_from_request` (95-111) passes `req.principal or Principal.anonymous()`.
- `_build_trigger_body` (469-490): `"user_id"` is replaced by `"principal": task.principal`
  (`None` only on a task created before the change, whose frozen body also still carries
  `user_id` and is therefore refused at fire time; such tasks are recreated, not migrated, and
  `update` refuses them with `ValueError` before re-freezing the body, while `cancel` is allowed).
- `record_trigger(task_id, principal, request_id, occurred_at, error=None)` (267-294) and
  `_owns_occurrence` (296-316) compare the stored `task.principal`'s namespace and subject with
  the principal's (an anonymous principal is a mismatch; a task without a stored principal falls
  back to `task.user_id` against the subject); `error` is recorded on the occurrence by the
  store's `record_trigger` (a new optional column `last_error`).
- `get_task`, `list_tasks`, `update`, `cancel` keep their `user_id` parameter; the handler
  (`schedule/handler.py:90-140`) passes `principal.subject`, and its listing route drops the
  `user_id` query parameter (93) for the reason 8.10 gives for the thread listing (iteration 10).
- `schedule/tools.py`: `ScheduleToolUtil.acting_user()` (72-81) returns
  `Session.get_principal().subject` for a non-anonymous principal, else `None`; `_NO_IDENTITY`
  (28) reads `{"error": "scheduling requires an authenticated principal"}`; `create_schedule`
  passes the principal object to `manager.create`.

#### 8.12 Sandbox (`sandbox/`)

- `AgentPrincipalResolver.resolve` (`sandbox/principal.py:29-39`): when
  `session.get_principal()` is neither anonymous nor a shared-channel principal it returns
  `SandboxPrincipal(mode="user", subject=principal.subject, groups=principal.groups,
  credentials={})`, else the agent-mode principal as today. A `messaging:` or `realtime:`
  principal's subject is a platform id (Gmail's is the unverified `From` address), never a user
  subject a provider may map onto credentials (section 6's rule that an edge sender is never
  matched by a user grant), so a `user`-mode profile fails closed for it (PR #937 review
  follow-up, 2026-11-12). A profile with `identity.mode: user` therefore works with no custom
  resolver (`sandbox/broker/worker.py:148-162` enforces the mode unchanged).
- PR #937 review follow-up (2026-11-11): `ExecutionManager._resolve_principal(profile_cfg)` holds
  the resolved principal to the profile, replacing a `user` principal under an `agent`-mode profile
  with the agent's own (`ec2_ssm` demanded `role_arn` and `kubernetes` impersonated the caller for
  every authenticated run otherwise), and the default resolver takes `session=None` for an
  operation driven outside any session (`PrincipalResolver.resolve` is typed `Session | None`).

### 9. Framework adapter tool gates

Shared pieces (`core/`):

- `Agent.get_tool_names() -> list[str]` and `Agent.ungated_tool_names() -> list[str]` (default
  `[]`), per adapter below.
- `ToolGate` (`core/tool.py`, a class with two static methods adapters call, no state):
  `current(session) -> Optional[ToolFilter]` (`session.get_tool_filter()`; `None` means no
  gating) and `deny_result(name, filter) -> str` (the reason string). Reading the session: a tool
  call runs inside `async with session` in every adapter (the `ToolContext` carries it), so the
  gate resolves the session as `ToolContext.get().session` where the native hook has no AK
  handle, and from the explicit `session` where it does.
- Every gate is a no-op when `current(session)` is `None`, which is what keeps the native call
  keyword-for-keyword unchanged without an `authorization` block.

| Adapter | `get_tool_names` source | List time | Call time | `ungated_tool_names` |
|---|---|---|---|---|
| OpenAI (0.20.0, `framework/openai/openai.py`) | `[t.name for t in agent.agent.tools]` (the `get_a2a_card` source, 1082-1091) | at wrap time, for every `FunctionTool` on `agent.agent.tools` (native and AK-bound): `is_enabled = AND(user_callable_or_bool, ak_check)` where `ak_check(ctx, agent)` reads `ToolGate.current(ToolContext.get().session).allows(name)`; the SDK evaluates it per turn (`agents/agent.py:272-292`) | the same wrap-time pass appends `ToolInputGuardrail(guardrail_function=ak_guard, name="ak_tool_gate")` to `tool_input_guardrails` (`agents/tool.py:480`), returning `ToolGuardrailFunctionOutput.reject_content(reason)` when denied (`tool_guardrails.py:59-117`) | `[]` (hosted tools are not `FunctionTool`s and are listed but never gated; documented) |
| Pydantic AI (2.13.0) | `FunctionToolset` tool names (the 864-886 visitor) | `AKToolGateCapability(AbstractCapability)`: `prepare_tools(ctx, tool_defs)` drops denied definitions | `before_tool_execute(ctx, call, tool_def, args)` raises `ModelRetry(reason)` for a denied tool (the SDK returns it to the model as a retry message, which is the closest native "result string") | `[]` (toolsets the app attaches at run time are gated by the same capability since it sees every `ToolDefinition`) |
| ADK (2.8.0) | names over `LlmAgent.tools` of the root and every `sub_agents` `LlmAgent` (`BaseTool.name` or `get_callable_name`, `google/adk/tools/_function_tool_declarations.py:100-114`) | none (static on `LlmAgent`) | at wrap time, on every reachable `LlmAgent`: `before_tool_callback = [ak_cb, *existing]` (`llm_agent.py:493`, list form); `ak_cb(tool, args, tool_context)` resolves `AKToolContext.fetch(tool_context.state["ak_tool_context"])` (the id the adapter seeds, `adk.py:388-389`) and returns `{"error": reason}` to skip the tool (`flows/llm_flows/functions.py:611-631`) | `[]` (ADK built-in tools are listed; a denied built-in returns the error dict too) |
| CrewAI (1.15.18) | `[t.name for t in agent.agent.tools]` (521) | none | `CrewAIModule` registers one process-wide `register_before_tool_call_hook(ak_hook)` (`crewai/hooks/tool_hooks.py:208-242`) on first load; `ak_hook(context)` reads `ToolContext.get()` (contextvars reach the kickoff thread, `crewai/crew.py:1179`) and returns `False` for a denied `context.tool_name` (compared after `sanitize_tool_name`, `crewai/utilities/string_utils.py:26-51`); CrewAI's own "Tool execution blocked by hook" message reaches the agent | `[]` (tools not routed through the executor are documented) |
| LangGraph (1.2.11, prebuilt 1.1.0) | over `agent.agent.nodes.values()` (`langgraph/pregel/main.py:705`), each `node.bound` that is a `ToolNode`, its `tools_by_name` keys (`langgraph/prebuilt/tool_node.py:789`) | none (compiled graph) | `LangGraphToolBuilder.bind` (1114-1155) wraps `func`/`coroutine` before `StructuredTool.from_function` and sets `metadata={"ak_gated": True}` on the tool; the wrapper checks `ToolGate.current(ToolContext.get().session)` and returns the reason string instead of calling the function | every `tools_by_name` entry whose `metadata` lacks `ak_gated` |
| smolagents (1.26.0) | `list(agent.agent.tools)` (a dict since `_setup_tools`, `smolagents/agents.py:389-393`) | none | at wrap time, for every value in `agent.agent.tools`: `tool.forward = ak_wrap(tool.forward)` (`Tool.__call__` calls `self.forward`, `smolagents/tools.py:231-249`; the AK wrapper marks itself with `__ak_gated__ = True`); the wrapper returns the reason string when denied | every `agent.agent.tools` value whose `forward` lacks `__ak_gated__` at validation time (a tool added after wrap) |
| MAF (1.20.0) | names over `agent.agent.default_options.get("tools", [])` (786-798) | none | per run: `kwargs = self._native_kwargs(options, session=..., middleware=[AKToolGateMiddleware(), *options.get("middleware", [])])` (`agent_framework/_agents.py:2014-2026`); `process(context, call_next)` sets `context.result = reason` and returns without `call_next()` for a denied `context.function.name` (`_middleware.py:910-997`) | `[]` (hosted and provider-executed tools are documented) |
| Claude Agent SDK (`framework/claude/claude.py`) | `[t.name for t in agent.agent.tools]` (the `get_a2a_card` source, 1061): the tools the in-process `ak` MCP server serves as `mcp__ak__<name>` | per run, in `_native_options` (454-515): a denied tool is left out of the `allowed_tools` list the runner builds (509) and added to `disallowed_tools`, so the SDK never offers it | the `PreToolUse` matcher the HITL gate installs (512) returns `{"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}` for a denied `mcp__ak__` tool, ahead of the approval branch (`_decision_hook`, 407-451) | `[]` (Claude Code's built-in tools and other `mcp_servers` are neither listed nor gated; documented) |
| Realtime (`core/realtime/runner.py:124`, both OpenAI and ADK realtime runners) | the agent's `get_tool_names` | none (declared at connect) | `RealtimeConnection._execute_tool_and_reply` (8.4) before `adapter.execute_tool` | n/a |

- Composition rule everywhere: AK's check runs first; a user-set hook, callback, middleware,
  capability or `is_enabled` value is preserved and runs after (OpenAI `is_enabled` is an AND of
  both; ADK and MAF lists are AK-first; CrewAI's global hook list keeps the user's hooks).
- The reason string is `ToolFilter.reason(name)`, for example
  `"Tool 'apply_manifest' requires level write; the current principal has read"`.
- Traced runner subclasses (`trace/*/<framework>.py`) call `super().run(...)` and need no change;
  the MAF middleware is added inside `MAFRunner._prepare_session`, which the traced runner reuses.
- System-prompt text about system tools stays composed per agent at load time
  (`core/tool.py:256-276`); it is not filtered per run (documented limitation, design section 7).

### Consumer changes

| Consumer | Deleted | Changed | Verified unchanged |
|---|---|---|---|
| `auth/` package, `auth.py` shadow module | both, whole | | |
| `core/model.py` | `BaseChatRequest.user_id` (427); `from_payload` user_id handling (497, 503, 505, 513-516) | `BaseChatRequest.principal`; `SystemTool.tier`; new models (section 2) | every other request and reply model; `BaseRunRequest.extra="allow"` |
| `core/runtime.py` | `ACTING_USER_CACHE_KEY` (40); `acting_user_id` (378, 433); `_agents` dict (144) | `run`/`stream` signatures and sequence; `_validate_resume` eighth check; `register`/`deregister`/`agents` delegate | system hook lists; `_prepare_requests`; `StreamBoundaryTracker` |
| `core/base.py` | | `Keys.OWNER`; accessors; `Agent.descriptor`, `get_tool_names`, `ungated_tool_names` (default `[]`) | framework-context accessors; run options; `_attach_system_tools` |
| `core/tool.py` | | `ToolContext.principal/access_level/credentials` | `SystemToolFactory.get_all`, `_agent_allowed` |
| `core/util/key_value_cache.py` | | reserved prefix | `get/has/keys/items` |
| `core/paused_run.py` | the "accepted risk" note (24-26) | subject/provider/namespace on `PausedRun`; reserved writes | accessors' contract |
| `core/service.py` | `acting_user_id` (162, 180) | `ensure_agent_available(name, principal)`; `principal=` | `select`, `new`, `clear`, `load`, `run` |
| `core/chat_service.py` | `acting_user_id` (277-315); `"user_id"` in known fields (150) | `req.principal` hand-off; 403/404 mapping; the `user_id` rejection in `reject_unprocessable` (the public name of `_reject_ambiguous`, which the thread and pipeline edges call before their first write); trigger skip | `_maybe_schedule`; `ResponseBuilder` |
| `core/builder.py` | `build(name, description, skills)` | `build(descriptor)` with security schemes | `SessionStoreBuilder`, `SessionCacheBuilder` |
| `core/__init__.py` | `ACTING_USER_CACHE_KEY` (48) | exports `Principal`, `AccessLevel`, `AgentDescriptor`, `SessionOwner`, `ToolFilter` | |
| `api/http.py` | `add_auth_handlers`, `_auth_token_validators` (22, 208-237) | `_get_router_dependencies` always returns the identity dependency | `run` delegation rule; `build_app` mounting; `reject_unqueued_protocols` |
| `api/handler.py` | `authoriser` argument; multipart `user_id` (121) | `AuthorisedRESTRequestHandler` identity requirement; `_resolve_user -> Principal`; catalog | path constants |
| `pipeline/request_handler.py` | multipart `user_id` (481, 507) | precheck before enqueue; `body.principal` | wait budget; `_reject_unroutable`; `QueuedReply` |
| `pipeline/ws/handler.py`, `gateway.py`, `io_handler.py` | `auth_validator` everywhere; `userId` read (185-188) | identity requirement; subject keying; custom route ctx | frame validation; registry/store registration; fail-fasts not about auth |
| `pipeline/agent_runner.py` | | `principal=` at 126; `ATTR_USER_ID` from the principal on the fallback path; `release` in `finally` | forwarded attributes; thread recording; stream runner marker rule |
| `integration/adapter/base.py`, `producer.py` | | `InboundRequest.namespace/claims`; principal built at enqueue | attributes; reply-context budget |
| `integration/agui/*` | `authoriser`/`auth_validator`; `agui.agents` read (60-68) | principal through `_resolve_run_inputs`; visibility | event mapping; envelope; pause outcome |
| `api/mcp/akmcp.py` | `mcp.agents` read (140) | `auth=`; per-tool `AuthCheck`; principal on the body | executor error mapping; `get_http_app` |
| `api/a2a/*` | `a2a.agents` read (137) | context builder; principal on the body; filtered cards | routes shape; data parts |
| `cli/cli.py` | | `--token` / `AK_CLI_TOKEN` | REPL commands |
| `deployment/aws/*`, `gcp/akauthorizer.py`, `azure/akfunction.py` | validator arguments; `GCPAuthorizer`; `set_auth_handler`; `set_auth_validator` | principal via authorizer context; WS keyed by subject | queue wiring; connection table schema |
| `integration/thread/*` | `authoriser`; `user_id` requirement text | ownership `PermissionError`; 403 mapping; 401 for anonymous | store layouts; naming; recording order |
| `schedule/*` | `user_id` in the trigger body | `principal` on tasks and triggers; tools read the principal | routes; providers; store key layouts (one new optional column) |
| `sandbox/principal.py` | | default resolver reads the run principal | `PrincipalResolver` ABC |
| `framework/*` | | `get_tool_names`, `ungated_tool_names`, gates (section 9) | every native run call with no `authorization` block |

### Config changes (`core/config.py`)

Three new optional top-level blocks on `AKConfig` (`core/config.py:1235-1281`), each
`Optional[...] = None` like `thread`, `schedule` and `okf` (1258-1272), with presence as the
enablement; no `enabled` flag.

```python
class _ClaimPathsConfig(BaseModel):
    subject: str = Field(default="sub", description="Dotted claim path of the subject")
    groups: str = Field(default="groups", description="Dotted claim path of the group list; missing = []")

class _CognitoProviderConfig(BaseModel): region: str; user_pool_id: str; token_use: str = "access"
class _EntraProviderConfig(BaseModel): tenant_id: str
class _FirebaseProviderConfig(BaseModel): project_id: str
class _StaticPrincipalConfig(BaseModel):
    subject: str; kind: Literal["user", "agent", "service"] = "user"
    groups: list[str] = []; roles: list[str] = []; claims: dict[str, Any] = {}
class _StaticProviderConfig(BaseModel):
    principals: dict[str, _StaticPrincipalConfig] = Field(default_factory=dict,
        description="Credential secret key -> principal; values resolved through the secret capability")

class _IdentityProviderConfig(BaseModel):
    type: str = Field(default="oidc", description="oidc | cognito | entra | firebase | static | dotted path to an IdentityProvider")
    issuer: Optional[str] = None; audience: Optional[str] = None; jwks_uri: Optional[str] = None
    algorithms: list[str] = ["RS256", "ES256"]; leeway: int = 30; required_claims: list[str] = []
    claims: _ClaimPathsConfig = Field(default_factory=_ClaimPathsConfig)
    cognito: Optional[_CognitoProviderConfig] = None; entra: Optional[_EntraProviderConfig] = None
    firebase: Optional[_FirebaseProviderConfig] = None; static: Optional[_StaticProviderConfig] = None
    # model validator: type oidc requires issuer and audience; cognito/entra/firebase require their
    # block; static requires its block; each failure is AKConfigError (the _ExecutionConfig precedent,
    # core/config.py:730-757)

class _RoleMapperConfig(BaseModel):
    type: str = "mapping"; pass_through: Optional[str] = None
    mapping: dict[str, list[str]] = Field(default_factory=dict)

class _CredentialRedisConfig(_RedisConfig): prefix: str = "ak:cred:"; ttl: int = 0
class _CredentialValkeyConfig(_ValkeyConfig): prefix: str = "ak:cred:"; ttl: int = 0
class _CredentialDynamoDBConfig(_DynamoDBConfig): table_name: str = "ak-credentials"; ttl: int = 0
class _CredentialStoreConfig(BaseModel):
    type: str = "in_memory"; redis: Optional[_CredentialRedisConfig] = None
    valkey: Optional[_CredentialValkeyConfig] = None; dynamodb: Optional[_CredentialDynamoDBConfig] = None
class _ExchangerConfig(BaseModel): audience: str; type: str = "passthrough"; scopes: list[str] = []
class _CredentialsConfig(BaseModel):
    store: _CredentialStoreConfig = Field(default_factory=_CredentialStoreConfig)
    encryption_key: Optional[str] = Field(default=None, description="Secret key name of the base64url 32-byte AES-GCM key")
    inbound_ttl: int = 300
    exchangers: list[_ExchangerConfig] = []

class _IdentityConfig(BaseModel):
    provider: _IdentityProviderConfig = Field(default_factory=_IdentityProviderConfig)
    role_mapper: Optional[_RoleMapperConfig] = None
    credentials: Optional[_CredentialsConfig] = None

class _GrantConfig(BaseModel):
    subjects: list[str]; agents: list[str]; level: AccessLevel
    # before validator coerces a bare string in subjects/agents to a one-element list
class _ToolPolicyConfig(BaseModel):
    agent: str; tiers: dict[str, AccessLevel] = {}; allow: Optional[list[str]] = None; deny: list[str] = []
class _AuthorizationConfig(BaseModel):
    type: str = Field(default="static", description="static | casbin | openfga | cedar | authzen | dotted path to an Authorizer")
    grants: list[_GrantConfig] = []; tools: list[_ToolPolicyConfig] = []

class _RegistryRedisConfig(_RedisConfig): prefix: str = "ak:registry:"; ttl: int = 0
class _RegistryValkeyConfig(_ValkeyConfig): prefix: str = "ak:registry:"; ttl: int = 0
class _RegistryDynamoDBConfig(_DynamoDBConfig): table_name: str = "ak-agent-registry"; ttl: int = 0
class _RegistryAgentOverlayConfig(BaseModel):
    version: Optional[str] = None; description: Optional[str] = None; owner: Optional[str] = None
    tags: Optional[list[str]] = None; visibility: Optional[Literal["private", "internal", "public"]] = None
    surfaces: Optional[list[Literal["rest", "a2a", "mcp", "agui"]]] = None
    identity: Optional[AgentIdentitySpec] = None
class _RegistryConfig(BaseModel):
    type: str = "in_memory"; redis: Optional[_RegistryRedisConfig] = None
    valkey: Optional[_RegistryValkeyConfig] = None; dynamodb: Optional[_RegistryDynamoDBConfig] = None
    agents: dict[str, _RegistryAgentOverlayConfig] = Field(default_factory=dict)

class AKConfig(...):
    identity: Optional[_IdentityConfig] = None
    authorization: Optional[_AuthorizationConfig] = None
    registry: Optional[_RegistryConfig] = None
```

- Reused whole or by defaults-only subclass: `_RedisConfig` (23-29), `_ValkeyConfig` (32-38),
  `_DynamoDBConfig` (41-48) for the registry and credential stores; `AccessLevel` and
  `AgentIdentitySpec` from `core/model.py`; the `secret` block for the static credentials and the
  encryption key; the `auth` extra for PyJWT.
- Removed fields: `_A2AConfig.agents` (142), `_MCPConfig.agents` (150), `_AGUIConfig.agents`
  (1228). Each model gains a `mode="before"` validator, the `_reject_legacy_stream` shape
  (730-736), that raises `AKConfigError(f"{block}.agents was removed: set registry.agents.<id>.
  surfaces instead")` when the raw input (YAML or `AK_<BLOCK>__AGENTS`) carries the key. The
  `agui.default_agent` validation moves to `AGUIRequestHandler` as "exposed on agui".
  `agui.state.agents`, `agui.client_context.agents`, `a2ui.agents`, `api.enabled_routes.agents`
  are untouched.
- Every new field carries a `description`; defaults keep every existing YAML and `AK_*` variable
  valid except the three removed lists, which fail with the message above by design.
- Field readers: see design section 9's table; this spec adds `identity.provider.cognito|entra|
  firebase|static` (their provider classes), `identity.credentials.store.<backend>`
  (`CredentialStoreFactory`), `registry.agents.<id>.identity` (`AgentRegistry.register`
  overlay), and `authorization.tools[].tiers` as `dict[str, AccessLevel]` (`StaticAuthorizer`).
- `ak-py/pyproject.toml`: the `auth` extra becomes `["PyJWT>=2.15.0,<3.0.0",
  "cryptography>=42.0,<51.0.0", "httpx>=0.27.0,<0.29.0"]` (develop's #919 pins plus the two
  additions); a `casbin` extra is **not** added in this change (the branch raises).
- Env-var caveat (design section 9): any `AK_IDENTITY__*` variable materializes the block; a
  materialized `identity` with the default `oidc` type and no `issuer` fails at startup with
  `AKConfigError` from the model validator, which is the intended fail-fast.

### Behavioural changes

Each is intentional; the justification is design section 10 unless stated.

1. A chat body, multipart form or WebSocket envelope carrying `user_id` is rejected (400 REST,
   `FAILED` frame WS) instead of being honoured as the acting user. The acting user is the
   credential's subject on every surface.
2. With no `identity` block, every request is the anonymous principal; the REST subject that was
   validated and discarded (`api/http.py:223-232`) no longer exists as a seam.
3. WebSocket, AG-UI, thread and schedule handlers refuse to construct without an `identity` block
   (`AKConfigError`); they refused without a validator or authoriser in code before.
4. WebSocket connections are keyed by `principal.subject`, not by a `userId` claim; a token whose
   provider yields a subject always connects. The WS ack frame carries `subject`.
5. `GET /api/v1/agents` returns descriptors filtered by the caller and paginated, not a list of
   names.
6. MCP `tools/list` and `/a2a/catalog` return only the agents the caller may see; a hidden
   agent's A2A card is 404; calling a hidden MCP tool is refused by FastMCP.
7. With an `authorization` block, an agent run is refused before pre-hooks (403), a hidden agent
   is 404, denied tools are hidden where the framework allows and refused at call time with a
   reason string everywhere, and a session is continued only by its owner (403) outside
   messaging and realtime.
8. A HITL resume by a different non-anonymous subject than the one that paused is refused (403).
9. A scheduled trigger whose owner lost access is recorded with an error and skipped, never run.
10. Threads: an existing thread is appended to only by its owner (403); the chat routes answer
    401 to anonymous callers instead of 400 "user_id is required".
11. Schedules: creation requires an authenticated principal (401 on the chat route, an error
    string from the tools); the frozen trigger body carries `principal`, not `user_id`.
12. `Runtime.register` raises `AgentRegistrationError`; `Runtime.agents()` returns the registry's
    dict (same contract).
13. `KeyValueCache.set/delete/update` refuse `ak.`-prefixed keys; `clear()` keeps them.
14. `A2ACardBuilder` emits the descriptor version and, with identity configured, security
    schemes; ADK agents now have a card.
15. The schedule tools act for `Session.get_principal()`; the reason string changes.
16. The sandbox default resolver returns a user-mode principal for an authenticated run on a
    direct surface (never for a `messaging:` or `realtime:` principal); the manager hands it to
    the provider only under a `user`-mode profile.
17. `mcp.agents`, `a2a.agents`, `agui.agents` fail at startup when present.
18. The three OpenAI realtime-only reads of `is_enabled` and the guardrail fields
    (`framework/openai/openai.py:836-850`) now see AK-set values: a realtime session offers only
    the tools whose composed `is_enabled` is true at connect, and AK-added input guardrails no
    longer cause a tool to be skipped (the skip is narrowed to user-added guardrails).
19. LangGraph `get_a2a_card` skills, always empty today because `node_data.tools` never exists
    (`framework/langgraph/langgraph.py:380-401` against
    `langchain_core/runnables/graph.py:95-105`), are populated from the compiled graph's tool
    nodes through the descriptor.
20. `APIGatewayAuthorizer` denies a bare token sent without the `Bearer` scheme; the base's
    `_extract_token` accepted it (section 8.9).
21. The routes of a handler that declares `authenticates_itself` are mounted without the identity
    dependency: every `WebhookRESTRequestHandler`, and in single-process async mode the co-hosted
    `PipelineWebSocketHandler` and `PushEndpointHandler` (section 8.2).
22. `AzureFunctions.handler` answers a refused credential with 401; the base had no
    authentication on that path.
23. With no `identity` block an `Authorization` header is ignored without being parsed, so a
    malformed or non-bearer one runs anonymous too.
24. `AWSWebsocketAPI.get_default_handlers()` raises `AKConfigError` without an identity block,
    where the base raised `ValueError` without a validator.
25. The built-in role mapper looks up the groups and only the claim paths listed in
    `role_mapper.claims`, not every string claim value (section 4).
26. A webhook delivery the adapter cannot verify (its verification secret unset) runs anonymous
    under `WebhookRESTRequestHandler` (section 8.4).
27. A 401 from the identity dependency or `AuthorisedRESTRequestHandler` carries
    `WWW-Authenticate: Bearer`; MCP's 401 points at RFC 9728 metadata for `mcp.url` that the app
    serves at its root (section 8.6).
28. An empty `static.principals` map, an empty or unknown `algorithms` entry (`none` included) and a
    Cognito `token_use` other than `access` or `id` are startup errors (section 4).
29. The API Gateway authorizer answers a refused, expired or malformed token with 401 (it raises
    `Unauthorized`) instead of a Deny's 403; a request with no token is still a Deny (section 8.9).

**Non-changes:** session, thread, schedule, attachment and response-store layouts (one optional
`last_error` on schedule occurrences and `principal` on tasks aside); the queue envelope
attributes and `ATTR_USER_ID` as the WS-entered marker; `RequestProducer`, `IntegrationProducer`
attribute stamping; every native framework call when no `authorization` block is present
(keyword-for-keyword, the #754 invariant); `AgentService.select`; `ChatService` wire shapes other
than the 403/404 branches; the HITL approval flags and resume contract; `Session.Keys` values
for the two caches and the framework context; public exports other than those named deleted.

## Error handling

| Failure | Where | What surfaces |
|---|---|---|
| Invalid, expired, wrong-audience credential | `RequestAuthenticator` | 401 `"Unauthorized"` (HTTP), 1008 `"Authentication failed"` (WS), `ToolError` (MCP via FastMCP's own 401), `AuthenticationError` logged at INFO with the reason |
| Malformed `Authorization` header | same | 401 `"Invalid authorization header"` when a provider is configured; without one the header is ignored unparsed and the request runs anonymous |
| Anonymous caller on a surface that needs a user | `AuthorisedRESTRequestHandler._resolve_user` | 401 `"Authentication required"` |
| No level on the agent | `AccessGate.authorize_agent` → `PermissionError` | 403 with the message; `StreamChunk(error, done=True)` on a stream; `ToolError("Agent not available")` on MCP; A2A `InternalError` |
| Agent not visible | `LookupError` | 404 `"Agent '<name>' not found"` (indistinguishable from unknown) |
| Session owned by another principal | `authorize_session` → `PermissionError` | 403 at the choke point; thread path 403 before any write |
| Resume by another subject | `_validate_resume` → `PermissionError` | 403; record kept |
| Denied tool at call time | adapter gate | a tool result string with the reason; never an exception into the framework; a failure inside the gate denies with `"tool gate failed: <type>"` |
| `identity.provider` misconfigured (no issuer, missing block, symmetric algorithm) | config validator / provider constructor | `AKConfigError` at startup |
| Static credential key not in the secret capability | `StaticIdentityProvider` | `AKConfigError` naming the key |
| JWKS unreachable | `JWKSCache` | `AuthenticationError` after one refresh attempt; no cache poisoning (the previous key set stays) |
| Shared credential store without `encryption_key`; wrong key length | store constructor | `AKConfigError` |
| `token_for` with no inbound credential, no exchanger, or exchange failure | `CredentialBroker` | `CredentialError` (tools return it as a result string) |
| Exchanger or engine name reserved but not shipped | the factories | `AKConfigError` naming the dotted-path alternative |
| Missing optional SDK (`redis`, `valkey`, `boto3`, PyJWT, cryptography) | factories under `require_extra` | `ImportError` naming the extra |
| Duplicate agent id | `AgentRegistry.register` | `AgentRegistrationError` |
| Policy naming an unknown tool on a hosted agent; LangGraph/smolagents ungated tools | `AccessGate.validate_configuration` | `AKConfigError` at `Module.load` / `get_router()` |
| Removed config lists present | `_A2AConfig`/`_MCPConfig`/`_AGUIConfig` validators | `AKConfigError` naming `registry.agents.<id>.surfaces` |
| Registry store unreachable | driver retries (3 × 2 s) then the driver's error | `register` fails the `Module.load`; catalog routes 500 |

Concurrency: `IdentityProviderFactory.get()`, `AuthorizerFactory.get()`, `AccessGate.get()` and
`AgentRegistryFactory.build()` are built once behind an `RLock` (the `ScheduleManager.get()`
shape, `schedule/manager.py:60-73`); `JWKSCache` guards its refresh with a `threading.Lock`
because ECS consumer threads share one provider; the redis-like and DynamoDB stores inherit the
drivers' per-instance connect lock; `InMemoryCredentialStore` and `InMemoryAgentRegistry` use
plain dicts under the GIL with no check-then-act across awaits. Per-operation cost on hot paths:
one `authorize_agent` at the surface and one at the choke point per request (accepted, design
section 6), one `filter_tools` per run, one cache read per tool call in the adapter gates, one
store `put` and one `delete` per authenticated request when `identity.credentials` is configured.

## Testing

New files under `ak-py/tests/`:

- `test_identity_models.py`: `Principal` frozen and copy helpers, `anonymous()`, `AccessLevel`
  ordering, `ToolFilter.allows/reason`, `AgentDescriptor` defaults and `exposed_on`,
  `SessionOwner`, `SystemTool.tier` default.
- `test_identity_providers.py`: `IdentityProviderContract` subclassed for `oidc`, `cognito`,
  `entra`, `firebase` (RSA and EC keys from `cryptography`, a local JWKS over
  `httpx.MockTransport`, discovery cached, unknown `kid` refresh once, cooldown), `static`
  (secret resolution, constant-time compare, namespace `"static"`); `RoleMapperContract` for
  `mapping` and a dotted mapper; `IdentityProviderFactory` built-in, dotted, unknown and missing
  extra; `RequestAuthenticator` bearer parsing, anonymous rules, 401 details, `credential_ref`
  minting and `release`, the contextvar.
- `test_identity_credentials.py`: `CredentialStoreContract` over in-memory and the redis-like
  and DynamoDB backends through fake drivers (the `test_schedule_store.py` pattern); cipher round
  trip; `TokenExchangerContract` over `passthrough` and a fake; the `passthrough` startup
  warning; `CredentialBroker` cache key, TTL, `CredentialError` cases; no token in a queue body or
  a log record (caplog asserted); the inbound entry deleted at run end on the direct and queued
  paths; reserved exchanger names raise.
- `test_agent_registry.py`: `AgentRegistryContract` over in-memory, redis-like (fake client at
  `store._driver._client`) and DynamoDB (fake driver); `AgentRegistryFactory` resolution;
  `Runtime.register` delegating and raising `AgentRegistrationError`; `Module.describe`
  (unloaded agent, unknown field, later wins); the config overlay; descriptors readable from a
  second registry instance over the same fake store (the io-handler case).
- `test_authorizer_static.py`: `AuthorizerContract` subclassed; grant normalization errors; the
  empty-grants warning; tier defaults from system tools.
- `test_access_gate.py`: visibility rules, 403 versus 404, `tool_filter` composition, `tag:`
  resolution, `authorize_session` (no owner, anonymous refused on an owned session, a
  shared-channel owner admitting its platform scope and refusing a REST caller, namespace
  mismatch), `validate_configuration` (unknown tool `AKConfigError`, unknown agent and tag
  warnings, `role:` without a mapper warning, the LangGraph and smolagents refusal).
- `test_session_identity.py`: `ak.` keys refused through `set`, `delete`, `update`, `__setitem__`
  and `__delitem__`; `clear()` keeps them and `_clear_all` does not; `get_principal`,
  `get_tool_filter`, `get_owner` and `ToolContext.access_level` read-only; `access_level` `None`
  without authorization; owner set once with its namespace and persisted by every store (fake
  drivers); principal never persisted; ownership 403 on a subject or namespace mismatch;
  messaging and realtime exemption; `PausedRunState` writes through the reserved path.
- `test_runtime_principal.py`: `Runtime.run`/`stream` publishing and unpublishing; the gate order
  (refused before pre-hooks, nothing stored); the actor chain; the resume subject check as the
  eighth failure mode with the record kept; realtime tool execution publishing through
  `_execute_tool_and_reply`.
- `test_tool_gates_<adapter>.py` for `openai`, `pydanticai`, `adk`, `crewai`, `langgraph`,
  `smolagents`, `maf`, `claude` and `realtime`: with a filter published, a denied tool is hidden
  where the framework allows (OpenAI `get_all_tools`, Pydantic AI `prepare_tools`, Claude
  `disallowed_tools`, LangGraph and smolagents not hidden, MAF not hidden, ADK not hidden), a denied call returns the reason string without
  raising into the framework, an allowed call runs, the composition with a user-set hook or
  middleware preserves the user's, and the no-authorization path's native call is
  keyword-for-keyword unchanged (asserted on the mocked native call as the `test_*_runner.py`
  files already do); `ungated_tool_names` for LangGraph (unmarked `StructuredTool` in a
  `ToolNode`) and smolagents (a tool added after wrap).
- `test_api_catalog.py`: `GET /api/v1/agents` descriptors, filtering by caller, `tools`
  narrowing, cursor and limit, 400 on a bad cursor, `surfaces` narrowing per surface.
- `test_api_mcp_auth.py`: `AKTokenVerifier` through a real `fastmcp.Client` with a bearer token,
  401 on a bad token, `tools/list` filtered by the per-tool check, the principal on the enqueued
  body, open MCP without identity; `RemoteAuthProvider` metadata served for an OIDC provider.
- `test_api_a2a_auth.py`: the context builder putting the principal on the call context, the
  executor setting it on the body, cards carrying `security_schemes` and per-skill requirements
  for `static` and `oidc`, none without identity, a hidden card 404, `/a2a/catalog` filtered.
- `test_cli_token.py`: `--token` and `AK_CLI_TOKEN` through the `static` provider; the principal
  on `run_multi`; an invalid token exits.
- `test_principal_messaging.py`: `IntegrationProducer.enqueue` building the `messaging:` and
  `realtime:` principals with namespace and claims; Gmail's `authentication_results` claim; the
  LiveKit edge passing the participant identity; anonymous when the adapter has no sender.
- `test_schedule_principal.py`: ownership over the real REST wiring, `RESTAPI.build_app` with a
  `static` provider resolving two principals: a task created from a chat request is readable,
  amendable and cancellable by its owner alone, the listing is the caller's own, every route
  answers an anonymous caller 401 and a refused credential the dependency's 401. The
  manager-level cases (`create` requiring a principal, the frozen `principal` in the trigger
  body, `record_trigger` ownership by namespace and subject) landed in `test_schedule_manager.py`
  in iteration 3 and the tools reading `Session.get_principal()` in `test_schedule_tools.py`; a
  pre-change task body (no principal) firing anonymous and the fire-time level re-check skipping
  with `last_error` join this file in iteration 19.
- `test_deployment_identity.py`: `APIGatewayAuthorizer` policy context carrying the serialized
  principal and the REST router rebuilding it (a client-sent `principal` replaced, the direct chat
  and queued bodies carrying it); the ECS and Lambda `$connect` handlers keyed by subject, refusing
  an invalid or missing token and a build without an identity block; ECS and Lambda frames resolving
  the stored principal (401 or `ValueError` without one), the queued, direct and custom routes
  carrying it; `AzureFunctions.handler` 401 before the body is read, anonymous without a header; the
  AWS connection store writing and rebuilding the `principal` attribute (`None` for a legacy row);
  the removed `agentkernel.auth` module, `set_auth_handler`, `set_auth_validator`,
  `add_auth_handlers` and `GCPAuthorizer` names, the validator-free entry-point signatures, and
  `Lambda.principal` rebuilding the authorizer context (anonymous without one). The
  provider is the `static_identity` fixture in `tests/conftest.py` (a recording `static` provider
  installed on `IdentityProviderFactory.get`, so the deployment modules' `SimpleNamespace` config
  stubs need no `identity` or `secret` block; the construction-from-config path is pinned in
  `test_identity_providers`).

Changed files and the exact targets that move:

- `tests/test_api_http.py:185-316, 338`: every `add_auth_handlers` / `_auth_token_validators`
  assertion is replaced by assertions on `RESTAPI._get_router_dependencies()` returning the
  identity dependency, and a body `user_id` answering 400; the `IOHandler.run` stubs at 485, 498,
  511, 530 and 689 drop the `auth_validator=None` parameter.
- `tests/test_pipeline_ws.py:83-89, 326-392, 450-462, 522-572, 647-693`: `_Validator` becomes a
  `static` provider configured through the `AKConfig.get` stub at 54-74 (`identity.provider.static`
  with two principals); the 1008 close texts lose the `userId` case (343); registry and store are
  keyed by the subject (360-372); the chat ack carries `subject` and the body carries `principal`
  (375-392); the custom route reads `msg["principal"]` (454); `WebSocketGateway.run()` and
  `_validate(transport, config)` lose the validator argument (522-560).
- `tests/test_pipeline_io_handler.py:65-80, 380-441`: the `_validate_topology` validator cases
  become identity-block cases; `IOHandler.run(auth_validator=...)` calls drop the argument; the
  "auth_validator ignored" assertions (399, 429, 433) are deleted.
- `tests/test_ecs_io_handler.py:23-64`: `add_auth_handlers` assertions deleted; the "requires
  auth_validator" cases become "requires an identity block".
- `tests/test_ecs_websocket_routes.py:30-42, 298-339`: `_FakeValidator` and the
  `set_auth_handler` calls become the `static_identity` conftest fixture; `WSRouteContext` is built
  with `principal`, `build_route_context` stubs `get_principal`, `get_default_handlers` without an
  identity block is an `AKConfigError` case, and the custom route ctx is `{"message", "principal"}`
  (192-204).
- `tests/test_agui_handler.py:48-52, 137-154, 208-294, 594` and `tests/test_agui_resume.py:38-40,
  112`, `tests/test_agui_queue_handler.py:67-69, 90, 116, 413-414, 568`: `StaticAuthoriser` /
  `_Auth` become a static provider in the config stubs; `agui.agents` cases (208-211, 274-294)
  become `registry.agents.<id>.surfaces` cases; the acting-user test (241-252) reads
  `ToolContext.get().principal.subject`; `_FakeHandler.run_stream_sync(requests, principal=None)`.
- `tests/test_thread_router.py:37-47, 145-186` and `tests/test_schedule_router.py:51-78,
  252-313`: `StaticAuthoriser` becomes a fake `IdentityProvider` behind
  `RequestAuthenticator(provider).dependency()` on the test app, the identity dependency as
  `RESTAPI` mounts it (the real `static` provider runs in `test_schedule_principal.py`); the 401
  variants keep their texts except that an absent header on these routes is
  `"Authentication required"`; construction without a provider is `AKConfigError`; a `user_id`
  query cannot widen a listing.
- `tests/test_schedule_tools.py:112-127, 295-326`: the `acting_session` fixture publishes a
  `Principal` through `Session._publish_run`; the no-identity error text changes.
- `tests/test_chat_service_core.py:41-45, 182, 208, 290-379`: fakes take `principal=None`;
  `TestActingUserPropagation` builds requests with `principal=` and asserts
  `Session.get_principal()`; a `user_id` body is a `ValueError`.
- `tests/test_chat_service_streaming.py:26-33, 140-237`: the same rename on the fakes and on the
  `run_stream_sync` patch lambda (234-237).
- `tests/test_chat_service_schedule.py:23-26, 173-197, 229-236`: bodies carry `principal`;
  `record_trigger` receives the principal; the "foreign task" test asserts a principal with
  another subject.
- `tests/test_thread_integration.py:108-143, 169-310` and
  `tests/test_thread_pipeline_recording.py:135-256`: bodies carry `principal`; the "missing
  user_id is 400" cases (176-185, 182-189) become "anonymous is 401"; a non-owner appending is
  403 and leaves the thread untouched. The HTTP cases mount the handler behind the identity
  dependency with a bearer token per test user, replacing the iteration 3 test-side handler
  subclasses that set `request.state.principal`; `tests/test_thread_manager.py` gains the
  foreign-thread `PermissionError` of `get_or_create_thread`.
- `tests/test_api_multipart_fields.py:5-102`: `user_id` leaves `EXPECTED_FORM_FIELDS` and the
  OpenAPI assertion; a form carrying it is asserted a 400 with nothing captured.
- `tests/test_serverless_request_handle.py:5-91, 147-150`: envelope `user_id` cases become
  rejection cases (`ValueError`), the SQS attribute case (134-143) stays.
- `tests/test_ws_lambda_stream.py:8-24`: the frame drops `"user_id"` and the handlers stub
  `get_principal` in place of `get_user_id`; `tests/test_akauthorizer.py` and
  `tests/test_authorizer_webhook_bypass.py:38-41`: the mocked validator becomes the `static_identity`
  conftest fixture; policy context assertions (165, 181, 252-303) check `context["principal"]`, the
  bypass cases assert on the provider's recorded calls instead of a mock validator, and the
  `_extract_token` cases go with the method (a bare token is now a Deny).
- `tests/test_serverless_agent_runner_schedule.py:33-59`, `tests/test_ecs_agent_runner_schedule.py:32-76`,
  `tests/test_pipeline_agent_runner_schedule.py:59-112`: the trigger body carries `principal`;
  the attribute derived from it on the fallback path.
- `tests/test_integration_producer.py:35, 59-64`: the body carries `principal` with
  `provider="messaging:<name>"` and no `ATTR_USER_ID`.
- `tests/test_module.py:80-84`, `tests/test_runtime.py:79-155`: the `FakeCfg` stubs gain
  `identity = authorization = registry = None` (the new reads are `getattr(..., None)`-tolerant,
  but the stubs are updated so the suites assert the intended default); `test_module.py:146`
  expects `AgentRegistrationError`.
- `tests/test_api_a2a_surface.py`, `tests/test_api_a2a.py:264`, `tests/test_api_mcp.py:51-53,
  280`, `tests/test_protocol_pipeline_roundtrip.py`, `tests/test_cross_surface_parity.py`: the
  config stubs gain the three `None` blocks; `A2ACardBuilder.build(descriptor)` call shape; the
  enqueued body carries an anonymous principal.
- Deleted: `tests/test_auth_handler.py`, `tests/test_authoriser_shared.py` (both pin the removed
  package); their surviving assertions (bearer parsing, 401 variants) live in
  `test_identity_providers.py`, the thread handler's membership of the `AuthorisedRESTRequestHandler`
  hierarchy moves to `test_thread_router.TestConstruction`, and the `AuthValidatorAuthoriser`
  adapter has nothing left to pin.

Run: `cd ak-py && uv run pytest`. The riskiest consumer, `pipeline/request_handler.py` (precheck
before enqueue on a store-backed registry with no local agents), gets dedicated cases in
`test_pipeline_request_handler.py` using a fake registry driver and no registered `Agent`.

## Documentation, skills and examples

Surfaces the implementation invalidates, from a sweep of the tree at `d9d0d18bc`. The phase A and
B portion landed with phase B itself (PR #937); `plan.md`'s docs and skills iterations (27 and 28)
cover phases C to F, and the sync skills verify them before merge.

- **Docs site (`docs/docs/`)**: new `advanced/identity-and-access.md`; `api/rest-api.md`
  (the Authentication section 474-499 and the `user_id` context claim 192-207, already
  inaccurate); `api/agui-server.md:26-76`; `integrations/agui.md:21-120`; `api/mcp-server.md:37,
  85-91`; `api/a2a-server.md:18-29`; `core-concepts/configuration.md:58-72, 128, 324-332, 524,
  534, 854-867, 1084`; `advanced/threads.md:21-218, 323`; `advanced/scheduling.md:21-274, 397-408`;
  `advanced/queue-mode-guide.md:80, 144, 323-412, 485-491, 673-674, 808`;
  `deployment/aws-serverless.md:280-342, 502-510, 579-599, 873, 1391-1397, 1674-1678` (whose
  `from agentkernel.api import AuthValidator` import is already broken); `deployment/aws-containerized.md:187-191,
  376-401, 710-734`; `deployment/onprem-kubernetes.md:86`; `architecture/execution-flow.md:111,
  256, 367-369`; `architecture/overview.md:132`; `advanced/sandbox.md:458-492` (the default
  resolver now reads the run principal); `ak-py/README.md:250-281, 459-461, 601-602, 1018-1091`;
  root `README.md:136`.
- **Dev skills (`.agents/skills/`)**: `ak-dev-architecture/SKILL.md` (acting-user paragraph 82,
  `Runtime`/`AgentService`/`ChatService` signatures 132-167, threads 398-405, AG-UI 462-477, the
  `agui` block 531-543, scheduling 645-655, sandbox 894, pipeline 926-927, ECS 1205-1248) gains
  an Identity and Access section; `ak-dev-testing-conventions/SKILL.md` rows 62-183 for the
  changed and deleted files plus the new ones; `ak-dev-new-messaging-integration/SKILL.md:34,
  124` (the `namespace` field and the authorizer bypass); new `ak-dev-new-identity-provider` and
  `ak-dev-new-authorizer` skills.
- **User skills (`ak-py/src/agentkernel/skills/`)**: `ak-cloud-deploy/SKILL.md:8-77, 292,
  635-662, 700-701, 780-797, 849-868, 928-930, 1061-1084, 1124-1125, 1386` and its
  `evals/evals.json:178`; `ak-add-capabilities/SKILL.md:543-660, 1046-1048, 1133-1160, 1230-1262,
  1314-1333` and `evals/evals.json:212-239`; `ak-add-integration/SKILL.md:78-79`.
- **Examples**: the five WebSocket examples (`aws-containerized/openai-websocket`,
  `openai-stream`, `openai-stream-queue-mode`, `openai-websocket-scalable`,
  `k8s/openai-queue-mode/app_ws_gateway.py` and `ws_client.py`), `aws-containerized/crewai-auth`,
  `api/thread-openai`, `api/multimodal/thread-openai`, `api/agui`, `api/hitl`, `api/a2ui-openai`
  (its frontend sends `user_id`), `api/schedule-openai`, `aws-containerized/openai-schedule`,
  `aws-serverless/openai-auth`, `slack-openai`, `websocket-openai`, `streaming-openai`,
  `schedule-openai`, and the three configs naming `mcp.agents` / `a2a.agents`
  (`aws-containerized/mcp/multi`, `k8s/openai-queue-mode/config.{kafka,nats}.yaml`): each gains
  an `identity.provider` block (`static` for the demos, credential values through the `secret`
  capability), drops `user_id` from bodies, READMEs and tests, and moves surface lists to
  `registry.agents.<id>.surfaces`. `examples/sandbox/identity` keeps its custom resolver and
  gains a note that the default resolver now covers it.
  - As implemented (iteration 12, 2026-11-10): the credential keys follow one convention, resolved
    through the secret capability's environment layer: `ALICE_TOKEN`/`BOB_TOKEN` for the two-user
    API demos, `DEMO_TOKEN` for the single-user API demos, `DEMO_AUTH_TOKEN` for every AWS and k8s
    example (a sensitive `demo_auth_token` Terraform variable passed to the one process that builds
    the provider: the ECS REST service, the Lambda authorizer or WebSocket connection handler; on
    k8s a `demo-credentials` Secret injected through the chart's `extraEnv`, because the
    `secretStore` mount reaches only the agent-executing tier while the io handler and the gateway
    build the provider). The API example tests start `app.py` with those values in its environment.
    `aws-serverless/schedule-openai` gains an authorizer Lambda (`lambda_auth.py`, an `authorizer`
    dependency set, the `dist_auth` package), since a task belongs to an authenticated caller, and
    its custom routes read the owner with `Lambda.principal(event)`. The ECS WebSocket custom routes
    receive `{"message", "principal"}` and `echo` returns the principal as a JSON dump. The GCP
    `openai-auth` examples authenticate Google identity tokens at the API Gateway and import nothing
    from the removed package, so they are unchanged; `examples/cli/adk-run-options` keeps ADK's own
    `user_id` run option. `aws-containerized/openai-websocket` has no `app_test.py`; its handshake
    is covered by `test_deployment_identity`. The k8s example's `protocol_client.py` sends
    `DEMO_AUTH_TOKEN` as the bearer token on both protocols, and the chart's kind smoke creates the
    `demo-credentials` Secret and passes the credential to every flavor (2026-11-10 follow-up).
  - Identity examples (plan iteration 29, the last; planned 2026-11-10 and deferred to after the
    docs and skills iterations, not yet implemented): one example per
    supported provider and per identity feature of phases A and B. `examples/api/identity/oidc-keycloak`
    runs the `oidc` provider against a Keycloak container (realm import, `claims.groups:
    realm_access.roles`, a `mapping` role mapper) with `config.auth0.yaml` and `config.okta.yaml`
    as documented alternates; `examples/api/identity/custom-provider` is a dotted-path
    `IdentityProvider` over signed API keys yielding `kind: service` principals;
    `examples/api/identity/principal-in-tools` reads `ToolContext.principal` (with `actor`),
    `session.get_principal()` in a hook and `session.get_owner()`; `examples/cli/openai-identity`
    shows `--token` / `AK_CLI_TOKEN`; `examples/api/identity/protocols` sends bearer tokens over
    MCP and A2A; `examples/sandbox/identity-provider` runs `identity.mode: user` on the default
    resolver with no custom code; `aws-serverless/openai-cognito`, `azure-serverless/openai-entra`
    and `gcp-containerized/openai-firebase` run the three cloud providers in their deployments;
    `azure-serverless/openai` moves to the static block and the two GCP `openai-auth` examples gain
    a bring-your-own provider that verifies the caller's token from `X-Forwarded-Authorization`
    (behind API Gateway a built-in `oidc` block sees only the gateway's own token). The local suites join the e2e tier, the cloud suites
    the weekly tier. Landing after the docs and skills iterations, it adds the new examples to the
    examples list and the supported-providers table of `advanced/identity-and-access.md` and to the
    user skills that list them.
- **Supported providers, wherever they are listed**: the docs site, the READMEs, the user skills
  and the examples name Auth0 as a supported identity provider served by the `oidc` type (decided
  2026-11-10), with its configuration spelled out rather than implied: `issuer:
  https://<tenant>.<region>.auth0.com/` (or the custom domain, trailing slash included),
  `audience: <API identifier>`, `claims.groups: https://<namespace>/roles` for the roles an Action
  sets, and `permissions` and `org_id` reaching the role mapper and tools through `claims`. The
  list reads: any OIDC issuer (Auth0, Keycloak, Okta as named configurations), Cognito, Entra ID,
  Firebase, static.
- **Deployment READMEs**: `ak-deployment/ak-k8s/README.md:90-92, 189` and the chart comments
  (`deployment-io.yaml:7`, `values.yaml:193`); `ak-aws/serverless/README.md:14, 396-425, 480-506,
  792-892, 1110+` and `modules/ws-connection-handler/README.md:10`;
  `ak-aws/containerized/README.md:186, 506-511`. The Terraform resources are unchanged: the
  connections table keeps its `user_id` hash key, and the authorizer Lambda keeps its
  `handler_path` contract.

## Design refinements

Mechanism changes found while detailing, each inside a settled decision and mirrored in
`design.md`:

1. **Registry ABC location.** `AgentRegistry`, `InMemoryAgentRegistry`, `AgentRegistryFactory`
   and `AgentRegistrationError` live in `core/registry.py`, not `identity/registry/`, because
   `Runtime` needs a registry with no `registry` block and `core/` imports `identity/` only
   lazily inside an enabled-check. The store-backed backends stay under `identity/registry/`.
2. **Pydantic AI gate mechanism.** pydantic-ai-slim 2.13.0 has no `prepare_tools` on
   `Agent.__init__` (`pydantic_ai/agent/__init__.py:341-362`); list-time and call-time gating go
   through a per-run capability (`AbstractCapability.prepare_tools` and `before_tool_execute`,
   `pydantic_ai/capabilities/abstract.py:392-406, 709-750`) passed as `capabilities=` on
   `agent.run` (`pydantic_ai/agent/abstract.py:366-387`), composed AK-first with any caller
   `capabilities` in the run options.
3. **Messaging principal built at the edge.** `IntegrationProducer.enqueue` builds the
   `messaging:`/`realtime:` principal, not `AgentRunner`, so the runner stays platform-agnostic
   and the LiveKit edge follows the same path.
4. **Native tools covered where the object is reachable.** OpenAI composes `is_enabled` and adds
   the input guardrail on every `FunctionTool` already on the native agent at wrap time, and
   smolagents wraps `forward` on every tool in `agent.tools` at wrap time, so the Q12 refusal
   applies to LangGraph graph tools not produced by `LangGraphToolBuilder.bind` and to smolagents
   tools added after wrap only.
5. **A2A principal hand-off.** A `ServerCallContextBuilder` carries `request.state.principal`
   into the executor's `call_context.state`, the SDK's own seam, rather than the `ServerCallContext.user`
   the design ruled out.
6. **JWKS fetching without `PyJWKClient`.** `JWKSCache` fetches discovery and the JWK set through
   one `httpx.AsyncClient` with an injectable transport and selects the key from
   `jwt.PyJWKSet`, instead of wrapping `PyJWKClient`: its `urllib` fetch blocks the event loop
   (the spec had it in a thread) and cannot be pointed at a test transport, so the contract suite
   could not serve a local key set. The design's rules hold unchanged: discovery once, one forced
   refresh per unknown `kid` with a 30 s cooldown, no blocking fetch, a failed fetch keeps the
   previous keys. Amended at the PR #937 review: the cache keeps no event-loop-bound state (the
   `AsyncClient`'s pooled connections and the `asyncio.Lock` broke a sync host that runs each call
   on a fresh loop), so a load runs on a worker thread through a short-lived `httpx.Client` with the
   same injectable transport, and "no blocking fetch" now means the loop never waits on one
   (section 4).
7. **The MCP principal rides a claim.** FastMCP 3.4.10 copies the verifier's access token into
   its own `AccessToken` (SDK fields only) before `get_access_token()` returns it to a tool, so
   the spec's `isinstance(token, AKAccessToken)` check never holds over HTTP. The verifier puts
   the principal under the `ak.principal` claim beside its `principal` field, and
   `AKAccessToken.principal_of` reads whichever it is handed; the design's rule (the executor
   runs as the authenticated caller, anonymous otherwise) holds unchanged.
