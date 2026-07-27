# #527: Thread store deployment support and Authoriser support for serverless and ECS — Implementation Spec

This spec details how the requirements in [`design.md`](./design.md) are built. It covers four bodies
of work: (1) a Valkey thread store in core; (2) DynamoDB/Firestore/Cosmos DB thread-store provisioning
and `AK_THREAD__*` env wiring across the AWS, GCP, and Azure Terraform (each mirroring its cloud's
existing session-store flag); (3) native thread REST routes on the Lambda serverless router, protected
by the existing gateway-level `APIGatewayAuthorizer`; and (4) an `Authoriser`-mounting parameter on
ECS's queue-mode `ECSIOHandler`. `design.md` is the requirements source — every requirement there maps
to a section here.

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
   `valkey` at module top (`core/util/driver/valkey.py:3`); the builder guards that import with
   `try/except ImportError` and the install hint (see below).

Builder wiring in `ThreadStoreBuilder` (`core/thread/store/base.py:128-192`):

- Add `VALKEY = "VALKEY"` to the `Types` StrEnum (`base.py:136-146`), between `REDIS` and `DYNAMODB`.
- Add a `VALKEY` branch to `build()` (`base.py:173-192`) mirroring `SessionStoreBuilder`'s guarded
  Valkey path (`core/builder.py:138-146`):

  ```python
  elif store_type == ThreadStoreBuilder.Types.VALKEY:
      try:
          from .valkey import ValkeyThreadStore
      except ImportError as e:
          raise ImportError(
              "The 'valkey' package is required for thread.type: valkey. "
              "Install it with: pip install agentkernel[valkey]"
          ) from e
      return ValkeyThreadStore()
  ```

Config in `core/config.py`:

- Add `_ThreadValkeyConfig(_ValkeyConfig)` next to `_ThreadRedisConfig` (`config.py:214-216`),
  overriding `ttl` default to `2592000` (30 days, matching the Redis thread default) and `prefix`
  default to `"ak:thread:"`:

  ```python
  class _ThreadValkeyConfig(_ValkeyConfig):
      ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
      prefix: str = Field(default="ak:thread:", description="Key prefix for Valkey thread storage")
  ```
- Add `valkey: Optional[_ThreadValkeyConfig] = None` to `_ThreadStoreConfig` (`config.py:245-253`)
  and extend its `type` pattern to `^(memory|redis|valkey|dynamodb|cosmosdb|firestore)$`
  (`config.py:248`) — this only **adds** the `valkey` backend option, aligning the thread store's
  backend set with `_SessionStoreConfig.type` (`config.py:80`). Note the two configs keep their
  existing default-token naming: `_ThreadStoreConfig.type` uses `memory` while
  `_SessionStoreConfig.type` uses `in_memory`; this change does **not** rename `memory` to
  `in_memory`.

### Serverless (Lambda): thread REST routes

The Lambda REST path does not use FastAPI — `RESTLambdaRouter` (`rest_lambda.py:292-388`) dispatches
raw API Gateway REST v1 events against a `self._routes[path][method]` table. Thread routes are added
natively, reusing `ConversationThreadManager` (the same data path `ThreadRESTRequestHandler` uses,
`api/thread.py`) — no logic is re-implemented, only the transport is translated from FastAPI to Lambda
handler functions.

New `ThreadEndpointsHandler` in
`ak-py/src/agentkernel/deployment/aws/serverless/core/router/thread_endpoints.py`, mirroring
`DefaultEndpointsHandler` (`rest_lambda.py:14-74`):

```python
class ThreadEndpointsHandler:
    """Native Lambda handlers for the thread read routes, keyed by API Gateway
    resource template so the {session_id} path parameter needs no path parsing."""

    LIST_RESOURCE = "/api/v1/threads"
    DETAIL_RESOURCE = "/api/v1/threads/{session_id}"

    def get_routes(self) -> Dict[str, Dict[str, Callable]]:
        return {
            self.LIST_RESOURCE:   {"GET": self._handle_list},
            self.DETAIL_RESOURCE: {"GET": self._handle_detail},
        }

    def _resolve_user(self, event) -> Optional[str]:
        # principal injected by the gateway APIGatewayAuthorizer; None when no
        # authorizer is attached (routes open — same semantics as ThreadRESTRequestHandler)
        return (event.get("requestContext", {}).get("authorizer") or {}).get("principalId")

    def _handle_list(self, event, context) -> tuple[int, dict]: ...
    def _handle_detail(self, event, context) -> tuple[int, dict]: ...
```

