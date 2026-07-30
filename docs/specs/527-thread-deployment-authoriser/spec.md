# #527: Thread store deployment support and Authoriser support for serverless and ECS — Implementation Spec

This spec details how the requirements in [`design.md`](./design.md) are built. It covers four bodies
of work: (1) a Valkey thread store in core; (2) DynamoDB thread-store provisioning and `AK_THREAD__*`
env wiring on the AWS Terraform, plus Firestore env wiring on the GCP Terraform (each mirroring its
cloud's existing session-store flag; Redis/Valkey thread wiring stays fully manual — no new Terraform
variables; Azure is out of scope for this change, see design.md Non-goals); (3) reusable thread-handler
logic for the Lambda serverless path that the deployer wires up themselves via the existing
`Lambda.register` decorator, at manually-configured `gateway_endpoints` paths, protected by the
existing gateway-level `APIGatewayAuthorizer`; and (4) an `Authoriser`-mounting parameter on ECS's
queue-mode `ECSIOHandler`. `design.md` is the requirements source — every requirement there maps to a
section here.

## Design

### Core: Valkey thread store

New store `ValkeyThreadStore` in `ak-py/src/agentkernel/core/thread/store/valkey.py`, a near-exact
twin of `RedisThreadStore` (`core/thread/store/redis.py:25-199`) differing only in which driver and
config block it reads — exactly how `ValkeySessionStore` (`core/session/valkey.py:10-96`) twins
`RedisSessionStore`. Redis and Valkey share one command surface via `_RedisLikeDriver`
(`core/util/driver/redis_like.py:16-298`; `ValkeyDriver` in `core/util/driver/valkey.py:8` simply
subclasses it), so the store body (key schema, `SET NX` create, `RPUSH` append,
`LRANGE`/`LLEN` paging, user/group index sets, TTL refresh) is identical.

```python
class ValkeyThreadStore(ThreadStore):
    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.valkey")
        cfg = AKConfig.get().thread.valkey                 # thread.valkey, not thread.redis
        if cfg is None:
            raise ValueError("AKConfig.thread.valkey must be set to use ValkeyThreadStore")
        self._prefix = cfg.prefix
        self._driver = ValkeyDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
    # create / update_name / load_metadata / append_message / get_messages /
    # list_threads / clear — identical bodies to RedisThreadStore
```

Governing rules:

1. **The store body is shared, not re-invented.** To avoid two divergent copies of the same key
   schema, factor the Redis body into a common implementation parameterised by the driver, and have
   both `RedisThreadStore` and `ValkeyThreadStore` supply their driver + config block. Simplest form:
   a `_RedisLikeThreadStore` base holding every method, with the two concrete classes providing only
   `__init__` (driver choice + config block + logger name). This mirrors the driver hierarchy
   (`_RedisLikeDriver` → `RedisDriver`/`ValkeyDriver`) and keeps the "one concept, one name" rule.
2. **Drivers never read `AKConfig`** — `ValkeyThreadStore.__init__` reads `thread.valkey` and passes
   explicit `url`/`prefix`/`ttl` to `ValkeyDriver`, same as the Redis store and every other driver
   consumer (per `ak-dev-architecture` shared-driver rule 1).
3. **`valkey` stays an optional extra.** The concrete module `import`s `ValkeyDriver`, which imports
   `valkey` at module top (`core/util/driver/valkey.py:3`); the builder guards that import with the
   `require_extra("valkey", ...)` context manager that raises the hinted `ImportError` (see below).

Builder wiring in `ThreadStoreBuilder` (`core/thread/store/base.py:139-186`). Post-#541 the builder
is a lowercase-key `if` chain with a `require_extra(...)` guard around each built-in import, a
`_BUILTIN_THREAD_STORES` list (`base.py:13`) named in the unknown-type `AKConfigError`, and a
`resolve_dotted` bring-your-own branch — there is no `Types` StrEnum:

- Add `"valkey"` to `_BUILTIN_THREAD_STORES` (`base.py:13`), between `"redis"` and `"dynamodb"`.
- Add a `valkey` branch to `build()` mirroring `SessionStoreBuilder`'s guarded Valkey path
  (`core/builder.py:108-112`); `require_extra` raises `ImportError` with the pip-extra hint
  (`core/util/factory.py:50-64`):

  ```python
  if key == "valkey":
      with require_extra("valkey", "thread.type: valkey"):
          from .valkey import ValkeyThreadStore

      return ValkeyThreadStore()
  ```

Config in `core/config.py`:

- Add `_ThreadValkeyConfig(_ValkeyConfig)` next to `_ThreadRedisConfig` (`config.py:220-223`),
  overriding `ttl` default to `2592000` (30 days, matching the Redis thread default) and `prefix`
  default to `"ak:thread:"`:

  ```python
  class _ThreadValkeyConfig(_ValkeyConfig):
      ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
      prefix: str = Field(default="ak:thread:", description="Key prefix for Valkey thread storage")
  ```
- Add `valkey: Optional[_ThreadValkeyConfig] = None` to `_ThreadStoreConfig` (`config.py:251-262`).
  Post-#541 `_ThreadStoreConfig.type` is a **description-only** field (no regex `pattern`,
  `config.py:254-257`); adding a backend means adding `"valkey"` to the built-in short-name list in
  the `type` field's `description` (and to `_BUILTIN_THREAD_STORES`), not editing a pattern. This
  aligns the thread store's built-in set with `SessionStoreBuilder`, which already has `valkey`.

### Serverless (Lambda): generic path-parameter routing

A standalone platform capability in `RESTLambdaRouter.dispatch()` (`rest_lambda.py:354-388`),
independent of thread — usable by any custom Lambda route, present or future.

**The gap**: `dispatch()` matches against `event["path"]` (the *concrete* URL, e.g.
`/api/v1/threads/abc-123`) exclusively — never `event["resource"]` (the *template* API Gateway
matched, e.g. `/api/v1/threads/{session_id}`, curly braces intact). A route registered via
`Lambda.register("/threads/{session_id}", method="GET")` already sits in `self._routes` under that
exact literal string (`register()` does no parsing of its `route` argument at all) — it just never
gets looked up correctly, and the request 500s via `dispatch()`'s no-route `ValueError`.

**The fix** — an additive fallback, appended after the existing lookup:

```python
# RESTLambdaRouter.dispatch(), after the existing exact-match lookup on `converted_event_path` misses:
if not handler:
    resource = event.get("resource")
    if resource and env_base_path:
        methods = self._routes.get(resource.removeprefix(env_base_path), {})
        handler = methods.get(method)
```

Governing rules:

1. **Still zero wildcard/regex parsing** — this is a second literal-string dict lookup, on a
   different field. API Gateway itself already resolves which resource template matched a given
   request and populates `event["pathParameters"]` accordingly; the router's only job is finding the
   handler registered under that same template string.
2. **`register()` is untouched.** `@Lambda.register("/threads/{session_id}", method="GET")` is
   already legal Python today — the string is just an opaque dict key to `register()`. This fix makes
   that already-legal call work.
3. **Zero regression risk for existing routes.** The fallback only ever triggers when the primary
   `path`-based lookup misses — i.e., only for requests that would otherwise hit the no-route
   `ValueError` today. Every existing static route (all four current examples using `Lambda.register`)
   matches on the first attempt, completely unaffected. This must be proven by a dedicated regression
   test asserting existing dispatch behavior is unchanged (see Testing), not just asserted here.
4. **Interacts with, but does not change, the default-chat-path special-casing** earlier in the same
   function (`rest_lambda.py:368-380`) — that logic runs first and is untouched; the new fallback
   only applies to the custom-route lookup that follows it.

### Serverless (Lambda): thread REST routes

The Lambda REST path does not use FastAPI — `RESTLambdaRouter` (`rest_lambda.py:292-388`) dispatches
raw API Gateway REST v1 events against a `self._routes[path][method]` table, populated via the
already-public `Lambda.register(route, method)` decorator (`aklambda.py:38-47`, delegating to
`RESTLambdaRouter.register`, `rest_lambda.py:327-352`) — the same decorator four existing examples
already use for custom routes (`examples/aws-serverless/openai-auth/lambda.py:30-38`,
`scalable-openai/lambda_request_handler.py`, `streaming-openai/lambda_request_handler.py`,
`websocket-openai/lambda_request_handler.py`).

**AK does not auto-register any thread routes.** Instead it exposes reusable thread-handling logic
that the deployer wires up themselves, in their own `lambda.py`, exactly like any other custom Lambda
route — no changes to `rest_lambda.py`, `aklambda.py`, or `common.py` at all.

New `ThreadLambdaHandler` in `ak-py/src/agentkernel/deployment/aws/serverless/akthreadhandler.py`,
reusing `ConversationThreadManager` (the same data path `ThreadRESTRequestHandler` uses,
`api/thread.py`) — no logic is re-implemented, only the transport differs:

```python
class ThreadLambdaHandler:
    """Reusable thread list/detail handlers for a deployer's own Lambda.register(...) wiring."""

    def _resolve_user(self, event) -> Optional[str]:
        # principal injected by the gateway APIGatewayAuthorizer; None when no
        # authorizer is attached (routes open — same semantics as ThreadRESTRequestHandler)
        return (event.get("requestContext", {}).get("authorizer") or {}).get("principalId")

    def list_threads(self, event, context) -> tuple[int, dict]: ...
    def get_thread(self, event, context) -> tuple[int, dict]: ...
```

