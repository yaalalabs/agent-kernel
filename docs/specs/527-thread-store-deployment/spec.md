# #527: Thread store deployment support — Implementation Spec

This spec details how the requirements in [`design.md`](./design.md) are built. It covers three bodies
of work: (1) a `ValkeyThreadStore` in core, factored so Redis and Valkey share one store body; (2)
DynamoDB thread-table provisioning + `AK_THREAD__*` env wiring + IAM on the AWS serverless and
containerized Terraform; and (3) Firestore thread env wiring on the GCP Terraform. `design.md` is the
requirements source — every requirement there maps to a section here.

## Deviations from `design.md` — raised and resolved

Three claims in `design.md` did not survive review. All were raised and are now **resolved**;
`design.md` has been updated to match, so the two documents agree. Recorded here because the reasoning
is evidence a reviewer will want.

0. **Terraform must not inject `AK_THREAD__TYPE`.** ✅ **Resolved — reversed in PR review (#559).**
   The original contract had Terraform inject the type *and* the connection detail, so a deployed stack
   needed no `thread:` block at all. That was rejected: the type is an application design decision, and
   every other store in the repo has the app declare it — `examples/memory/dynamodb/config.yaml` says
   `session: {type: dynamodb}` while AWS Terraform injects only the table name. GCP's Terraform does
   inject `AK_SESSION__TYPE`, but redundantly (its example declares the type too), so it is not a
   precedent. Thread was the only place Terraform was the sole source of the type.
   The reversal removed the injection from six Terraform sites (4 AWS env blocks, 2 GCP), added
   `thread: {type: dynamodb}` to the AWS example, and re-pointed the docs. It does **not** eliminate the
   silent in-memory hazard — it moves it from "Terraform forgot `TYPE`" to "config forgot the block" —
   so the warnings in `threads.md` and the deployment READMEs were rewritten rather than deleted.

1. **The DynamoDB `table_name` input is a *suffix*, not the deployed table name.** ✅ **Resolved —
   `"thread_store"` approved.** `design.md` originally specified `table_name = "ak-agent-threads"` and called it
   the "Python-side default". In reality the shared module composes the real name as
   `"${product_alias}-${env_alias}-${module_name}-${table_name}"`
   (`ak-deployment/ak-aws/common/modules/dynamodb/main.tf:6`) and its `table_name` output returns that
   composed name (`common/modules/dynamodb/outputs.tf:1-3`), which Terraform then injects into the env
   var. So the Python-side default (`config.py:226-229`) never applies on a deployed stack. Session
   passes the suffix `"session_store"` (`ak-aws/serverless/state.tf:316`,
   `ak-aws/containerized/state.tf:128`), not its Python default — and
   `examples/memory/dynamodb/config.yaml` independently confirms the composed result by hardcoding
   `table_name: "ak-oai-ddb-dev-examples-session_store"`.
   The suffix `"thread_store"` is therefore used throughout, consistent with session; the deployed table
   is `<product>-<env>-<module>-thread_store`. A literal `ak-agent-threads` table was considered and
   rejected — it would break the naming convention every other table in the stack follows.
2. **`AKConfig.thread` is at `config.py:609`, not `config.py:580`.** ✅ **Resolved — `design.md` corrected.**
   Its "Env-var contract" bullet cited `580`, which is inside the sandbox provider mapping. Pre-existing
   citation error, unrelated to any code change.

One asymmetry worth recording (no design change needed): the containerized session IAM policy grants
on both the table ARN **and** `"${arn}/index/*"` (`ak-aws/containerized/modules/rest-service/main.tf:55-58`),
whereas serverless grants on the table ARN only (`ak-aws/serverless/modules/request-handler/main.tf:49`).
The thread table has no GSI, so this spec follows the serverless (table-only) form on **both** clouds
and deliberately does not copy containerized's `/index/*` grant.

## Design

### Core: Valkey thread store

`RedisThreadStore` (`ak-py/src/agentkernel/core/thread/store/redis.py:25-199`) and the new
`ValkeyThreadStore` differ only in which driver they construct and which config block they read —
exactly how `ValkeySessionStore` (`core/session/valkey.py:10-95`) twins `RedisSessionStore`. Redis and
Valkey share one command surface via `_RedisLikeDriver` (`core/util/driver/redis_like.py:16-298`);
`ValkeyDriver` (`core/util/driver/valkey.py:8-19`) overrides only `_backend_name`, `_error_class`, and
`_from_url`. Every command the thread store uses — `set(nx=)`, `get`, `rpush`, `lrange`, `llen`,
`sadd`, `smembers`, `scan_keys`, `expire`, `clear_prefix`, `key`, `ttl` — is on that shared base, so
the store body is identical between the two backends.

**Per `design.md` rule 1, the body is shared, not copied.** Factor the existing Redis body into a
`_RedisLikeThreadStore` base holding every method; the two concrete classes provide only `__init__`.
This mirrors the driver hierarchy (`_RedisLikeDriver` → `RedisDriver`/`ValkeyDriver`).

New file `ak-py/src/agentkernel/core/thread/store/redis_like.py`:

```python
class _RedisLikeThreadStore(ThreadStore):
    """Shared Redis/Valkey thread store body. Subclasses set _driver, _prefix, _log."""
    # _meta_key / _updated_key / _messages_key / _user_index_key / _group_index_key / _expire
    # create / update_name / load_metadata / append_message / get_messages / list_threads / clear
    # — bodies moved verbatim from RedisThreadStore
```

`redis.py` and the new `valkey.py` then reduce to:

```python
class RedisThreadStore(_RedisLikeThreadStore):
    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.redis")
        cfg = AKConfig.get().thread.redis
        if cfg is None:
            raise ValueError("AKConfig.thread.redis must be set to use RedisThreadStore")
        self._prefix = cfg.prefix
        self._driver = RedisDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))


class ValkeyThreadStore(_RedisLikeThreadStore):
    def __init__(self):
        self._log = logging.getLogger("ak.thread.store.valkey")
        cfg = AKConfig.get().thread.valkey          # thread.valkey, not thread.redis
        if cfg is None:
            raise ValueError("AKConfig.thread.valkey must be set to use ValkeyThreadStore")
        self._prefix = cfg.prefix
        self._driver = ValkeyDriver(url=cfg.url, prefix=cfg.prefix, ttl=int(cfg.ttl))
```

Governing rules:

1. **Refactor is behaviour-preserving.** Moving the Redis body to a base class must not change key
   schema, TTL behaviour, or return values. `tests/test_thread_store_redis.py` is the regression gate —
   it must pass untouched (it reaches into `store._driver._client`, which the refactor does not move).
2. **Drivers never read `AKConfig`** — each `__init__` reads its own config block and passes explicit
   `url`/`prefix`/`ttl` to the driver, per the `ak-dev-architecture` shared-driver rule.
3. **`valkey` stays an optional extra.** `valkey/__init__` imports `ValkeyDriver`, which imports
   `valkey` at module top (`core/util/driver/valkey.py:3`); the builder guards that import with
   `require_extra`.
4. **Logger names follow the module path** (`ak.thread.store.valkey`), per `ak-dev-code-quality`.

Builder wiring in `ThreadStoreBuilder.build()` (`core/thread/store/base.py:139-186`) — a lowercase-key
`if` chain with a `require_extra` guard per built-in, mirroring `SessionStoreBuilder`'s Valkey branch
(`core/builder.py:108-112`):

- Add `"valkey"` to `_BUILTIN_THREAD_STORES` (`base.py:13`), **after `"redis"`** so the list reads
  `["memory", "redis", "valkey", "dynamodb", "cosmosdb", "firestore"]` — the same ordering as
  `_BUILTIN_SESSION_STORES` (`core/builder.py:8`).
- Add the branch after the `redis` branch (`base.py:160-164`):

  ```python
  if key == "valkey":
      with require_extra("valkey", "thread.type: valkey"):
          from .valkey import ValkeyThreadStore

      return ValkeyThreadStore()
  ```
- Add `"valkey"` to the built-in list in `build()`'s docstring (`base.py:143`).

No new pip extra is needed: `valkey = ["valkey>=6.0.0"]` already exists (`ak-py/pyproject.toml:71-73`).

### Config changes

In `ak-py/src/agentkernel/core/config.py`:

- New `_ThreadValkeyConfig(_ValkeyConfig)` beside `_ThreadRedisConfig` (`config.py:220-223`),
  overriding the two defaults that differ from session's, exactly as `_ThreadRedisConfig` does:

  ```python
  class _ThreadValkeyConfig(_ValkeyConfig):
      ttl: int = Field(default=2592000, description="Thread TTL in seconds (0 disables)")
      prefix: str = Field(default="ak:thread:", description="Key prefix for Valkey thread storage")
  ```

  Inherited from `_ValkeyConfig` (`config.py:31-37`): `url` (default `valkey://localhost:6379`).
- New field on `_ThreadStoreConfig` (`config.py:251-262`): `valkey: Optional[_ThreadValkeyConfig] = None`,
  placed after `redis` to match the existing ordering.
- Add `valkey` to the built-in short-name list in `_ThreadStoreConfig.type`'s **description**
  (`config.py:254-257`). Post-#541 `type` is a description-only field with no regex `pattern`, so
  adding a backend means editing the description text, not a validator.

Compatibility: all three changes are additive. `thread.valkey` is absent (`None`) in every existing
config; no YAML file changes; no existing `AK_*` env var changes. The `type` description surfaces in
generated config docs.

### AWS serverless (Lambda) Terraform: DynamoDB thread table

Mirror the session-memory table wiring end to end.

- **Variable** (`ak-deployment/ak-aws/serverless/variables.tf`, beside `create_dynamodb_memory_table`
  at `:122-126`):

  ```hcl
  variable "create_dynamodb_thread_table" {
    type        = bool
    description = "Create a dynamodb table to store conversation threads"
    default     = false
  }
  ```
- **Locals** (`serverless/state.tf`, beside `:22-23`):

  ```hcl
  dynamodb_thread_table_arn  = var.create_dynamodb_thread_table == true ? module.dynamodb_thread[0].table_arn : null
  dynamodb_thread_table_name = var.create_dynamodb_thread_table == true ? module.dynamodb_thread[0].table_name : null
  ```
- **Module** (`serverless/state.tf`, cloned from `module "dynamodb_memory"` at `:300-315`):

  ```hcl
  module "dynamodb_thread" {
    source  = "yaalalabs/ak-common/aws//modules/dynamodb"
    version = "0.7.0"
    count   = var.create_dynamodb_thread_table == true ? 1 : 0
    attributes = [
      { name = "session_id", type = "S" },
      { name = "sk", type = "S" },
    ]
    hash_key           = "session_id"
    range_key          = "sk"
    ttl_enabled        = true
    env_alias          = var.env_alias
    module_name        = var.module_name
    product_alias      = var.product_alias
    table_name         = "thread_store"
    ttl_attribute_name = "expiry_time"
  }
  ```

  Key schema matches `DynamoDBThreadStore`'s documented expectation (partition `session_id`, sort `sk`,
  TTL attribute `expiry_time` — `core/thread/store/dynamodb.py:4-7`). **No `global_secondary_indexes`** —
  `list_threads` is a full-table `Scan` filtered on `sk = "meta"` (`dynamodb.py:225-238`), never an
  indexed query.