Handler behaviour mirrors `ThreadRESTRequestHandler.get_router()` (`api/thread.py:57-107`) exactly:

- Both call `ConversationThreadManager.get()`; when it is `None` → `(404, {"error": "Thread support
  is not enabled"})` (matches `api/thread.py:72-73,89-90`).
- `_handle_list`: read `user_id`/`group_id`/`limit`/`cursor` from `event.get("queryStringParameters")`;
  when `_resolve_user` returns non-`None`, force `user_id` to it (matches `api/thread.py:74-76`); call
  `manager.list_threads(...)`; return the same `{"threads": [...exclude messages...], "next_cursor":
  ...}` body (matches `api/thread.py:81-84`); `ValueError` (bad cursor) → `(400, ...)`.
- `_handle_detail`: `session_id` from `event["pathParameters"]["session_id"]`; call
  `manager.get_thread(session_id, user_id=resolved)`; `PermissionError` → `(403, ...)`, `None` →
  `(404, ...)`; then `manager.get_messages(...)`; return the merged thread + messages + `next_cursor`
  body (matches `api/thread.py:86-105`).

Governing rules:

1. **Routing keys off `event["resource"]` (the template), not `event["path"]` (the concrete URL).**
   API Gateway REST v1 proxy events carry `resource` = `/api/v1/threads/{session_id}`, `path` =
   `/api/v1/threads/abc-123`, and `pathParameters` = `{"session_id": "abc-123"}`. Matching the
   template means the `{session_id}` segment needs no wildcard parsing — this is the **thread-specific**
   path-parameter handling the design calls for, not a general router feature.
2. **`RESTLambdaRouter.dispatch()` gets one thread pre-check.** Before the existing default-chat-path
   rewrite (`rest_lambda.py:368-385`), add: if `event.get("resource")` is a registered thread route
   and the method matches, dispatch straight to that handler and return. The existing chat-path logic
   is untouched for all other events.
3. **Thread routes are registered at cold start, only when enabled.** In `RESTLambdaRouter.__init__`
   (`rest_lambda.py:300-315`), after the default routes are built, if `AKConfig.get().thread is not
   None`, merge `ThreadEndpointsHandler().get_routes()` into `self._routes`. The router is a
   module-level singleton (`Lambda._router`, `aklambda.py:29-32`) built once per cold start, so
   registration is race-free.

Handler returns are `(status, dict)` tuples; `Lambda._wrap_response` (`aklambda.py:50-67`) already
serialises those to `{"statusCode", "body": json.dumps(...)}`.

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
- **Route exposure**: no auto-append logic in `state.tf`. The deployer lists `api/v1/threads` and
  `api/v1/threads/{session_id}` in the `gateway_endpoints` variable — the api-gateway module already
  supports the segment depth and treats a literal `{session_id}` `path_part` as a path parameter
  (`modules/api-gateway/main.tf`). Endpoints in `gateway_endpoints` are covered by the deployment's
  `authorizer` variable. The example (below) ships the exact entries.

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

### Azure Terraform: Cosmos DB thread table

Thread reuses the Cosmos DB **account** provisioned by `create_cosmosdb_cluster`
(`ak-azure/serverless/state.tf:70-73`) but needs its own table — the cosmos module currently
provisions exactly one `azurerm_cosmosdb_table` (`common/modules/cosmos/main.tf:63-76`) named from
`var.table_name`, coupled to the account it also creates.

