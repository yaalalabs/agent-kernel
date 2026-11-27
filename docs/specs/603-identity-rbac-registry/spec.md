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

The places where detailing refined the design are listed in [Design refinements](#design-refinements)
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
│   │                       #   Agent.descriptor, Agent.get_tool_names; get_a2a_card removed
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
│   │   ├── static.py       # StaticAuthorizer, GrantTable, ToolPolicyTable, SubjectMatcher
│   │   ├── gate.py         # AccessGate
│   │   └── testing.py      # AuthorizerContract
│   ├── registry/
│   │   ├── base.py         # StoreBackedAgentRegistry
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
    def catalog_entry(self) -> dict: ...   # model_dump(mode="json") without `identity`
```

- `Principal.frozen` means a hook or tool holding one cannot mutate it; `with_actor` and
  `with_credential_ref` return copies, and only `Runtime` and the surfaces call them.
- `SystemTool` (`core/model.py:357-360`) gains `tier: AccessLevel = AccessLevel.READ`. The
  declared tiers (design section 1): sandbox tools and the five schedule tools `WRITE`
  (`sandbox/tools.py:447-459`, `schedule/tools.py:370-374`); `analyze_attachments`
  (`core/multimodal/tools.py:89-101`), the OKF read tools (`knowledgebase/okf/tools.py:55`),
  `get_agui_state`, `get_forwarded_props`, `get_agui_context` (`integration/agui/state.py:198-212`)
  `READ`; `write_kb` and `update_agui_state` `WRITE`. `AnalyzeAttachmentsTool` declares it as a
  field default like its other fields. Declared in iteration 18. Every sandbox tool is `WRITE`,
  the ones that only read a sandbox included (`read_sandbox_file`, `check_sandbox_task`,
  `list_sandbox_sessions`), and so are `list_schedules` and `get_schedule`: they are of use only
  to a principal that may run code or create a task. A policy's `tiers` entry lowers one.
- `BaseChatRequest` (`core/model.py:408-431`): `user_id` (line 427) is **removed**;
  `principal: Optional[Principal] = None` is **added** with the docstring rule "assigned by the
  surface after authentication; a value arriving from a client is overwritten, never read".
  `group_id`, `thread_name`, `schedule` and `resume` stay. The docstring lines 411-417 that
  say `user_id` is required for threads and schedules are rewritten to "a non-anonymous
  principal is required".
  `surface: Optional[AgentSurface] = None` is **added** in iteration 17b (design refinement 13):
  the agent surface the request entered by, assigned by the entry point where it assigns the
  principal and carried in the queued body. `None` for a request that entered by none of the
  four (a messaging integration, the CLI, a scheduled occurrence). It is one of
  `ChatRunRequest.INTERNAL_FIELDS`, so the client-facing body refuses a value for it and leaves
  it out of the published schema, and `RequestBuilder` never hands it to the agent as context.
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
- As built (iteration 18): steps 2 to 4 are `Runtime._admit(agent, session, principal)`, awaited
  first inside `async with session:`; with no gate it is the publication alone. The gate is
  reached through `Runtime.access_gate()`, the enabled-check `core` uses: it returns `None`
  without reading anything of `identity/` when the configuration has no `authorization` block.
  `_admit` awaits the gate's `async` forms and hands `authorize_agent` the descriptor of the
  agent it was given (`descriptor=agent.descriptor`), so the decision does not depend on that
  agent being registered in whichever runtime is current, and hands `tool_filter` the level it
  just resolved. `_publish(agent, session, principal, tool_filter=None)` stays synchronous for
  the realtime connection, which publishes each input's principal with no filter until
  iteration 23. In `stream` an `AgentNotFoundError` from the gate (an agent the principal may
  not see) is the same single error chunk as a `PermissionError`.
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
- As built (iteration 25, design refinement 24): authenticating keeps nothing. `authenticate_bearer`
  and `authenticate_token` stay pure; retention is `CredentialManager.retain(principal, credential,
  connection=False)` (`credential/manager.py`), called by the surfaces that keep a credential: the
  dependency (every authenticated HTTP request that can start a run, so REST, A2A, AG-UI and the threads;
  not a `GET`, `HEAD` or `OPTIONS` request, `READ_ONLY_METHODS`, and never a WebSocket handshake, whose
  run reference the first frame's run would delete), the MCP executor
  (each tool call, from the token on the access token FastMCP verified, deleted once the reply is in;
  never the verifier, which FastMCP asks on every HTTP request, initialize and listings included),
  the pipeline WebSocket gateway and the CLI
  (both `connection=True`, a `conn:` reference forgotten with `CredentialManager.forget` when the
  connection or session ends). The constructor is `RequestAuthenticator(provider, credentials:
  CredentialManager | None = None)`; `from_config(retains=True)` hands it `CredentialManager.get()` when a
  provider is configured, and `credentials` exposes it. `release(principal)` stays async and delegates to
  the manager off the loop. The Lambda authorizer retains nothing: its result is cached (150 s by default,
  keyed on the token), so a reference it minted would be shared by requests whose runs each release it.
  It builds through `from_config(retains=False)`, so no manager is built there and a store its role
  cannot reach does not fail it. A request a surface answers without a run releases its credential
  itself (from the #1023 re-review), through `CredentialManager.release_unclaimed` (off the loop, never
  raising) or `released_on_error` (an async context manager that releases when its block raises): the
  pipeline router wraps everything before the message is on the queue (`run_chat`, `_enqueue_and_wait`,
  the SSE enqueue, `request()`, the thread router's `run_chat`, the queued AG-UI `_run`), so a refusal
  or a failed send releases and a wait that times out after the send does not; the direct REST and
  thread routes release once their in-process reply is in (`AgentRESTRequestHandler._reply`) or when
  the stream never starts (`_stream_reply`); the direct AG-UI `_run` releases when it raises before
  the stream. A body FastAPI refuses (`422`) is answered before any route code runs, after the
  dependency retained, so that entry expires within `inbound_ttl`. `bearer_token(header)` is the one bearer parser, public and
  non-raising; the dependency's raising `_bearer_token` and the Lambda REST router both use it.
  TTLs as specified: a run's credential until `min(exp, now + inbound_ttl)`, a connection's until `exp`,
  else `now + inbound_ttl`; an expired token keeps nothing, and a store that cannot be reached is logged
  (no token) and leaves the request without a credential.
- As built (iteration 25b, design refinement 25), the AWS adapters and renewal:
  - The Lambda REST router (`DefaultEndpointsHandler`) retains where a run starts, `_send_to_queue`
    (REST_SYNC and the REST_ASYNC submit) and the direct `_handle_agent_chat`, from the event's own
    `Authorization: Bearer` header found whatever its case (`_bearer_token`, which finds it with
    `RequestAuthenticator.authorization_header`, the authorizer's rule too, so two names that disagree
    count as none and the authorizer denies them, and parses it with `RequestAuthenticator.bearer_token`);
    `_parse_body`, which a poll uses too, retains nothing. The direct route releases in a `finally`, so a
    request refused before its run starts (an unknown agent) keeps nothing. With queues, `get_routes`
    refuses an `in_memory` store.
  - The Lambda `$connect` (`ConnectionRoutesHandler`) and the ECS `$connect`
    (`ECSWebSocketSystemRequestHandler`) retain for the connection, and both refuse a store that is not
    shared at construction: on ECS a frame can reach another task than the one that took the handshake,
    as it does under every rolling deploy. A `$connect` whose connection row cannot be written forgets
    the credential it just kept, since no `$disconnect` would find it. `AWSWebSocketHandler.on_disconnect`, shared by both, reads the
    stored principal before the row goes and forgets its credential (`CredentialManager.forget_for`).
  - Renewal is `CredentialManager.renew(principal)`: for a `conn:` reference whose principal carries no
    `exp`, it extends the stored entry to `inbound_ttl` from now with `CredentialStore.touch`, which
    extends only an entry still live, so a credential that has expired, or that a disconnect in another
    process deleted between two frames, is not brought back; it never raises. Because it goes through
    the store it works on Lambda too, which the design thought could not renew. Called on every frame:
    the pipeline gateway's `_dispatch`, the Lambda frame's `_connection_principal` and the ECS
    `build_route_context` (both through `CredentialManager.renew_for`); and by the CLI before each
    prompt's run.
  - The serverless runners release in `process_message`'s `finally` (`_ServerlessCredentials.release`).
  - One check for every place that keeps a credential in one process and reads it in another:
    `CredentialManager.require_shared_store(config, where)`, which `AgentRunner._validate_credential_store`
    now calls too. `CredentialStoreFactory.is_shared(store)` decides without building the store: False
    for `in_memory`, by its short name or its dotted path, and a bring-your-own store's `shared`.

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
    def __init__(self, principal: Principal, store: CredentialStore,
                 exchangers: dict[str, TokenExchanger], agent_id: str): ...  # no cipher: the store encrypts (refinement 23)
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

- As built (iteration 24, design refinement 23), where the store differs from the text above:
  - **The store encrypts.** `put`, `get`, `touch`, `delete` and `clear` are concrete on
    `CredentialStore`: `put` refuses an `expires_at` that has passed (`ValueError`, nothing stored) and
    seals the value with the store's cipher, the key as associated data; `get` opens it. A backend
    implements `_write(key, data, expires_at)`, `_read(key)` (None for a missing or expired entry),
    `_touch(key, expires_at)`, `_remove(key)` and `_clear()` over ciphertext only, so no caller handles
    ciphertext and the broker (iteration 25) takes no cipher.
  - **`touch(key, expires_at)`** (added in the #1023 review, for renewal) extends a live entry without
    reading or rewriting it, in one step that cannot bring back an entry that expired or was deleted:
    a class-level lock in memory (held by every change, so a touch never writes back an entry another
    thread replaced), `EXPIRE` on Redis and Valkey (whole seconds rounded up; it sets nothing on a key
    that is gone) and a conditional `update_item` on DynamoDB (`attribute_exists(credential_key) AND
    expires_at > :now`). An expiry that has passed is a `ValueError`. `CredentialStoreContract` pins
    that it extends a live entry and never creates, revives or restores one. The in-memory read drops an
    expired entry only if it is still the one it looked up, so a renewal between the two stands.
  - **Shared means encrypted.** `CredentialStore.shared` (a class attribute, `True` by default,
    `False` on `InMemoryCredentialStore`) decides it in the base constructor: a shared store built
    without a cipher raises `AKConfigError` naming `identity.credentials.encryption_key`, a
    bring-your-own store included. The in-memory store without a key keeps values as they came and
    logs one warning when it is built.
  - **The cipher** (`CredentialCipher`, `store.py`): `encrypt(plaintext, reference)` and
    `decrypt(sealed, reference)`; a value under another key, under another reference, changed, or
    shorter than a nonce and a tag raises `CredentialError` (`identity/errors.py`, added here
    rather than in iteration 25). `from_config(credentials)` is None without `encryption_key`,
    reads the secret through `SecretManager`, decodes base64url strictly (padding optional) and
    raises `AKConfigError` for a missing secret, a malformed key name, a value that is not base64url
    or one that is not 32 bytes, never quoting the value. The `auth` extra already carries
    `cryptography`; the cipher imports it under `require_extra("auth", ...)`.
  - **Redis and Valkey** write the value and its expiry in one command,
    `_RedisLikeDriver.set_with_expiry(key, value, ttl)` (`SET ... PX`, milliseconds, a non-positive
    `ttl` refused), new on the shared driver beside `rpush_with_expiry`: `set` followed by
    `expire_in` could leave a credential without an expiry. The driver has no store-wide TTL.
  - **DynamoDB** keeps `credential_key`, `value` (binary), `expires_at` (what a read checks, since
    DynamoDB removes an expired item late) and `expiry_time` (`expires_at` rounded up, for
    DynamoDB's own TTL). The driver has no store-wide TTL. A read is strongly consistent
    (`DynamoDBDriver.get(..., consistent=True)`, a parameter new on the shared driver): the process that
    reads a credential is often not the one that wrote it a moment earlier.
  - **The factory** builds the cipher first, then the backend from explicit settings (`url`,
    `prefix`, `table_name`), the registry's shape; a shared type without its block is an
    `AKConfigError` (`identity.credentials.store.<type> must be set ...`), as the registry's is. A
    dotted path is built through `CredentialStore.from_config(store_config, cipher)`, whose default
    passes the cipher alone; a store of your own overrides it to read `model_extra`.
  - **Exports**: `agentkernel.identity` exports `CredentialError`, `CredentialCipher`,
    `CredentialStore`, `CredentialStoreFactory` and `InMemoryCredentialStore` lazily; importing the
    package loads no credential module.
- As built (iteration 25, design refinement 24), exchange, the broker and the manager:
  - **`CredentialManager`** (`credential/manager.py`, not in the outline): the process's store and
    exchangers, built once from `identity.credentials` (`get()` None without the block, `reset()` for
    tests, `from_config`), so a bad store or exchanger fails when it is first built: at the app build for
    the processes that mount routes, at the first credential use in a runner. It owns the lifecycle:
    `retain`, `release` (a run's reference only), `forget` (a `conn:` reference only), `release_for`
    (the classmethod `Runtime` and the runners call; never raises) and `broker(principal, agent_id)`.
    A store that fails on delete is logged by the error's type alone (a client's message can quote its
    connection URL or the reference); the entry expires with its TTL.
  - **Exchange** (`credential/exchange.py`): `IssuedToken` is a frozen model whose `repr` leaves the
    token out. `TokenExchanger(config)` keeps its entry's `audience` and `scopes`; a dotted-path
    exchanger is built with its entry and reads `model_extra`. `PassthroughTokenExchanger(config,
    inbound_ttl)` reads `exp` from the JWT payload without verifying it and reports `min(exp, now +
    inbound_ttl)`. `TokenExchanger.cacheable` (a class attribute, True by default) is False on
    `PassthroughTokenExchanger`: what it issues is the inbound token itself, so caching it would leave a
    second copy that outlives the run's release. `TokenExchangerFactory.create(config, inbound_ttl)` and `create_all(credentials)`
    (by audience; two entries for one audience are an `AKConfigError`).
  - **The broker** takes no cipher (refinement 23). Its order: no store raises "identity.credentials is
    not configured" (or "credentials are unavailable: <type>" when `for_run` could not build the
    manager, so reading `ToolContext.credentials` never raises); then a run without `credential_ref`
    raises "no inbound credential for this run" before the cache is read, so a run started without a
    credential of its own (a scheduled occurrence) does not borrow one another run cached; then the
    exchanger for the audience; then the inbound entry, whose absence raises "no inbound credential for
    this run", so a run whose credential was released (a redelivered message) or expired is served
    nothing; then the cache, read and written only when the exchanger is `cacheable`. Store calls run off
    the loop and a store that cannot be reached is a `CredentialError` too. The cache key is a digest of
    the JSON list `[subject, provider, namespace, agent_id, audience, sorted scopes, sha256 of the inbound
    credential]`, so it names no one and a later credential of the same user is exchanged afresh (both
    from the #1023 review).
  - **`ToolContext.credentials`** is `CredentialBroker.for_run(self.principal, agent.descriptor.id)`.
  - **Exports**: `agentkernel.identity` also exports `CredentialManager`, `CredentialBroker`,
    `TokenExchanger`, `IssuedToken`, `PassthroughTokenExchanger` and `TokenExchangerFactory` lazily.
  - **Release**: `Runtime.run` and `Runtime.stream` call `CredentialManager.release_for` off the loop in
    their `finally`, after the cache is cleared (also for a run the access gate refuses), and
    `AgentRunner.process` in its `finally` for every runner subclass and both branches, reading the
    principal from the body only when it names a `credential_ref`. A queued message delivered again
    after its run started therefore finds its credential gone. The serverless runner's release moves to
    iteration 25b with the AWS adapters.
  - **Topology**: `AgentRunner._validate_credential_store(transport, config)`, called by
    `AgentRunner.run` and `IOHandler._validate_topology`, refuses an `in_memory` credential store on a
    broker transport.

### 6. Registry (`core/registry.py`, `identity/registry/`)

```python
class AgentRegistrationError(Exception): ...
class AgentDescriptorPage(BaseModel): agents: list[AgentDescriptor]; next_cursor: Optional[str]

class AgentRegistry(ABC):
    @abstractmethod def register(self, descriptor: AgentDescriptor, agent: Agent) -> None   # AgentRegistrationError when a different agent
                                                                               # holds the id; the same agent again replaces its descriptor
    @abstractmethod def deregister(self, id: str) -> None
    @abstractmethod def get(self, id: str) -> Optional[Agent]                  # process-local object
    @abstractmethod def descriptor(self, id: str) -> Optional[AgentDescriptor]
    @abstractmethod def agents(self) -> dict[str, Agent]                       # the Runtime.agents() contract
    @abstractmethod def descriptors(self) -> list[AgentDescriptor]             # every known descriptor
    def list(self, cursor: Optional[str] = None, limit: Optional[int] = None, tags: Optional[list[str]] = None) -> AgentDescriptorPage
        # concrete: AgentDescriptorPage.of(self.descriptors(), cursor, limit, tags), the one
        # paging rule: filtered by tags (every tag present), sorted by id, paged with
        # core/util/pagination.py decode_cursor / clamp_limit / paginate / encode_cursor
    def is_empty(self) -> bool     # concrete: not self.descriptors(); a store answers it without a listing
    def clear(self) -> None
```

- `InMemoryAgentRegistry` (`core/registry.py`): two instance dicts, `_agents` and
  `_descriptors`, replacing `Runtime._agents` (`core/runtime.py:144`). Per `Runtime` instance as
  today (`tests/test_module.py:164-179`).
- Store-backed registries (`identity/registry/`) persist descriptors only and keep the local
  `_agents` dict for `get`/`agents()`: `register` upserts `{descriptor JSON, updated_at}`;
  `descriptor(id)` and `descriptors()` read the store, so an io-handler process lists agents it
  does not host. `StoreBackedAgentRegistry` (`identity/registry/base.py`) is their shared body:
  it holds the `_agents` dict and implements `register` (the duplicate check, then the store
  write of a copy stamped with `updated_at`, then the local entry, so an unreachable store leaves
  the agent unregistered), `deregister`, `get` and `agents`; a backend implements `_put`,
  `_remove`, `descriptor` and `descriptors`, and takes its connection settings as constructor
  arguments (`RedisAgentRegistry(url, prefix)`, `DynamoDBAgentRegistry(table_name)`).
  `deregister` removes the store record before the local entry, so a delete the store refused
  can be retried: dropped locally first, `Runtime.deregister` would find no hosted agent on the
  retry, skip the delete, and leave other processes advertising an agent that is gone.
  The duplicate rule is one helper on the ABC, `AgentRegistry._ensure_free(held, id, agent)`,
  which the in-memory registry uses too: only an agent this process hosts under the id is a
  duplicate, so two processes hosting the same agent both register and write the same record
  (design refinement 10). The store holds one record per id, and a `deregister` by either
  process removes it until the other registers again. Redis-like layout `{prefix}agent:{id}`
  plus `{prefix}index:all` set (the `schedule/store/redis_like.py:103-118` shape); the document
  and its index membership are written in one MULTI/EXEC transaction and removed in another
  (`driver.client.pipeline()`, the `rpush_with_expiry` shape), so an interrupted write leaves
  no document a peer resolves and never lists, and a registration by another process lands
  wholly before or wholly after a removal. A transaction is not a rollback: a command that fails
  inside it (`SADD` against an index key of the wrong type) leaves the commands before it
  applied, so a registration over a keyspace something else wrote into fails on every attempt
  and can leave a document behind, which the next registration that succeeds overwrites; no
  server-side check guards against that, the registry prefix being the registry's own.
  `is_empty` checks the index members with `EXISTS` until one has a document, so a member whose
  document was deleted on its own does not make the registry look populated.
  DynamoDB one item per agent, partition key `agent_id`, no sort key, denormalized `updated_at`,
  listing by scan (`schedule/store/dynamodb.py:1-18`) with `ConsistentRead`, since cards and
  tools are built from one listing at mount and an agent an eventually consistent scan missed
  would stay unserved until a restart; `is_empty` is `scan(Limit=1)`.
  Records never expire, and the registry takes no TTL (design refinement 11): nothing registers
  a hosted agent again while its process runs, so an expiry would drop running agents from the
  catalog, A2A, MCP and AG-UI. The store blocks reuse the connection models, which carry a
  `ttl`; a non-zero value there is an `AKConfigError` at load (section 9). Nothing deregisters
  on a normal exit either (`Module.unload` is the one caller), so the record of an agent a
  later deployment renamed or removed, like the one a crashed process left, stays until it is
  deleted from the store by its id. That is the documented boundary.
- `AgentRegistryFactory.build() -> AgentRegistry` (`core/registry.py`), one registry per call, so
  each `Runtime` has its own: `in_memory` when the `registry` block is absent or
  `registry.type == "in_memory"`; `redis`, `valkey`, `dynamodb`
  under `require_extra` with lazy imports from `identity/registry/`; dotted path (built with no
  arguments); else `AKConfigError`. A store type whose connection block is absent is an
  `AKConfigError` naming `registry.<type>`, the schedule store's rule. The config overlay
  `registry.agents.<id>` is applied inside `register` and again on every read (section 6,
  descriptor sources): when any entry sets a field, `build()` returns the backend wrapped in
  `_OverlaidAgentRegistry` (`core/registry.py`), whose `register`, `descriptor` and
  `descriptors` apply the entry (`list` pages over the overlaid descriptors, so a tag the
  overlay sets filters) and whose other methods are the backend's own, so a bring-your-own
  registry gets the overlay without implementing it. With no field set anywhere the backend
  itself is returned. A registry handed to `Runtime(sessions, registry=...)` is used as given,
  without the overlay.
- `AgentRegistryContract` (`identity/registry/testing.py`): duplicate id, upsert on re-register,
  `descriptors()` after `deregister`, `list` paging and tag filtering, a descriptor written by one
  instance read by another over the same fake driver. A subclass overrides the `registry`
  fixture, and a registry over a shared store also the `peer` fixture (a second registry over the
  same store); the shared-store cases (read by another instance, two instances hosting one id, a
  deregistration seen by the other, `clear` leaving the agents only the other instance hosts, a
  record removed by one host returning when the other registers again) are skipped without one.
  The suite also round-trips a whole descriptor (`surfaces=[]`, an `identity`, a skill), because
  a backend that drops an empty list turns "on no surface" into "on every surface", and pins
  `is_empty`. A duplicate is asserted on the exception type alone, not its message. Descriptors
  are compared with `updated_at` left out, since a store stamps it, and the expectation is taken
  before the registry sees the descriptor.

**Descriptor sources, later wins per field:**

1. `Agent.descriptor` (`core/base.py`, a read-only property) is built once, on first read, from
   `_build_descriptor()` (not in `Agent.__init__`: every adapter assigns its native agent and
   attaches the system tools after the base constructor returns, so the first read is
   `Runtime.register`): `id = name`, `name`, `tools = self.get_tool_names()`, `skills` one per
   tool (`id = name = tool name`, `description = self._tool_descriptions().get(name, "")`),
   `runner = runner.name`, `supports_streaming = runner.supports_streaming`, `description =
   self._native_description()`.
   `Agent._native_description() -> str` (base `""`) returns the description the native framework
   keeps for the agent where it defines one apart from the instructions, text written to tell
   other agents and people what the agent does (design refinement 14): OpenAI
   `handoff_description`; the `description` of an ADK, Pydantic AI, MAF or smolagents agent;
   `ClaudeAgentSpec.description`. CrewAI (role, goal and backstory all go into the prompt) and
   LangGraph (a compiled graph carries none) leave the default. An adapter returns the field as
   it is and never falls back to instructions, a system prompt, a goal or a backstory, which is
   what separates it from `get_description()`; the ADK adapter removes the system-tool guidance
   it appends to the native `description` itself (`override_system_prompt`). The base keeps only
   a string, stripped, so a native agent that is a test double seeds nothing.
   `Agent.get_tool_names() -> list[str]` is a new method each adapter implements (section 9 lists
   the source per adapter); the base implementation returns `[]`. It reports the tools
   **declared** on the native agent when it is loaded, under the names the model calls them by,
   with no I/O: tools that only exist at run time (a remote MCP server's, a toolset resolved per
   run, a handoff target's, those of a sub-workflow or sub-graph the adapter does not walk) are
   not reported, and each adapter's docstring names what it leaves out (phase E, which gates on
   these names, revisits the per-adapter gaps listed in the plan).
   `_build_descriptor` also warns, once per class, about an adapter that still defines the
   removed `get_a2a_card`: it loads, and its hand-built card is otherwise silently replaced.
   `Agent._tool_descriptions() -> dict[str, str]` (tool name to the native tool's description;
   base `{}`) is implemented beside it from the same native tools. It is the path a skill's
   description takes now that no adapter builds a card (A2A card, below).
2. `Module.describe(agent, **fields) -> Self` (`core/module.py`, beside `pre_hook`, `post_hook`
   and `run_options`, resolving the wrapped agent through `_wrapped` (`core/module.py:134-145`)):
   `ValueError` for an unloaded agent, for a field `AgentDescriptor` does not declare, for `id`
   (the registry key, and the name every other layer addresses the agent by), for a value the
   model refuses (the merged descriptor is validated, not `model_copy`-ed, because a shared
   registry hands it to other processes), for the fields the adapter, the runner and the registry
   report (`Module._REPORTED_DESCRIPTOR_FIELDS`: `tools`, `runner`, `supports_streaming`,
   `updated_at`; a descriptor claiming its runner streams would open an AG-UI stream that can
   only fail, and a declared tool list would name tools the agent cannot call to whoever writes a
   policy from it; `name` and `skills` stay declarable) and for
   an agent the current runtime does not host; nothing is stored on any of them. It then
   registers the described descriptor (`runtime.registry.register(described, wrapped)`), which is
   how the registry, already holding the descriptor from `load`, receives it, and only once that
   returns does the agent take it (unless the overlay already set one over it). The registry
   first, the agent after: a run that starts while a store is still writing never acts as
   described (an `identity`, say) before any reader can see it, and a registration that raises
   leaves the agent as it was. After such an error the outcome of the write is not known: a store
   can apply a write and still report failure (a reply lost, or a redis transaction whose `SET`
   ran before a later command failed), so it holds the old record or the new one while the agent
   keeps the old. Nothing reconciles them in the background. `describe` raises, which at module
   definition time stops the load; a caller that carries on describes the agent again, and that
   write settles both. An identity or a description the host has not confirmed is never used by
   the host, which is the half that matters.
3. The `registry.agents.<id>` overlay, applied by `AgentRegistryFactory`'s returned registry in
   `register` (`_OverlaidAgentRegistry`, constructed with each entry's set fields: a field left
   out or null in the block is not an override), which also sets the resulting descriptor on the
   agent it was handed (`Agent._set_descriptor`) once the backend has accepted the registration,
   so a refused one leaves the agent as declared. In the hosting process
   `agent.descriptor` and `registry.descriptor(id)` are therefore one record (a store's
   `updated_at` aside) after every registration that returned: Runtime's actor subject (section
   3) sees an overlaid `identity`, and nothing reads a descriptor the overlay has not reached.
   The one exception is a registration that raised over a shared store, whose outcome is
   unknown until the next one (source 2, above).

   The overlay is applied again on every read (`descriptor`, `descriptors`, and so `list`), which
   changes nothing for an agent registered here and is what makes the configuration of a process
   that only serves agents count (design refinement 12). The removed `a2a.agents`, `mcp.agents`
   and `agui.agents` lists were read by the process that mounts the surface; a process over a
   shared store never registers the agents it lists, so applied at `register` alone its own
   `registry.agents.<id>.surfaces` would restrict nothing and say so nowhere. Each process
   therefore serves an agent as its own configuration describes it, and two processes configured
   differently publish different views of one record.

   An overlay key matches the agent with that id, else, when no key matches exactly, the one whose
   id differs only in case: an environment variable arrives lowercased
   (`AK_REGISTRY__AGENTS__Billing__SURFACES` is the key `billing`), and a restriction that reads
   as set must not be dropped for that.

   The merge is per top-level field, with one exception: `identity` is overlaid field by field
   (`{**descriptor.identity, **entry.identity}`). It is the one nested object the overlay
   carries, and replaced as a unit an entry naming only `subject` would drop the `client_id` and
   `client_secret_key` the code declared, against the rule that a field left out keeps its value.

The registry's descriptor is the one record of an agent. The catalog, AG-UI's `/agents`, the A2A
card and MCP's agent tools (section 8.6) are built from `registry.descriptors()`, never from the
adapter, the native agent or `get_description()`.

**Availability** (`core/service.py:49-70`):

```python
@staticmethod
def ensure_agent_available(
    name: Optional[str], principal: Optional[Principal] = None, *, hosted: bool = False, surface: Optional[AgentSurface] = None
) -> None
```

`registry = Runtime.current().registry`; a named agent must have `registry.descriptor(name)`, and
an unnamed request needs the registry not to be empty (`registry.is_empty()`, never a listing).
The agents the process hosts answer first (`registry.get(name)`, `registry.agents()`), so the
store is read only for an agent that is not hosted here and a hosted agent costs no round trip
per request. (`principal` arrives with the gate in phase D; phase C ships `name` and `hosted`,
iteration 17b adds `surface`.)

`surface` is the request's `BaseChatRequest.surface` (iteration 17b, design refinement 13). With
one, an agent is available only when its descriptor exposes it there (`descriptor.exposed_on`):
a named agent kept off the surface raises the unknown agent's `AgentNotFoundError`, hosted or
known only to the registry, and an unnamed request counts only the hosted agents that are on it.
A hosted agent is judged by the descriptor it carries, so the surface costs no store read
either. With no surface the descriptor's `surfaces` are not consulted. One case is left to the
process that runs the agent: an unnamed request in the registry-wide form still asks only
`is_empty()`, whatever the surface, since the default is that process's to pick and reading
every descriptor at an edge to second-guess it would list the store on each request that names
no agent.

`hosted=True` is what a caller that runs the agent in its own process passes: only the agents
hosted here count and the store is never read. Three callers do. `AgentHandler.initialize`
(`core/chat_service.py`), the execution point every surface reaches, so a request for an agent
this process cannot select is refused before a session is loaded or a stream opened, where it
was a 200 stream carrying an error chunk. The direct thread handler
(`AgentThreadRequestHandler._check_agent_available`): such an agent would otherwise pass, have
its user message recorded, and then fail to be selected, where before the registry the request
failed before any thread write. And `ScheduleManager.create` on the `in_memory` transport, where
this process fires the occurrences: a descriptor a removed agent left in a shared registry would
otherwise arm a task every occurrence of which fails. The queue-mode edge handlers, and the
schedule manager on a broker transport, keep the registry-wide form, since another process runs
the agent. For an agent hosted elsewhere the check is a blocking store read, so an `async` caller
over a shared registry runs it off the event loop (`ThreadRequestHandler._record_user_message`
through `asyncio.to_thread`; AG-UI's resolution likewise, section 8.5).

The two failures are different errors (settled 2026-11-18, design refinement 9):

- A request naming an agent it cannot have raises `AgentNotFoundError(name)` (`core/registry.py`,
  exported from `agentkernel.core`), a `LookupError` whose text is `Agent '<name>' not found`,
  which every HTTP route answers with 404 (MCP and the schedule tools keep their own error forms,
  below, the same for an unknown agent as for a hidden one). It is the error, the text and the
  status of an agent the caller may not see (section 7), so a hidden agent cannot be told apart
  from one that does not exist. Left as the 400 it was beside the hidden agent's 404, the status
  alone would have answered whether a name exists. AG-UI already answered 404 with this text.
  The `hosted=True` form raises it as well, for an agent the registry knows from another process:
  to a process that runs agents itself that is an agent it does not have, and a 400 there beside
  the 404 of an unknown name would say the name exists somewhere.
- A request naming no agent while there is none to default to raises `ValueError("No agent
  available")`, a 400 as before: there is no name to hide.

The error is a class of its own and not a bare `LookupError` (settled in iteration 17a) because
of where it is mapped. The presentation wrappers and the thread handlers catch around the whole
run, and `KeyError` and `IndexError` are lookup errors too: the `KeyError` a strict session load
or a thread store raises, or one out of a hook, would have been answered 404 where it is a 500.
A surface maps `AgentNotFoundError` alone.

It landed in iteration 17a, together with the mapping it needs and ahead of the gate (iteration
18), which raises the same error for an agent the caller may not see: wired in before any surface
maps it, a hidden agent would answer 500 (moved from iteration 19 on 2026-11-19).
The mapping, each in its own section: `ChatService`'s two non-streaming presentation wrappers
(8.1), which the queue pipeline's runner and the deployment adapters answer through as well, so
the queued chat route gives the same status and body; the SSE branches of the chat and multipart
routes (8.2), where the streaming wrappers raise before the stream opens; and the thread
handlers, before any write (8.10): the direct handler's JSON and SSE branches and the queue-mode
edge's `_record_user_message`. The schedule routes need none: a task is created by a chat
request, which the chat mapping answers, and `update` cannot change a task's agent, so no
schedule route reaches the check. AG-UI's `_resolve_agent` (8.5) answers 404 with this text from
its own descriptor lookup and does not call the check, so it needs no mapping. The pipeline
precheck (8.3, iteration 19) answers the same 404 and 403 before anything is enqueued, in the
body a queued refusal arrives in, so the edge's answer and the runner's are one; until it landed
a queued request for an unknown agent made the round trip and was answered 404 by the runner,
which still happens where the edge knows no agent at all. The schedule
tools already turn any error into `{"error": ...}` and now carry this text; MCP keeps
`ToolError("Agent not available")`.

Then, when `AccessGate.get()` is not `None` and a name is given:
`gate.authorize_agent(principal or Principal.anonymous(), name)`, which raises `PermissionError`
(no level) or `AgentNotFoundError` (not visible; section 7). As built in iteration 18: the gate
is asked last, after the registry and the surface, with the descriptor the check already
resolved, so an unknown agent, one kept off the surface and one the caller may not see are one
answer and cost one lookup. A caller that passes no principal is asked about as the anonymous
one, which is what `Runtime` would run it as: a caller that forgets the principal refuses, it
does not let through. Every caller in the tree passes the request's principal:
`AgentHandler.initialize(session_id, agent, surface, principal)` through
`ChatService.prepare_agent_handler(..., principal=)` (from `execute*` with `req.principal`, from
the AG-UI handler, the queue runner's AG-UI branch and the realtime pool with theirs), both
thread handlers, and `ScheduleManager.create` with the task's owner. For a request naming no
agent the gate is asked only in the `hosted` form, where the default is known (the first hosted
agent on the surface, `AgentService._default_agent`, which `select` uses too): a default the
principal may not see is `ValueError("No agent available")` and not the 404 that would name an
agent the request never did; one it may see and not use is the `PermissionError`. The default
is not chosen per caller: a principal that cannot use it is refused, although a later agent
might have served it. `select` (`core/service.py:72-101`)
still needs the local `Agent`: for an agent the process does not host it selects nothing, and
the run that follows raises `ValueError("No agent selected...")`. Since iteration 17b it takes
the same `surface` and follows the check's rule, so the two cannot disagree: a named agent kept
off the surface is not selected, and an unnamed request defaults to the first hosted agent that
is on it (the first agent, as before, with no surface). `AgentHandler.initialize` and
`ChatService.prepare_agent_handler` take `surface` and hand it to both; `ChatService.execute*`
pass `req.surface`.

**Catalog** (`api/handler.py:102-103`, `list_agents`): becomes
`GET /api/v1/agents?cursor=&limit=&tags=` returning `{"agents": [descriptor...],
"next_cursor": ...}` where the list is `AccessGate.visible_agents(principal)` narrowed to
`surfaces` containing `"rest"` (or `surfaces is None`), and each descriptor's `tools` is
replaced by `gate.tool_filter(principal, agent).allowed` when the process hosts the agent, else
the stored list filtered by `check_tool` through the authorizer (the io-handler case, Q15). Its
`skills` are narrowed with it: a skill whose `id` is one of the descriptor's tool names stays only
when that tool does, and a skill that names no tool (declared through `Module.describe`) stays;
otherwise a denied tool's name would still be listed, since the skills default to one per tool.
With no gate nothing is filtered by caller; the narrowing to the `rest` surface still applies.
As built (iteration 19): `list_agents(request, cursor, limit, tags)` reads the principal the
identity dependency put on the request (a router mounted with none is the anonymous principal),
and each entry is narrowed by one gate method, `AccessGate.narrow(principal, descriptors)`
(section 7), over the tools the descriptor records. A hosted agent and one another process
hosts are therefore narrowed the same way, by `filter_tools` and not by a full `tool_filter`
(the catalog has no use for the refusal reasons, which cost a question per denied tool), and
only the entries of the page are narrowed, after the cut: which tools an entry shows does not
change which agents the page holds. A principal that sees an agent through its visibility alone
holds no level and is shown no tool.
The narrowing of the listing (surface, and the caller)
happens before the page is cut, by handing the narrowed list to `AgentDescriptorPage.of(
descriptors, cursor, limit, tags)`, so a page is never short because of an agent it may not show;
`tags` is a repeated query parameter and keeps the agents carrying every one. `limit` is clamped
by `clamp_limit(limit, DEFAULT_PAGE_SIZE)`; a malformed cursor is 400, decided before the
registry is read, so the caller's mistake is not answered with the store's failure. The
queue-mode `RequestHandler` mounts the same `list_agents` (`pipeline/request_handler.py:342,
375`). The cursor is the shared offset cursor, so a listing is cut from the registry as it is
when each request arrives: an agent added or removed between two requests can repeat or skip an
entry on the next page.

`rest` in `surfaces` governs this listing and, since iteration 17b, the chat requests that enter
by the REST API as well (design refinement 13, decided 2026-11-19). Until then a chat request
that named an agent kept off `rest` was still served: the three removed lists had no REST
counterpart, so phase C carried nothing over. Such a request now answers like one for an agent
that does not exist, and a request naming no agent defaults to the first agent on `rest`.
The check cannot simply sit in the shared service, which also runs the requests A2A, MCP, the
messaging integrations, the CLI and scheduled occurrences bring, so the request carries the
surface it entered by: `BaseChatRequest.surface`, set by the entry point beside `principal`,
refused from a client, and riding the queued body. `ensure_agent_available(name, ...,
surface=)` and `AgentService.select(..., surface=)` then refuse or skip an agent not exposed on
it (Availability, above). Who sets what:

- `rest`: the chat and multipart routes (`AgentRESTRequestHandler.run`, `run_multipart`), the
  queue-mode chat routes (`RestHandler.enqueue_and_wait`, `RequestHandler.run_chat`, which the
  multipart route goes through), both thread handlers, the WebSocket gateway's chat frames
  (`pipeline/ws/handler.py`), and the deployment entry points that assign the principal: the
  REST Lambda router's `_parse_body`, the Lambda WebSocket frames and the ECS WebSocket API's
  chat route.
- `a2a`, `mcp`, `agui`: the A2A and MCP executors on the body they enqueue, the AG-UI handlers on
  `prepare_agent_handler` (direct) and on the queued `AGUIRunRequest`, whose surface the runner
  hands on. Their routes already serve only the agents on their surface; the body says so too,
  so the process that runs the agent applies that surface and never `rest`. `RestHandler.request`
  enqueues the body as its executor built it.
- the surface of the creating request: the trigger body of a scheduled occurrence (iteration
  19, below).
- none: `IntegrationProducer` (messaging and the realtime edges), the CLI, the schedule tools,
  and the occurrences of a task a schedule tool created. `surfaces` does not govern them.

A task's agent is checked when the task is created, against the surface of the request that
creates it: `ScheduleManager.create(..., surface=)`, which `create_from_request` fills from the
request, so a REST request cannot schedule an agent it could not run. Since iteration 19 the
task keeps that surface (`ScheduledTask.surface`) and the trigger body carries it, so an
occurrence is served the agents the creating request would have been (design refinement 17):
a task naming no agent runs the first agent on that surface, where it ran the firing process's
default whatever its `surfaces`, and a named agent taken off the surface after the task was
created is refused at fire time and the occurrence skipped (8.1). A task created with no surface
(a schedule tool, or a record from before the field) fires with none, in the body it always had.

Where the check runs, as built in iteration 19:

- A queued request is checked twice, by each process against the descriptor it holds (what the
  code declared and its own `registry.agents` overlay): by the process that accepts it, before
  anything is enqueued (8.3), and by the process that runs the agent. An overlay set in either
  narrows what the other declares and neither widens it, on REST as on A2A, MCP and AG-UI.
- The accepting process checks a named agent only, and only when its registry knows some agent.
  A process whose registry is empty (it loads no agent module and shares no registry) has
  nothing to judge a name by, and enqueues as it did before the precheck (design refinement 17).

An entry is `AgentDescriptor.catalog_entry()`, the descriptor without its `identity`, and the
response is `AgentDescriptorPage.catalog()` (added 2026-11-18, before phase C merged). `identity`
says how the agent authenticates itself (its subject, its client id, the name of its secret): the
registry stores it for the process that hosts the agent, and any caller can read the catalog, so
it is left out of what is published and kept in what is stored. The endpoint returns the dict
itself rather than relying on a response model, so no mount of the route can publish the field.
Without an `authorization` block every agent exposed on `rest` is listed to every caller,
whatever its `visibility`; with one the listing is the caller's own (iteration 19, above).

**A2A card** (`core/builder.py:40-74`): `A2ACardBuilder.build(descriptor: AgentDescriptor) ->
AgentCard` replaces `build(name, description, skills)`: `name = descriptor.name`, `description =
descriptor.description` (or the neutral `UNDESCRIBED_AGENT_TEXT`, "The '<id>' agent.", when it is
empty; a skill with no description gets `UNDESCRIBED_SKILL_TEXT` the same way), `version =
descriptor.version` (not `library_version`, line 69),
`supported_interfaces` as today with the URL built from `descriptor.id` (the route segment, and
the name the A2UI labelling check takes), `skills` from `descriptor.skills` (tags defaulted to
`[descriptor.id]`, the agent-name default of lines 90-101), and when
`IdentityProviderFactory.get()` is not `None`: `security_schemes = {"ak": SecurityScheme(
http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))}` for `static` and dotted
providers, or `SecurityScheme(open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
open_id_connect_url=<discovery url>))` for the OIDC family; `security_requirements =
[SecurityRequirement(schemes={"ak": StringList(list=[])})]`, mirrored onto every skill
(`a2a/types/a2a_pb2.pyi:188-277, 305-376` in a2a-sdk 1.2.3). Without identity, neither field is set.
The requirement stays the single one, with no empty alternative (decided 2026-11-19, from the
phase C review), although a call without a credential still runs as the anonymous principal
until an `authorization` block gives that principal no level: a card tells a client how it is
expected to call, and one that follows it always authenticates, where an empty alternative
would advertise credentials as optional to a deployment that configured an identity provider.
The A2A page states what the server does today.

Cards are built by the A2A surface from the registry, not by the adapters (design refinement 8):

- `A2A._build` (`api/a2a/a2a.py:144-160`) iterates `Runtime.current().registry.descriptors()`
  where it iterated `Runtime.current().agents()`, in id order so that every process lists the
  same catalog whatever order its registry answers in, and builds each card with
  `A2ACardBuilder.build(descriptor)`. A card therefore carries the config overlay, and a process
  over a store-backed registry builds cards for agents it does not host, which is what lets the
  io process stop loading every agent's code to serve them (`examples/k8s/openai-queue-mode/
  app_io_handler.py:5-8`). `IOHandler._warn_if_no_agents` (`pipeline/io_handler.py:264-284`)
  accordingly asks the registry (`is_empty()`), where it asked the runtime for hosted agents,
  and warns only when the registry knows none; its advice names both fixes, loading the agent
  modules here or sharing the registry the agent runner registers into. It is a diagnostic and
  never ends the process: when the registry's store cannot be read it says so and returns, and
  the mount that follows raises the store's own error (Error handling, below).
- `Agent.get_a2a_card` is removed: the abstract method on `Agent` (`core/base.py`) and its eight
  implementations, whose one caller was `A2A._build` (line 155). ADK agents get a card the same
  way as the rest, with no adapter code, so the `TODO` (`framework/adk/adk.py:1197-1202`) and the
  "has no A2A card" branch (`api/a2a/a2a.py:156-158`) go. An adapter outside this repository that
  still defines the method keeps an unused one, and `Agent._build_descriptor` logs one warning
  per such class saying nothing calls it and where the card comes from now.
- The description is the declared catalog text and nothing else. Six adapters put the agent's
  instructions or backstory on the card (`openai.py:905`, `crewai.py:523`, `maf.py:798`,
  `smolagents.py:319`, `claude.py:1062`, `pydanticai.py:886`); that source is gone. The
  descriptor's description is what `Module.describe` or the overlay declares, else the native
  description field where the framework keeps one (descriptor sources, above), else empty. A2A 1.0
  requires the field on a card and on each skill, and the pinned SDK leaves an empty string out
  of the served JSON altogether (protobuf drops default-valued fields), so the builder puts a
  neutral sentence naming the agent, or the skill, on the card in its place, as MCP does for an
  agent tool (section 8.6); the catalog entry keeps the empty description, which is the truth.
  `_build` logs one warning per agent it serves that way, naming `Module.describe` and
  `registry.agents.<id>.description`. A card with no skill at all (an agent that reports no
  tool) still serializes without `skills`, as it did before this change.
- Cards are still built once, when the A2A routes are mounted, because the SDK binds the card
  into `DefaultRequestHandler` and `create_agent_card_routes` (`api/a2a/handler.py:64-78`). An
  agent whose descriptor is not in the registry when a process mounts its routes is served by
  that process only after it restarts, whatever the reason it was missing: a first deployment
  whose IO process started before the runner had registered, a newly added agent, or a record
  that was deregistered and registered again. Stored descriptors do not expire, so nothing else
  removes one; it is a documented boundary, not solved here. The same holds for the agents'
  placement: a request is taken by whichever runner reads it from the input queue, with no
  routing by agent, so every runner on a queue has to host every agent the registry lists for
  the IO process, and on the single-process `in_memory` transport an agent the registry only
  knows from another process is listed and cannot be run. Both are documented deployment rules
  (queue mode guide), as they were when the IO process had to load the agents itself.
- When the registry knows agents and none is exposed on `a2a`, `_build` logs one warning naming
  `registry.agents.<id>.surfaces` and `a2a.enabled` (added 2026-11-18): the surface is otherwise
  mounted empty and silent, an empty catalog with every agent route a 404. A registry that knows
  no agent at all stays the host's to report (`IOHandler._warn_if_no_agents`), so the two never
  say the same thing twice.

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

`Decision` and `AuthorizerCapabilities` are frozen models: the class-level `capabilities` is one
object every instance of a backend shares.

**`StaticAuthorizer`** (`authz/static.py`), constructed with `grants`, `tools`, a
`descriptor_lookup: Callable[[], list[AgentDescriptor]]`, an optional `hosted_descriptor:
Callable[[str], AgentDescriptor | None]` and an optional `system_tiers:
Callable[[str], Mapping[str, AccessLevel]]`, its only dependencies, for `tag:` and for tier
defaults. `from_config(authorization_config, descriptor_lookup=None, system_tiers=None,
hosted_descriptor=None)` builds it
from the block's `static` section (`AKConfigError` when the section is missing) and supplies each
lookup that is omitted (below); the constructor reads no configuration and keeps no copy of the
registry:

- `GrantTable` normalizes each grant at construction. An entry is a `_GrantConfig` or the mapping
  one is built from, so the block's own models are taken as they are and a hand-built policy
  (a test, a wrapper) is validated the same way: `subjects` and `agents` coerced from a bare
  string to a one-element list, `level` parsed into `AccessLevel`. An entry that does not
  validate, an unknown subject form, an empty list, an empty agent entry or a bare `tag:` is
  `AKConfigError` naming `authorization.static.grants[<index>]`.
- `SubjectMatcher.matches(form: str, principal) -> bool`: `*` always; `authenticated` when not
  anonymous (messaging senders included, design 5); `provider:<name>` when `principal.provider ==
  name`, or when `name` ends with `:` and `principal.provider.startswith(name)`; `user:<subject>`
  on `principal.subject` unless `principal.is_shared_channel` (design 5: an edge sender's subject
  is a platform id, never matched by a user grant) or the principal is anonymous (its subject is
  the placeholder `anonymous`, which a real user of that name must not share); `group:<name>` on
  `groups`; `role:<name>` on `roles`. `SubjectMatcher.is_valid(form)` is the grammar check the
  table uses.
- Agent entries: an id (matched exactly), `*`, or `tag:<name>` resolved at evaluation time against
  the agent's `tags` (a tag no descriptor carries matches nothing), and only for a principal one
  of whose grants selects by tag: a policy without `tag:` entries never reads the registry.
  - An agent the process hosts answers with the tags of its own descriptor
    (`hosted_descriptor(agent_id)`, no read). Every run is of a hosted agent, so no question a
    run asks reads the registry for a tag (design refinement 19).
  - An agent hosted elsewhere is looked up in `descriptor_lookup()`, a registry listing, which
    over a shared registry is a blocking store read: it runs through `asyncio.to_thread`, at
    most once per question or listing. When a listing reads the registry for one candidate,
    a hosted candidate still answers from its own descriptor.
  - Without a `hosted_descriptor` every agent's tags come from `descriptor_lookup()`.
- `agent_level`: the maximum `level` over grants where any subject matches and any agent entry
  matches `agent_id`; `None` when none.
- `ToolPolicyTable` holds the section's `tools` by agent, each entry a `_ToolPolicyConfig` or the
  mapping one is built from. A second policy for an agent is `AKConfigError` naming
  `authorization.static.tools[<index>]`: which allow-list would apply is not guessed at.
- Tool tier for `(agent_id, tool)`: the `tiers` entry of the agent's tool policy, else the
  tier `system_tiers(agent_id)` gives the name (the tier the `SystemTool` of that name attached to
  that agent declares, asked per agent so an application tool that shares a system tool's name on
  another agent is not tiered by it), else `READ`.
- `check_tool`: `Decision(False, f"Tool '{tool}' is denied for agent '{agent_id}'")` when in
  `deny`; `Decision(False, f"Tool '{tool}' is not in the allow-list of agent '{agent_id}'")` when
  `allow` is set and the tool is absent (an empty `allow` offers nothing); `Decision(False,
  f"Tool '{tool}' requires level {tier}; the current principal has {level or 'none'}")` when
  `agent_level` is `None` or below the tier; else `Decision(True)`. The deny list and the
  allow-list are decided first and without the level, so the reason is the same whoever asks.
- `filter_tools` and `visible_agents` are overridden to resolve the level, the declared tiers and
  the tags once for the whole list, where the base class asks per tool and per candidate.
- With a `static` section that states no grants, every `agent_level` is `None` and one startup
  warning names `authorization.static.grants`. A block of type `static` with no `static` section
  at all never reaches the authorizer: it is refused when the configuration is loaded (Config
  changes).

**`AuthorizerFactory`** (`authz/factory.py`): `create(authorization_config)`; `get()` returns the
process-wide authorizer or `None` without the block; `reset()`. Every backend is built from the
block and nothing else (design refinement 15): a built-in one through its `from_config`, which
reads the section named after it, and a dotted path to an `Authorizer` subclass by handing the
whole block to its constructor, since it owns its policy. What the static backend looks up it
supplies itself, in `StaticAuthorizer.from_config` and not in the factory or the gate:
`descriptor_lookup` defaults to `Runtime.current().registry.descriptors` and `hosted_descriptor`
to the descriptor of `Runtime.current().registry.get(agent_id)`, both resolved when a decision
asks (so the shared authorizer follows a context-managed runtime) and defaulted together: a
caller that hands in its own `descriptor_lookup` and no `hosted_descriptor` is answered from
that lookup alone. `system_tiers` defaults to
`{tool.name: tool.tier for tool in SystemToolFactory.get_all(agent_id)}`, the factory an agent's
system tools are attached from, so it answers for an agent the process does not host as long as
both read the same configuration. Branches, the type matched whatever its case: `static`;
`casbin` (first engine after static, Q11; its `require_extra("casbin", ...)` arrives with the
adapter), `openfga`, `cedar`, `authzen`: each a reserved name that raises
`AKConfigError(f"authorization.type: {name} is not shipped yet; use a dotted path")` until its
adapter lands; a dotted path; else `AKConfigError`.
`agentkernel.identity` exports `Authorizer`, `AuthorizerCapabilities`, `Decision`,
`AuthorizerFactory` and `StaticAuthorizer`, lazily.

**`AccessGate`** (`authz/gate.py`):

```python
class AccessGate:
    @classmethod def get(cls) -> Optional["AccessGate"]        # None without an authorization block
    @classmethod def reset(cls) -> None
    def authorize_agent(self, principal, agent_id) -> AccessLevel      # PermissionError | AgentNotFoundError
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
- `authorize_agent`: `descriptor = registry.descriptor(agent_id)`; `AgentNotFoundError(agent_id)`
  when absent, the error `ensure_agent_available` raises for an unknown agent (section 6): a
  `LookupError` that is not a `KeyError`, which the schedule routes read as a missing schedule;
  `level = agent_level(...)`; when `None`: the same `AgentNotFoundError`, text included, if
  `not visible(principal, descriptor)` (surfaces map it to 404) else
  `PermissionError(f"Principal '{principal.subject}' holds no level on agent '{agent_id}'")`
  (403).
- `visible`: `agent_level is not None`, or `visibility == "public"`, or `"internal"` and the
  principal is not anonymous. `visible_agents`: `authorizer.visible_agents` over the ids of
  `registry.descriptors()`. The base implementation is the candidate walk; the static backend
  resolves its tags once for the whole list, and a backend declaring
  `capabilities.lists_resources` answers natively.
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

As built (iteration 18), where the gate differs from the outline above:

- `authorize_agent(principal, agent_id, descriptor=None)`: a caller that holds the descriptor
  hands it over (`Runtime`, `ensure_agent_available`); otherwise the hosted agent's own answers,
  and only an agent hosted elsewhere reads the registry's store (off the loop in the `async`
  form).
- `visible` has an `async` twin as well, since it asks the authorizer. `visible_agents` is the
  authorizer's listing plus the agents a visibility admits, so it agrees with `visible`.
- `tool_filter(principal, agent, level=None)` takes the level already resolved; a principal with
  no level has no filter and gets the `PermissionError` of `authorize_agent`.
- The synchronous forms work from any context. With no event loop running in the thread they go
  through `run_async_sync`; called from inside a coroutine (`AgentHandler.initialize` under
  `ChatService.execute`) they run the question to completion on a thread of their own with the
  caller's context, and the caller waits. An authorizer may therefore be awaited on more than
  one event loop, and must not bind a connection to the first (stated on `Authorizer`).
- `authorize_session` matches a shared-channel owner on provider and namespace alone, and a
  direct-channel owner on namespace and subject. The outline's rule tried namespace and subject
  first for every owner, which would have let a principal of another provider continue a shared
  session by carrying the same two strings as the sender who opened it.
- `validate_configuration(agents, *, registry_wide=True)`. What depends on a backend's policy is
  asked of the backend through a new hook, `Authorizer.validate(agents, descriptors=None) ->
  list[str]`, a no-op by default: it raises `AKConfigError` for what cannot work for a hosted
  agent and returns the findings worth a warning, which the gate logs once each. The static
  backend implements the three checks named above (the `role:` finding through a `roles_mapped`
  lookup that `from_config` fills from the `identity` block, like its other two lookups). The
  gate itself keeps the one check that is about the agent and not the policy: an agent whose
  `ungated_tool_names()` is not empty is refused, whatever its runner. `Module.load` passes
  `registry_wide=False`, because a module loaded later has not registered yet and a grant
  naming one of its agents would be warned about wrongly; the findings that compare the policy
  with the whole registry are made by the call from `get_router()` (iteration 19). A failed
  validation rolls the load back like a failed registration.

Added in iteration 19:

- `narrow(principal, descriptors) -> list[AgentDescriptor]` (and `narrow_async`): each descriptor
  as the principal is shown it. `tools` keeps what `authorizer.filter_tools` allows of the tools
  the descriptor records, and `skills` follows by the catalog's rule (section 6): a skill whose
  id is one of the agent's tools stays only while the tool does, a skill that names no tool
  stays. A descriptor with no tools costs no question, the order handed in is kept, and the
  registry's records are not changed (copies). The catalog calls it for one page; the A2A card
  of iteration 20 is the same call for one descriptor.
- `validate_configuration` is called with `registry_wide=True` by
  `AgentRESTRequestHandler._validate_access()`, the first statement of the three routers that
  serve the chat and catalog routes (`AgentRESTRequestHandler.get_router`, `RestHandler`'s
  queue-mode router and `RequestHandler.get_router`), with the agents the process hosts. The
  accepting side of a split deployment hosts none and makes only the registry-wide findings. A
  registry that cannot be read then raises its own error and the app is not built, as at the
  A2A and MCP mounts. A process that mounts none of these routers (a bare agent runner) makes
  the per-module checks of `Module.load` only.

Added in iteration 20:

- `visible_agents(principal, descriptors=None)` (and the `async` form): the listing among
  candidates the caller hands in, where it was always among everything the registry knows. A
  surface that serves a fixed set asks about that set: the direct AG-UI handler the agents its
  process hosts, A2A the descriptors its cards were mounted with. The authorizer is still asked
  once, and the registry's store is not listed for it.
- `_validate_access()` moved from `AgentRESTRequestHandler` to the base `RESTRequestHandler`, and
  `AGUIRequestHandler.get_router()` calls it too: an app that serves its agents over AG-UI alone
  mounts no chat router and would never have made the registry-wide check.

**`AuthorizerContract`** (`authz/testing.py`): level resolution across the six subject forms,
highest level wins, `*` and `tag:` agent entries, tier gating, `allow`/`deny` precedence,
anonymous handling, `provider:` prefix matching, and `visible_agents` equivalence with the
candidate walk; `StaticAuthorizer` subclasses it, and every later engine must. The suite states
one policy in the static backend's terms (`GRANTS`, `TOOLS`, over the agents in `DESCRIPTORS`)
and a set of principals, and asserts what each may do; a subclass overrides the `authorizer`
fixture with a backend holding that policy, which an engine loads in its own language. Reason
texts are the static backend's own and are not part of the contract; that a refusal carries one
is.

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
  agent as `AgentRequestAny`. `"surface"` joins it in iteration 17b for the same reason.
- `ChatService.execute*` also pass `req.surface` to `prepare_agent_handler(session_id, agent,
  surface=)`, which `AgentHandler.initialize` hands to the availability check and to `select`
  (iteration 17b; section 6, Availability and Catalog). The queue runner and the AG-UI handlers,
  which prepare the handler themselves, pass the surface the same way.
- Since iteration 18 the same path carries the principal for the access gate:
  `prepare_agent_handler(session_id, agent, surface=None, principal=None)` and
  `AgentHandler.initialize(..., principal=)` hand it to `ensure_agent_available`, and `execute*`
  pass `req.principal`, so a request its principal may not make is refused before a session is
  loaded, a stream opened or a schedule registered after it. The check is synchronous; on the
  `async` paths the gate answers it on a thread of its own (section 7).
- `_record_trigger` (`core/chat_service.py:572-600`) forwards `req.principal` instead of
  `req.user_id`; `_maybe_schedule` is unchanged (the manager reads `req.principal`, section 8.11).
- Presentation wrappers (`core/chat_service.py:690-695, 708-713`): a `PermissionError` branch
  mapping to 403 is added before the `Exception` branch; an `AgentNotFoundError` branch maps to
  404 (that class alone, so a `KeyError` or `IndexError` out of the run stays a 500). The
  streaming wrappers already deliver errors as chunks; `execute_stream` (line 500-506) lets the
  eager `PermissionError`/`AgentNotFoundError` propagate to the route, which maps them the same
  way.
- Scheduled triggers: in `execute*`, when `req.scheduled_task_id` is set and
  `ensure_agent_available` raises `PermissionError` or `AgentNotFoundError`, the service calls
  `ScheduleManager.record_trigger(task_id, principal, request_id, occurred_at, error=str(e))`
  (a new keyword the store records on the occurrence) and returns `(AgentReplyText(response=
  "scheduled task skipped: the owner no longer holds access to the agent"), session_id)` with
  status 403 through `success_status`; one warning names the task. The run never starts.
  As built (iteration 19):
  - `_record_trigger(req)` makes the check itself, before it records, and returns the reply of
    an occurrence that must not run (None otherwise); each `execute*` returns it as it returns a
    deferred request's acknowledgement. The check is the run's own,
    `ensure_agent_available(req.agent, req.principal, hosted=True, surface=req.surface)`, asked
    first so the outcome is on the one record of the occurrence; an occurrence that runs is then
    asked again by `AgentHandler.initialize`, which is one more question for a scheduled run and
    none for any other request.
  - The reply is `SkippedOccurrenceReply`, an `AgentReplyText` whose text is the sentence above
    (`SkippedOccurrenceReply.TEXT`). `success_status` answers 403 for that type, so the status
    follows what the service did and never the text an agent replied with. The body is
    `{"result": <text>, "session_id": ...}`: a reply, not an error body.
  - The streaming paths yield one `StreamChunk(error=<text>, done=True)` and never raise: the
    queue's streaming runner reads the stream inside its consumer, where a raised refusal is a
    failed message, redelivered and recorded once per delivery.
  - The skip does not depend on an `authorization` block. `AgentNotFoundError` is also what a
    removed agent and one taken off the task's surface raise, with no gate at all, and a hidden
    agent is not to be told apart from them: such an occurrence was recorded as fired and
    answered 404, and is now skipped with the reason and answered 403.
  - A task naming no agent while there is none to default to (no agent hosted on the task's
    surface, or a default its owner may not see, section 6) is not a skip: there is no name to
    refuse, the run raises `ValueError("No agent available")` as before and the caller answers
    400. The record carries that reason too, so `last_error` says why an occurrence did not run
    in every case the check decides.
  - It is skipped whether or not it can be recorded: with no `schedule` block in the process
    (the existing warning), or a store that fails, the reply is the same.

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
- As built (iteration 19). `RestHandler._availability_refusal(body)` asks
  `ensure_agent_available(body.agent, body.principal, surface=body.surface)` in the
  registry-wide form, off the event loop, and returns the status and message of the refusal or
  None. `_reject_unavailable(body)` raises it as `HTTPException(status, detail={"error": ...,
  "session_id": ...})`, the detail a queued refusal carries (`_build_sync_response`) and the
  direct route answers with, so the edge's 404 and 403 are the runner's, byte for byte.
  - Where it runs: `RequestHandler.run_chat` after the last refusal that reads no store and
    before `_offload_attachments`, so no file is saved for a refused request and the SSE path
    is covered (it enqueues without `enqueue_and_wait`); `enqueue_and_wait`, now the route
    alone, hands on to `_enqueue_and_wait(body, admitted=False)`, which asks unless its caller
    did (`run_chat` passes `admitted=True`), so the registry is read once for a request.
    `ThreadRequestHandler` overrides `_reject_unavailable` to ask only for a deferred request:
    `_record_user_message` has asked for every other, before its first thread write (8.10).
  - `request` returns a `QueuedReply` with the refusal's status and
    `{"error": ..., "session_id": ...}`, the reply the runner would have stored: this path
    raises no HTTP error and the A2A and MCP executors already read `is_error`. Nothing is
    sent and the response store is not read. How each protocol words the refusal is iteration 20.
  - What is left to the runner: a request naming no agent (the registry-wide form would only
    ask `is_empty()`, and the default is the runner's to pick), and a named agent when this
    process's registry knows no agent at all (`is_empty()`, read only after a not-found). The
    second is what keeps a split deployment working whose accepting process neither loads the
    agent modules nor shares a registry: it enqueued every request before, and would otherwise
    answer every one of them 404 (design refinement 17). A process that knows some agents and
    not the one named answers 404, as its A2A and MCP mounts already leave that agent out.
  - A deferred request (a `schedule` block) is asked the same way, so a task is not enqueued
    for an agent its creator cannot have; one naming no agent is not asked, as
    `ScheduleManager.create` does not check it either.
  - Not covered: the producers that do not go through `RestHandler`. The WebSocket gateway's
    chat frames (`pipeline/ws/handler.py`), the messaging and realtime edges
    (`IntegrationProducer`) and the deployment adapters' own entry points enqueue as before, and
    the runner refuses what their caller cannot have, after the queue trip.
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
  Settled in iteration 23 (design refinement 22): for tools the room runs as all of its
  speakers. The connection keeps the tool filter of every participant who has spoken and
  publishes their intersection (`RealtimeConnection._room_tool_filter`): a tool is offered only
  when every one of them may use it, at the lowest of their levels, and a participant holding no
  level on the agent leaves the room no tool. A participant the authorizer cannot answer for
  (it raises) leaves the room no tool, whoever speaks next, until a later input of theirs is
  answered (review of #1018). The order of speakers changes nothing, so the race
  decides no tool. The principal a tool reads, and the owner recorded, are still the last
  speaker's; whether a participant may speak to the agent at all is still asked only of the
  caller who opened the call.
- `RealtimeConnectionPool.dispatch(body, request_id, user_id, attributes, chat_service)`
  (`pipeline/realtime_pool.py:520-558`): the connection stores `body.principal` on every input
  (`RealtimeConnection.principal`, None when the input named nobody); on first connect
  `chat_service.prepare_agent_handler` (line 550) runs the agent check through
  `ensure_agent_available(body.agent, body.principal)` once the gate exists (iterations 17 to
  20; since iteration 18 the pool passes `principal=body.principal`, so the check is made for
  the first input's caller, and what iteration 20 adds is how a refusal reaches the edge).
  `_execute_tool_and_reply` (`228-252`) wraps `adapter.execute_tool` in
  `Runtime._publish(agent, session, principal)` / `session._unpublish_run()`, so the tool sees
  the participant with the agent as actor and the session's owner is recorded as on a turn; the
  tool filter (`gate.tool_filter(principal, agent)`, `ToolFilter.allows(name)` returning the
  reason string as the tool result when denied) joins the same wrap in iteration 23. Amended at
  the develop merge of #845 (native realtime agents, spec #810, 2026-11-12): the pool no longer
  runs tools, the framework's native session does, so `_execute_tool_and_reply` is gone.
  `dispatch` calls `RealtimeConnection.publish_principal(body.principal)`, which publishes the
  input's principal on the session through `Runtime._publish` on the connection's loop, ahead of
  that input's audio or text (only a changed principal is republished, since every audio chunk
  is an input); a native tool reads it through `ToolContext.principal` or
  `session.get_principal()`, and `close()` unpublishes it. Iteration 23 therefore gates realtime
  tools inside each framework's native session rather than in the pool. Amended in
  iteration 9: the `user_id` parameter stays. It is the `ATTR_USER_ID` WebSocket routing marker
  the output is stamped with (`_emit`, `258-259`), not an identity, so replacing it would break
  the WebSocket edge's delivery; the principal rides beside it, and the callers
  (`pipeline/agent_runner.py:391`, `deployment/aws/containerized/akagentrunner.py:329-331`) keep
  passing the attribute.
- As built (iteration 20), how a refusal reaches the edge. `dispatch` catches the
  `PermissionError` and `AgentNotFoundError` of the agent check made for a new connection
  (`realtime/pool.py`, the file `pipeline/realtime_pool.py` became at the develop merge of #941)
  and calls `_refuse(session_id, request_id, attributes, refusal)`:
  - The edge is sent one terminal error chunk through `send_permanent_failure`, marked realtime
    and addressed by the input's routing attributes: `StreamChunk(error="Realtime session could
    not start: <the refusal>", done=True)`, the wording of a connect that failed.
  - Nothing is raised. Raised, the refusal went back to the queue, was redelivered up to
    `max_receive_count` times and ended as a "failed after N retries" chunk, once for every
    audio frame of the call, since each frame is an input.
  - The session is recorded in `_failures` with the back-off of a failed connect (1 s, 2 s, 4 s
    up to 30 s for each refusal in a row). The frames that follow are dropped without asking the
    gate again, and the caller is asked about at the retry time, so a grant given meanwhile
    opens the call. The end-of-session control forgets the record, as it forgets a failure.
  - A chunk the output queue cannot take is logged and not raised, so the refusal never becomes
    a retry. Any other error of the check (`ValueError("No agent available")`, a store failure)
    is raised as before.
  - It applies without an `authorization` block too: a call naming an agent the runner does not
    host is the same `AgentNotFoundError` and was retried the same way.

#### 8.5 AG-UI (`integration/agui/`)

- `AGUIRequestHandler.__init__()` (`integration/agui/handler.py:26-58`): the `authoriser` and
  `auth_validator` parameters and the `AuthValidatorAuthoriser` wrap (41-47) go; the
  `AuthorisedRESTRequestHandler` identity requirement (8.2) replaces the "never served
  anonymously" check with the same guarantee. `_is_exposed` (60-68) reads
  `descriptor.exposed_on("agui")` through the registry; the `agui.default_agent` validation
  (53-58) becomes "exposed on agui".
  The default agent must be served by the handler when it is built, so the agents are loaded
  (or, for the queue-mode handler, a shared registry holds them) before it is constructed.
- Which agents a handler serves is one class attribute, `serves_hosted_agents_only` (decided
  2026-11-19, from the phase C review). The direct `AGUIRequestHandler` runs agents in its own
  process and sets it: it lists, resolves and accepts as `default_agent` only the agents that
  process hosts, reading each descriptor from the hosted agent. `AGUIPipelineRequestHandler`
  enqueues the run for the process that hosts the agent and clears it: everything the registry
  knows is served. Before this the direct handler listed and resolved agents another process
  hosts and then answered every run for one with a "could not be selected" 500; an agent it
  cannot run is now a 404, the answer for any name it does not serve. `_descriptor(name)` and
  `_descriptors()` are the two reads both handlers share.
- `/agents` (140-152): `AccessGate.visible_agents(principal)` narrowed by `exposed_on("agui")` and
  the descriptor's `supports_streaming`; ids only, in id order. Without a gate the source is
  `_descriptors()`: the hosted agents for the direct handler, `registry.descriptors()` for the
  queue-mode one, so there agents another process hosts are listed.
- `_resolve_agent` (103-127): 404 for unknown or hidden, 403 for a visible agent the principal
  holds no level on (`PermissionError` from the gate, phase D), 400 for a non-streaming
  runner, unchanged order. It returns the agent's `AgentDescriptor`, not the `Agent`: everything
  it checks (existence, surfaces, `supports_streaming`, the `runner` name its 400 cites) is on
  the descriptor, so the queue-mode handler resolves and enqueues, by `descriptor.id`, an agent
  its process does not host. The descriptor is read once: the hosted agent's own
  (`registry.get(name).descriptor`, the record it registered, overlay included) and otherwise
  `registry.descriptor(name)`, which is a blocking store read on a shared registry, so
  `_resolve_run_inputs` runs the resolution through `asyncio.to_thread`. It does not call
  `ensure_agent_available`, whose existence check the one read subsumes; the gate, when it
  lands, is asked here with `AccessGate.authorize_agent` rather than through a second registry
  read (iteration 20). Since iteration 18 the handler hands the caller's principal to
  `prepare_agent_handler`, so the pre-run check decides for the caller and not for nobody; until
  the handler's own check lands, a run the gate refuses there is an unmapped error (a 500).
  The direct handler never reads the store here: an agent it does not host is not
  served (above), so its `_descriptor` returns `None` and the route answers 404. The "could not
  be selected" 500 stays as the guard for a resolved agent whose session cannot be created.
- As built (iteration 20). `_resolve_agent(agent_name, principal)` asks
  `gate.authorize_agent(principal, descriptor.id, descriptor=descriptor)` with the one
  descriptor it read, after the surface check and before the streaming check: the 400 names the
  agent's framework, which is not for a caller who may not see the agent. A hidden agent raises
  the very `HTTPException` an unknown one does (one status, one detail), and a visible agent the
  caller holds no level on is a 403 with the gate's reason. `_resolve_run_inputs` hands it the
  caller's principal; it runs on a worker thread, where the gate's synchronous form applies.
  Both handlers inherit it, so the queue-mode edge refuses before it enqueues.
  `/agents` asks `gate.visible_agents(principal, self._descriptors())`: among what the handler
  serves, so the direct handler does not list the registry's store for it (section 7).
  The bare route (`agui.default_agent`) answers a 404 from the run with a bare 404, the answer
  of the route when no default is configured: the caller named no agent, so a default it cannot
  have is not named to it (the rule of section 6 for a request naming no agent).
  `get_router()` validates the policy at mount (section 7).
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
- The agent tools are registered from the registry, not from the agents the process hosts
  (design refinement 8): `_build` iterates `Runtime.current().registry.descriptors()` in id order
  where it iterated `Runtime.current().agents()` (144), with `name = descriptor.id` and
  `description = descriptor.description`, where the tool text was `agent.get_description()`, the
  agent's instructions (154). A process over a store-backed registry therefore exposes agents it
  does not host, as it serves their A2A cards. A description is always passed, because FastMCP
  publishes the executor's own docstring when given none: an agent whose descriptor carries none
  (none declared, and no native description field to seed it) gets `MCP.UNDESCRIBED_TOOL_TEXT`
  ("Sends a prompt to the '<id>' agent and returns its reply."), which says what the call does and
  nothing about the agent, and `_build` logs one warning naming
  `Module.describe` and `registry.agents.<id>.description`, since a client chooses a tool by
  that text. Unlike a card's description this one is not left empty: it describes the tool, and
  an empty one leaves a client nothing to choose by. Tools are registered once, at build, so an
  agent registered later is exposed after a restart (the A2A boundary, section 6). With
  `expose_agents` on, agents known and none exposed on `mcp`, `_build` logs one warning naming
  `registry.agents.<id>.surfaces` and `mcp.expose_agents`, as A2A does (section 6).
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
  BaseRunRequest(prompt, agent, session_id, principal=principal)`; a `PermissionError`/`AgentNotFoundError` from `RestHandler.request`'s precheck
  becomes `ToolError("Agent not available")`.
- As built (iteration 20, FastMCP 3.4.11). Every agent tool is registered with
  `auth=MCP._visible_to_the_caller(descriptor)`, an `async` `AuthCheck` that reads the request's
  token (`AuthContext.token`, through `AKAccessToken.principal_of`) and answers
  `gate.visible_async(principal, descriptor)`, with the descriptor the tool was registered with
  (`exposed_on("mcp")` already decided whether it was registered at all). The gate is read at
  each request, not at build, and without one the check admits everyone. FastMCP leaves a tool
  whose check fails out of `tools/list` and answers a call to it `Unknown tool`, its answer for
  a name it does not know, so a hidden agent is not told apart from an unknown one. A check that
  raises is FastMCP's denial: an authorizer that cannot answer hides the tool. FastMCP skips
  component checks on the stdio transport, which Agent Kernel does not serve.
  Visibility lists a tool, a level runs it: a call to an agent the caller sees and holds no
  level on reaches the executor, whose precheck refuses it before the queue. Since iteration 19
  that refusal is a reply (`QueuedReply` 403 or 404), not an exception, so the executor maps the
  status: `Executor.REFUSED_STATUSES` raise `ToolError(Executor.UNAVAILABLE_MESSAGE)` ("Agent
  not available"), whichever process refused and for whichever reason, and the reason goes to
  the log. A failed run keeps "The agent could not process the request".

#### 8.7 A2A (`api/a2a/`)

- `A2ARESTRequestHandler.get_agent_routers()` (`api/a2a/handler.py:49-63`): `create_rest_routes(
  request_handler, context_builder=AKCallContextBuilder())` (`a2a/server/routes/rest_routes.py:30-35`),
  where `AKCallContextBuilder(DefaultServerCallContextBuilder)` (`a2a/server/routes/common.py:99`)
  calls the SDK's `build(request)`, keeping its state (headers, the auth scope), and adds
  `state["principal"] = request.state.principal`. The executor
  (`api/a2a/a2a.py:68-90`) reads `context.call_context.state["principal"]`, falling back to
  `RequestAuthenticator.current()` and then to anonymous, and sets it on the body (line 76).
- `_build()` (129-146): the `a2a.agents` line (137) is deleted; one card is built, with
  `A2ACardBuilder.build(descriptor)`, for every descriptor in `Runtime.current().registry` that is
  `exposed_on("a2a")` (section 6, A2A card), and the cards, executors and `/a2a/{id}` routers are
  keyed by `descriptor.id`. The process need not host the agent: the executor only enqueues, and
  availability resolves through the registry (section 6).
- `get_cards()` becomes `get_cards(principal)` filtered by `AccessGate.visible`; the catalog
  route (36-46) and the well-known card route take the request's principal; a hidden agent's card
  is 404 (the A2A 1.0 rule).
- A served card's `skills` are narrowed to the caller by the catalog's rule (section 6): a skill
  backed by a tool the caller's level does not allow is left out of a copy of the mounted card;
  with no gate the card is served as built. Because a card then varies by caller, the catalog and
  well-known card responses carry `Vary: Authorization`, and an ETag is computed over the card as
  served. Authenticated extended cards stay a non-goal (design, Non-goals).
- As built (iteration 20, a2a-sdk 1.2.3). `A2A` keeps the descriptor each card was built from
  (`A2A._descriptors`) and decides from it, so no request reads the registry for a card or a
  guard; like the cards, the descriptors are those of mount time. The two are one record:
  `A2A.reset()` (for tests) drops them together with the executors and the client, since a
  descriptor left without its card would be listed to a caller with no card to show.
  - `A2A.get_cards(principal=None)`: without a gate every mounted card; with one,
    `gate.visible_agents(principal, mounted descriptors)` then `gate.narrow`, one question for
    the listing. A missing principal is the anonymous one. `A2A.card_for(principal, name)`
    (`async`) is one card as a caller is served it, or None for an agent it may not see, and
    for a card with no descriptor to decide by, which is served to nobody.
    A narrowed card is a copy of the mounted one without the skills the caller is not offered
    (`_card_as_shown`); a caller offered every skill gets the mounted card itself.
  - The catalog route reads the request's principal and, with a gate, marks the response
    `Vary: Authorization` (added to what it already varies by; the app's CORS middleware adds
    `Origin`).
  - The well-known card route is the SDK's, built with a `card_modifier` (the SDK's hook for a
    per-request card), so the SDK's own `ETag` and `If-None-Match` handling are over the card
    as served and two callers offered different skills never share a tag. The modifier is
    handed the card and not the request, so the endpoint is wrapped: the wrapper puts the
    caller in a context variable for the modifier and marks the answer (a 304 included)
    `Vary: Authorization`. The modifier is the one place the card is decided, once for a
    request: it serves `card_for`'s card, and raises the bare 404 when there is none for the
    caller. Without a gate the wrapper is the SDK's endpoint, untouched.
  - The protocol routes (`message:send`, the task and push-notification routes, the extended
    card) each carry a dependency, `_usable_by_the_caller(agent)`, which asks
    `gate.authorize_agent_async(principal, agent, descriptor=<mounted>)` before the SDK parses
    anything: a hidden agent is `HTTPException(404)` with no detail of its own, byte for byte
    the answer of a path that is not mounted, and a visible agent the caller holds no level on
    is `HTTPException(403, detail=<the gate's reason>)`. The a2a-sdk has no permission error
    (its REST errors map to 400, 404 and 500), so the 403 is made in front of it, in the shape
    of the identity dependency's 401. The card needs only visibility; the other routes need a
    level, the task routes too, since reading a task is using the agent.
  - The executor still answers a refusal that reaches it as `InternalError`: with the guard in
    front, that is a runner whose policy or registry disagrees with this process's.
  - What the router itself answered, closed on 2026-11-25 (design refinement 18). The routes
    are mounted per agent, so three answers were made before any check of ours ran, and each
    told a mounted name from one that is not, hidden or not. A method the route does not serve
    was a 405 with an `Allow` header where an unmounted name is a 404, for every caller,
    credential or none. A credential the provider refuses was a 401 from the identity
    dependency, where an unmounted name has no route to refuse it and is a 404. And a trailing
    slash on a route's path was a redirect only a mounted name got. The first account of this
    point (iteration 20) named only the 401 and said a caller with no credential, or a valid
    one, could not tell.
    `get_agent_routers()` now returns one more router after the agents' own, holding one route,
    `UnservedA2ARoute` at `/a2a/{agent_name}/{rest:path}`: every request under a name that no
    A2A route served falls through to it and is answered `HTTPException(404)`, the answer of a
    path that is not mounted. It is an ordinary route, so the identity dependency runs first and
    a refused credential is a 401 for every name. Its `matches` claims the request whatever the
    method (a route that matched the path and not the method is the router's second choice, and
    an agent's own route that matched the same way would be preferred, with its own 405), so a
    method outside its list, one that is no HTTP method, is this route's 405, the same for every
    name. It stands aside (`Match.NONE`) without an `authorization` block, so a deployment
    without one keeps the router's answers, and for a path with nothing after the name, so the
    catalog's trailing-slash redirect is untouched.
    What it costs, with the block only: a wrong method on a real A2A route is a 404 and no
    longer a 405 naming the method to use, for an agent the caller may use as for any other. A
    route that named no method at all would have been simpler and was not possible: FastAPI
    0.141 builds a route's operation id from its first method and asserts there is one.

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
  query string can carry the function key (`?code=`). As built (iteration 27): `develop` removed
  Azure Functions support, `AzureFunctions.handler` with it (#984, 2026-11-19), so this handler
  and its cases are gone and the identity page no longer documents it.

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
  `_record_user_message` (304-306) beside the `ValueError` 400, and `AgentNotFoundError` to 404
  there and in the direct handler's two SSE branches (iteration 17a; section 6); both run
  `ChatService.reject_unprocessable` before the recorder's first write, so a `user_id` extra is a
  400 with no thread written; an anonymous principal on the chat routes is 401 (8.2): the chat
  routes assign `body.principal` from the composed read handler's `_resolve_user(request)`, so
  the 401 fires before any validation or write (iteration 10). On the same line they assign
  `body.surface = "rest"`, and both prechecks pass it (`_check_agent_available(name, surface)`,
  and `ensure_agent_available(body.agent, surface=body.surface)` at the queue-mode edge), so an
  agent kept off `rest` is refused before the thread is opened (iteration 17b; section 6,
  Catalog). Both prechecks also hand over `body.principal` (iteration 18), so with an
  `authorization` block the gate's 403 and 404 come before any thread write too. The pipeline
  handler the queue-mode one extends asks the same question before it enqueues (iteration 19,
  8.3); `ThreadRequestHandler` overrides `_reject_unavailable` to ask there only for a deferred
  request, which records nothing and was not asked about, so a recorded request reads the
  registry once.
  `ThreadRESTRequestHandler`
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
  `create_from_request` (95-111) passes `req.principal or Principal.anonymous()`. Since
  iteration 17b `create` also takes `surface` (`create_from_request` passes `req.surface`) and
  hands it to the named agent's availability check; a schedule tool passes none. Since
  iteration 19 the task keeps it (`ScheduledTask.surface`, None for a tool's task and for a
  record from before the field) and `_build_trigger_body` adds `"surface"` when the task has
  one, so the body of a task with none is unchanged (section 6, Catalog). The same check is
  handed the owner (iteration 18), so with an `authorization` block a task is not created for
  an agent its owner may not use; the fire-time re-check and skip are iteration 19 (8.1).
- `_build_trigger_body` (469-490): `"user_id"` is replaced by `"principal": task.principal`
  (`None` only on a task created before the change, whose frozen body also still carries
  `user_id` and is therefore refused at fire time; such tasks are recreated, not migrated, and
  `update` refuses them with `ValueError` before re-freezing the body, while `cancel` is allowed).
- `record_trigger(task_id, principal, request_id, occurred_at, error=None)` (267-294) and
  `_owns_occurrence` (296-316) compare the stored `task.principal`'s namespace and subject with
  the principal's (an anonymous principal is a mismatch; a task without a stored principal falls
  back to `task.user_id` against the subject); `error` is recorded on the occurrence by the
  store's `record_trigger` (a new optional column `last_error`). As built (iteration 19):
  `ScheduledTask.last_error` describes the most recent occurrence, as `last_request_id` does,
  so `apply_trigger(..., error=None)` sets it on every occurrence and one that runs clears it.
  A skipped occurrence is otherwise recorded like any other: counted, and the last of a
  one-time task. The three stores hand `error` to `apply_trigger`; the documents they store are
  the task as JSON, so no table or key layout changes. `ScheduleStore.record_trigger` gains
  `error: str | None = None`, and the manager passes the keyword only when there is a reason,
  so a bring-your-own store written against the old signature keeps recording every occurrence
  that runs (a skipped one fails to record there, which is logged and never raised). A forged
  trigger records no reason, as it records nothing.
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
- As built (iteration 21): the one question every hook asks is a third method,
  `ToolGate.refusal(name, session=None) -> str | None` (the reason, or `None` when the run is
  not gated or the tool is allowed). It never raises: a failure in reading or asking the filter
  refuses the tool with `tool gate failed: <type>` (Error handling). `current()` with no session
  and no `ToolContext` is `None`: a native hook that fires outside a run gates nothing.
- A filter is over the tools the agent declares, and `allows(name)` is false for a name it never
  listed. So a gate refuses an undeclared tool wherever it sees one, and what an adapter
  declares has to be what its gate matches (design refinement 20).

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
| Realtime (`core/realtime/runner.py:124`, both OpenAI and ADK realtime runners) | the agent's `get_tool_names` | none (declared at connect) | inside each framework's native session, which runs its own tools since #845 (8.4); the pool's `_execute_tool_and_reply` no longer exists | n/a |

- As built (iteration 21), where the four adapters differ from the table (design refinement 20):
  - **OpenAI.** The gate is put on the tools only when an `authorization` block is configured
    (`OpenAIAgent._gate_tools`, at wrap and again in `attach_tool`), so without the block no
    native tool object changes. `OpenAIToolGate.install` is idempotent (a tool that carries
    the `ak_tool_gate` guardrail is left alone) and puts that guardrail first.
    `OpenAIToolGate.reachable(root)` walks the agents a run can call the tools of: the ones
    it hands off to (an `Agent` in `handoffs`, or a `handoff(agent)` object through its
    `_agent_ref`) and the ones it uses as tools (`FunctionTool._agent_instance`), each once.
    `get_tool_names` declares their tools after the agent's own and the gate is put on them
    too, because the run's filter stays the first agent's. `ungated_tool_names` names what
    can be neither declared nor gated, on any reachable agent: an `mcp_servers` entry and a
    handoff that does not hold its agent (a `Handoff` built by hand, a `realtime_handoff`).
  - **Pydantic AI.** Call time is `wrap_tool_execute`, which returns the reason as the call's
    result without running the handler; `ModelRetry` asked the model to try again and spent
    the tool's retry budget. `get_tool_names` reports the name each toolset serves a tool
    under (`_served_tools`: `<prefix>_<name>` through a `PrefixedToolset`, the new name
    through a `RenamedToolset`, unchanged through any other wrapper). The capability is added
    by `PydanticAIRunner._gated` at all four native calls. On a resume, an approval of a tool
    the filter denies by then is handed to the SDK as `ToolDenied(reason)`
    (`_deferred_results`): left as an approval, the call finds its tool gone from the step and
    the run fails on the tool's retry limit.
  - **MAF.** As the table has it, added in `_prepare_session` only for a gated run. The
    middleware sees every function the loop calls, so the functions of an MCP tool, which the
    agent declares under the tool's own name only, are refused. Not seen: the calls a nested
    agent makes inside a tool.
  - **Claude.** As the table has it. In addition a denied tool the application approved by
    name in its own `allowed_tools` is dropped from the run's list, a tool is added to
    `disallowed_tools` once, and the hook is installed for a refusal alone (an agent with no
    approval tool had none). `_native_options` takes the run's `session`.
- As built (iteration 22), where the two callback-driven adapters differ from the table (design
  refinement 21):
  - **ADK.** `GoogleADKToolGate.before_tool` is the callback, put first on every agent a run
    can reach (`GoogleADKToolGate.install`, from `GoogleADKAgent.__init__`) and only when an
    `authorization` block is configured. `GoogleADKToolGate.agents(root)` is the one walk the
    gate and `get_tool_names` share: the root, the agents it uses as tools (`AgentTool.agent`),
    the nodes of a workflow, one nested in another included, and each level of `sub_agents`.
    A workflow keeps copies of the agents it is given, so the gate is on the copies. The
    callback leaves ADK's own two tools alone (`TransferToAgentTool`,
    `SetModelResponseTool`): no filter lists them and a run could not move without them. A
    call whose state names no Agent Kernel tool context is not gated; one whose context can
    no longer be fetched is refused (`tool gate failed: <type>`). `get_tool_names` reports a
    bare callable under the name of the `FunctionTool` ADK wraps it in (a callable object by
    its class, a `functools.partial` by the function it wraps in google-adk 2.13, `partial` in
    2.8). ADK's live flow calls the same callbacks
    (`flows/llm_flows/functions.py`), so the realtime runner needs no gate of its own once a
    filter is published for a call (iteration 23).
  - **CrewAI.** `CrewAIToolGate` registers two hooks, once for the process, from
    `CrewAIModule.load` and only when the block is configured. `before_tool_call` returns
    `False` for a refused call. `after_tool_call` returns the reason for the same call:
    CrewAI runs its after hooks for a blocked call too, and a string they return replaces its
    own `Tool execution blocked by hook` line, so the model reads the reason. A hook is given
    the sanitized name CrewAI serves a tool under, and the call is matched to the declared
    name that sanitizes to it. The hooks never raise (CrewAI lets a call through when a hook
    fails): a failure refuses the call. The delegation tools CrewAI adds (`BaseAgentTool`)
    are left alone, and `get_tool_names` declares the tools of the coworkers when the agent
    may delegate, since a delegated call runs under the first agent's filter.
- As built (iteration 23), the wrap-time adapters and realtime (design refinement 22):
  - **LangGraph.** As the table has it, with `LangGraphToolGate`: `LangGraphToolBuilder.bind` wraps
    each function (`functools.wraps`, so the argument schema is the function's) and marks the tool
    `metadata={"ak_gated": True}`; the wrapper reads the tool's name when a call is checked, so a
    tool renamed after binding is asked about under its served name. `get_tool_names` and
    `ungated_tool_names` walk the tool nodes of the graph and of every compiled subgraph
    (`get_subgraphs(recurse=True)`), which closes the subgraph gap. The wrapper is always present
    (it is the builder's own tool, not an object the application made). A tool that paused on
    `interrupt()` is asked about again on resume, because LangGraph runs the node again.
    `ToolNode` also takes a per-call `wrap_tool_call`, but only as a constructor argument kept in
    a private attribute, so gating native tools that way would mean changing a compiled graph's
    private state; Q12's refusal stands.
  - **smolagents.** `SmolagentsToolGate` wraps `forward` on the instance of every tool a run can
    call (marked `__ak_gated__`), only when the block is configured, at wrap and in `attach_tool`.
    `agents(root)` adds the managed agents, whose tools are declared under the manager and
    gated. `final_answer` is neither declared nor gated, and calling a managed agent is not gated
    (both are how a run moves or ends). A code agent whose executor is not the
    `LocalPythonExecutor` is not wrapped and all its tools are ungated: a remote executor rebuilds
    each tool from its source in the sandbox.
  - **Realtime.** No pool-side check: the gates on the native agents are what the native
    sessions call (ADK's live flow runs `before_tool_callback`; OpenAI's realtime session asks
    `is_enabled` on every call). What was missing is a filter, so `publish_principal` now
    publishes the room's (section 8.4). OpenAI's realtime session runs no input guardrail for an
    ordinary call, so a denied tool there answers `Tool <name> not found`, not the reason.
  - **Provider-run tools** (design Q12's warning). `Agent.provider_tool_names()` (base `[]`): an
    OpenAI agent's non-function tools, an ADK agent's tools with no function declaration
    (`google_search`, `url_context`), a Claude agent's Claude Code built-ins (all of them unless
    `options.tools` is a list) and its other MCP servers. `validate_configuration` logs them once
    per agent and does not refuse.
- As built (review of #1018), where the review changed what iterations 21 to 23 shipped:
  - **OpenAI, tools the SDK runs in the process.** A local `ShellTool` (no `environment`, or
    `{"type": "local"}`), `LocalShellTool`, `ApplyPatchTool`, `ComputerTool` and `CustomTool` run
    the application's code here, and the SDK asks no `is_enabled` and runs no input guardrail for
    them. They are named by `ungated_tool_names`, so the agent does not load under the block.
    `OpenAIToolGate.provider_run(tool)` decides what is the provider's: the hosted types
    (`WebSearchTool`, `FileSearchTool`, `CodeInterpreterTool`, `ImageGenerationTool`,
    `HostedMCPTool`, `ToolSearchTool`, `ProgrammaticToolCallingTool`) and a `ShellTool` whose
    environment is one of `HOSTED_ENVIRONMENTS` (`container_auto`, `container_reference`);
    `provider_tool_names` reports only those. Both are lists of what is known to be hosted, so a tool
    type or a shell environment a later SDK adds is ungated until it is classified, and
    `test_every_tool_type_the_sdk_defines_is_classified` fails on the upgrade that adds one. A tool
    with no `name` is declared and refused under the name of its type (`OpenAIToolGate.tool_name`),
    so the load fails with the refusal rather than an `AttributeError`.
  - **MAF, list time and placement.** The table's per-run middleware is replaced by two middleware
    the adapter puts first on the native agent at wrap time, only under the block
    (`MAFAgent._gate_tools`): `AKToolGateMiddleware` (function, call time, as the table has it) and
    `AKToolOfferMiddleware` (chat, list time), which hands each model request a copy of the options
    without the tools the filter refuses. On the agent, the gate runs ahead of the agent's own
    function middleware, so a cache or audit middleware never sees a refused call; per run it ran
    behind them. Hiding the tool also keeps a denied `approval_mode="always_require"` tool from
    pausing the run, since MAF asks for the approval before any function middleware runs. The
    function loop keeps the full tool list, so a call to a hidden tool is still answered with the
    reason; one to a hidden approval tool is still put to a person first and refused on resume.
    `_prepare_session` passes no middleware of its own any more, so the native call is keyword for
    keyword the same with and without the block.
  - **ADK.** ADK 2.8's task mode adds `FinishTaskTool` to an agent's tools; it joins
    `TransferToAgentTool` and `SetModelResponseTool` in `GoogleADKToolGate.OWN_TOOLS` (imported
    only where the SDK has it), so it is neither gated nor declared.
  - **CrewAI.** The before hook is put first in CrewAI's global list, so an application's before
    hook never sees a refused call; the after hook is still last, so its reason is the line the
    model reads. A call is decided by the declared name of the tool CrewAI is running
    (`context.tool.name`), not by matching the sanitized name it serves the tool under: two tools
    whose names sanitize alike (`Refund Order`, `refund_order`) are each decided by their own.
    Without a tool on the context, the sanitized match is the fallback, and a name more than one
    declared tool sanitizes to is refused as ambiguous.
  - **LangGraph.** `ungated_tool_names` asks of every tool instance in every tool node, so a native
    tool that shares its name with a bound one in another node is still named.
  - **smolagents, code agents.** The local executor runs the model's code in a worker thread under
    a timeout (`local_python_executor.timeout`), which does not carry context variables, so the
    gate inside a tool saw no `ToolContext` and let every call through. `SmolagentsToolGate`
    replaces that `timeout` once for the process, under the block, with one that runs the code in
    a copy of the caller's context.
  - **Realtime, a filter that cannot be decided.** When the authorizer raises for a participant
    (anything but the `PermissionError` of no level), the participant is kept as unanswered
    (`RealtimeConnection._unanswered`, with the reason `tool gate failed: <type>`) and the room is
    offered no tool while any participant is unanswered, whoever speaks next; a warning is logged.
    The speaker's input is not counted as published while they are unanswered, so their next input
    asks the authorizer again once `RealtimeConnection.RETRY_PAUSE_SECONDS` (1 s) have passed since
    the last attempt, and a decision it gives replaces the unanswered entry. The pause exists because
    every audio chunk is an input: without it an authorizer that is down would be asked on each one. Any other
    failure in deciding the room's filter publishes a filter that allows no tool, with the same
    reason, and is retried on the next input. Raising would have handed the input back to the pool's
    queue to be retried, every audio chunk of it.
- Composition rule everywhere: AK's check runs first; a user-set hook, callback, middleware,
  capability or `is_enabled` value is preserved and runs after (OpenAI `is_enabled` is an AND of
  both; ADK and MAF lists are AK-first; CrewAI's before hook goes first in its global list).
- The reason string is `ToolFilter.reason(name)`, for example
  `"Tool 'apply_manifest' requires level write; the current principal has read"`.
- Traced runner subclasses (`trace/*/<framework>.py`) call `super().run(...)` and need no change;
  the MAF middleware is on the native agent, which the traced runner runs.
- System-prompt text about system tools stays composed per agent at load time
  (`core/tool.py:256-276`); it is not filtered per run (documented limitation, design section 7).

### Consumer changes

| Consumer | Deleted | Changed | Verified unchanged |
|---|---|---|---|
| `auth/` package, `auth.py` shadow module | both, whole | | |
| `core/model.py` | `BaseChatRequest.user_id` (427); `from_payload` user_id handling (497, 503, 505, 513-516) | `BaseChatRequest.principal` and `surface`; `ChatRunRequest.INTERNAL_FIELDS` gains `surface`; `SystemTool.tier`; new models (section 2) | every other request and reply model; `BaseRunRequest.extra="allow"` |
| `core/runtime.py` | `ACTING_USER_CACHE_KEY` (40); `acting_user_id` (378, 433); `_agents` dict (144) | `run`/`stream` signatures and sequence; `_validate_resume` eighth check; `register`/`deregister`/`agents` delegate | system hook lists; `_prepare_requests`; `StreamBoundaryTracker` |
| `core/base.py` | abstract `Agent.get_a2a_card` | `Keys.OWNER`; accessors; `Agent.descriptor`, `get_tool_names`, `ungated_tool_names` (default `[]`), `_tool_descriptions` (default `{}`) | framework-context accessors; run options; `_attach_system_tools` |
| `core/tool.py` | | `ToolContext.principal/access_level/credentials` | `SystemToolFactory.get_all`, `_agent_allowed` |
| `core/util/key_value_cache.py` | | reserved prefix | `get/has/keys/items` |
| `core/paused_run.py` | the "accepted risk" note (24-26) | subject/provider/namespace on `PausedRun`; reserved writes | accessors' contract |
| `core/service.py` | `acting_user_id` (162, 180) | `ensure_agent_available(name, principal)`; `principal=` | `select`, `new`, `clear`, `load`, `run` |
| `core/chat_service.py` | `acting_user_id` (277-315); `"user_id"` in known fields (150) | `req.principal` hand-off; 403/404 mapping; the `user_id` rejection in `reject_unprocessable` (the public name of `_reject_ambiguous`, which the thread and pipeline edges call before their first write); trigger skip | `_maybe_schedule`; `ResponseBuilder` |
| `core/builder.py` | `build(name, description, skills)` | `build(descriptor)` with security schemes | `SessionStoreBuilder`, `SessionCacheBuilder` |
| `core/__init__.py` | `ACTING_USER_CACHE_KEY` (48) | exports `Principal`, `AccessLevel`, `AgentDescriptor`, `SessionOwner`, `ToolFilter`, `AgentRegistry`, `AgentRegistrationError` | |
| `api/http.py` | `add_auth_handlers`, `_auth_token_validators` (22, 208-237) | `_get_router_dependencies` always returns the identity dependency | `run` delegation rule; `build_app` mounting; `reject_unqueued_protocols` |
| `api/handler.py` | `authoriser` argument; multipart `user_id` (121) | `AuthorisedRESTRequestHandler` identity requirement; `_resolve_user -> Principal`; catalog | path constants |
| `pipeline/request_handler.py` | multipart `user_id` (481, 507) | precheck before enqueue; `body.principal` | wait budget; `_reject_unroutable`; `QueuedReply` |
| `pipeline/ws/handler.py`, `gateway.py`, `io_handler.py` | `auth_validator` everywhere; `userId` read (185-188) | identity requirement; subject keying; custom route ctx | frame validation; registry/store registration; fail-fasts not about auth |
| `pipeline/agent_runner.py` | | `principal=` at 126; `ATTR_USER_ID` from the principal on the fallback path; `release` in `finally` | forwarded attributes; thread recording; stream runner marker rule |
| `integration/adapter/base.py`, `producer.py` | | `InboundRequest.namespace/claims`; principal built at enqueue | attributes; reply-context budget |
| `integration/agui/*` | `authoriser`/`auth_validator`; `agui.agents` read (60-68) | principal through `_resolve_run_inputs`; visibility | event mapping; envelope; pause outcome |
| `api/mcp/akmcp.py` | `mcp.agents` read (140); `agent.get_description()` as the tool text (154) | `auth=`; per-tool `AuthCheck`; principal on the body; tools registered from registry descriptors | executor error mapping; `get_http_app` |
| `api/a2a/*` | `a2a.agents` read (137); the `agent.get_a2a_card()` call and its "no card" branch (155-158) | context builder; principal on the body; cards built from registry descriptors, filtered and narrowed per caller | routes shape; data parts; cards built once at mount |
| `cli/cli.py` | | `--token` / `AK_CLI_TOKEN` | REPL commands |
| `deployment/aws/*`, `gcp/akauthorizer.py`, `azure/akfunction.py` | validator arguments; `GCPAuthorizer`; `set_auth_handler`; `set_auth_validator` | principal via authorizer context; WS keyed by subject | queue wiring; connection table schema |
| `integration/thread/*` | `authoriser`; `user_id` requirement text | ownership `PermissionError`; 403 mapping; 401 for anonymous | store layouts; naming; recording order |
| `schedule/*` | `user_id` in the trigger body | `principal` on tasks and triggers; tools read the principal | routes; providers; store key layouts (one new optional column) |
| `sandbox/principal.py` | | default resolver reads the run principal | `PrincipalResolver` ABC |
| `framework/*` | `get_a2a_card` in all eight adapters | `get_tool_names`, `_tool_descriptions`, `ungated_tool_names`, gates (section 9) | every native run call with no `authorization` block |

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

class _GrantConfig(BaseModel):                          # extra="forbid"
    subjects: list[str]; agents: list[str]; level: AccessLevel
    # before validator coerces a bare string in subjects/agents to a one-element list
class _ToolPolicyConfig(BaseModel):                     # extra="forbid"
    agent: str; tiers: dict[str, AccessLevel] = {}; allow: Optional[list[str]] = None; deny: list[str] = []
class _StaticAuthorizerConfig(BaseModel):               # extra="forbid"
    grants: list[_GrantConfig] = []; tools: list[_ToolPolicyConfig] = []
class _AuthorizationConfig(BaseModel):                  # extra="allow"; after validator below
    type: str = Field(default="static", description="static | dotted path to an Authorizer; casbin, openfga, cedar, authzen reserved")
    static: Optional[_StaticAuthorizerConfig] = None    # one section per built-in backend

class _RegistryStoreConfig(BaseModel):        # mixin: STORE names the block; a field validator on `ttl`
    STORE: ClassVar[str]                      # raises AKConfigError for any value but 0
class _RegistryRedisConfig(_RegistryStoreConfig, _RedisConfig): prefix: str = "ak:registry:"; ttl: int = 0
class _RegistryValkeyConfig(_RegistryStoreConfig, _ValkeyConfig): prefix: str = "ak:registry:"; ttl: int = 0
class _RegistryDynamoDBConfig(_RegistryStoreConfig, _DynamoDBConfig): table_name: str = "ak-agent-registry"; ttl: int = 0
class _RegistryAgentOverlayConfig(BaseModel):
    version: Optional[str] = None; description: Optional[str] = None; owner: Optional[str] = None
    tags: Optional[list[str]] = None; visibility: Optional[Literal["private", "internal", "public"]] = None
    surfaces: Optional[list[Literal["rest", "a2a", "mcp", "agui"]]] = None
    identity: Optional[AgentIdentitySpec] = None
class _RegistryConfig(BaseModel):                       # extra="forbid"
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
  (1228). The three models share a base, `_SurfaceConfig`, which names its block in a `SURFACE`
  class variable and carries one `mode="before"` validator, the `_reject_legacy_stream` shape
  (730-736), that raises `AKConfigError(f"{block}.agents was removed: set registry.agents.<id>.
  surfaces instead")` when the raw input (YAML or `AK_<BLOCK>__AGENTS`) carries the key. The
  `agui.default_agent` validation moves to `AGUIRequestHandler` as "exposed on agui".
  `agui.state.agents`, `agui.client_context.agents`, `a2ui.agents`, `api.enabled_routes.agents`
  are untouched.
- `_RegistryAgentOverlayConfig` refuses unknown keys (`extra="forbid"`), unlike the other
  blocks: a misspelt `surfaces` or `visibility` silently ignored would leave an agent more
  exposed than the configuration reads. Its `surfaces` and `visibility` take the descriptor's own
  literals, so a value outside them fails at load. `_RegistryConfig` refuses unknown keys for the
  same reason one level up: `agent:` written for `agents:` would drop every restriction beneath
  it. A bring-your-own registry is built with no arguments, so nothing reads a key of its own
  here.
- The credential store's blocks refuse a `ttl` too (`_CredentialStoreBackendConfig`,
  `AKConfigError` naming `identity.credentials.store.<store>.ttl`): each entry expires with the
  token it holds, so a store-wide expiry would keep one past it or drop it while its run still
  needs it; `inbound_ttl` caps how long an inbound credential is kept, and must be positive.
  `_CredentialsConfig` refuses unknown keys (a misspelt `encryption_key` would keep credentials in
  plaintext); `_CredentialStoreConfig` and `_ExchangerConfig` keep them in `model_extra` for a
  bring-your-own store or exchanger (iteration 24).
- The registry's store blocks refuse a `ttl` (`_RegistryStoreConfig`, `AKConfigError` naming
  `registry.<store>.ttl`). They reuse the connection models, which carry the field, and the
  registry cannot honour it: nothing registers a hosted agent again, so an expiry would remove
  running agents from every listing (section 6; design refinement 11). The field stays, at 0,
  because a defaults-only subclass cannot drop it.
- The static authorizer's policy sits in a section of its own, `authorization.static`, the shape
  `identity.provider.static` and `registry.redis` have (design refinement 15). The block carries
  `type` and one section per built-in backend, so no key of the block belongs to one backend and a
  later engine adds a sibling section. An after validator on `_AuthorizationConfig` raises
  `AKConfigError("authorization.type static requires the authorization.static block")` when the
  type is `static`, whatever its case, and the section is missing: the identity provider block's
  rule. An empty section is a policy with no grants (section 7). A section left under another
  type is not refused, as an unselected provider's section is not.
- The authorization models refuse unknown keys for the registry's reason. `_GrantConfig`,
  `_ToolPolicyConfig` and `_StaticAuthorizerConfig` are `extra="forbid"`: a misspelt `deny`,
  `allow`, `tiers` or `tools` silently ignored would leave a tool more reachable than the
  configuration reads. `_AuthorizationConfig` is `extra="allow"`, since a bring-your-own
  authorizer (a dotted-path `type`) reads the settings of its own from `model_extra`, and the same
  validator raises `AKConfigError` naming `authorization.<key>` for any unknown key when the type
  is not a dotted path: `grants:` written beside `type`, or a misspelt `static`, would otherwise
  drop the whole policy. That check runs before the missing-section one, so the flat form is told
  which key is misplaced. The subject grammar is not checked here but when the authorizer is built
  (`GrantTable`, section 7), which names the grant by its index.
- Every new field carries a `description`; defaults keep every existing YAML and `AK_*` variable
  valid except the three removed lists, which fail with the message above by design.
- Field readers: see design section 9's table; this spec adds `identity.provider.cognito|entra|
  firebase|static` (their provider classes), `identity.credentials.store.<backend>`
  (`CredentialStoreFactory`), `registry.agents.<id>.identity` (`AgentRegistry.register`
  overlay), and `authorization.static.tools[].tiers` as `dict[str, AccessLevel]`
  (`StaticAuthorizer`).
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
   names: `{"agents": [<descriptor>...], "next_cursor": ...}`, narrowed to the agents exposed on
   `rest`, in id order, each descriptor without its `identity`. AG-UI's `/agents` lists ids in
   id order too, where it followed the registration order; the queue-mode handler also lists
   agents another process hosts, while the direct handler lists the ones its process hosts.
6. MCP `tools/list` and `/a2a/catalog` return only the agents the caller may see; a hidden
   agent's A2A card is 404; calling a hidden MCP tool is refused by FastMCP. As built
   (iteration 20), with an `authorization` block: every route of a hidden A2A agent is that
   404, a visible agent the caller holds no level on is a 403 on A2A's protocol routes and on
   AG-UI, a card and the catalog carry `Vary: Authorization` and the skills the caller is
   offered, and AG-UI's `/agents` is the caller's own.
7. With an `authorization` block, an agent run is refused before pre-hooks (403), a hidden agent
   is 404, denied tools are hidden where the framework allows and refused at call time with a
   reason string everywhere, and a session is continued only by its owner (403) outside
   messaging and realtime.
8. A HITL resume by a different non-anonymous subject than the one that paused is refused (403).
9. A scheduled trigger whose owner lost access is recorded with an error and skipped, never run.
   The same holds with no `authorization` block for a task whose agent was removed or taken off
   the task's surface: its occurrence was recorded as fired and answered 404, and is now
   recorded with `last_error` and answered 403 with the skip text (iteration 19; section 8.1).
10. Threads: an existing thread is appended to only by its owner (403); the chat routes answer
    401 to anonymous callers instead of 400 "user_id is required".
11. Schedules: creation requires an authenticated principal (401 on the chat route, an error
    string from the tools); the frozen trigger body carries `principal`, not `user_id`.
12. `Runtime.register` raises `AgentRegistrationError`; `Runtime.agents()` returns the registry's
    dict (same contract). Registering the same agent object again replaces its descriptor where
    it raised before; a different agent under a registered name still raises (section 6).
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
19. LangGraph's card skills, always empty today because `node_data.tools` never exists
    (`framework/langgraph/langgraph.py:380-401` against
    `langchain_core/runnables/graph.py:95-105`), are populated from the compiled graph's tool
    nodes through the descriptor.
20. `APIGatewayAuthorizer` denies a bare token sent without the `Bearer` scheme; the base's
    `_extract_token` accepted it (section 8.9).
21. The routes of a handler that declares `authenticates_itself` are mounted without the identity
    dependency: every `WebhookRESTRequestHandler`, and in single-process async mode the co-hosted
    `PipelineWebSocketHandler` and `PushEndpointHandler` (section 8.2).
22. `AzureFunctions.handler` answers a refused credential with 401; the base had no
    authentication on that path. (Moot since `develop` removed Azure Functions support, #984.)
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
30. `Agent.get_a2a_card` is removed from the base class and the eight adapters. A2A cards are
    built from the registry's descriptors when the A2A routes are mounted, so they carry the
    config overlay and a process over a store-backed registry serves A2A for agents it does not
    host. An agent that registers after a process mounted its routes is served there once that
    process restarts (section 6, A2A card).
31. An A2A card's description is the declared `descriptor.description`, where the OpenAI, CrewAI,
    MAF, smolagents, Pydantic AI and Claude cards carried the agent's instructions or backstory.
    The description is what `Module.describe` or `registry.agents.<id>.description` declares,
    else the description the framework keeps for the agent apart from its instructions (OpenAI
    `handoff_description`; the `description` of an ADK, Pydantic AI, MAF, Claude or smolagents
    agent). An agent with neither gets a neutral sentence naming it ("The '<id>' agent."), since
    A2A requires the field and an empty one is dropped from the served JSON, and logs a warning
    at mount. A skill
    with no description gets a sentence of the same kind. A card's `version` is the descriptor's
    (`0.0.0` until declared), where it was the Agent Kernel library version.
32. In the catalog and on A2A cards, a skill backed by a tool the caller's level does not allow
    is left out with the tool; the A2A catalog and card responses carry `Vary: Authorization`
    (sections 6 and 8.7).
33. An agent's MCP tool is described by `descriptor.description` (declared, else the native
    description field of item 31), or by a neutral sentence naming the agent when there is none
    (with a warning at build), where it carried the agent's instructions. The tools are registered
    from the registry's descriptors, in id order, so a process over a store-backed registry
    exposes agents it does not host (section 8.6).
34. A request naming an agent the registry does not know is answered 404 `Agent '<name>' not
    found` on the REST chat and thread chat routes, a chat request that schedules included, and
    by the queue pipeline's runner and the deployment adapters, where it was 400 `No agent
    available`: the answer a hidden agent gets, so the two cannot be told apart (AG-UI already
    answered so). The schedule tools return that text in their `error`. A request naming no agent
    while none exists stays 400. A caller of `ChatService.execute*` or `prepare_agent_handler`
    that caught `ValueError` for the unknown agent catches `AgentNotFoundError` for it now
    (section 6, Availability).
35. `Agent.get_description()` is no longer abstract and nothing in Agent Kernel reads it: the
    base returns `""`, the eight adapters keep their implementations, and a bring-your-own
    adapter need not write one. An adapter class that still defines `get_a2a_card` logs one
    warning when its first descriptor is built.
36. A direct thread chat (`AgentThreadRequestHandler`) naming an agent the registry knows only
    from another process is refused before any thread write, as it was before the registry
    existed, where the registry-wide check alone let the user message be recorded ahead of a run
    that could not select the agent. It is answered like the unknown agent of item 34, a 404
    (section 6, Availability).
37. Connecting to Redis or Valkey logs the scheme, host, port and path of the connection URL at
    DEBUG, never its user, password or query, and a fixed placeholder for a value that does not
    parse as a URL with a scheme and a host, where it logged the URL whole
    (`core/util/driver/redis_like.py`; every store on the shared driver, not the registry alone).
38. A chat request that enters by the REST API and names an agent whose `surfaces` leaves out
    `rest` is answered like one for an unknown agent (404), and a request naming no agent runs
    the first agent that is on `rest`, where either ran whatever agent was named or registered
    first (iteration 17b; section 6, Catalog; design refinement 13). It holds on the chat and
    multipart routes, the thread chat routes (before any thread write), WebSocket chat and a
    chat request that schedules a task. Requests from a messaging integration, the CLI and a
    scheduled occurrence are served as before.
39. `surface` is a field of the chat body the entry point sets (iteration 17b). A client that
    sends a value for it is refused like the other internal fields (422 on the FastAPI chat
    routes, an invalid-request frame on the WebSocket gateway), where the key was passed to the
    pre-hooks as additional context. `AgentService.select`, `AgentHandler.initialize`,
    `ChatService.prepare_agent_handler` and `ScheduleManager.create` take an optional
    `surface`; a double or subclass that overrides one with the old signature must accept it.
40. A queued chat request naming an agent its caller cannot have is answered by the process that
    accepts it, before anything is enqueued, with the status and body the runner answered with
    (iteration 19; section 8.3). The answer changes only where the two processes disagree: an
    accepting process that knows some agents and not the one named answers 404 for an agent the
    runner would have served (it already left that agent off A2A and MCP), and one whose
    registry knows no agent enqueues as before. `RequestHandler.run_chat` now goes on to
    `_enqueue_and_wait(body, admitted=True)` and no longer through the `enqueue_and_wait` route
    method, so a subclass that overrode `enqueue_and_wait` to change the pipeline chat route
    overrides `run_chat` or `_enqueue_and_wait`. `AgentRESTRequestHandler.list_agents` takes the
    request as its first parameter.
41. A scheduled task created by a chat request keeps that request's surface, and its occurrences
    are served the agents on it (iteration 19; section 6, Catalog): a task naming no agent runs
    the first agent on the surface, where it ran the first agent registered. Tasks created
    before the change, and by a schedule tool, are unaffected. A task record gains `surface`
    and `last_error`, and `ScheduleStore.record_trigger` an optional `error`.
42. Three answers change with no `authorization` block (iteration 20). An MCP call the runner
    answers 404 or 403 (an agent the runner does not serve) is `ToolError("Agent not
    available")`, where it was "The agent could not process the request". A realtime call
    naming an agent the runner does not host is told once, with a terminal error chunk, and
    held back, where each of its inputs was retried and failed. And AG-UI's bare route answers
    a default agent that has since gone with a bare 404, where it named the agent.
43. With an `authorization` block, a request with the wrong method on an A2A route is a 404
    (`{"detail": "Not Found"}`), where it was a 405 naming the methods the route serves, and a
    credential the provider refuses is a 401 on every path under `/a2a/<name>/`, where a name
    that is not mounted answered 404 (2026-11-25; section 8.7). Without the block both are as
    they were.
44. What two adapters declare changes with no `authorization` block (iteration 21; section 9),
    and with it the agent's catalog entry, A2A card skills and the names a policy uses. An
    OpenAI Agents SDK agent also declares the tools of the agents it hands off to and of the
    agents it uses as tools, after its own. A Pydantic AI tool behind a prefixed or renamed
    toolset is declared under the name the model calls it by, where it was declared under the
    inner name.
45. With an `authorization` block (iteration 21), a tool the running agent does not declare is
    not offered and not run where the gate sees it: the tools of a toolset listed only inside
    a run on Pydantic AI, the functions of an MCP tool on MAF. An OpenAI agent with an
    `mcp_servers` entry, or a handoff that does not hold its agent, fails `Module.load` with
    the `AKConfigError` of an ungated tool. Without the block nothing of this applies.
46. Two more adapters declare more with no `authorization` block (iteration 22; section 9), as
    change 44 did. A Google ADK agent also declares the tools of the agents it uses as tools
    and of the nodes of a workflow nested in another, and a callable object under the name ADK
    serves it by (it was left out). A CrewAI agent that may delegate also declares the tools
    of its coworkers, the other agents of its module.
47. With an `authorization` block (iteration 22), a tool the running agent does not declare is
    refused on ADK and CrewAI as well: a toolset's tools on ADK, for one. The tools the two
    frameworks move a run with (ADK's transfer and structured response, CrewAI's delegation
    tools) are not gated.
48. Two adapters declare differently with no `authorization` block (iteration 23; section 9). A
    LangGraph agent also declares the tools of its compiled subgraphs. A smolagents agent no
    longer declares `final_answer`, and declares the tools of its managed agents.
49. With an `authorization` block (iteration 23), the Q12 refusal is live: a LangGraph agent with
    a tool not bound through `LangGraphToolBuilder.bind`, and a smolagents code agent on a remote
    executor, fail `Module.load` with the `AKConfigError` of an ungated tool. A tool a provider
    runs is logged, not refused.
50. With an `authorization` block (iteration 23), a realtime call publishes a tool filter, the
    room's (section 8.4), so its tools are gated: a participant with a lower level narrows what
    the model is offered for the rest of the call.
51. With an `identity.credentials` block (iteration 25; sections 4 and 5), every authenticated HTTP
    request that can start a run (not `GET`, `HEAD` or `OPTIONS`) and every MCP tool call writes its
    credential, encrypted, to the credential store and its principal carries a `credential_ref`; the run
    deletes it when it ends, and `passthrough` leaves no cached copy. A request the surface answers without a
    run (a refusal, a failed send to the queue) deletes it too. One that changes a record without a run (a
    schedule amended, an A2A `tasks/get`) or whose body FastAPI cannot parse (a `422`, after the dependency
    ran) leaves its entry to expire within `inbound_ttl`. The WebSocket APIs (the pipeline gateway,
    ECS, Lambda) and the CLI keep one for the connection or session, renewed by each frame (the CLI: each
    prompt) when the token has no `exp`, and the Lambda REST router keeps one from the request's header
    when it starts a run (iteration 25b). A WebSocket route of the application's own on a router behind
    the identity dependency keeps none. Without the block nothing is written and no principal carries a
    ref.
52. `ToolContext.credentials` is new: a broker whose `token_for(audience, scopes=None)` hands a tool a
    token, or raises `CredentialError` (iteration 25).
53. An `in_memory` credential store on a broker transport stops `IOHandler` and `AgentRunner` at
    startup (iteration 25), and on AWS Lambda it stops the queued REST router and the WebSocket
    connection routes (iteration 25b), as it does the ECS WebSocket API. A bring-your-own store whose
    class sets `shared = False` is refused in the same places.

**Non-changes:** session, thread, schedule, attachment and response-store layouts (the optional
`last_error`, `surface` and `principal` on a task's document aside); the queue envelope
attributes and `ATTR_USER_ID` as the WS-entered marker; `RequestProducer`, `IntegrationProducer`
attribute stamping; every native framework call when no `authorization` block is present
(keyword-for-keyword, the #754 invariant); `AgentService.select` for a request with no surface
(item 38); `ChatService` wire shapes other than the 403/404 branches; the HITL approval flags and resume contract; `Session.Keys` values
for the two caches and the framework context; public exports other than those named deleted.

## Error handling

| Failure | Where | What surfaces |
|---|---|---|
| Invalid, expired, wrong-audience credential | `RequestAuthenticator` | 401 `"Unauthorized"` (HTTP), 1008 `"Authentication failed"` (WS), `ToolError` (MCP via FastMCP's own 401), `AuthenticationError` logged at INFO with the reason |
| Malformed `Authorization` header | same | 401 `"Invalid authorization header"` when a provider is configured; without one the header is ignored unparsed and the request runs anonymous |
| Anonymous caller on a surface that needs a user | `AuthorisedRESTRequestHandler._resolve_user` | 401 `"Authentication required"` |
| No level on the agent | `AccessGate.authorize_agent` → `PermissionError` | 403 with the message; `StreamChunk(error, done=True)` on a stream; `ToolError("Agent not available")` on MCP; on A2A a 403 `{"detail": <message>}` from the route's guard (`InternalError` only when the runner refuses what this process let through); on AG-UI a 403 `{"detail": <message>}`; on a realtime call one terminal error chunk and no native session |
| Agent named in a request is unknown to the registry, or not visible to the caller | `AgentService.ensure_agent_available`, `AccessGate.authorize_agent` → `AgentNotFoundError` | 404 `"Agent '<name>' not found"`, one status and body for both, on REST chat (direct and queued, a request that schedules included), the thread chat routes and AG-UI; `ToolError("Agent not available")` on MCP; `{"error": ...}` from the schedule tools |
| Agent hidden from the caller, on a surface that addresses it by its own path or tool | the surface's check: `A2ARESTRequestHandler._usable_by_the_caller` and the card wrapper, `MCP._visible_to_the_caller`, the AG-UI bare route | A2A: 404 `{"detail": "Not Found"}` on every route of the agent, the answer of a path that is not mounted, and no card in the catalog. MCP: the tool is not listed and a call is FastMCP's `Unknown tool`. AG-UI's bare route (`agui.default_agent`): the bare 404 of a route with no default |
| A request under `/a2a/<name>/` that no A2A route serves (a name that is not mounted, an unserved path, a method the route does not take, a trailing slash), with an `authorization` block | `UnservedA2ARoute`, behind the identity dependency | 404 `{"detail": "Not Found"}` for every name; 401 first for a credential the provider refuses; 405 from this one route for a method that is no HTTP method. Without the block the router's own answers stand (405 for a wrong method on a mounted route) |
| A realtime call whose caller cannot have the agent | `RealtimeConnectionPool._refuse` | One terminal error chunk to the edge (`"Realtime session could not start: <reason>"`), nothing raised to the queue, the session held back with the reconnect back-off |
| Agent named in a request is kept off the surface the request entered by | `AgentService.ensure_agent_available(..., surface=)` → `AgentNotFoundError` | The unknown agent's 404 and body on REST chat (direct and queued, a request that schedules included), the thread chat routes before any write, and WebSocket chat |
| No agent named and the registry knows none, or none hosted here is on the request's surface, or the default agent is one the caller may not see | `AgentService.ensure_agent_available` → `ValueError` | 400 `"No agent available"` |
| A queued request naming an agent its caller cannot have | `RestHandler._availability_refusal` (the same check, at the accepting process) | The 404 or 403 above with `{"error", "session_id"}`, nothing enqueued, no file saved; from `request` a `QueuedReply` with that status and body. Left to the runner when the request names no agent, or this process's registry knows none |
| A scheduled occurrence whose named agent its owner cannot have (no level, hidden, removed, off the task's surface) | `ChatService._record_trigger` | Not run: `{"result": "scheduled task skipped: the owner no longer holds access to the agent"}` with 403, one error chunk on a stream; the occurrence recorded with the reason in `last_error`; one warning naming the task |
| A scheduled occurrence naming no agent, with none to default to | `ChatService._record_trigger`, then the run | 400 `"No agent available"` as before; the reason recorded in `last_error` |
| `surface` sent by a client | `ChatRunRequest` (`INTERNAL_FIELDS`) | 422 naming the field on the FastAPI chat routes; an invalid-request frame on the WebSocket gateway; on the Lambda and ECS entry points, what each answers for the other internal fields (#884) |
| Session owned by another principal | `authorize_session` → `PermissionError` | 403 at the choke point (`Runtime._admit`, after the agent check and before any pre-hook); one error chunk on a stream; thread path 403 before any write |
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
| `registry.type` unknown, or a store type without its block | `AgentRegistryFactory.build` | `AKConfigError` at the first `Runtime` |
| Unknown key or out-of-range value under `registry.agents.<id>` | the config model | a validation error at load |
| Agent served over A2A with no description | `A2A._build` | one warning per agent at mount; the card carries the neutral `UNDESCRIBED_AGENT_TEXT` |
| Agent exposed as an MCP tool with no description | `MCP._build` | one warning per agent at build; the tool carries the neutral `UNDESCRIBED_TOOL_TEXT` |
| A2A, or MCP agent tools, enabled while no known agent is exposed on the surface | `A2A._build`, `MCP._build` | one warning at build naming `registry.agents.<id>.surfaces`; the surface serves nothing |
| Policy naming an unknown tool on a hosted agent (`Authorizer.validate`); an agent reporting ungated tools | `AccessGate.validate_configuration` | `AKConfigError` at `Module.load` (the load is rolled back) / `get_router()` |
| A grant naming an agent id or a `tag:` no descriptor carries; a `role:` subject with no role mapper | `Authorizer.validate` findings, logged by the gate | one warning each; the two that need the whole registry only from the registry-wide check |
| A key the `authorization` block, its `static` section, a grant or a tool policy does not take | the config model | `AKConfigError` naming `authorization.<key>` for the block (unless `type` is a dotted path); a validation error at load for the section, a grant or a policy |
| `authorization.type: static` with no `static` section | `_AuthorizationConfig` (`StaticAuthorizer.from_config` for a block built without validation) | `AKConfigError` naming `authorization.static`, at load |
| A grant or tool policy that cannot be used (unknown subject form, empty `subjects` or `agents`, bare `tag:`, a second policy for an agent) | `GrantTable`, `ToolPolicyTable` | `AKConfigError` naming `authorization.static.grants[<index>]` or `authorization.static.tools[<index>]`, when the authorizer is built |
| `authorization.type` naming an engine that is not shipped, an unknown short name, or a dotted path that is not an `Authorizer` | `AuthorizerFactory.create` | `AKConfigError` |
| Removed config lists present | `_A2AConfig`/`_MCPConfig`/`_AGUIConfig` validators | `AKConfigError` naming `registry.agents.<id>.surfaces` |
| Registry store unreachable | driver retries (3 × 2 s) then the driver's error | `register` fails the `Module.load`; `deregister` raises and keeps the agent hosted, so a retry removes the record; at mount, `A2A._build`, `MCP._build` and the `agui.default_agent` check raise and the process does not start (cards and tools built from an unread registry would stay empty until a restart), while `IOHandler._warn_if_no_agents` only logs that it could not check; per request, the catalog route, `ensure_agent_available` for an agent hosted elsewhere and AG-UI's resolution raise, which the surface answers 500 |
| `ttl` set on a registry store block, or a key the `registry` block does not take | the config model | `AKConfigError` naming `registry.<store>.ttl`; a validation error at load |
| `Module.describe` naming `tools`, `runner`, `supports_streaming` or `updated_at` | `Module.describe` | `ValueError`; nothing stored |
| `Module.describe` whose registration the registry refuses | `Module.describe` | the registry's error; the agent keeps the descriptor it had; a shared store holds the old record or the new one until the agent is described again |
| A load fails part way and its cleanup fails too (a shared store down) | `Module.load` (`_roll_back`) | the load's own error is raised; each cleanup failure is logged; the agents that could not be deregistered stay registered and in the module, for `unload()` to finish |
| Direct execution of an agent only the registry knows | `AgentHandler.initialize`, the direct thread handler, `ScheduleManager.create` on `in_memory` | Named: `AgentNotFoundError` before a session, a thread write or a task; 404, as for an unknown agent. Unnamed, with no agent hosted: `ValueError("No agent available")`; 400 |
| Adapter class still defining `get_a2a_card` | `Agent._build_descriptor` | one warning per class; the method is never called |

Concurrency: `IdentityProviderFactory.get()`, `AuthorizerFactory.get()` and `AccessGate.get()`
are built once behind an `RLock` (the `ScheduleManager.get()` shape,
`schedule/manager.py:60-73`); `AgentRegistryFactory.build()` is called once per `Runtime` and
returns a registry of its own each time (section 6); `JWKSCache` guards its refresh with a
`threading.Lock` because ECS consumer threads share one provider; the redis-like and DynamoDB
stores inherit the
drivers' per-instance connect lock; `InMemoryCredentialStore` and `InMemoryAgentRegistry` use
plain dicts under the GIL with no check-then-act across awaits. The redis-like registry writes
and removes a descriptor and its index membership in one MULTI/EXEC, so two processes
registering and deregistering one id never leave the two keys disagreeing. Per-operation cost on
hot paths: for an agent the process hosts, no registry read at all (`ensure_agent_available` and
AG-UI's resolution answer from the hosted agent); for one hosted elsewhere, one store read per
request (`descriptor(id)`, or `is_empty()` for a request naming no agent), off the event loop on
the `async` paths, plus one `AgentDescriptor` validation when the overlay names the agent;
for a principal holding a `tag:` grant, no registry read for a hosted agent and one listing per
question for an agent hosted elsewhere (design refinement 19);
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
  `mapping` and a dotted mapper built by the factory; `IdentityProviderFactory` built-in, dotted,
  unknown and missing extra (the missing extra, with the OIDC family's branches, in
  `test_identity_oidc.py`); `RequestAuthenticator` bearer parsing, anonymous rules, 401 details, `credential_ref`
  minting and `release`, the contextvar.
- `test_identity_credentials.py`: `CredentialStoreContract` over in-memory and the redis-like
  and DynamoDB backends through fake drivers (the `test_schedule_store.py` pattern); cipher round
  trip; `TokenExchangerContract` over `passthrough` and a fake; the `passthrough` startup
  warning; `CredentialBroker` cache key, TTL, `CredentialError` cases; no token in a queue body or
  a log record (caplog asserted); the inbound entry deleted at run end on the direct and queued
  paths; reserved exchanger names raise.
- `test_agent_registry.py`: `AgentRegistryContract` over in-memory, redis-like (fake client at
  `registry._driver._client`) and DynamoDB (fake driver); `AgentRegistryFactory` resolution;
  `Runtime.register` delegating and raising `AgentRegistrationError`; `Module.describe`
  (unloaded agent, unknown field, later wins); a skill's description from
  `_tool_descriptions`; the config overlay, on the registry's descriptor and on
  `agent.descriptor` (the run's actor subject follows an overlaid `identity`); descriptors
  readable from a second registry instance over the same fake store (the io-handler case).
  From the phase C review: the overlay applied on read for an agent the process does not host
  (a registry over a store another process wrote, `_SharedStoreRegistry`, built through the
  factory), a listing filtering on an overlaid tag, a key in another case matching and an exact
  key winning; the store rules (the document and its index membership in one transaction, on
  write and on removal, with the fake client's pipeline applying its commands together or not
  at all; no expiry; a store delete that fails keeps the agent hosted and a retry removes the
  record; DynamoDB scans consistent, with the fake paging on an exclusive start key; `is_empty`
  reading one DynamoDB item, or on redis-like the index and an existence check per member, never a
  document); `Module.describe` refusing the reported fields and
  leaving the descriptor as it was when the registry refuses the registration; one warning per
  class that still defines `get_a2a_card`.
- `test_authorizer_static.py`: `AuthorizerContract` subclassed twice (the policy handed over as
  mappings, and read from an `authorization.static` section through `from_config`); the base class's two
  list defaults; `SubjectMatcher` form by form (the shared-channel and anonymous exclusions of
  `user:`, the `provider:` prefix); grant normalization errors, each naming the grant's index;
  the static backend's corners (a tag resolved when asked, no registry read without a tag
  grant, a hosted agent's tags read from its own descriptor with no registry read for its
  level, its tool decisions or a listing among hosted agents, one read per question and per
  listing for an agent hosted elsewhere, the read off the event loop); the three reason
  strings and deny and allow decided before the level; one policy per agent; tier defaults from
  system tools (per agent, overridden by a `tiers` entry); the empty-grants warning;
  `StaticAuthorizer.from_config` (the section as the policy, the lookups it is given, a
  `descriptor_lookup` of the caller's being its only source of tags, a block with no section
  refused); the factory (a static authorizer built from the block alone asking the current
  runtime's hosted agent first, never listing the registry for it, and listing the registry
  for an agent hosted elsewhere, reserved names, dotted path with the whole block, `get()`
  built once, following the current runtime's registry and reading system tool tiers); the lazy
  exports.
- `test_config.py` (`TestAuthorizationConfig`): the block absent by default, parsed from YAML and
  from `AK_AUTHORIZATION__STATIC__*`, the static type refused without its section (in the model
  and from `AK_AUTHORIZATION__TYPE` alone), a bare string coerced, levels and tiers outside the
  three refused, unknown keys refused under a grant, a tool policy, the static section and (for
  a built-in type) the block, the flat form named by its misplaced key, and a bring-your-own
  type keeping its own settings.
- `test_access_gate.py`: visibility rules, 403 versus 404, `tool_filter` composition, `tag:`
  resolution, `authorize_session` (no owner, anonymous refused on an owned session, a
  shared-channel owner admitting its platform scope and refusing a REST caller, namespace
  mismatch), `validate_configuration` (unknown tool `AKConfigError`, unknown agent and tag
  warnings, `role:` without a mapper warning, the LangGraph and smolagents refusal).
  As built (iteration 18) it also holds: the shared gate following a rebuilt authorizer; a
  hosted agent decided with no store read and a descriptor handed in decided with no registry;
  the synchronous forms answering inside a running event loop; one authorizer listing per
  `visible_agents`; the level handed to `tool_filter`; `registry_wide=False`; the availability
  check asking the gate (`TestTheAvailabilityCheckAsksTheGate`: the principal, a missing one
  read as anonymous, the surface decided first, the default agent in the hosted form);
  `Module.load` validating and rolling back; and `TestTheConfiguredGate`, over the real factory
  and the static backend's own lookups (a tier a system tool declares reaching the filter, a
  policy tier overriding it, the role mapper read from the `identity` block, and a `tag:`
  grant deciding the check before a run, the gate's answer and the tool filter of a hosted
  agent without listing the registry, from inside a running event loop as well). The gate through
  each surface that hands it the caller's principal is pinned beside that surface:
  `test_chat_service_core` (`TestTheGateThroughTheService`: 403, the unknown agent's 404, no
  session loaded, the default agent), `test_thread_integration` and
  `test_thread_pipeline_recording` (no thread written, nothing enqueued),
  `test_schedule_manager` (no task for an agent its owner may not use), `test_agui_handler`,
  `test_agui_queue_handler` and `test_realtime_pool` (the principal handed to the pre-run
  check). The declared tiers are pinned in `test_schedule_tools`, `test_sandbox`,
  `test_agui_state` and `test_knowledgebase_okf_tools`. A shared fixture, `authorization`
  (`conftest.py`), installs a static block on the live configuration and resets the shared
  authorizer and gate around the test.
- `test_session_identity.py`: `ak.` keys refused through `set`, `delete`, `update`, `__setitem__`
  and `__delitem__`; `clear()` keeps them and `_clear_all` does not; `get_principal`,
  `get_tool_filter` and `get_owner` read through accessors, and `ToolContext.principal` and
  `access_level` have no setter; `access_level` `None` without authorization; owner set once with
  its namespace; `PausedRunState` writes through the reserved path. As built (iteration 26): the
  owner kept and the principal never stored, by the in-memory store (`test_runtime_principal`),
  the redis-like stores through Valkey's fake client (`test_sessions_valkey`, and
  `test_realtime_session_store` after a realtime call) and the DynamoDB store's fake driver
  (`test_sessions_dynamodb`); Cosmos DB and Firestore store it as any other session key and have
  no fake-driver suite. The ownership check (a subject or namespace mismatch, and a shared-channel
  owner bound to its platform's provider and namespace rather than exempt) is
  `test_access_gate`'s `TestAuthorizeSession`; the chat service answers it 403
  (`test_chat_service_core`).
- `test_runtime_principal.py`: `Runtime.run`/`stream` publishing and unpublishing; the gate order
  (refused before pre-hooks, nothing stored; `TestGate`, iteration 18, which also pins the
  filter per principal, `ToolContext.access_level` read during a run, the single error chunk of
  a refused stream, the agent decided before the session, and an anonymous resume refused by the
  session's ownership); the actor chain; the resume subject check as the
  eighth failure mode with the record kept. Realtime publication is pinned in
  `test_realtime_pool.py` (`TestRealtimePrincipal`, `TestDispatchPrincipal`): a native tool reads
  the input's principal with the agent as actor, an anonymous input publishes the anonymous
  principal, only a change republishes, and closing unpublishes.
- `test_tool_gates_<adapter>.py` for `openai`, `pydanticai`, `adk`, `crewai`, `langgraph`,
  `smolagents`, `maf`, `claude` and `realtime`: with a filter published, a denied tool is hidden
  where the framework allows (OpenAI `get_all_tools`, Pydantic AI `prepare_tools`, Claude
  `disallowed_tools`, MAF a chat middleware that leaves it out of every request; LangGraph,
  smolagents and ADK not hidden), a denied call returns the reason string without raising into
  the framework, an allowed call runs, where the gate is a hook, callback or middleware (OpenAI,
  Pydantic AI, ADK, CrewAI, MAF, Claude) the application's own is kept (LangGraph and smolagents
  put the gate in the tool itself and have none to compose with; realtime reuses the OpenAI and
  ADK gates), and the no-authorization path's native call is
  keyword-for-keyword unchanged (asserted on the mocked native call as the `test_*_runner.py`
  files already do); `ungated_tool_names` for LangGraph (unmarked `StructuredTool` in a
  `ToolNode`) and smolagents (a tool added after wrap).
  As built (iteration 21): `test_tool_gate.py` holds `ToolGate` on its own (the session
  handed in or the current run's, a name never listed, failing closed). The four adapter
  suites run on real SDK objects with no model call: OpenAI through `Agent.get_all_tools` and
  `ToolInputGuardrail.run`, Pydantic AI through `FunctionModel` (what a step offers, what the
  model receives), MAF through a scripted chat client (what the function loop ran, what the
  model saw), Claude through the options and the hook the runner builds. Each also pins: the
  gate ahead of the application's own hook (Claude's is appended after it: the SDK combines
  `PreToolUse` decisions as `deny > defer > ask > allow`, so the gate's deny wins in any order),
  a run through `Runtime` with a configured block,
  and a call approved while paused that the filter denies by the time of the resume (not for
  OpenAI, where that path is read from the SDK and not run). The declared names are pinned
  in `test_tool_gates_openai.py` (handoff targets, agents as tools, what is ungated) and
  `test_tool_pydanticai.py` (each compared with the names a real run serves).
  As built (iteration 22): `test_tool_gates_adk.py` runs real agents over a scripted `BaseLlm`
  (what ADK's function handling ran, what the model received), including a transfer to a
  sub-agent whose tool is then refused, a confirmation that never pauses, a confirmed call
  denied by the resume, ADK's own two tools, and a call outside a run. `test_tool_gates_crewai.py`
  runs real crews over a scripted `BaseLLM` on the ReAct path, where the result of a call is
  text the test reads; it needs the CrewAI overlay and is skipped without it, like the other
  CrewAI suites.
  As built (iteration 23): `test_tool_gates_langgraph.py` on real compiled graphs with a scripted
  model node (run, stream, async tool, a renamed tool, an interrupt resumed under a denying
  filter, subgraph declaration, ungated native tools and the load refused);
  `test_tool_gates_smolagents.py` on real agents over a scripted `Model` (a managed agent's tool
  refused in its manager's run, `final_answer` never refused, a remote executor reported and
  refused); `test_tool_gates_realtime.py` (the room's filter at the connection, and a denied tool
  through OpenAI's native realtime session and through ADK's live flow, each with two
  participants). `test_access_gate.py` holds the provider-run warning; the Q12 refusal on real
  adapters is in the LangGraph, smolagents and OpenAI gate suites.
- `test_agent_registry.py` also holds `TestAvailability`: a named agent known only through the
  registry is available, an unknown one is not, an unnamed request needs some descriptor (asked
  through `is_empty`, never a listing), a hosted agent is answered without a store read, and the
  `hosted=True` form refuses an agent the registry only knows. `test_thread_integration` pins
  the direct handler using it: an agent another process hosts is refused with no thread written
  (the unknown agent's 404, since iteration 17a).
- With `AgentNotFoundError` (iteration 17a), the cases that pinned the unknown named agent as a
  `ValueError` or a 400 follow it: `TestAvailability` (the unknown name, and the `hosted` form
  for an agent another process hosts), `test_chat_service_core` (the error propagating from
  `execute*` and `prepare_agent_handler`, the wrappers' 404, `AgentHandler.initialize` loading no
  session), `test_schedule_manager`, `test_schedule_tools` and `test_thread_integration` expect
  the error, the 404 and the `Agent '<name>' not found` text; the unnamed case keeps its
  `ValueError` and its 400 in `TestAvailability`, `test_chat_service_core` and
  `test_thread_integration`, while a schedule naming no agent is not checked when it is created
  (`test_schedule_manager`: the process that fires it resolves the default agent). New beside them: `TestAgentNotFoundError` in
  `test_agent_registry` (one text, a `LookupError` that is not a `KeyError`, the export);
  `test_chat_service_core` pinning that a `KeyError` or an `IndexError` raised inside the run
  stays a 500, and the unmocked path over an empty runtime; `test_api_http`
  (`TestUnknownAgentOnTheChatRoute`: the chat and multipart routes, JSON and SSE, the 404 sent
  before a stream opens); the thread chat routes over HTTP with no thread written, JSON and SSE;
  `test_thread_pipeline_recording` (the queued edge: 404, nothing recorded, nothing enqueued); and
  `test_pipeline_agent_runner` (the runner forwarding the 404 the queued route answers with).
  In iteration 19 `test_api_http` gains the parity case: an unknown agent and a hidden one answer
  with the same status and body.
- As built in iteration 19. `test_api_http` (`TestTheAccessGateOnTheChatRoute`): the parity on
  the chat and multipart routes, JSON and SSE (the two answers differ in nothing but the name
  the caller sent), the 403, a served caller, the anonymous caller, and a hidden default answered
  `No agent available`. `test_pipeline_request_handler` (`TestThePrecheckBeforeTheQueue`, over
  an `edge` fixture whose registry knows descriptors, hosts nothing and counts its reads): 404
  and 403 with nothing enqueued on the JSON, multipart, SSE and base queue routes, the hidden
  and unknown parity, the edge's own `surfaces`, a grant not putting an agent on a surface, no
  file saved for a refused request, one registry read per request and off the event loop, the
  unnamed request and the empty registry left to the runner, a deferred request, and the single
  process with nothing mocked; `TestThePrecheckOnAProtocolRequest`: the refusal as a
  `QueuedReply` with no queue or store touched, the body's surface and principal applied.
  `test_thread_pipeline_recording`: one registry read for a recorded request, and a deferred
  request asked before the queue. `test_api_catalog` (`TestTheCatalogOfACaller`,
  `TestMountingValidatesThePolicy`): the listing per principal, a hidden agent named nowhere in
  the answer, tools and skills narrowed (hosted and stored), an agent listed by visibility alone
  naming no tool, the page cut after the caller's filter and only its entries narrowed, the
  malformed cursor refused before any read, the listing whole without the block; the three
  routers validating the policy at mount, the registry-wide warning made there, and an
  unreadable registry stopping the mount. `test_access_gate` (`TestNarrow`). The scheduled
  skip: `test_schedule_model`, `test_schedule_store` (all three backends) and
  `test_schedule_manager` for `last_error`, the keyword handed over only when set and the kept
  surface; `test_chat_service_schedule` (`TestAnOccurrenceTheOwnerMayNoLongerRun`: every
  execution path, the wrappers' 403 with a reply body, the one error chunk, the one warning, a
  reply that reads like a skip, the unnamed task's 400); `test_schedule_principal`
  (`TestFireTimeAccess`: the real manager, store and gate, a grant taken away and given back,
  `last_error` read through the management route, a trigger carrying no owner).
- With the request's surface (iteration 17b), two shared fixtures in `conftest.py`:
  `surface_agent`, the class of an agent served on the surfaces it is built with whose reply is
  its own name, and `kept_off_rest`, a runtime hosting `internal` (on `a2a` only, registered
  first) beside `public`, so a test reads from the reply which agent a request reached.
  `test_agent_registry` (`TestAvailabilityOnASurface`, `TestSelectionOnASurface`): the named
  agent kept off the surface in both forms, the registry-held surfaces of an agent another
  process hosts, no store read for a hosted agent, the unnamed request in the hosted form and
  at an edge (no listing), and `select` following the same rule. `test_model`
  (`TestRequestSurface`): the field, its ride through the queued body, the client-facing body
  and `from_payload` refusing it, the schema leaving it out, and no additional context from it;
  `test_chat_internal_fields` runs the refusal over the five chat handlers.
  `test_chat_service_core` (`TestSurfaceThroughTheService`): the wrappers' 404 beside the
  unknown agent's, the default, a request from a surface the agent is on, one with no surface,
  every execution path and `prepare_agent_handler`. Per entry point: `test_api_http`
  (`TestAnAgentKeptOffRestOnTheChatRoute`: chat and multipart, JSON and SSE, the default, a
  form field named `surface` changing nothing), `test_pipeline_request_handler`
  (`TestAnAgentKeptOffRest`: the queued body carrying `rest` from each queue route, the 404 and
  the default through the runner, `request` leaving a protocol body as built),
  `test_pipeline_ws`, `test_thread_integration` and `test_thread_pipeline_recording` (no
  thread written, nothing enqueued, an agent another process hosts), `test_deployment_identity`
  (`TestEntryPointsNameTheSurface`: the Lambda routers and the ECS WebSocket API),
  `test_schedule_manager` (a REST request cannot schedule the agent, a tool can, the trigger
  body carries no surface), `test_api_a2a_auth`, `test_api_mcp_auth`, `test_agui_handler` and
  `test_agui_queue_handler` (each surface naming itself, the runner handing the body's surface
  on), `test_pipeline_agent_runner` (a queued body's surface deciding which agents serve it)
  and `test_principal_messaging` (a messaging body carries none).
- `test_api_catalog.py` also pins that an entry never carries the agent's `identity`, and
  `test_agent_registry` that the stored descriptor keeps it. `test_api_a2a_surface` and
  `test_api_mcp` cover the empty-surface warning: once when agents are known and none is exposed,
  not when one is exposed, and not when the registry knows no agent. `test_api_catalog` also
  covers the page-size bounds at the route (50 by default, 200 at most), the same catalog through
  the queue pipeline's `RequestHandler`, and a malformed cursor answered 400 while the registry's
  store is unreachable. `test_api_a2a_surface` requires the `description` key in the served card
  and catalog of an undescribed agent. `test_agui_handler` and `test_agui_queue_handler` pin the
  resolution: a hosted agent without a store read, an agent hosted elsewhere with one read off
  the event loop, and the queued request naming the agent by its id. `test_pipeline_io_handler`
  pins that the no-agents check asks `is_empty` and survives a registry it cannot read.
  `test_config` covers the refused `ttl` and the unknown `registry` key, from YAML-shaped input
  and from the environment; `test_shared_drivers` the connection log without credentials.
  The description default is pinned on real SDK objects in each `test_tool_<adapter>.py`: the
  native field seeds `descriptor.description`, an agent with instructions and no description
  gets an empty one (the Pydantic AI, MAF, Claude and smolagents cases show `get_description()`
  answering with the prompt while the descriptor does not), ADK's leaves out the appended
  system-tool guidance on a first and a second wrap, and CrewAI and LangGraph seed nothing.
  `test_agent_registry` covers the precedence: `Module.describe` and the overlay replace the
  native description, and an empty overlaid one withholds it.
  From the third review pass: `Module.describe` writing the registry before the agent takes the
  descriptor (a registry that records what the agent carried during each write); the failed-load
  rollback (`TestModuleLoadRollback`: the load's error raised whatever the cleanup does, every
  agent attempted, the ones that could not be removed kept for `unload()`); an overlay set
  through `AK_REGISTRY__AGENTS__<Id>__SURFACES` reaching an agent with a mixed-case id; redis-like
  emptiness agreeing with the listing when an index member has no document; the contract's
  round trip for a non-empty `surfaces`; `AgentHandler.initialize` refusing an agent only the
  registry knows (`test_chat_service_core`); a schedule refused for such an agent on the
  in-memory transport and accepted on a broker (`test_schedule_manager`); and the connection log
  placeholder for a URL that does not parse (`test_shared_drivers`).
- `test_api_catalog.py`: `GET /api/v1/agents` descriptors, filtering by caller, `tools`
  narrowing and the `skills` narrowed with it (a tool-backed skill goes with its tool, a declared
  skill that names no tool stays), cursor and limit, 400 on a bad cursor, `surfaces` narrowing
  per surface.
- `test_api_mcp_auth.py`: `AKTokenVerifier` through a real `fastmcp.Client` with a bearer token,
  401 on a bad token, `tools/list` filtered by the per-tool check, the principal on the enqueued
  body, open MCP without identity; `RemoteAuthProvider` metadata served for an OIDC provider.
  As built (iteration 20): `TestTheToolsOfACaller`, through the server `MCP` builds and
  FastMCP's HTTP layer with two callers: the list per caller, an agent kept off `mcp` not listed
  by a grant, every agent listed without the block, a call to a hidden tool answered like a call
  to an unknown one with nothing sent, the policy read at each request, and a check that raises
  hiding the tool; `TestARefusedCall`: a 403 or 404 reply worded `Agent not available`, a failed
  run keeping its own message, and the real queue client's precheck refusing a caller.
- `test_api_a2a_auth.py`: the context builder putting the principal on the call context, the
  executor setting it on the body, cards carrying `security_schemes` and per-skill requirements
  for `static` and `oidc`, none without identity, a hidden card 404, `/a2a/catalog` filtered, a
  card's skills narrowed to the caller with `Vary: Authorization` and an ETag of the card as
  served. As built (iteration 20): `TestAgentAccessOverA2A`, through `RESTAPI.build_app` with a
  static provider of two callers and a registry that hosts nothing and counts its reads: the
  catalog per caller with a hidden agent named nowhere, skills narrowed (and none tool-backed
  for an agent seen by visibility alone), `Vary` on the catalog and the card, no registry read
  per request, a hidden agent's card and its message and task routes byte for byte the answer
  of an agent that is not mounted, a card served to a caller with no level, the ETag of the
  card as served and a conditional request not answered 304 for another caller's card, the 403
  with nothing sent, a caller naming nobody listed as the anonymous principal, a card with no
  descriptor served to nobody, the card decided once for a request, and the surface unchanged
  without the block; `TestTheCallerOfARequest`: the request's principal before its context,
  and `Vary` keeping what a response already varies by. The fallback route (2026-11-25), in
  `TestAgentAccessOverA2A`: for a hidden agent and a name that is not mounted, one answer byte
  for byte to a method the route does not serve (eight method and path pairs, with no
  credential and with a valid one), to a refused credential on every one of them, to a method
  that is no HTTP method, to a trailing slash and to an unserved path; a wrong method answered
  404 for an agent the caller may use; the 405 kept without the block; the catalog, its
  trailing-slash redirect and the API document untouched.
- The other two surfaces of iteration 20. `test_agui_handler` (`TestAgentAccessOverAGUI`): the
  listing per caller, among the hosted agents without listing the registry, the hidden agent's
  404 with the unknown agent's body and headers, the 403 before a session is loaded, a hidden
  agent that cannot stream still a 404, the bare route not naming a hidden default, the mount
  validating the policy; `test_agui_queue_handler` (`TestTheEdgeAnswersForTheCaller`): the
  listing, the hidden agent's 404, the 403 and a hidden agent that cannot stream, decided from
  the registry's descriptors at the queue-mode edge with nothing enqueued and one descriptor read.
  The bare route, its default and the check at mount are the direct handler's, which the queue
  handler inherits, and its edge half is the direct handler's `_resolve_run_inputs`.
  `test_realtime_pool` (`TestRealtimeRefusedCaller`): one terminal error chunk addressed to the
  room and nothing raised, the next inputs dropped without asking again, the doubling delay, a
  grant given meanwhile opening the call, the end of the call forgetting the refusal, another
  call not held back, any other error still raised, and the real gate through the real chat
  service. `test_access_gate`: the listing among candidates handed in.
- `test_cli_token.py`: `--token` and `AK_CLI_TOKEN` through the `static` provider; the principal
  on `run_multi`; an invalid token exits.
- `test_principal_messaging.py`: `IntegrationProducer.enqueue` building the `messaging:` and
  `realtime:` principals with namespace and claims; a sender claim such as Gmail's
  `authentication_results` carried onto the principal (Gmail producing it is
  `test_gmail_integration`); an edge passing the participant identity (a generic
  `StatefulEdgeAdapter` here, the LiveKit edge's own in `test_livekit_edge_adapter`); anonymous
  when the adapter has no sender.
- `test_schedule_principal.py`: ownership over the real REST wiring, `RESTAPI.build_app` with a
  `static` provider resolving two principals: a task created from a chat request is readable,
  amendable and cancellable by its owner alone, the listing is the caller's own, every route
  answers an anonymous caller 401 and a refused credential the dependency's 401. The
  manager-level cases (`create` requiring a principal, the frozen `principal` in the trigger
  body, `record_trigger` ownership by namespace and subject) landed in `test_schedule_manager.py`
  in iteration 3 and the tools reading `Session.get_principal()` in `test_schedule_tools.py`; a
  trigger body carrying no principal firing anonymous and the fire-time level re-check skipping
  with `last_error` joined this file in iteration 19 (`TestFireTimeAccess`).
- `test_deployment_identity.py`: `APIGatewayAuthorizer` policy context carrying the serialized
  principal and the REST router rebuilding it (a client-sent `principal` replaced, the direct chat
  and queued bodies carrying it); the ECS and Lambda `$connect` handlers keyed by subject, refusing
  an invalid or missing token and a build without an identity block; ECS and Lambda frames resolving
  the stored principal (401 or `ValueError` without one), the queued, direct and custom routes
  carrying it (the `AzureFunctions.handler` cases left with Azure Functions support, #984); the
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
  enqueued body carries an anonymous principal. The test agents in the three A2A suites
  (`test_api_a2a_surface.py:44, 127`, `test_api_a2a_auth.py:144`,
  `test_protocol_pipeline_roundtrip.py:69`) stop building a card; `test_api_a2a_surface` asserts
  the card built from the registered descriptor instead: the described name, description and
  version, the warning for an empty description, a card for an ADK agent, and a card for a
  descriptor the process hosts no agent for (a stub `AgentRegistry` passed to `Runtime`); its
  "agent without a card is not served" case goes with the branch.
- `tests/test_api_mcp.py` gains `TestAgentTools`: a tool for an agent the process does not host,
  named by the id and described by the catalog text; a hosted agent's tool carrying its catalog
  text and never its instructions; the neutral text and the one warning for an agent with no
  description; id order; the allow-list by descriptor id; nothing registered with
  `expose_agents` off. `tests/conftest.py` gains the `descriptor_only_registry` fixture, the
  stand-in for a process over a shared registry that the A2A and MCP surface suites share.
- `tests/test_base.py:60` and `tests/test_maf_runner.py:122-123`: the `get_a2a_card` assertions go
  with the method. The thirty or so test agents that define `get_a2a_card` to satisfy the old
  abstract method keep an unused method and need no change.
- Deleted: `tests/test_auth_handler.py`, `tests/test_authoriser_shared.py` (both pin the removed
  package); their surviving assertions (bearer parsing, 401 variants) live in
  `test_identity_providers.py`, the thread handler's membership of the `AuthorisedRESTRequestHandler`
  hierarchy moves to `test_thread_router.TestConstruction`, and the `AuthValidatorAuthoriser`
  adapter has nothing left to pin.

As built (iteration 26), where the end state differs from the list above.
`test_ecs_io_handler.py` and `test_ecs_agent_runner_schedule.py` were deleted when ECS moved
onto the shared pipeline (#962): an identity block being required is pinned in
`test_ecs_websocket_routes` and `test_pipeline_io_handler`, and the trigger body's `principal` in
`test_pipeline_agent_runner_schedule`, which the ECS runner now shares. `test_pipeline_ws` hands
`PipelineWebSocketHandler` a provider of its own as its `authenticator` rather than configuring
`static` through the stub. The AG-UI suites install fake providers on
`IdentityProviderFactory.get`, and the acting-user case reads the run's
`Session.get_principal()` through a recording runner. `TestActingUserPropagation` is
`TestPrincipalPropagation`. In `test_akauthorizer` a bare token is answered `Unauthorized` (401,
decided 2026-11-12), not a Deny. The messaging principal on the body is asserted in
`test_principal_messaging`, while `test_integration_producer` pins that neither `ATTR_USER_ID`
nor a body `user_id` is sent. The anonymous principal on an enqueued body is asserted in
`test_api_a2a_auth` and `test_api_mcp_auth`, and `A2ACardBuilder.build(descriptor)` is called
from `test_api_a2a_surface` and `test_api_a2a_auth`. A config stub gains the three `None` blocks
only where its module reads them: `test_api_mcp`'s does not, and `test_api_a2a` and
`test_cross_surface_parity` have no stub. `TestAgentTools` pins that only agents exposed on `mcp`
get a tool, since the `mcp.agents` allow-list became `surfaces`. The walk also added the
`/chat` body `user_id` 400 on the JSON and SSE paths to `test_api_http`
(`TestUnknownAgentOnTheChatRoute`), and dropped a stale body `user_id` from
`test_serverless_integration_delivery`'s input record.

Run: `cd ak-py && uv run pytest`. The riskiest consumer, `pipeline/request_handler.py` (precheck
before enqueue on a store-backed registry with no local agents), gets dedicated cases in
`test_pipeline_request_handler.py` over the `descriptor_only_registry` fixture (a registry that
knows descriptors and hosts no agent) with no registered `Agent`.

## Documentation, skills and examples

Surfaces the implementation invalidates, from a sweep of the tree at `d9d0d18bc`. The phase A and
B portion landed with phase B itself (PR #937), and the phase C portion with phase C (2026-11-18:
the `registry` block, descriptors and `Module.describe`, the catalog response, where A2A cards
and MCP tool text come from, per-agent `surfaces` in place of the three removed lists, and the
adapter contract without `get_a2a_card`, across the docs site, `ak-py/README.md`, the dev skills
`ak-dev-architecture`, `ak-dev-new-framework-integration` and `ak-dev-testing-conventions`, the
user skill `ak-add-capabilities` with its evals, and the four examples that expose agents over A2A
or MCP, which now declare a description for each agent). The phase D portion of the docs landed
with phase D (2026-11-25, `plan.md`, "Phase D as shipped": the Authorization section of
`advanced/identity-and-access.md`, the pages of each surface, the configuration reference, the
READMEs, What's New and the features and landing pages). `plan.md`'s docs and skills iterations
(27 and 28) cover phases E and F and the `ak-dev-new-authorizer` skill, and the sync skills
verify the whole before merge.

- **Docs site (`docs/docs/`)**: new `advanced/identity-and-access.md`; `api/rest-api.md`
  (the Authentication section 474-499 and the `user_id` context claim 192-207, already
  inaccurate); `api/agui-server.md:26-76`; `integrations/agui.md:21-120`; `api/mcp-server.md:37,
  85-91` (an agent's tool is described by its declared description, set with `Module.describe`
  or the overlay, not by its instructions); `api/a2a-server.md:18-29, 79, 141` (the card is built
  from the agent's descriptor, not by the adapter's `get_a2a_card()`; how to give a card its
  description and version; the restart needed for an agent registered after mount);
  `core-concepts/configuration.md:58-72, 128, 324-332, 524,
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
  changed and deleted files plus the new ones, and its stub agent at 265, which loses
  `get_a2a_card`; `ak-dev-new-messaging-integration/SKILL.md:34,
  124` (the `namespace` field and the authorizer bypass); `ak-dev-new-framework-integration/
  SKILL.md:273-284` (the adapter contract loses `get_a2a_card` and gains `get_tool_names`,
  `_tool_descriptions` and `ungated_tool_names`); new `ak-dev-new-identity-provider` and
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
  gains a note that the default resolver now covers it. `examples/cli/session-context/
  hooks_test.py:40` drops the `get_a2a_card` its stub agent no longer needs.
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
8. **A2A cards come from the registry, not the adapters** (decided 2026-11-16, before iteration
   14). The descriptor and the A2A card describe the same agent, and the design already made the
   card a projection of the descriptor; detailing left two descriptors in play (the agent's own,
   which each adapter's `get_a2a_card` would have rendered, and the registry's, which carries the
   config overlay) and kept the card dependent on the process hosting the agent. The registry's
   descriptor is now the one record: `A2A._build` builds every card from
   `registry.descriptors()`, `Agent.get_a2a_card` leaves the adapter contract, the overlay-applying
   `register` sets the final descriptor back on the agent, and a skill's description reaches the
   descriptor through `Agent._tool_descriptions`. Two consequences follow from rules the design
   had already set: a card's description is only ever the declared catalog text (never
   `get_description()`), so it is empty until declared and a warning says so; and the skills,
   which default to one per tool, are narrowed with the tools wherever the caller's level narrows
   them, in the catalog and on a served card. Cards are still built once at mount (the SDK binds
   them), which leaves an agent registered later unserved until a restart (section 6, A2A card;
   section 8.7). MCP follows the same rule (extended 2026-11-17): its agent tools are registered
   from the registry's descriptors and described by the declared catalog text, where they were
   built from the hosted agents and carried their instructions; an agent with no declared text
   gets a neutral sentence about the call instead of an empty description, since a client chooses
   a tool by that text (section 8.6).
9. **An unknown agent answers like a hidden one** (decided 2026-11-18, after iteration 16). The
   design makes a hidden agent indistinguishable from one that does not exist, and gives it a
   404; detailing had left the agent that really does not exist as the 400 it was before the
   change (`ValueError("No agent available")`), and the gate's own absent-descriptor case as a
   `KeyError`, so the status told the two apart. One error now covers all three:
   `LookupError(f"Agent '{name}' not found")`, from `ensure_agent_available` for an unknown name
   and from `AccessGate.authorize_agent` for an absent or invisible one, mapped to 404 with that
   body on the HTTP routes (REST chat, the pipeline chat route, threads, schedules, AG-UI). The
   two surfaces that answer in another form keep it, the same for unknown as for hidden: MCP's
   `ToolError("Agent not available")` and the schedule tools' `{"error": ...}`. A request naming
   no agent stays a 400. It lands in iteration 17a with the mapping (section 6, Availability;
   section 7).
   Amended in iteration 17a (2026-11-23), three points. The error is `AgentNotFoundError`, a
   `LookupError` subclass with that text, and the surfaces map that class alone: they catch
   around the whole run, where a `KeyError` or `IndexError` from a session store, a thread store
   or a hook is a lookup error too and has to stay a 500. The `hosted=True` form of the check
   raises it for a named agent the registry knows from another process, which detailing had left
   as the 400: beside the unknown name's 404, that status would have said the name exists. And
   the schedule routes get no mapping, since none of them reaches the check: a task is created by
   a chat request, and an amendment cannot change its agent.
10. **A duplicate id is refused per process, not across the store** (recorded 2026-11-19, from
   the phase C review). Design section 4 has `register` raise `AgentRegistrationError` on a
   duplicate `id`. Replicas of one agent register the same id by design, and a store cannot
   tell a replica from a different agent another process put under that id, so only an agent
   this process already hosts under the id is a duplicate (`AgentRegistry._ensure_free`).
   Across processes the later registration replaces the record, and either process's
   `deregister` removes it. Stamping the record with an owner to tell the two apart was
   considered and left out: nothing would act on the difference except to refuse a rolling
   deployment's second replica (section 6).
11. **The registry takes no TTL** (decided 2026-11-19, from the phase C review). Design section
   4 gives the store records a `ttl` defaulting to 0. With any other value a record expired
   while its agent ran, because nothing registers a hosted agent again, and the agent left the
   catalog, A2A, MCP and AG-UI; a liveness refresh is what a TTL would need, and none ships.
   The backends therefore take no `ttl` and a value under a store block is refused at load.
   Retiring an agent from a shared registry is deleting its record (section 6; section 9).
12. **The config overlay is applied on read as well as at registration** (decided 2026-11-19,
   from the phase C review). Applied at `register` alone, `registry.agents.<id>` took effect
   only in the process that hosts the agent, so a `surfaces` restriction in the configuration
   of a process that serves agents hosted elsewhere was ignored without a word, where the lists
   it replaces were read by exactly that process. The overlaid registry applies its entries to
   every descriptor it returns, and matches a key that differs from an id only in case, which
   is how an environment variable spells it (section 6, descriptor sources).
13. **`surfaces` governs the REST chat routes, not only the catalog** (decided 2026-11-19, from
   the phase C review; iteration 17b). The design narrows the catalog routes by `surfaces` and
   says nothing of the chat route, so an agent kept off `rest` was hidden from the listing and
   still ran for anyone who named it, unlike the other three surfaces, where leaving a surface
   out makes the agent unreachable on it. A REST-entered chat request now gets the answer an
   unknown agent gets. The request carries its entry surface, set where its principal is set,
   so the one availability check enforces it for requests that are queued and run elsewhere
   (section 6, Catalog).
   Amended in iteration 17b (2026-11-23), four points. A client that sends `surface` is refused
   like the other internal fields, where the plan had the entry point overwrite it: a body may
   carry any extra key as context for the pre-hooks, `surface` is a likely one, and dropping it
   would change what an agent sees without a word. The unnamed request at an edge still asks
   only whether the registry knows an agent, since the default is the running process's to pick
   and the alternative is a listing of the store per request. `AgentService.select` applies the
   surface to a named agent too, so it cannot select what the check would refuse. And the check
   runs where the agent runs: for a queued request that is the runner, with the descriptor the
   runner holds, so an overlay set only at the edge does not narrow a queued REST chat request
   until the edge precheck of iteration 19, and for A2A, MCP and AG-UI the runner's check is
   added to the edge's (an edge overlay can narrow what the hosting process declares, no longer
   widen it). Left open: a task that names no agent, created by a REST request, runs the firing
   process's default whatever its `surfaces`, because an occurrence carries no surface; keeping
   the creating surface on the task would close it and is a decision for the iteration that
   next changes the task record (19).
14. **The description defaults to a native description field** (decided 2026-11-19, from the
   phase C review). The design never defaults `description` from `get_description()`, which
   for most frameworks is the system prompt, and refinement 8 left it empty until declared.
   Where a framework keeps a description of the agent apart from its instructions, that text is
   catalog text already, so `Agent._native_description()` seeds the descriptor with it and a
   declared description replaces it (an empty declared one withholds it). Frameworks without
   such a field are as before. It softens the break for the agents whose cards carried a real
   description, at the cost of publishing a field written for a neighbouring audience (a
   handoff description) without a declaration; instructions stay unpublished (section 6,
   descriptor sources).
15. **The static authorizer's policy sits in its own section of the block** (decided 2026-11-23,
   after iteration 17). Design section 5 and the config example put `grants` and `tools` directly
   in the `authorization` block, and the factory handed the static backend the two lookups it
   needs. That made the one backend that ships a special case twice: the shared block carried one
   backend's policy as its own keys, with nowhere for a second engine's, and
   `AuthorizerFactory.create` took parameters only `static` used while a bring-your-own
   authorizer was built another way. The policy is now `authorization.static.grants` and
   `authorization.static.tools`, the shape `identity.provider.static` already has; `create` takes
   the block and nothing else; and the static backend supplies its registry and system tool
   lookups itself, in `from_config`. A block of type `static` with no `static` section is refused
   at load, where it denied every agent with a warning; an empty section still does that.
   Nothing enforced or documented the block yet, so no configuration in use changes. Weighed
   against it: one more level of YAML for the only backend that ships, and `type: static` beside
   `static:` (section 7; Config changes).
16. **The access gate, where building it settled the outline** (iteration 18, 2026-11-23). Five
   points, each written into the section it belongs to.
   A backend's policy is checked by the backend: `Authorizer.validate(agents, descriptors)` is a
   hook the gate calls, with the static backend's three checks behind it, where design section 5
   had the gate read the static policy itself. After refinement 15 the gate knows no backend's
   settings, and an engine that can read its policy back gets the same startup check.
   The findings that compare the policy with every registered agent are not made as a module
   loads (`registry_wide=False`): an application with two modules would be warned, once and
   wrongly, about the agents of the second. They are made where the registry is complete, at
   `get_router()` (iteration 19).
   A shared-channel session is matched on its platform scope alone. The design's rule tried the
   owner's namespace and subject first for every session.
   A request naming no agent is decided for the default agent where the agent runs, and a
   default the caller may not see is `No agent available`: the 404 would have named an agent the
   request did not.
   The gate's synchronous forms answer from inside a coroutine by running the question on a
   thread of their own, because the availability check is synchronous and is reached from
   `ChatService.execute`. The alternative was an `async` twin of the check and of everything
   between it and the routes; the cost of this one is that a remote engine holds the event loop
   for the length of that one question, where `Runtime` awaits it (sections 3, 6 and 7).
17. **The edge, the catalog and the occurrence, where building them settled the outline**
   (iteration 19, 2026-11-23). Five points, each written into the section it belongs to.
   A task keeps the surface of the request that created it, which closes the point refinement 13
   left open: `surfaces` is strict since iteration 17b, and a chat request that scheduled a task
   without naming an agent reached, when the task fired, an agent kept off the surface it came
   in by. The occurrence is now served what the request would have been. A task a schedule tool
   creates has no surface and is governed by none, as before.
   The precheck at the accepting process is not made by a process whose registry knows no agent.
   Design section 6 has the edge refuse before it enqueues; a split deployment whose accepting
   process neither loads the agent modules nor shares a registry (shipped examples do this for
   plain REST chat) would have answered every request 404. Such a process leaves the answer to
   the runner, which asks in any case, so nothing is admitted that would run. The precheck is
   an early answer and the edge's own view of `surfaces`; the boundary is the process that runs
   the agent. A request naming no agent is left to the runner as well.
   The skip of a scheduled occurrence follows the availability check, with or without an
   `authorization` block, because a removed agent and a hidden one raise one error and must stay
   one answer. A task naming no agent with none to default to keeps its 400, and its reason is
   recorded too. The skipped reply is a type of its own so the 403 cannot be triggered by what
   an agent says.
   A catalog entry is narrowed over the tools its descriptor records, for hosted agents as for
   those hosted elsewhere, by `filter_tools`; section 6's outline took a hosted agent's from a
   full `tool_filter`. One rule for both, and no question per denied tool for reasons a listing
   never shows.
   `ScheduleStore.record_trigger` gains `error`, and the manager passes it only for an
   occurrence that was not run, so a bring-your-own store written before it keeps working for
   every occurrence that is (sections 6, 7, 8.1, 8.3 and 8.11).
18. **The protocol surfaces, where building them settled the outline** (iteration 20,
   2026-11-25). Five points, each written into the section it belongs to.
   A2A answers a refusal in front of the SDK. The a2a-sdk has no permission error and its REST
   errors are 400, 404 and 500, so the design's "403" cannot come out of the executor: each
   protocol route carries a dependency that asks the gate first, and a hidden agent gets the
   bare 404 of a path that is not mounted, on every one of its routes and not on its card
   alone. Seeing an agent serves its card; a level is needed for everything else.
   A card's ETag is the SDK's, over the card as served. Section 8.7 planned to compute one; SDK
   1.2.3 does it for a card built by `card_modifier`, with the conditional request handled, so
   the narrowing is that modifier and nothing is hashed here.
   The surfaces that serve a fixed set decide from it. A2A keeps the descriptors its cards were
   mounted with and the direct AG-UI handler asks about the agents it hosts
   (`visible_agents(principal, descriptors)`), so neither lists nor reads the registry per
   request, and what a caller is shown agrees with what is mounted until the next start.
   A realtime refusal is told once and held back, because raising it handed every audio frame
   of the call to the queue's retries. The same holds, without an `authorization` block, for a
   call naming an agent the runner does not host.
   A default agent the caller may not see is not named on AG-UI's bare route, the rule
   refinement 16 set for a request naming no agent.
   Closed on 2026-11-25, after the iteration was committed: what the router answers before any
   check runs. Because A2A routes are mounted per agent, a method a route does not serve (405),
   a credential the provider refuses (401) and a trailing slash (a redirect) each told a mounted
   name from one that is not, the first and the last for any caller. The first account here
   named only the 401. One route behind the agents' own (`UnservedA2ARoute`) now takes every
   request under `/a2a/<name>/` that no A2A route served and answers the 404 of an unmounted
   path, behind the identity dependency, so all three are one answer for every name. It stands
   aside without an `authorization` block. The cost, with the block: a wrong method on a real
   route is a 404 where it was a 405 naming the method. Deciding the 401 per agent, the other
   way considered, would have closed the 401 alone (sections 7, 8.4, 8.5, 8.6 and 8.7).
19. **A hosted agent's tags are read from its own descriptor** (decided 2026-11-25, from the
   phase D review). Section 7 resolved a `tag:` entry against a listing of the registry for
   every question. Over a shared registry that listing is a scan of the store, made for the
   tags of the one agent asked about, and a run asked it several times: the check before the
   run, `Runtime._admit`, the allowed list, and once more for each tool denied by its tier.
   On the direct chat path the first of those is the gate's synchronous form, which holds the
   server's event loop until its answer is in (refinement 16), so with a `tag:` grant the loop
   waited on a store read for every request. Refinement 16 had accepted that for a remote
   engine, not for the backend that ships.
   The static backend now takes a second lookup, `hosted_descriptor`, and asks it first: an
   agent the process hosts answers from its own descriptor, as it already does for its
   visibility (`AccessGate._descriptor`). Every run is of a hosted agent, so no run reads the
   registry for a tag. The registry is still listed for an agent hosted elsewhere, at most once
   per question or listing, and the edge that asks about one asks off the event loop. The
   `Authorizer` contract is unchanged.
   Left as it is: a process that hosts none of the agents it serves, the accepting side of a
   split deployment, lists the registry once for each agent it is asked about on behalf of a
   caller holding a `tag:` grant (a catalog page or the A2A catalog narrowed entry by entry,
   MCP `tools/list`). Reading the one descriptor, or one listing per request, would cut that;
   it waits for a deployment that shows the cost (section 7).
20. **The first four tool gates, where building them settled the outline** (iteration 21,
   2026-11-25). Six points, each written into section 9.
   A gate refuses a tool the filter never listed. `ToolFilter.allows` was always so; what
   building the gates showed is the consequence: an adapter has to declare every tool its gate
   can see, or a run under an `authorization` block loses that tool with no policy able to offer
   it. The phase C review had listed the undeclared tools; each is closed or refused here.
   An OpenAI run keeps the filter of the agent it started with while a handoff, or an agent used
   as a tool, has it calling another agent's tools. Gated with only its own tools declared, a
   triage agent would have had every tool of the agents it hands off to refused. Those agents
   are walked, their tools declared under the first agent and gated. A policy for the agent a
   caller runs therefore states the tiers of the tools it reaches; the policy of the agent
   handed off to is not consulted in that run.
   What OpenAI can neither declare nor gate is refused at startup, as Q12 settled for
   application-bound tools: an MCP server's tools, listed only once a run connects, and the
   tools behind a handoff that does not hold its agent. The table had `[]` there. A hosted tool
   stays declared and not gated: the provider runs it.
   The OpenAI gate is installed only when the block is configured. Installed always, as the
   table read, every tool call of every deployment would run one more guardrail and carry its
   result, and `is_enabled` would no longer be the value the application set.
   Pydantic AI answers a denied call through `wrap_tool_execute`, with the reason as the result.
   Refinement 2 chose `before_tool_execute` raising `ModelRetry`, which tells the model to call
   again and fails the run when the retry budget is spent.
   A call approved while its run was paused is decided again by the filter of the resume, on
   every adapter that pauses: the policy or the caller's level may have changed in between
   (section 9; behavioural changes 44 and 45).
21. **The ADK and CrewAI gates, where building them settled the outline** (iteration 22,
   2026-11-25). Four points, each written into section 9.
   A framework's own control-flow tools are not gated. ADK reaches its transfer and its
   structured-response tool through the same callback as an application tool, and CrewAI its
   delegation tools through the same hooks. No agent declares them, so refinement 20's rule
   would have refused every one and a run could not have moved between agents. The gate
   recognises them by type and stands aside; the tools the run reaches next are gated. A policy
   therefore cannot deny a move between agents, as it cannot deny an OpenAI handoff.
   What a run can reach is declared under the agent it started with, on these two as on OpenAI:
   an ADK agent used as a tool and the nodes of a nested workflow, and the coworkers of a CrewAI
   agent that may delegate. One walk serves the declaration and the gate on ADK.
   On CrewAI the model reads the reason. The table expected CrewAI's own blocked-by-hook line
   to be all a refused call could answer; an after hook's return replaces it, and CrewAI runs
   after hooks for a blocked call.
   Both gates are put in place only when the block is configured, as the OpenAI one is: ADK's
   callback list and CrewAI's process-wide hook lists are otherwise as the application left
   them (section 9; behavioural changes 46 and 47).
22. **The last gates, the realtime room and provider-run tools** (iteration 23, 2026-11-25).
   Five points, each written into section 9 or 8.4.
   A multi-participant call runs its tools as all of its speakers. Section 8.4 left open which
   identity a room runs as, because the connection's principal is whoever spoke last. Keying the
   gate on the last speaker would let a participant borrow another's level by speaking after
   them; keying it on the caller who opened the call would let every later participant use that
   caller's level. The room's filter is the intersection of every speaker's, which no order of
   speech changes. The principal a tool reads stays the last speaker's.
   smolagents' `final_answer` and a call to a managed agent are not gated, as refinement 21 set
   for other control-flow tools, and the managed agents' tools are declared under the manager.
   The phase C review had found `final_answer` declared, which an `allow` list would have had to
   name.
   A smolagents code agent on a remote executor is ungated as a whole. Wrapping `forward` there
   does nothing at best: the executor rebuilds each tool from its source in the sandbox.
   OpenAI's realtime session does not tell the model the reason. It runs input guardrails for an
   ordinary call only when pre-approval guardrails are configured, and it asks `is_enabled` on
   every call, so a denied tool is one it does not find. Adding a third hook to every native tool
   (`on_invoke_tool`) to carry the reason was judged not worth the change.
   Tools a provider runs are warned about, not refused, as design Q12 settled; this iteration
   adds the report (`Agent.provider_tool_names`) and the warning (section 9; behavioural changes
   48 to 50).
23. **The credential store encrypts** (iteration 24, 2026-11-26). Section 5 handed the broker a
   store and a cipher beside it, which left every caller to seal a value before `put` and open it
   after `get`, and a caller that forgot would write a credential to a shared database as it came.
   The store now owns its cipher: `put` seals, `get` opens, the store key is the associated data,
   and a backend sees ciphertext only. A store shared with other processes refuses to be built
   without a key, which also covers a bring-your-own one. Redis and Valkey write a value and its
   expiry in one command rather than two, and DynamoDB checks the expiry on read, since its own
   TTL removes items late, and reads strongly consistently, since the process that reads a
   credential is often not the one that wrote it a moment earlier (section 5, "As built").
24. **Retention is the surface's call, and one manager holds it** (iteration 25, 2026-11-26).
   Section 4 minted a `credential_ref` inside authentication, so every caller of
   `authenticate_bearer` and `authenticate_token` would keep a credential whether or not it could
   release it: the Lambda authorizer's cached result would hand one reference to many requests, and a
   WebSocket handshake would get a reference the first frame's run deleted. Authentication now keeps
   nothing, and each surface that keeps a credential calls `CredentialManager.retain` itself, for a run
   or for a connection, beside the code that ends it. The store, the exchangers and the lifecycle sit
   on one process-wide `CredentialManager`. The identity dependency retains only for an HTTP request
   that can start a run (not `GET`, `HEAD` or `OPTIONS`) and never on a WebSocket handshake, and the
   Lambda authorizer builds no manager at all. On MCP the executor retains, for each tool call, since
   FastMCP asks the verifier on every HTTP request of a session (found after the FastMCP 4 upgrade,
   #1013: two tool calls came with four to seven verifications). The broker reads the run's own
   inbound credential before its cache, and the cache key carries a digest of it, so a run whose
   credential is gone, or a later credential of the same user, is served nothing cached; `passthrough`
   caches nothing, since what it issues is the inbound token itself, and caps the expiry it reports at
   `inbound_ttl`. The AWS adapters follow in iteration 25b (sections 4 and 5, "As built").
25. **A connection's credential is renewed through the store** (iteration 25b, 2026-11-26). Design 3.1
   renewed a token without `exp` from the token a gateway still held in memory, which left Lambda, with
   no memory between frames, unable to renew. Renewal extends the stored entry with
   `CredentialStore.touch`, which extends only an entry still live, in one step on every backend (a
   lock in memory, `EXPIRE` on Redis and Valkey, a conditional update on DynamoDB), so every frame on
   every deployment keeps it, nothing holds the token in memory, and a disconnect in another process
   between two frames stays final. The CLI renews before each prompt's run. The Lambda REST router
   retains from the request's own header where a run starts, never the authorizer, and both AWS
   WebSocket APIs retain at `$connect` and forget at `$disconnect`; both refuse a store that is not
   shared (section 4, "As built").