- **Pass-through** into both module blocks, following the memory-table pattern:
  - `request_handler` (`state.tf:487-494`): the memory flags are zeroed under `queue_mode`
    (`:487`, `:491`); **thread is not** — pass `var.create_dynamodb_thread_table` and the locals
    through unchanged, since the agent-runner and request-handler both read/write threads regardless of
    queue mode.
  - `agent_runner` (`state.tf:542-545`): pass through unchanged, same as memory.
- **Module variables** — add to `modules/request-handler/variables.tf` and
  `modules/agent-runner/variables.tf`, matching the memory-table shape
  (`request-handler/variables.tf:163-167`, `:175-185`): `create_dynamodb_thread_table` (bool, default
  `false`), `dynamodb_thread_table_arn` (string, default `null`), `dynamodb_thread_table_name` (string,
  default `null`). Note the deployed table is `<product>-<env>-<module>-thread_store` (see Deviations),
  so nothing in the Python config needs to know the name — Terraform injects it.
- **Env vars** in both modules' `environment_variables = merge(...)` blocks
  (`request-handler/main.tf:283-318`; agent-runner equivalent). Gate on the **ARN being non-null**, which
  is the condition the existing session/multimodal entries use (`:264`, `:267`) rather than the boolean:

  ```hcl
  var.dynamodb_thread_table_arn != null ? {
    AK_THREAD__DYNAMODB__TABLE_NAME = var.dynamodb_thread_table_name
  } : {},
  ```

  The connection detail only — `AK_THREAD__TYPE` is **not** injected; the application declares
  `thread.type` in its `config.yaml` (see design.md's env-var contract).

  Both vars together — see "Env-var contract" in `design.md` for why `TYPE` is mandatory here when
  session gets away with injecting only the table name (`:265`).
- **IAM** on both Lambda roles — clone `lambda_dynamodb_describe_policy`
  (`request-handler/main.tf:32-53`, `Resource` at `:49`) and its attachment (`:56-60`), `count`-gated on
  `var.create_dynamodb_thread_table`, granting
  `DescribeTable/GetItem/PutItem/UpdateItem/DeleteItem/Query/Scan` with
  `Resource = var.dynamodb_thread_table_arn` — table ARN only, no `/index/*`.

### AWS containerized (ECS) Terraform: DynamoDB thread table

Same shape, against the ECS modules.

- **Variable**: `create_dynamodb_thread_table` (bool, default `false`) in
  `ak-deployment/ak-aws/containerized/variables.tf`.
- **Locals + module** in `containerized/state.tf`: `dynamodb_thread_table_arn`/`_name` beside `:12-13`,
  and a `module dynamodb_thread` cloned from `module dynamodb_memory` (`:112-127`) with the same key
  schema / TTL / no-GSI / `table_name = "thread_store"` as serverless.
- **Pass-through** into both the `rest_service` and `agent_runner` module blocks, plus matching
  variables in `modules/rest-service/variables.tf` and `modules/agent-runner/variables.tf`.
- **Env vars** in both modules' environment locals — `modules/rest-service/main.tf:2-20` (the
  `rest_service_environment` merge) and the agent-runner equivalent — gated on
  `var.dynamodb_thread_table_arn != null`, injecting `AK_THREAD__DYNAMODB__TABLE_NAME` only,
  mirroring the session entry at `rest-service/main.tf:10-12`.