- Add an **optional second table** in the same account rather than re-instantiating the module (which
  would duplicate the account, private endpoint, DNS zone, and NSG). Two acceptable shapes; pick one
  in implementation and keep it consistent:
  1. Extend the cosmos module with an optional `thread_table_name` input that adds a second
     `azurerm_cosmosdb_table` (`count` on the name being set) in the existing account, exposed via a
     new output; or
  2. A small sibling resource/module that creates only an `azurerm_cosmosdb_table` in the existing
     `module.cosmos` account.
- Gate on a new bool `create_cosmosdb_thread_table` (default `false`), valid only with
  `create_cosmosdb_cluster = true`.
- Env vars, appended to the existing cosmosdb env block when the flag is true
  (`serverless/linux_function.tf:132-133`, `containerized/container_app.tf:106-108`):
  `AK_THREAD__TYPE=cosmosdb`, `AK_THREAD__COSMOSDB__TABLE_NAME` (default `akagentthreads`,
  `config.py:237`), `AK_THREAD__COSMOSDB__CONNECTION_STRING` — the connection string sourced the same
  way session does (direct local on serverless `linux_function.tf:133`; Key Vault secret reference on
  containerized `container_app.tf:108,120`).

### Docs and example

- New `examples/aws-serverless/thread-openai/`, structured like `examples/aws-serverless/openai-auth/`
  (`build.sh`, `config.yaml`, `lambda.py`, `lambda_auth.py`, `lambda_test.py`, `pyproject.toml`,
  `deploy/`, `test-config.yaml`, `README.md`):
  - `config.yaml` declares a `thread:` block (type omitted → Terraform injects `AK_THREAD__TYPE`).
  - `deploy/` sets `create_dynamodb_thread_table = true` and lists `api/v1/threads` +
    `api/v1/threads/{session_id}` in `gateway_endpoints`, with the `authorizer` wired to the auth
    Lambda (per `openai-auth`).
  - `lambda_test.py` exercises: chat (creates a thread) → `GET /api/v1/threads` (list) → `GET
    /api/v1/threads/{session_id}` (history) → an unauthorized call asserts 401/403.
  - Register under `weekly.tests` in `.github/integration-test-config.yaml:56-71` as
    `{type: aws-serverless, path: examples/aws-serverless/thread-openai, deploy_dir: deploy}`.
- Docs: document the `AK_THREAD__TYPE` + backend-vars pairing prominently (deployment guide), since
  thread is the only `AK_*` store whose type Terraform must set explicitly.

### Config changes

- `_ThreadStoreConfig.type` pattern: `^(memory|redis|dynamodb|cosmosdb|firestore)$` →
  `^(memory|redis|valkey|dynamodb|cosmosdb|firestore)$` (`config.py:248`). Additive — every existing
  value still validates.
- New `_ThreadValkeyConfig` and `_ThreadStoreConfig.valkey: Optional[...] = None`. Additive; absent in
  existing configs (`None`).
