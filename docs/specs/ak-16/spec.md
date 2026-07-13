# Valkey session store with AWS deployment support (AK-16)

This change adds Valkey as a first-class session storage backend in Agent Kernel, alongside the
existing Redis, DynamoDB, Cosmos DB, and Firestore backends. It also adds the AWS infrastructure to
deploy a Valkey cluster (ElastiCache for Valkey) via Terraform, wires it into both the containerized
(ECS) and serverless (Lambda) deployment modules, and ships a runnable example. In addition to the
session store, Valkey is added as a response-store backend for async execution
(`execution.response_store.type: valkey`), alongside the existing Redis and DynamoDB response
stores. The implementation closely mirrors the existing Redis session and response stores — Valkey
is wire-compatible with Redis — but is a distinct backend with its own client library, configuration
block, and Terraform module.

## Motivation

1. Valkey is the open-source, Linux Foundation-governed fork of Redis (created after Redis moved
   away from the BSD license). Many teams are standardizing on Valkey to avoid Redis licensing
   concerns and want it as an explicit, supported backend rather than "point the Redis config at a
   Valkey server".
2. AWS ElastiCache supports Valkey as a native engine at a lower price point than the Redis OSS
   engine, making it the preferred managed cache/session option on AWS going forward.
3. Agent Kernel already has a clean per-backend pattern (`session.type`, per-backend config block,
   `SessionStoreBuilder` branch, per-backend Terraform module). Valkey should follow that pattern so
   users select it the same way they select any other backend.

## Design decisions

| Decision | Choice |
|---|---|
| Python client | Official `valkey` package (valkey-py, a drop-in fork of redis-py) — not valkey-glide, not a reuse of redis-py |
| Backend identity | First-class: `session.type: valkey` with its own `session.valkey` config block and `AK_SESSION__VALKEY__*` env vars |
| Terraform | New `ak-deployment/ak-aws/common/modules/valkey` module (clone of the `redis` module with `engine = "valkey"`); the published `redis` module is left untouched |
| Deployment scope | Both `ak-deployment/ak-aws/containerized` and `ak-deployment/ak-aws/serverless` get a `create_valkey_cluster` toggle |
| Example | New `examples/memory/valkey/` mirroring `examples/memory/redis/` |
| Response store | In scope. A new `ValkeyResponseStore` is added alongside the `redis`/`dynamodb` types (`execution.response_store.type: valkey`), with a matching `create_valkey_response_store` toggle in the serverless deployment |
| `RedisDriver` defects | Two latent defects in `RedisDriver` are fixed in `redis.py` as part of this change (silent retry exhaustion, class-level client attribute) so `ValkeyDriver` clones the corrected driver instead of duplicating known bugs |
| Redis-only surfaces | The multimodal attachment store (`multimodal.storage_type`) and A2A task store (`a2a.task_store_type`) stay Redis-only in this change; the docs note the wire-compatibility workaround and first-class support is deferred to a follow-up ticket |

## `ValkeySessionStore` (`session.type: valkey`)

**File:** `ak-py/src/agentkernel/core/session/valkey.py` (new)

Before cloning, two latent defects in `RedisDriver` (`ak-py/src/agentkernel/core/session/redis.py`)
are fixed in place, so the Valkey driver starts clean and Redis benefits from the same fix:

- `RedisDriver._connect()` currently swallows all three retry failures and leaves the client
  `None`, so the next operation dies with an opaque `AttributeError: 'NoneType' object has no
  attribute 'hset'`. Fixed to re-raise the last `redis.RedisError` once retries are exhausted, so
  a misconfigured or unreachable server surfaces as a clear connection error at first use.
- `_redis_client = None` is declared as a class-level attribute and shadowed by instance
  assignment in `_connect()`. Fixed to initialize it as an instance attribute in `__init__`.

The observable behavior of a *healthy* Redis connection is unchanged; only the
total-connection-failure path changes (clear error instead of `AttributeError`).

`ValkeySessionStore` is then a near-clone of the corrected `redis.py`, using `import valkey`
instead of `import redis`:

- `ValkeyDriver` — connection management and namespaced hash helpers:
  - Reads `AKConfig.get().session.valkey.{url, prefix, ttl}` in `__init__`.
  - Lazy `client` property with `ping()` health check and reconnect on `valkey.ValkeyError`
    (valkey-py's equivalent of `redis.RedisError`).
  - `_connect()` via `valkey.from_url(url, decode_responses=False, socket_connect_timeout=5)` with
    3 retries and a 2-second back-off, identical to the corrected `RedisDriver._connect` (raises
    the last `valkey.ValkeyError` when retries are exhausted).
  - Same helper surface: `key()`, `hset()`, `hget()`, `expire()`, `hkeys()`, `exists()`,
    `clear_prefix()`.
- `ValkeySessionStore(SessionStore)` — implements `new` / `load` / `store` / `clear` exactly as
  `RedisSessionStore` does:
  - One Valkey **hash per session** at key `{prefix}{session_id}`, with an `"__init__"` sentinel
    field so the key exists and TTL can apply on `new()`.
  - Values serialized with the shared `BinarySerde` (pickle) from
    `ak-py/src/agentkernel/core/session/serde.py`.
  - `store()` persists `session.get_all(volatile=False)` (volatile cache is not persisted) and
    refreshes the TTL via `EXPIRE` when `ttl` is non-zero.
  - Optional `SessionCache` (LRU) injected by the builder, same as all other stores.

No changes to the `Session` object (`ak-py/src/agentkernel/core/base.py`) or the `SessionStore`
ABC (`ak-py/src/agentkernel/core/session/base.py`) are required.

## `ValkeyResponseStore` (`execution.response_store.type: valkey`)

**File:** `ak-py/src/agentkernel/deployment/aws/core/response_store/valkey.py` (new)

A near-clone of `ak-py/src/agentkernel/deployment/aws/core/response_store/redis.py`, using
`valkey.Valkey.from_url(url, decode_responses=True)` instead of `redis.Redis.from_url`:

- `ValkeyResponseStore(ResponseStore)` with `__init__(url, prefix="ak:responses:", ttl=0)`.
- `add_message()` — JSON-serializes the message under key `{prefix}{request_id}` and issues
  `EXPIRE` when `ttl > 0`.
- `get_message()` — returns the parsed `message["body"]` or `None` when absent; supports
  `get_and_delete`.
- `delete_message()` — deletes the key.

**File:** `ak-py/src/agentkernel/deployment/aws/core/response_store/handler.py`

- Add `VALKEY = "VALKEY"` to `ResponseDBHandler.Type`.
- Add a branch in `ResponseDBHandler.__init__` mirroring the Redis branch: when
  `response_store_type == Type.VALKEY` and `response_store_config.valkey is not None`, lazily
  import `ValkeyResponseStore` and construct it from
  `execution.response_store.valkey.{url, prefix, ttl}`.
- The final `ValueError` message is updated to mention Valkey as a valid option.

No changes to the `ResponseStore` ABC (`ak-py/src/agentkernel/deployment/common/response_store.py`)
or its consumers (`queue_request_handler.py`, `akresponsehandler.py`, `akoutputconsumer.py`,
`ecs_queue_handler.py`) are required — they operate on the ABC via `ResponseDBHandler`.

## Configuration

**File:** `ak-py/src/agentkernel/core/config.py`

Add a `_ValkeyConfig` model and register it on `_SessionStoreConfig`:

```python
class _ValkeyConfig(BaseModel):
    url: str = Field(
        default="valkey://localhost:6379",
        description="Valkey connection URL. Use valkeys:// for SSL",
    )
    ttl: int = Field(default=604800, description="Valkey saved value TTL in seconds")
    prefix: str = Field(default="ak:sessions:", description="Key prefix for Valkey session storage")


class _SessionStoreConfig(BaseModel):
    type: str = Field(default="in_memory", pattern="^(in_memory|redis|valkey|dynamodb|cosmosdb|firestore)$")
    ...
    valkey: Optional[_ValkeyConfig] = None
```

The response store config gains a matching backend, mirroring how
`_ResponseStoreRedisConfig` extends `_RedisConfig`:

```python
class _ResponseStoreValkeyConfig(_ValkeyConfig):
    prefix: str = Field(default="ak:responses:", description="Key prefix for Valkey response storage")


class _ResponseStoreConfig(BaseModel):
    type: str = Field(default=None, pattern="^(redis|valkey|dynamodb)$")
    ...
    valkey: Optional[_ResponseStoreValkeyConfig] = None
```

valkey-py's `from_url` accepts `valkey://` / `valkeys://` as well as `redis://` / `rediss://`
schemes, so ElastiCache endpoints work with either form; the spec standardizes on `valkey://`.

YAML example:

```yaml
session:
  type: valkey
  cache:
    size: 256
  valkey:
    url: "valkey://my-cluster.xxxxxx.cache.amazonaws.com:6379"
    prefix: "ak:sessions:"
    ttl: 604800

execution:
  mode: rest_async
  response_store:
    type: valkey
    valkey:
      url: "valkey://my-cluster.xxxxxx.cache.amazonaws.com:6379"
      prefix: "ak:responses:"
```

Environment variables (env beats YAML, prefix `AK_`, `__` nesting — unchanged mechanism):
`AK_SESSION__TYPE=valkey`, `AK_SESSION__VALKEY__URL`, `AK_SESSION__VALKEY__TTL`,
`AK_SESSION__VALKEY__PREFIX`, and for the response store
`AK_EXECUTION__RESPONSE_STORE__VALKEY__URL` (matching the existing
`AK_EXECUTION__RESPONSE_STORE__REDIS__URL`).

**Out of scope — Redis-only surfaces.** The multimodal attachment store
(`multimodal.storage_type`) and the A2A task store (`a2a.task_store_type`) do not gain a `valkey`
option in this change. Because Valkey is wire-compatible with the Redis protocol, users
standardizing on Valkey can point those existing `redis` config blocks at a Valkey endpoint using
the `redis://` scheme. The docs state this explicitly (see "Documentation updates"), and
first-class `valkey` support for those surfaces is deferred to a follow-up ticket.

## Builder changes

**File:** `ak-py/src/agentkernel/core/builder.py`

- Add `VALKEY = "VALKEY"` to `SessionStoreBuilder.Types`.
- Add a branch in `SessionStoreBuilder.build()` with the same lazy-import pattern used for every
  other backend:

```python
elif session_store_type == SessionStoreBuilder.Types.VALKEY:
    from .session.valkey import ValkeySessionStore

    return ValkeySessionStore(cache=SessionCacheBuilder.build())
```

Unknown types continue to fall back to `InMemorySessionStore` via `Types.from_str`.

## Optional dependency

**File:** `ak-py/pyproject.toml`

Add a new extra next to the existing `redis` extra:

```toml
valkey = [
    "valkey>=6.0.0",
]
```

Users install with `agentkernel[openai,valkey]`. The imports stay inside
`core/session/valkey.py` and `deployment/aws/core/response_store/valkey.py` (both loaded lazily —
by `SessionStoreBuilder` and `ResponseDBHandler` respectively), so the base package is unaffected.

## Terraform: new `valkey` module

**Directory:** `ak-deployment/ak-aws/common/modules/valkey/` (new — `main.tf`, `variables.tf`,
`outputs.tf`, `README.md`)

A clone of `ak-deployment/ak-aws/common/modules/redis/` provisioning ElastiCache with the Valkey
engine:

- `aws_security_group.valkey` — ingress on `var.port` (default 6379) from `var.vpc_cidr`.
- `aws_elasticache_subnet_group.valkey` over `var.subnet_ids`.
- `aws_elasticache_cluster.valkey`:

```hcl
engine               = "valkey"
engine_version       = var.engine_version        # default "8.0"
node_type            = var.node_type             # default "cache.t4g.micro"
num_cache_nodes      = var.node_count            # default 1
parameter_group_name = var.parameter_group_name  # default "default.valkey8"
port                 = var.port
```

- Variables mirror the redis module (`product_alias`, `env_alias`, `module_name`, `tags`,
  `vpc_cidr`, `vpc_id`, `subnet_ids`, `node_type`, `node_count`, `port`) plus `engine_version` and
  `parameter_group_name` so future Valkey majors don't require a module change.
- Output `url = "valkey://<node address>:<port>"` (same single-output shape as the redis module).
- Like Redis, Valkey needs no IAM — access is network-level via the security group.
- The README documents that `engine_version` and `parameter_group_name` must move together — the
  parameter group family must match the engine major version (e.g. overriding `engine_version` to
  a 7.x requires `parameter_group_name = "default.valkey7"`); overriding only one fails at
  `terraform apply`.

The module ships in the next `yaalalabs/ak-common/aws` release; the containerized and serverless
root modules bump their pinned `version` of `ak-common` accordingly.

## AWS containerized (ECS) wiring

**Files:** `ak-deployment/ak-aws/containerized/variables.tf`,
`ak-deployment/ak-aws/containerized/state.tf`,
`ak-deployment/ak-aws/containerized/modules/rest-service/{main.tf,variables.tf}`,
`ak-deployment/ak-aws/containerized/modules/agent-runner/{main.tf,variables.tf}`

Mirror the existing `create_redis_cluster` path end to end:

1. `variables.tf`: `create_valkey_cluster` (bool, default `false`), plus optional pass-through
   sizing variables if desired (`valkey_node_type`).
2. `state.tf`: `local.valkey_url = var.create_valkey_cluster ? module.valkey[0].url : null` and a
   count-gated `module "valkey"` block sourcing `yaalalabs/ak-common/aws//modules/valkey`, wired to
   the same VPC/subnets as the redis block.
3. `modules/rest-service/main.tf` and `modules/agent-runner/main.tf`: accept a `valkey_url`
   variable and merge `{ AK_SESSION__VALKEY__URL = var.valkey_url }` into the container environment
   map when non-null — exactly how `AK_SESSION__REDIS__URL` is injected today.

As with Redis, the env var alone does not switch the backend: the `config.yaml` baked into the
Docker image must set `session.type: valkey`. Terraform injects only the endpoint URL.

## AWS serverless (Lambda) wiring

**Files:** `ak-deployment/ak-aws/serverless/variables.tf`,
`ak-deployment/ak-aws/serverless/state.tf`, and the Lambda submodules that currently receive
`redis_url` or `response_store_redis` (`serverless/modules/agent-runner/`,
`serverless/modules/request-handler/`, `serverless/modules/response-handler/`)

Mirror both roles of the existing redis wiring — session store and response store:

1. `variables.tf`: `create_valkey_cluster` (bool, default `false`) and
   `create_valkey_response_store` (bool, default `false`). Validation blocks mirror the existing
   redis/dynamodb ones: `create_valkey_response_store` must be `false` when `execution_mode` is
   `async` or `stream` (WebSocket modes push responses over the connection), and at most one of
   `create_redis_response_store` / `create_dynamodb_response_store` /
   `create_valkey_response_store` may be `true`.
2. `state.tf`: `local.create_valkey_response_store_effective = var.create_valkey_response_store &&
   !local.is_websocket_mode`; the count-gated `module "valkey"` block is created when
   `var.create_valkey_cluster || local.create_valkey_response_store_effective` (same dual-purpose
   gating as the redis module); `local.valkey_url`, `local.response_store_valkey_url`, and
   `local.response_handler_response_store_valkey = { url = ... }` mirror their redis counterparts.
3. Lambda submodules: `agent-runner` and `request-handler` receive `valkey_url` and inject
   `AK_SESSION__VALKEY__URL` when set; `request-handler` and `response-handler` receive
   `response_store_valkey` and inject `AK_EXECUTION__RESPONSE_STORE__VALKEY__URL` when set —
   exactly how `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` is injected today.

As with the session store, Terraform injects only endpoint URLs; selecting
`execution.response_store.type: valkey` happens in the `config.yaml` packaged with the Lambda.

## Runnable example

**Directory:** `examples/memory/valkey/` (new)

A copy of `examples/memory/redis/` adapted to Valkey:

- `config.yaml` with `session.type: valkey` and a placeholder `session.valkey.url`.
- `pyproject.toml` depending on `agentkernel[openai,valkey]`.
- `lambda.py`, `lambda_test.py`, `test-config.yaml`, `build.sh` — unchanged in structure.
- `deploy/` (`main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`, `Dockerfile`,
  `deploy.sh`) calling the published serverless module with `create_valkey_cluster = true`.
- `README.md` documenting local run (a local `valkey` container / `valkey://localhost:6379`
  default) and AWS deployment steps.

## Error handling

- **Unknown `session.type`**: unchanged — `SessionStoreBuilder.Types.from_str` logs a warning and
  falls back to `InMemorySessionStore`. `valkey` becomes a recognized value.
- **`valkey` package not installed**: the lazy imports in `SessionStoreBuilder.build()` and
  `ResponseDBHandler.__init__()` raise `ImportError` at startup when `session.type: valkey` or
  `execution.response_store.type: valkey` is selected; the error message should tell the user to
  install `agentkernel[valkey]`.
- **Connection failures**: `ValkeyDriver` retries connection 3 times with a 2-second back-off and
  reconnects on a failed `ping()`, identical to `RedisDriver`. When all retries are exhausted, the
  last client error is raised (a clear connection error) instead of leaving a `None` client that
  later fails with `AttributeError` — this corrected behavior is applied to `RedisDriver` in this
  change and cloned by `ValkeyDriver`.
- **`load(strict=True)` on a missing session**: raises `KeyError`; non-strict load creates a new
  session — same contract as every other store.
- **`ttl = 0`**: disables expiry (no `EXPIRE` issued), matching Redis behavior — for both the
  session store and the response store.
- **Config validation**: a `session.type` or `execution.response_store.type` value outside the
  pattern regex fails Pydantic validation at config load, same as today.
- **Response store misconfiguration**: `ResponseDBHandler` raises `ValueError` when
  `execution.response_store.type: valkey` is set but the `valkey` config block is missing — the
  same contract as the redis and dynamodb branches.

## Documentation updates

- `docs/docs/core-concepts/session.md` — add Valkey to the backend list and a "Valkey Storage"
  section (env vars, TTL, `valkeys://` for SSL, caching) next to the Redis section.
- `docs/docs/core-concepts/configuration.md` — YAML/JSON examples and the
  `AK_SESSION__VALKEY__*` / `AK_EXECUTION__RESPONSE_STORE__VALKEY__*` env-var reference, plus
  `valkey` in the `execution.response_store.type` options. Add a note that
  `multimodal.storage_type` and `a2a.task_store_type` remain Redis-only for now, and that a
  Valkey server can be used for those surfaces by pointing the existing `redis` config blocks at
  it with the `redis://` scheme (Valkey is wire-compatible).
- `docs/docs/deployment/aws-containerized.md` and `docs/docs/deployment/aws-serverless.md` —
  document `create_valkey_cluster`; the serverless page also documents
  `create_valkey_response_store` next to the existing response-store toggles.
- `ak-deployment/ak-aws/serverless/modules/request-handler/README.md` and
  `ak-deployment/ak-aws/serverless/modules/response-handler/README.md` — add
  `AK_EXECUTION__RESPONSE_STORE__VALKEY__URL` to the env-var lists.
- `ak-deployment/ak-aws/common/modules/valkey/README.md` (new) — modeled on the redis module
  README.
- `ak-deployment/ak-aws/containerized/README.md` and `ak-deployment/ak-aws/serverless/README.md` —
  add the toggle to the quick-start/variables tables.
- `examples/memory/valkey/README.md` (new).
- (Versioned docs under `docs/versioned_docs/` are frozen snapshots and are not touched.)

## Implementation plan

### Task 1: Implement the Valkey session store

**Files:** `ak-py/src/agentkernel/core/session/redis.py`,
`ak-py/src/agentkernel/core/session/valkey.py` (new)

1. Fix the two latent `RedisDriver` defects in `redis.py` first: `_connect()` re-raises the last
   `redis.RedisError` once retries are exhausted (instead of silently leaving a `None` client),
   and `_redis_client` becomes an instance attribute initialized in `__init__` (instead of a
   shadowed class attribute).
2. Create `ValkeyDriver` mirroring the corrected `RedisDriver` (`core/session/redis.py`), reading
   `AKConfig.get().session.valkey.{url,prefix,ttl}` and using `valkey.from_url(...,
   decode_responses=False, socket_connect_timeout=5)` with retry/reconnect logic.
3. Create `ValkeySessionStore(SessionStore)` implementing `new`, `load`, `store`, `clear` with the
   hash-per-session layout, `"__init__"` sentinel, `BinarySerde` serialization, TTL handling, and
   optional `SessionCache` support.

---

### Task 2: Implement the Valkey response store

**Files:** `ak-py/src/agentkernel/deployment/aws/core/response_store/valkey.py` (new),
`ak-py/src/agentkernel/deployment/aws/core/response_store/handler.py`

1. Create `ValkeyResponseStore(ResponseStore)` mirroring `RedisResponseStore`
   (`add_message` / `get_message` / `delete_message`, JSON per `{prefix}{request_id}` key,
   `EXPIRE` when `ttl > 0`), using `valkey.Valkey.from_url(url, decode_responses=True)`.
2. Add `VALKEY` to `ResponseDBHandler.Type` and the corresponding lazy-import construction branch
   in `ResponseDBHandler.__init__`; update the fallback `ValueError` message.

---

### Task 3: Configuration schema

**File:** `ak-py/src/agentkernel/core/config.py`

1. Add `_ValkeyConfig` (url / ttl / prefix, defaults as specified above).
2. Add `valkey: Optional[_ValkeyConfig] = None` to `_SessionStoreConfig` and extend the `type`
   pattern to `^(in_memory|redis|valkey|dynamodb|cosmosdb|firestore)$`.
3. Add `_ResponseStoreValkeyConfig(_ValkeyConfig)` (prefix default `ak:responses:`), add
   `valkey: Optional[_ResponseStoreValkeyConfig] = None` to `_ResponseStoreConfig`, and extend its
   `type` pattern to `^(redis|valkey|dynamodb)$`.

---

### Task 4: Builder support

**File:** `ak-py/src/agentkernel/core/builder.py`

1. Add `VALKEY` to `SessionStoreBuilder.Types`.
2. Add the `VALKEY` branch in `build()` with a lazy `from .session.valkey import
   ValkeySessionStore`.

---

### Task 5: Optional dependency

**File:** `ak-py/pyproject.toml`

1. Add the `valkey = ["valkey>=6.0.0"]` extra under `[project.optional-dependencies]`.

---

### Task 6: Unit tests

**Files:** `ak-py/tests/test_config.py`, `ak-py/tests/test_runtime.py`,
`ak-py/tests/test_sessions_valkey.py` (new), `ak-py/tests/test_response_store_valkey.py` (new),
`ak-py/tests/test_sessions_redis.py` (new)

1. `test_config.py`: YAML parsing of `session.type: valkey` with a nested `valkey` block; defaults
   (`session.valkey is None`); env-var overrides (`AK_SESSION__TYPE=valkey`,
   `AK_SESSION__VALKEY__TTL`); rejection of the type by the old pattern is replaced by acceptance.
   Same for the response store: `execution.response_store.type: valkey` with a nested `valkey`
   block parses, and the `_ResponseStoreValkeyConfig` prefix defaults to `ak:responses:`.
2. `test_runtime.py`: builder-selection test mirroring
   `test_runtime_instance_redis_when_config` — monkeypatched `AKConfig.get` with
   `session.type = "valkey"` asserts `SessionStoreBuilder.build()` returns a
   `ValkeySessionStore` (construction is lazy; no live server needed).
3. `test_sessions_valkey.py`: store behavior tests with a mocked/monkeypatched valkey client
   (`new`/`load`/`store`/`clear`, sentinel-field skipping, TTL application, strict-load
   `KeyError`), following the repo's monkeypatch conventions. Includes the connection-failure
   path: `from_url` mocked to always raise asserts that `_connect()` raises a clear client error
   after 3 attempts, not an `AttributeError` on a `None` client.
4. `test_sessions_redis.py` (new, minimal): mirrors the connection-failure test against the
   corrected `RedisDriver._connect()` so the Task 1 redis.py fix is pinned by a test.
5. `test_response_store_valkey.py`: `ValkeyResponseStore` behavior with a mocked valkey client
   (`add_message` key/TTL handling, `get_message` miss returns `None`, `get_and_delete`), plus a
   `ResponseDBHandler` selection test asserting `type: valkey` yields a `ValkeyResponseStore` and
   a missing `valkey` block raises `ValueError`.

---

### Task 7: Terraform `valkey` module

**Files:** `ak-deployment/ak-aws/common/modules/valkey/{main.tf,variables.tf,outputs.tf,README.md}`
(all new)

1. Clone the redis module; set `engine = "valkey"`, add `engine_version` (default `"8.0"`) and
   `parameter_group_name` (default `"default.valkey8"`) variables, default `node_type` to
   `cache.t4g.micro`.
2. Output `url` in `valkey://host:port` form.
3. Write the README modeled on `common/modules/redis/README.md`, documenting only outputs that
   actually exist, and stating that `engine_version` and `parameter_group_name` must move
   together (parameter group family must match the engine major version).

---

### Task 8: Containerized deployment wiring

**Files:** `ak-deployment/ak-aws/containerized/{variables.tf,state.tf}`,
`ak-deployment/ak-aws/containerized/modules/rest-service/{main.tf,variables.tf}`,
`ak-deployment/ak-aws/containerized/modules/agent-runner/{main.tf,variables.tf}`

1. Add `create_valkey_cluster` variable and the count-gated `module "valkey"` + `local.valkey_url`
   in `state.tf`.
2. Thread `valkey_url` into both service submodules and merge
   `AK_SESSION__VALKEY__URL` into their container environment maps when non-null.
3. Bump the pinned `yaalalabs/ak-common/aws` version once the new module is published.

---

### Task 9: Serverless deployment wiring

**Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf}`,
`ak-deployment/ak-aws/serverless/modules/agent-runner/`,
`ak-deployment/ak-aws/serverless/modules/request-handler/`,
`ak-deployment/ak-aws/serverless/modules/response-handler/`

1. Add `create_valkey_cluster` and `create_valkey_response_store` variables with the validation
   blocks described in the serverless wiring section (mutual exclusion with the other response
   stores; forbidden in WebSocket modes).
2. Add `local.valkey_url`, `local.create_valkey_response_store_effective`,
   `local.response_handler_response_store_valkey`, and the count-gated `module "valkey"` block
   (created for either the session-store or response-store role).
3. Pass `valkey_url` into the Lambda submodules and inject `AK_SESSION__VALKEY__URL`; pass
   `response_store_valkey` into `request-handler` and `response-handler` and inject
   `AK_EXECUTION__RESPONSE_STORE__VALKEY__URL`.

---

### Task 10: Runnable example

**Directory:** `examples/memory/valkey/` (new)

1. Copy `examples/memory/redis/`, switch `config.yaml` to `session.type: valkey`, dependencies to
   `agentkernel[openai,valkey]`, and `deploy/main.tf` to `create_valkey_cluster = true`.
2. Verify locally against a local Valkey container, then via `deploy/deploy.sh` on AWS.

---

### Task 11: Update documentation

**Files:** `docs/docs/core-concepts/session.md`, `docs/docs/core-concepts/configuration.md`,
`docs/docs/deployment/aws-containerized.md`, `docs/docs/deployment/aws-serverless.md`,
`ak-deployment/ak-aws/containerized/README.md`, `ak-deployment/ak-aws/serverless/README.md`,
`ak-deployment/ak-aws/serverless/modules/request-handler/README.md`,
`ak-deployment/ak-aws/serverless/modules/response-handler/README.md`,
`examples/memory/valkey/README.md` (new)

1. Apply the documentation updates listed in the "Documentation updates" section.