- **IAM** on **both** task roles: a `dynamodb_thread_policy` cloned from `dynamodb_policy`
  (`rest-service/main.tf:36-64`) but scoped to the thread table ARN **only** (dropping the
  `"${arn}/index/*"` element at `:54` — no GSI exists), attached through the
  `tasks_iam_role_policies` map (`:187-189`), which must merge the new policy alongside the existing
  `DynamoDB` entry rather than replacing it:

  ```hcl
  tasks_iam_role_policies = merge(
    var.create_dynamodb_memory_table ? { DynamoDB = aws_iam_policy.dynamodb_policy[0].arn } : {},
    var.create_dynamodb_thread_table ? { DynamoDBThread = aws_iam_policy.dynamodb_thread_policy[0].arn } : {},
  )
  ```

### GCP Terraform: Firestore thread wiring

Thread reuses the Firestore **database** provisioned by `create_firestore_database`
(`ak-gcp/serverless/variables.tf:169-173`, module at `serverless/state.tf:150-163`). Firestore
collections are created implicitly on first write, so no new database or collection resource is needed.

- **Variable** on both `ak-gcp/serverless` and `ak-gcp/containerized`:

  ```hcl
  variable "create_firestore_thread_collection" {
    type        = bool
    description = "Wire the Firestore-backed conversation thread store (requires create_firestore_database)"
    default     = false
  }
  ```

  Valid only with `create_firestore_database = true`. Enforce with a `validation` block on the
  variable — it can reference only its own value, so use a `lifecycle` precondition or a `null_resource`
  check if a cross-variable guard is wanted; otherwise document the dependency and let the
  `local.firestore_db_name != null` gate below make it a no-op when the database is absent.