- **`AK_THREAD__TYPE` is mandatory in Terraform env injection.** `AKConfig.thread` is
  `Optional[_ThreadStoreConfig] = Field(default=None, ...)` (`config.py:393`) with no
  `default_factory`, so any `AK_THREAD__*` env var materialises the block, but unset fields fall to
  their model defaults — `type` to `"memory"` (`config.py:248`), which `ThreadStoreBuilder.build()`
  reads directly (`base.py:167-171`). Unlike session (where the committed `config.yaml` declares the
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
   at `build()` time. Intentional — mirrors `SessionStoreBuilder`'s Valkey path
   (`core/builder.py:141-144`); fail-fast beats an opaque `ModuleNotFoundError`.
3. **`thread.type: valkey` with no `thread.valkey` block raises `ValueError`.** Intentional — mirrors
   `RedisThreadStore`'s missing-config guard (`redis.py:33-34`) and `ValkeySessionStore`'s
   (`valkey.py:24-25`).
4. **Lambda serverless now serves `GET /api/v1/threads[...]`** when `thread` is configured and the
   routes are added to `gateway_endpoints`. Previously the router had no such routes and `dispatch()`
   raised `ValueError` → 500 (`rest_lambda.py:383-385`). Intentional — the feature being added.
5. **ECS `RESTAPI.run` receives an explicit `ThreadRESTRequestHandler`** from `ECSIOHandler` when
   thread is enabled, instead of relying on auto-mount. Intentional and behaviour-preserving when
   `authoriser=None` (open routes, as before); the new capability is that a caller can now pass an
   `Authoriser`.

**Non-changes** (verified): the DynamoDB thread table schema/`Scan` behaviour
(`core/thread/store/dynamodb.py`); `ThreadStore` ABC and the Redis/DynamoDB/Firestore/Cosmos store
bodies; `ConversationThreadManager`'s API and the FastAPI `ThreadRESTRequestHandler`
(`api/thread.py`); the default chat-path routing in `RESTLambdaRouter.dispatch()`
(`rest_lambda.py:368-385`); the `Authoriser` ABC (`authoriser.py`); and all existing
session/multimodal/response-store deployment wiring.

## Error handling

- **Thread not configured** (`AKConfig.get().thread is None`): Lambda thread routes are never
  registered (cold-start guard), so no `ThreadStoreBuilder.build()` is attempted; the ECS handler
  skips mounting the thread handler. FastAPI/`ConversationThreadManager.get()` returns `None` → 404 on
  any thread route that is somehow reached (`api/thread.py:72-73`).
- **Missing `valkey` extra**: `ImportError` with `pip install agentkernel[valkey]` hint at build time
  (change 2 above).
- **Missing `thread.valkey`/`thread.redis` block for the chosen type**: `ValueError` at store
  construction (change 3; `redis.py:33-34`).
- **`AK_THREAD__DYNAMODB__TABLE_NAME` set but `AK_THREAD__TYPE` unset**: no exception — silently
  in-memory. This is the failure the Terraform contract (always inject `AK_THREAD__TYPE`) prevents;
  documented, and enforced by every cloud's env block setting both.
- **Lambda authorizer absent on a thread route**: `requestContext.authorizer` missing →
  `_resolve_user` returns `None` → open access (matches open `ThreadRESTRequestHandler`).
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
- **`tests/test_lambda_thread_routes.py`** — for `ThreadEndpointsHandler` + the `RESTLambdaRouter`
  thread pre-check. Following `tests/test_lambda_router.py`'s patched-`DefaultEndpointsHandler`/
  `SQSHandler` fixture and enabling thread via `AKConfig.get().thread` + `InMemoryThreadStore` +
  `ConversationThreadManager.reset()` (as `tests/test_thread_router.py:22-37` does). Assert: list
  route dispatches on `resource="/api/v1/threads"`; detail route resolves `pathParameters.session_id`;
  `requestContext.authorizer.principalId` scopes listings and drives 403 on ownership mismatch; no
  authorizer → open; 404 when thread disabled; 400 on bad cursor.
- **`tests/test_ecs_io_handler.py`** (new — no existing coverage) — patch `RESTAPI.run` and
  `ThreadRunner.run`; assert that with `thread` enabled, `ECSIOHandler.run(authoriser=a)` builds a
  handlers list containing a `ThreadRESTRequestHandler` whose `_authoriser is a`, and that with
  `thread` disabled no thread handler is added. This is the riskiest changed consumer on the ECS side.

Changed test files:

- **`tests/test_lambda_router.py`** — the router fixture builds a real `RESTLambdaRouter`; ensure it
  runs with `AKConfig.get().thread` at its default (`None`) so no thread routes register and existing
  assertions hold. Add an autouse guard resetting `AKConfig.get().thread = None` +
  `ConversationThreadManager.reset()` if any new thread-enabling test shares the module.
- **`tests/test_config.py`** — add an assertion that `thread.type: "valkey"` validates and that
  `_ThreadValkeyConfig` carries the `2592000` ttl / `ak:thread:` prefix defaults.
- **`tests/test_thread_store.py`** — extend the builder-dispatch coverage with the `VALKEY` branch
  (that `ThreadStoreBuilder.build()` returns a `ValkeyThreadStore` when the extra is present, and
  raises the hinted `ImportError` when the import is forced to fail).

Terraform changes are validated by the `examples/aws-serverless/thread-openai` weekly integration test
(deploy → chat → list → history → unauthorized), not by pytest.