Handler behaviour mirrors `ThreadRESTRequestHandler.get_router()` (`api/thread.py:57-107`) exactly,
now that the generic path-parameter routing above makes the path-parameter shape work on Lambda too:

- Both call `ConversationThreadManager.get()`; when it is `None` → `(404, {"error": "Thread support
  is not enabled"})` (matches `api/thread.py:72-73,89-90`).
- `list_threads`: read `user_id`/`group_id`/`limit`/`cursor` from `event.get("queryStringParameters")`;
  when `_resolve_user` returns non-`None`, force `user_id` to it (matches `api/thread.py:74-76`); call
  `manager.list_threads(...)`; return the same `{"threads": [...exclude messages...], "next_cursor":
  ...}` body (matches `api/thread.py:81-84`); `ValueError` (bad cursor) → `(400, ...)`.
- `get_thread`: `session_id` from `event["pathParameters"]["session_id"]` (populated by API Gateway
  once the detail route's `{session_id}` template matches, per the routing fix above); call
  `manager.get_thread(session_id, user_id=resolved)`; `PermissionError` → `(403, ...)`, `None` →
  `(404, ...)`; then `manager.get_messages(...)`; return the merged thread + messages + `next_cursor`
  body (matches `api/thread.py:86-105`).

Governing rules:

1. **List is a flat endpoint; detail uses a `{session_id}` path parameter**, symmetric with
   ECS/FastAPI's `/api/v1/threads/{session_id}`. This depends on "Serverless (Lambda): generic
   path-parameter routing" above — without that fix, `Lambda.register("<path>/{session_id}", ...)`
   would never match a real request, since the router previously matched only against
   `event["path"]` (concrete), never `event["resource"]` (template).
2. **The deployer chooses both path names and wires both decorators themselves**, e.g.:

   ```python
   from agentkernel.aws import Lambda, ThreadLambdaHandler

   thread_handler = ThreadLambdaHandler()

   @Lambda.register("/threads", method="GET")
   def thread_list(event, context):
       return thread_handler.list_threads(event, context)

   @Lambda.register("/threads/{session_id}", method="GET")
   def thread_detail(event, context):
       return thread_handler.get_thread(event, context)
   ```

   Path names are illustrative — the deployer names them whatever they like, as long as the same
   names (including the `{session_id}` segment) are used in the `gateway_endpoints` Terraform entries
   (see below).
3. **`ThreadLambdaHandler` is exported alongside `Lambda`** — add it to
   `deployment/aws/serverless/__init__.py` and `deployment/aws/__init__.py` (both already re-export
   `Lambda` from `aklambda.py`; `agentkernel/aws.py`'s `from .deployment.aws import *` picks it up
   automatically) so `from agentkernel.aws import Lambda, ThreadLambdaHandler` works.

Handler returns are `(status, dict)` tuples; `Lambda._wrap_response` (`aklambda.py:50-67`) already
serialises those to `{"statusCode", "body": json.dumps(...)}` — this is what every other
`Lambda.register`-decorated handler already returns, so no new response-shape handling is needed.

### Serverless (Lambda): authorization

Authorization is **not** done inside the thread Lambda. It rides on the existing gateway-level
`APIGatewayAuthorizer` (`deployment/aws/serverless/akauthorizer.py:24-101`) — a separate REQUEST
authorizer Lambda that validates the Bearer token via a user-supplied `AuthValidator` and returns an
IAM policy whose `principalId` is the validator's `subject` and whose `context` is the validator's
`claims` (`akauthorizer.py:35-48,75-92`). The example wiring is
`examples/aws-serverless/openai-auth/lambda_auth.py:8-19`.

- When the deployment attaches an authorizer to the thread routes (via the Terraform `authorizer`
  variable), API Gateway injects `requestContext.authorizer.principalId`; the thread handler reads it
  as the owning `user_id`. Listings are forced to that user and detail reads enforce ownership — the
  same scoping `ThreadRESTRequestHandler` applies with an `Authoriser`.
- When no authorizer is attached, `requestContext.authorizer` is absent, `_resolve_user` returns
  `None`, and the routes are open — identical to `ThreadRESTRequestHandler` with no `Authoriser`
  (`api/thread.py:43-44`).
- No new cold-start hook, no in-Lambda `Authoriser` instance, and `authoriser.py`'s `Authoriser` ABC
  is not used on the serverless path.
- **Risk — implement and test this carefully.** There is no code-level guard here that fails closed:
  `_resolve_user`'s `(event.get("requestContext", {}).get("authorizer") or {}).get("principalId")`
  returns `None` in two situations that must stay distinguishable in tests even though they hit the
  same code path — (a) no authorizer attached at all (intentionally open, per above), and (b) an
  authorizer *is* attached but a misconfiguration or bug leaves `principalId` unset (unintentionally
  open — a silent security gap). Both need an explicit assertion in `tests/test_lambda_thread_routes.py`
  (see Testing) so this equivalence is a deliberate, tested design choice rather than an accident of
  the code path.

### Serverless (Lambda) Terraform: DynamoDB thread table

Mirror the session-memory table wiring end to end.

- **Variable**: `create_dynamodb_thread_table` (bool, default `false`) in
  `ak-deployment/ak-aws/serverless/variables.tf`, beside `create_dynamodb_memory_table`.
- **Module + locals** in `serverless/state.tf`: a `dynamodb_thread` module cloned from
  `dynamodb_memory` (`state.tf:297-313`) with `count = var.create_dynamodb_thread_table ? 1 : 0`,
  `attributes = [{session_id, S}, {sk, S}]`, `hash_key = "session_id"`, `range_key = "sk"`,
  `ttl_enabled = true`, `ttl_attribute_name = "expiry_time"`, `table_name = "ak-agent-threads"`, and
  **no `global_secondary_indexes`** (`list_threads` is a full `Scan`, not an indexed query —
  `core/thread/store/dynamodb.py`). Add `dynamodb_thread_table_arn`/`_name` locals mirroring
  `state.tf:22-23`.
- **Pass-through** into the `request_handler` block (`state.tf:482-489`) and `agent_runner` block
  (`state.tf:535-540`), following the memory-table pattern. Note the request_handler block zeroes the
  memory flag under `queue_mode` (`state.tf:482`); thread is independent of queue mode (thread routes
  are served by the request handler in non-queue mode; in queue mode ECS/serverless-queue serve them),
  so pass `create_dynamodb_thread_table` through unchanged rather than gating it on `queue_mode`.
- **Env vars** (both `modules/request-handler/main.tf` and `modules/agent-runner/main.tf` env-merge
  blocks, e.g. `request-handler/main.tf:264`), injected only when the flag is true:
  `AK_THREAD__TYPE = "dynamodb"` **and** `AK_THREAD__DYNAMODB__TABLE_NAME = var.dynamodb_thread_table_name`.
  Both together — see Config changes for why `TYPE` is mandatory here.
- **IAM** (both Lambda roles): a policy cloned from `lambda_dynamodb_describe_policy`
  (`request-handler/main.tf:32-59`) granting
  `DescribeTable/GetItem/PutItem/UpdateItem/DeleteItem/Query/Scan` on the thread table ARN only (no
  `/index/*`), `count`-gated on the flag, with its attachment.
- **Module variables**: add `create_dynamodb_thread_table`, `dynamodb_thread_table_arn`,
  `dynamodb_thread_table_name` to `modules/request-handler/variables.tf` and
  `modules/agent-runner/variables.tf`, matching the memory-table variable shape.
- **Route exposure**: manual — the deployer adds `gateway_endpoints` entries for whatever path names
  they chose in their `lambda.py` `Lambda.register` decorators (see "Serverless (Lambda): thread REST
  routes"). `gateway_endpoints` paths are **relative** to `/{api_base_path}/{api_version}` (the
  module prepends `api`/`v1`), so an entry named e.g. `threads` deploys as `/api/v1/threads` —
  **not** `api/v1/threads`, which would deploy `/api/v1/api/v1/threads`. The detail route's
  `{session_id}` segment brings it to 2 segments, within the module's 3-segment limit
  (`modules/api-gateway/main.tf:1-16`); the literal `{session_id}` `path_part` is treated as a path
  parameter, same as containerized. Entries are covered by the deployment's `authorizer` variable,
  same as any other endpoint.

### Containerized (ECS) Terraform: DynamoDB thread table

Same shape as serverless, against the ECS modules:

- `create_dynamodb_thread_table` (bool, default `false`) in
  `ak-deployment/ak-aws/containerized/variables.tf`.
- `dynamodb_thread` module + `dynamodb_thread_table_arn`/`_name` locals in `containerized/state.tf`,
  cloned from `dynamodb_memory` (`state.tf:12-13`, module at `:115`), same key schema / TTL / no-GSI
  as the serverless table.
- Env vars on both `modules/rest-service/main.tf` (beside `rest-service/main.tf:11`) and
  `modules/agent-runner/main.tf` env-merge blocks: `AK_THREAD__TYPE=dynamodb` +
  `AK_THREAD__DYNAMODB__TABLE_NAME`, injected only when the flag is true.
- IAM: a `dynamodb_policy`-style policy (`rest-service/main.tf:33-34`) scoped to the thread table ARN
  attached via `tasks_iam_role_policies` (`rest-service/main.tf:187-188`) on **both** the rest-service
  task role and the agent-runner task role, flag-gated.

### Containerized (ECS): Authoriser mounting

`ECSIOHandler.run()` (`deployment/aws/containerized/ecs_io_handler.py:29-51`) gains an optional
parameter and forwards it into the REST API:

```python
@classmethod
def run(cls, authoriser: Optional[Authoriser] = None) -> None:
    from ....api.http import RESTAPI
    from ....core.thread import ThreadRESTRequestHandler
    from .ecs_queue_handler import ECSQueueRequestHandler

    handlers = [ECSQueueRequestHandler()]
    if AKConfig.get().thread is not None:
        handlers.append(ThreadRESTRequestHandler(authoriser=authoriser))
    # ... existing ThreadRunner.run(...) with the rest-api task calling
    #     RESTAPI.run(handlers=handlers)
```

- Passing `ThreadRESTRequestHandler` explicitly makes `RESTAPI.run`'s auto-mount check
  (`api/http.py:97-104`) skip adding a second, open one (its `isinstance` guard sees the supplied
  handler). When `authoriser=None` the mounted handler is open — behaviourally identical to today's
  auto-mounted one, so existing deployments are unaffected.
- `ThreadRESTRequestHandler` is imported from `agentkernel.api.thread`; `Authoriser` from
  `agentkernel.core.thread` for the type hint (both already public). Import stays inside `run()` to
  preserve the existing lazy-import style (`ecs_io_handler.py:31-32`).
- The entry-point call site `runner = ECSIOHandler.run` (e.g.
  `examples/aws-containerized/openai-dynamodb-scalable/app_rest_service.py`) is unchanged for callers
  who don't need an authoriser; a caller supplying one wraps it: `runner = lambda:
  ECSIOHandler.run(authoriser=MyAuthoriser())`.

### Containerized (ECS): thread route exposure

Mounting the handler (above) only registers the routes inside the service — the containerized HTTP
API must also expose them, the same mechanism as serverless but a different entry shape and, unlike
serverless, no code-side workaround needed: FastAPI already supports path parameters natively
(`ThreadRESTRequestHandler.get_router()` already serves `/api/v1/threads/{session_id}`,
`api/thread.py:63,86`). Routes come from `gateway_endpoints`
(`containerized/variables.tf:51-70`); by default only the chat endpoints exist
(`containerized/state.tf`), so the deployer adds the thread entries.

- The containerized entry shape is `{path, method, overwrite_path}` — `overwrite_path` is **required**
  (validated non-empty), unlike the serverless `{path, method}` shape. Paths are relative to
  `/{api_base_path}/{api_version}`. The HTTP API (v2) imposes no segment-depth limit, and
  `{session_id}` is a valid HTTP API path variable; the detail route's `overwrite_path` must
  reference it so the id reaches the ALB backend (a static `overwrite_path` would drop it):
  - `{ path = "threads",              method = "GET", overwrite_path = "/api/v1/threads" }`
  - `{ path = "threads/{session_id}", method = "GET", overwrite_path = "/api/v1/threads/${request.path.session_id}" }`
- As with serverless, `gateway_endpoints` entries are covered by the deployment's `authorizer`
  variable.

### GCP Terraform: Firestore thread wiring

Thread reuses the Firestore **database** provisioned by `create_firestore_database`
(`ak-gcp/serverless/state.tf:150-152`, `ak-gcp/containerized`) — Firestore collections are created
implicitly on first write, so no new database resource is needed.

- New bool `create_firestore_thread_collection` (default `false`) on both `ak-gcp/serverless` and
  `ak-gcp/containerized`, valid only with `create_firestore_database = true` (documented; optionally a
  `validation` block or precondition).
- Env vars, appended to the existing firestore env block when the flag is true
  (`serverless/cloud_function.tf:160-164`, `containerized/cloud_run.tf:161-164`):
  `AK_THREAD__TYPE=firestore`, `AK_THREAD__FIRESTORE__COLLECTION_NAME` (default `ak-agent-threads`,
  `config.py:228-231`), `AK_THREAD__FIRESTORE__PROJECT_ID=var.project_id`,
  `AK_THREAD__FIRESTORE__DATABASE_ID=module.firestore[0].database_name`. GCP already sets
  `AK_SESSION__TYPE` explicitly (`cloud_function.tf:160`), so thread matches the established pattern.
- **TTL**: the firestore module registers a per-collection TTL field policy
  (`common/modules/firestore/main.tf:20-27`) for the session collection. Thread's Firestore TTL
  defaults to `0` (disabled, `config.py:232`), so no TTL resource is required by default; if a thread
  TTL is later wanted, add a second `google_firestore_field` for the thread collection — out of scope
  unless the deployer sets a thread TTL.
- **IAM**: the service account's existing Firestore datastore access (granted for session storage on
  the same database) already covers the thread collection; verify the binding is database-scoped (not
  collection-scoped) and extend only if not.

### Docs and example

- New `examples/aws-serverless/thread-openai/`, structured like `examples/aws-serverless/openai-auth/`
  (`build.sh`, `config.yaml`, `lambda.py`, `lambda_auth.py`, `lambda_test.py`, `pyproject.toml`,
  `deploy/`, `test-config.yaml`, `README.md`):
  - `config.yaml` declares a `thread:` block (type omitted → Terraform injects `AK_THREAD__TYPE`).
  - `lambda.py` imports `ThreadLambdaHandler` alongside `Lambda` and wires the two thread handlers via
    `@Lambda.register(...)` at the example's chosen path names (e.g. `/threads`, `/threads/{session_id}`)
    — see "Serverless (Lambda): thread REST routes" for the exact pattern.
  - `deploy/` sets `create_dynamodb_thread_table = true` **and** manually lists `gateway_endpoints`
    entries matching the exact path names used in `lambda.py`'s decorators, with the `authorizer`
    wired to the auth Lambda (per `openai-auth`).
  - **`lambda_auth.py` must set a real per-user `subject`.** `ValidationResult.subject` defaults to
    `"user"` (`auth/handler.py:13-17`) and `openai-auth`'s validator never sets it (`lambda_auth.py:14-16`);
    cloned as-is, every authorized caller resolves to principal `"user"`, so list scoping is trivially
    satisfied and a 403 ownership mismatch can never occur. The example validator must map the token to
    a real per-user `subject` (e.g. the JWT `email`), and the chat requests' `user_id` must match that
    subject — otherwise the list route returns nothing for the caller.
  - `lambda_test.py` exercises: chat (creates a thread) → `GET /api/v1/threads` (list) → `GET
    /api/v1/threads/{session_id}` (history) → **a `thread_name` rename step** (via the chat request,
    per issue #527's "exercises chat + thread read + rename" acceptance) → an unauthorized call asserts
    401/403.
  - Register under `weekly.tests` in `.github/integration-test-config.yaml:56-71` as
    `{type: aws-serverless, path: examples/aws-serverless/thread-openai, deploy_dir: deploy}`.
- Docs: document the `AK_THREAD__TYPE` + backend-vars pairing prominently (deployment guide) — thread
  is the one `AK_*` store where Terraform must set the type explicitly, and it is easy to
  misconfigure (feature "on", silently wrong backend). Also document the `Lambda.register` +
  `gateway_endpoints` wiring pattern for thread routes as the canonical example of exposing a custom,
  deployer-named Lambda endpoint.

### Config changes

- `_ThreadStoreConfig.type` is a description-only field post-#541 (no regex `pattern`,
  `config.py:254-257`); add `"valkey"` to the built-in short-name list in its `description` and to
  `_BUILTIN_THREAD_STORES` (`base.py:13`). Additive — every existing value still resolves.
- New `_ThreadValkeyConfig` and `_ThreadStoreConfig.valkey: Optional[...] = None`. Additive; absent in
  existing configs (`None`).
- **`AK_THREAD__TYPE` is mandatory in Terraform env injection.** `AKConfig.thread` is
  `Optional[_ThreadStoreConfig] = Field(default=None, ...)` (`config.py:580`) with no
  `default_factory`, so any `AK_THREAD__*` env var materialises the block, but unset fields fall to
  their model defaults — `type` to `"memory"` (`config.py:254-257`), which `ThreadStoreBuilder.build()`
  reads directly (`base.py:149-153`). Unlike session (where the committed `config.yaml` declares the
  type and Terraform injects only the connection detail), thread is deployment-toggled with no
  committed `thread:` type to fall back on. Injecting only a table name would silently run threads
  in-memory (lost on every cold start / restart). Hence every cloud's Terraform sets `AK_THREAD__TYPE`
  alongside the connection vars.
- No YAML files change; no existing `AK_*` env var changes. Field descriptions are additive (surface
  in generated config docs).

### Behavioural changes

1. **`_ThreadStoreConfig.type` accepts `valkey`.** Intentional — enables the Valkey backend. Existing
   values unaffected.
2. **`thread.type: valkey` without the `valkey` extra raises `ImportError`** with the install hint,
   at `build()` time via `require_extra` (`core/util/factory.py:50-64`). Intentional — mirrors
   `SessionStoreBuilder`'s Valkey path (`core/builder.py:108-112`); fail-fast beats an opaque
   `ModuleNotFoundError`.
3. **`thread.type: valkey` with no `thread.valkey` block raises `ValueError`.** Intentional — mirrors
   `RedisThreadStore`'s missing-config guard (`redis.py:33-34`) and `ValkeySessionStore`'s
   (`valkey.py:24-25`).
4. **`RESTLambdaRouter.dispatch()` gains a path-parameter fallback lookup** keyed on
   `event["resource"]`, tried only when the existing `event["path"]`-based lookup misses. Intentional
   and additive — every existing static route (all four current `Lambda.register` examples) matches
   on the first attempt, unchanged; the fallback only activates for requests that would otherwise hit
   the no-route `ValueError` (`rest_lambda.py:383-385`) today. This is a general Lambda platform
   capability, not thread-specific.
5. **A deployer who wires `ThreadLambdaHandler` via `Lambda.register` gets working
   `GET /threads[...]`-shaped endpoints** — including a `{session_id}` path-parameter detail route,
   thanks to change 4 — at whatever paths they chose, once matching `gateway_endpoints` entries
   exist. Previously no reusable thread-handling logic existed for Lambda at all. Intentional — the
   feature being added; opt-in, entirely under the deployer's own control, same as every other custom
   Lambda route.
6. **ECS `RESTAPI.run` receives an explicit `ThreadRESTRequestHandler`** from `ECSIOHandler` when
   thread is enabled, instead of relying on auto-mount. Intentional and behaviour-preserving when
   `authoriser=None` (open routes, as before); the new capability is that a caller can now pass an
   `Authoriser`.

**Non-changes** (verified): the DynamoDB thread table schema/`Scan` behaviour
(`core/thread/store/dynamodb.py`); `ThreadStore` ABC and the Redis/DynamoDB/Firestore/Cosmos store
bodies; `ConversationThreadManager`'s API and the FastAPI `ThreadRESTRequestHandler`
(`api/thread.py`); `RESTLambdaRouter.register()` and the existing default-chat-path dispatch logic
(`rest_lambda.py:368-380`) — unchanged; only `dispatch()`'s no-route fallback path gains the new
lookup (change 4); the `Authoriser` ABC (`authoriser.py`); the existing `chat_endpoint`/
`default_gateway_map`/`mcp_gateway_map` auto-attach logic (untouched — thread routes never join it);
and all existing session/multimodal/response-store deployment wiring.

## Error handling

- **Thread not configured** (`AKConfig.get().thread is None`): if the deployer has wired
  `ThreadLambdaHandler` regardless, `ConversationThreadManager.get()` returns `None` inside
  `list_threads`/`get_thread`, and both return `(404, {"error": "Thread support is not enabled"})` —
  no `ThreadStoreBuilder.build()` is attempted. The ECS handler skips mounting the thread handler
  entirely in this case. FastAPI/`ConversationThreadManager.get()` returns `None` → 404 on any thread
  route that is somehow reached (`api/thread.py:72-73`).
- **Missing `valkey` extra**: `ImportError` with `pip install agentkernel[valkey]` hint at build time
  (change 2 above).
- **Missing `thread.valkey`/`thread.redis` block for the chosen type**: `ValueError` at store
  construction (change 3; `redis.py:33-34`).
- **`AK_THREAD__DYNAMODB__TABLE_NAME` set but `AK_THREAD__TYPE` unset**: no exception — silently
  in-memory. This is the failure the Terraform contract (always inject `AK_THREAD__TYPE`) prevents;
  documented, and enforced by every cloud's env block setting both.
- **Lambda authorizer absent on a thread route**: `requestContext.authorizer` missing →
  `_resolve_user` returns `None` → open access (matches open `ThreadRESTRequestHandler`).
- **Lambda authorizer attached but `principalId` missing/falsy**: same code path and same result
  (open access) as the fully-absent case above — intentional per `_resolve_user`'s `or {}` fallback,
  but this equivalence must be covered by an explicit test (see Testing), not left as an accidental
  consequence of the missing-authorizer case.
- **Lambda thread reads**: unknown `session_id` → 404; ownership mismatch (`PermissionError` from
  `manager.get_thread`) → 403; malformed cursor (`ValueError`) → 400 — same mapping as
  `api/thread.py:92-101`.
- **Concurrency**: `ConversationThreadManager` is a process-wide singleton guarded by an `RLock`
  (`manager.py:62-90`) — already shared safely across ECS peer threads. `ValkeyDriver` serialises
  connect/reconnect via the per-instance lock in `_RedisLikeDriver` (per `ak-dev-architecture`
  shared-driver notes), so `ValkeyThreadStore` is as thread-safe as `RedisThreadStore`. The Lambda
  router is a cold-start singleton with one event per invocation — no per-request registration race.
- **Per-operation cost**: none added to the chat hot path — the Valkey store matches the Redis store's
  round-trip profile, and the thread routes are separate endpoints, not steps in `Runtime.run`.

## Testing

Run: `cd ak-py && uv run pytest` (see `ak-dev-testing-conventions`).

New test files:

- **`tests/test_thread_store_valkey.py`** — mirror `tests/test_thread_store_redis.py`: monkeypatch
  `AKConfig.get().thread = _ThreadStoreConfig(type="valkey", valkey=_ThreadValkeyConfig(...))`, inject
  a `FakeValkeyClient` (as in `tests/test_sessions_valkey.py:9-40`) into `store._driver._client`, and
  assert create/append/list/paginate round trips, TTL refresh on the user/group index keys, and the
  missing-`thread.valkey` `ValueError`.
- **`tests/test_lambda_thread_routes.py`** — for `ThreadLambdaHandler` directly, calling
  `list_threads(event, context)`/`get_thread(event, context)` with synthetic `event` dicts. Enable
  thread via `AKConfig.get().thread` + `InMemoryThreadStore` + `ConversationThreadManager.reset()`
  (as `tests/test_thread_router.py:22-37` does). Assert: `get_thread` resolves `session_id` from
  `event["pathParameters"]["session_id"]`; `requestContext.authorizer.principalId` scopes listings
  and drives 403 on ownership mismatch; no authorizer → open; 404 when thread disabled; 400 on bad
  cursor. **Also assert, as a distinct case from "no authorizer attached"**:
  `requestContext.authorizer` present but `principalId` missing or falsy (e.g. `{}` or
  `{"principalId": None}`) resolves to the same open-access behavior — this is the risk flagged in
  Design/Error handling above, and it must be a named test case, not incidentally covered by the
  no-authorizer test. A separate, integration-style case may also dispatch through the real
  `RESTLambdaRouter` (registering `ThreadLambdaHandler` via `Lambda.register` and calling
  `dispatch()` with an event carrying both `path` and `resource`) to prove the two modules work
  together end to end — but the unit-level assertions above don't require it.
- **`tests/test_ecs_io_handler.py`** (new — no existing coverage) — patch `RESTAPI.run` and
  `ThreadRunner.run`; assert that with `thread` enabled, `ECSIOHandler.run(authoriser=a)` builds a
  handlers list containing a `ThreadRESTRequestHandler` whose `_authoriser is a`, and that with
  `thread` disabled no thread handler is added. This is the riskiest changed consumer on the ECS side.

Changed test files:

- **`tests/test_lambda_router.py`** — add dedicated coverage for the new path-parameter fallback in
  `dispatch()`: register a synthetic `{param}`-containing route via `RESTLambdaRouter.register()`,
  dispatch a synthetic event whose `path` has the concrete value and whose `resource` has the literal
  template, and assert the correct handler fires with `event["pathParameters"]` intact. Also add an
  explicit regression assertion that every existing static-route dispatch scenario in this file
  (the default chat path, and any `Lambda.register`-style custom route already covered) is unchanged —
  this is the proof that the fallback is additive, not just an assertion in `spec.md`.
- **`tests/test_config.py`** — add an assertion that `thread.type: "valkey"` validates and that
  `_ThreadValkeyConfig` carries the `2592000` ttl / `ak:thread:` prefix defaults.
- **`tests/test_store_builders.py`** — extend the builder-dispatch coverage with the `valkey` branch
  (that `ThreadStoreBuilder.build()` returns a `ValkeyThreadStore` when the extra is present, and
  `require_extra` raises the hinted `ImportError` when the import is forced to fail). Post-#541 this
  is the only test file exercising `ThreadStoreBuilder` dispatch; store-behaviour tests stay in
  `tests/test_thread_store_valkey.py`.

AWS Terraform changes are validated by the `examples/aws-serverless/thread-openai` weekly integration
test (deploy → chat → list → history → unauthorized), not by pytest. GCP Terraform changes have no
live integration test in this change (consistent with GCP's env-wiring-only scope) — they are
verified with `terraform validate` only, the same level the AWS Terraform iterations get outside that
one live example.