- **Env vars**, appended to the existing firestore env block when the flag is true — the same block
  that sets the session vars in each dir (`serverless/cloud_function.tf:159-164`,
  `containerized/cloud_run.tf:160-165`):

  ```hcl
  (local.firestore_db_name != null && var.create_firestore_thread_collection) ? {
    AK_THREAD__FIRESTORE__COLLECTION_NAME = "ak-agent-threads"
    AK_THREAD__FIRESTORE__PROJECT_ID      = var.project_id
    AK_THREAD__FIRESTORE__DATABASE_ID     = module.firestore[0].database_name
  } : {},
  ```

  Note this **cannot** reuse `module.firestore[0].collection_name` — that output returns the module's
  single `var.collection_name` (default `"sessions"`,
  `ak-gcp/common/modules/firestore/variables.tf:27-31`), i.e. the *session* collection. Thread needs a
  distinct collection name, so it is supplied literally. **Use `"ak-agent-threads"`, matching the Python
  default exactly** (`config.py:234-237`) — unlike DynamoDB there is no name composition for Firestore
  collections, so injecting the same value the code would have defaulted to keeps behaviour identical
  whether or not the var is set, and avoids inventing a second name for one collection. Note GCP's
  Terraform *does* inject `AK_SESSION__TYPE` (`cloud_function.tf:160`), but redundantly — its example
  declares `session: {type: firestore}` anyway — so that is not a precedent for injecting the thread
  type here.
- **TTL**: the firestore module registers one `google_firestore_field` TTL policy scoped to
  `var.collection_name` (`common/modules/firestore/main.tf:20-27`) — the session collection only.
  Thread's Firestore TTL defaults to `0` (disabled, `config.py:238`), so **no TTL resource is required**.
  Adding one later means a second `google_firestore_field` for the thread collection; out of scope here.
- **IAM**: no change needed — **resolved**, closing the design's open "verify" item. The service
  account is granted `roles/datastore.user` at **project** scope
  (`ak-gcp/serverless/cloud_function.tf:16-19`), not per-collection, so it already covers the thread
  collection in the same database.

### Docs (example deferred)

**No deployable example ships in this change, on either cloud** — see `design.md` Non-goals. The only
thread example today remains the local-only `examples/api/thread-openai` (FastAPI).

An intermediate implementation added a `thread:` block plus `create_dynamodb_thread_table = true` to
`examples/memory/dynamodb`; that was **reverted**. Recorded here because the reasoning is what the
follow-up needs:

- **A chat-only test can't demonstrate threads.** `_thread_pre_run` (`core/chat_service.py:507-541`)
  stores attachments, creates the thread and appends the user message — it never injects thread history
  into the agent's requests. Threads are a *record*, not a context mechanism, so a passing follow-up
  question proves the *session* store.
- **There is no HTTP surface to read thread state back from**, because the thread REST read routes are
  out of scope. The FastAPI showcase makes 8 `GET /api/v1/threads*` calls and every assertion but one
  ("`user_id` required") depends on them.
- **So a serverless example needs a deliberate test design** — reading the provisioned store directly
  (boto3 `Query` on `session_id`), which no example test does today. That is worth its own review rather
  than a bolt-on.
- **Bolting onto a session-storage example was the wrong host anyway**: it proved only that provisioning
  doesn't crash, while forcing thread's `user_id` requirement onto tests about session memory.
- **Do not use `examples/aws-serverless/openai`** when the follow-up lands: it is `deployment_base` —
  "always deployed but not part of test matrix" (`integration-test-config.yaml:4-8`). Nothing tests it,
  and it is shared infrastructure other tests deploy against, so imposing thread's `user_id` requirement
  on it risks breaking them.
- **Note for the follow-up:** CI passes only `AK_TEST_ENDPOINT`, from `terraform output agent_invoke_url`
  (`.github/scripts/run_single_test.py:304-324`) — a store-reading test must source the table name itself.
- **Docs**: document `create_dynamodb_thread_table` / `create_firestore_thread_collection` and, per
  `design.md`, the two-step contract prominently — the app declares `thread.type`, the flag provisions
  the backend and injects its address, and setting the flag *without* declaring the type fails silently
  on the in-memory backend. Targets: `docs/docs/advanced/threads.md` (storage backends section) and the AWS/GCP deployment
  READMEs under `ak-deployment/`.

### Behavioural changes

1. **`thread.type: valkey` resolves to `ValkeyThreadStore`.** New capability; existing values
   unaffected.
2. **`thread.type: valkey` without the `valkey` extra raises `ImportError`** with the
   `pip install "agentkernel[valkey]"` hint, at `build()` time via `require_extra`
   (`core/util/factory.py:50-64`). Intentional — mirrors `SessionStoreBuilder`'s Valkey path; fail-fast
   beats an opaque `ModuleNotFoundError`.
3. **`thread.type: valkey` with no `thread.valkey` block raises `ValueError`.** Intentional — mirrors
   `RedisThreadStore`'s guard (`redis.py:33-34`) and `ValkeySessionStore`'s (`session/valkey.py:24-25`).
4. **`RedisThreadStore` gains a base class.** Behaviour-preserving refactor: no key schema, TTL, or
   return-value change. `RedisThreadStore` remains importable from
   `agentkernel.core.thread.store.redis` — its module path and name do not move.
5. **A deployment with `create_dynamodb_thread_table = true` (or
   `create_firestore_thread_collection = true`) runs threads on a durable backend** instead of the
   in-memory default. Intentional — the feature being added; opt-in, default `false`.
6. **Enabling thread on the AWS/GCP examples makes `user_id` required on their chat requests** — a
   pre-existing consequence of thread support, newly reached by those examples.

**Non-changes** (verified): the `ThreadStore` ABC and its method contracts (`base.py:31-127`); the
DynamoDB/Firestore/Cosmos thread store bodies; `ConversationThreadManager`; `ThreadRESTRequestHandler`
and `RESTAPI.run`'s handler/auto-mount logic (`api/http.py`) — untouched by this change; the `Authoriser`
ABC; the `memory` short name for the in-memory thread backend (its rename is a separate issue); all
existing session/multimodal/response-store deployment wiring; and every existing `AK_*` env var.

## Error handling

- **Missing `valkey` extra**: `ImportError` with the pip-extra hint at store-build time (change 2).
- **`thread.type: valkey` with `thread.valkey` unset**: `ValueError` at construction (change 3).
- **Unknown `thread.type`**: unchanged — `AKConfigError` naming `_BUILTIN_THREAD_STORES` (now including
  `valkey`) or a dotted path (`base.py:180-183`).
- **Terraform flag enabled but `thread.type` not declared in `config.yaml`**: no exception — the injected
  connection var materialises the block, `type` falls back to `"memory"`, and threads run in-memory with
  the provisioned backend unused. Not defended in code; documented in `threads.md` and the deployment
  READMEs. A `_ThreadStoreConfig` validator rejecting `type: memory` alongside a populated backend
  sub-block would close it — scoped to a separate follow-up.
- **Valkey connection failure**: handled by `_RedisLikeDriver` — lazy connect, 3 retries with 2s
  back-off, ping health-check with reconnect (`core/util/driver/redis_like.py`). Identical to Redis;
  `ValkeyDriver` adds no error handling of its own and raises `valkey.ValkeyError` where Redis raises
  `redis.RedisError` (`driver/valkey.py:15`).
- **Flag enabled without its prerequisite**: `create_firestore_thread_collection = true` with
  `create_firestore_database = false` injects nothing — the `local.firestore_db_name != null` gate makes
  it inert rather than producing a broken deployment.
- **Concurrency**: `ValkeyThreadStore` is exactly as thread-safe as `RedisThreadStore` — the same
  `SET NX` create, `RPUSH` append, and per-instance connect/reconnect lock in `_RedisLikeDriver`.
- **Per-operation cost**: none added to the chat hot path. The Valkey store matches the Redis store's
  round-trip profile, and the Terraform work only sets env vars.

## Testing

Run: `cd ak-py && uv run pytest` (see `ak-dev-testing-conventions`).

New test files:

- **`tests/test_thread_store_valkey.py`** — mirror `tests/test_thread_store_redis.py:1-35`: a
  `make_store` fixture that sets
  `AKConfig.get().thread = _ThreadStoreConfig(type="valkey", valkey=_ThreadValkeyConfig(ttl=..., prefix=...))`,
  constructs the store, injects a `MagicMock` at `store._driver._client`, and restores the original
  config on teardown. Assert: create/append/list/paginate round trips; TTL refresh on the user/group
  index keys (the behaviour `test_thread_store_redis.py` guards for Redis); and the missing-`thread.valkey`
  `ValueError`. A `FakeValkeyClient` (as in `tests/test_sessions_valkey.py:11-41`, monkeypatching
  `valkey_driver_module.valkey.from_url`) is the alternative if a real command surface is wanted rather
  than a mock — the `MagicMock` form is closer to the existing thread-store test and preferred for
  consistency.

Changed test files:

- **`tests/test_thread_store_redis.py`** — **unchanged, and that is the point.** It is the regression
  gate proving the `_RedisLikeThreadStore` extraction is behaviour-preserving. If it needs edits, the
  refactor changed behaviour and should be reconsidered.
- **`tests/test_store_builders.py`** — add a `valkey` branch case beside the existing thread-builder
  tests (`:115-150`), following their `patch.object(AKConfig, "get")` + `Mock()` cfg style: assert
  `ThreadStoreBuilder.build()` returns a `ValkeyThreadStore` when the extra is importable, and that a
  forced import failure surfaces the hinted `ImportError`. Post-#541 this is the only file exercising
  `ThreadStoreBuilder` dispatch; store behaviour stays in `test_thread_store_valkey.py`.
- **`tests/test_config.py`** — currently has **no** thread coverage (verified by grep). Add assertions
  that `_ThreadStoreConfig(type="valkey")` validates and that `_ThreadValkeyConfig` carries the
  `2592000` ttl / `ak:thread:` prefix / `valkey://localhost:6379` url defaults.

Not covered by pytest: the Terraform changes. With no example shipping in this change (see "Docs"),
**neither cloud gets live integration coverage** — both are verified with
`terraform init && terraform validate` per module directory, the same depth the existing Terraform gets
outside the live examples. End-to-end proof arrives with the deferred example.
