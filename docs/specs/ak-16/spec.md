# Valkey session store with AWS deployment support (AK-16)

This change adds Valkey as a first-class session storage backend in Agent Kernel, alongside the
existing Redis, DynamoDB, Cosmos DB, and Firestore backends. It also adds the AWS infrastructure to
deploy a Valkey cluster (ElastiCache for Valkey) via Terraform, wires it into both the containerized
(ECS) and serverless (Lambda) deployment modules, and ships a runnable example. The implementation
closely mirrors the existing Redis session store — Valkey is wire-compatible with Redis — but is a
distinct backend with its own client library, configuration block, and Terraform module.

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
| Response store | Out of scope. The AWS response store keeps its `redis`/`dynamodb` types. (Because Valkey is protocol-compatible, users can point `execution.response_store.redis.url` at a Valkey endpoint, but no new response-store type is added in this CR.) |

## `ValkeySessionStore` (`session.type: valkey`)

**File:** `ak-py/src/agentkernel/core/session/valkey.py` (new)

A near-clone of `ak-py/src/agentkernel/core/session/redis.py`, using `import valkey` instead of
`import redis`:

- `ValkeyDriver` — connection management and namespaced hash helpers:
  - Reads `AKConfig.get().session.valkey.{url, prefix, ttl}` in `__init__`.
  - Lazy `client` property with `ping()` health check and reconnect on `valkey.ValkeyError`
    (valkey-py's equivalent of `redis.RedisError`).
  - `_connect()` via `valkey.from_url(url, decode_responses=False, socket_connect_timeout=5)` with
    3 retries and a 2-second back-off, identical to `RedisDriver._connect`.
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
```

Environment variables (env beats YAML, prefix `AK_`, `__` nesting — unchanged mechanism):
`AK_SESSION__TYPE=valkey`, `AK_SESSION__VALKEY__URL`, `AK_SESSION__VALKEY__TTL`,
`AK_SESSION__VALKEY__PREFIX`.

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

Users install with `agentkernel[openai,valkey]`. The import stays inside
`core/session/valkey.py` (loaded lazily by the builder), so the base package is unaffected.

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
`redis_url` (`serverless/modules/agent-runner/`, `serverless/modules/request-handler/`)

Mirror the session-store half of the existing redis wiring:

1. `variables.tf`: `create_valkey_cluster` (bool, default `false`).
2. `state.tf`: `local.valkey_url` + count-gated `module "valkey"` block; pass `valkey_url` into the
   Lambda submodules alongside the existing `redis_url`.
3. Lambda submodules inject `AK_SESSION__VALKEY__URL` into their function environment when set.

The redis module's second role in serverless — the response store
(`create_redis_response_store`) — is **not** duplicated for Valkey in this CR (see Design
decisions).

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
- **`valkey` package not installed**: the lazy import in `SessionStoreBuilder.build()` raises
  `ImportError` at startup when `session.type: valkey` is selected; the error message should tell
  the user to install `agentkernel[valkey]`.
- **Connection failures**: `ValkeyDriver` retries connection 3 times with a 2-second back-off and
  reconnects on a failed `ping()`, identical to `RedisDriver`.
- **`load(strict=True)` on a missing session**: raises `KeyError`; non-strict load creates a new
  session — same contract as every other store.
- **`ttl = 0`**: disables expiry (no `EXPIRE` issued), matching Redis behavior.
- **Config validation**: a `session.type` value outside the pattern regex fails Pydantic validation
  at config load, same as today.

## Documentation updates

- `docs/docs/core-concepts/session.md` — add Valkey to the backend list and a "Valkey Storage"
  section (env vars, TTL, `valkeys://` for SSL, caching) next to the Redis section.
- `docs/docs/core-concepts/configuration.md` — YAML/JSON examples and the
  `AK_SESSION__VALKEY__*` env-var reference.
- `docs/docs/deployment/aws-containerized.md` and `docs/docs/deployment/aws-serverless.md` —
  document `create_valkey_cluster`.
- `ak-deployment/ak-aws/common/modules/valkey/README.md` (new) — modeled on the redis module
  README.
- `ak-deployment/ak-aws/containerized/README.md` and `ak-deployment/ak-aws/serverless/README.md` —
  add the toggle to the quick-start/variables tables.
- `examples/memory/valkey/README.md` (new).
- (Versioned docs under `docs/versioned_docs/` are frozen snapshots and are not touched.)

## Implementation plan

### Task 1: Implement the Valkey session store

**File:** `ak-py/src/agentkernel/core/session/valkey.py` (new)

1. Create `ValkeyDriver` mirroring `RedisDriver` (`core/session/redis.py`), reading
   `AKConfig.get().session.valkey.{url,prefix,ttl}` and using `valkey.from_url(...,
   decode_responses=False, socket_connect_timeout=5)` with retry/reconnect logic.
2. Create `ValkeySessionStore(SessionStore)` implementing `new`, `load`, `store`, `clear` with the
   hash-per-session layout, `"__init__"` sentinel, `BinarySerde` serialization, TTL handling, and
   optional `SessionCache` support.

---

### Task 2: Configuration schema

**File:** `ak-py/src/agentkernel/core/config.py`

1. Add `_ValkeyConfig` (url / ttl / prefix, defaults as specified above).
2. Add `valkey: Optional[_ValkeyConfig] = None` to `_SessionStoreConfig` and extend the `type`
   pattern to `^(in_memory|redis|valkey|dynamodb|cosmosdb|firestore)$`.

---

### Task 3: Builder support

**File:** `ak-py/src/agentkernel/core/builder.py`

1. Add `VALKEY` to `SessionStoreBuilder.Types`.
2. Add the `VALKEY` branch in `build()` with a lazy `from .session.valkey import
   ValkeySessionStore`.

---

### Task 4: Optional dependency

**File:** `ak-py/pyproject.toml`

1. Add the `valkey = ["valkey>=6.0.0"]` extra under `[project.optional-dependencies]`.

---

### Task 5: Unit tests

**Files:** `ak-py/tests/test_config.py`, `ak-py/tests/test_runtime.py`,
`ak-py/tests/test_sessions_valkey.py` (new)

1. `test_config.py`: YAML parsing of `session.type: valkey` with a nested `valkey` block; defaults
   (`session.valkey is None`); env-var overrides (`AK_SESSION__TYPE=valkey`,
   `AK_SESSION__VALKEY__TTL`); rejection of the type by the old pattern is replaced by acceptance.
2. `test_runtime.py`: builder-selection test mirroring
   `test_runtime_instance_redis_when_config` — monkeypatched `AKConfig.get` with
   `session.type = "valkey"` asserts `SessionStoreBuilder.build()` returns a
   `ValkeySessionStore` (construction is lazy; no live server needed).
3. `test_sessions_valkey.py`: store behavior tests with a mocked/monkeypatched valkey client
   (`new`/`load`/`store`/`clear`, sentinel-field skipping, TTL application, strict-load
   `KeyError`), following the repo's monkeypatch conventions.

---

### Task 6: Terraform `valkey` module

**Files:** `ak-deployment/ak-aws/common/modules/valkey/{main.tf,variables.tf,outputs.tf,README.md}`
(all new)

1. Clone the redis module; set `engine = "valkey"`, add `engine_version` (default `"8.0"`) and
   `parameter_group_name` (default `"default.valkey8"`) variables, default `node_type` to
   `cache.t4g.micro`.
2. Output `url` in `valkey://host:port` form.
3. Write the README modeled on `common/modules/redis/README.md`, documenting only outputs that
   actually exist.

---

### Task 7: Containerized deployment wiring

**Files:** `ak-deployment/ak-aws/containerized/{variables.tf,state.tf}`,
`ak-deployment/ak-aws/containerized/modules/rest-service/{main.tf,variables.tf}`,
`ak-deployment/ak-aws/containerized/modules/agent-runner/{main.tf,variables.tf}`

1. Add `create_valkey_cluster` variable and the count-gated `module "valkey"` + `local.valkey_url`
   in `state.tf`.
2. Thread `valkey_url` into both service submodules and merge
   `AK_SESSION__VALKEY__URL` into their container environment maps when non-null.
3. Bump the pinned `yaalalabs/ak-common/aws` version once the new module is published.

---

### Task 8: Serverless deployment wiring

**Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf}`,
`ak-deployment/ak-aws/serverless/modules/agent-runner/`,
`ak-deployment/ak-aws/serverless/modules/request-handler/`

1. Add `create_valkey_cluster` variable, `local.valkey_url`, and the count-gated `module "valkey"`.
2. Pass `valkey_url` into the Lambda submodules and inject `AK_SESSION__VALKEY__URL` into their
   environments (session store only; response store unchanged).

---

### Task 9: Runnable example

**Directory:** `examples/memory/valkey/` (new)

1. Copy `examples/memory/redis/`, switch `config.yaml` to `session.type: valkey`, dependencies to
   `agentkernel[openai,valkey]`, and `deploy/main.tf` to `create_valkey_cluster = true`.
2. Verify locally against a local Valkey container, then via `deploy/deploy.sh` on AWS.

---

### Task 10: Update documentation

**Files:** `docs/docs/core-concepts/session.md`, `docs/docs/core-concepts/configuration.md`,
`docs/docs/deployment/aws-containerized.md`, `docs/docs/deployment/aws-serverless.md`,
`ak-deployment/ak-aws/containerized/README.md`, `ak-deployment/ak-aws/serverless/README.md`,
`examples/memory/valkey/README.md` (new)

1. Apply the documentation updates listed in the "Documentation updates" section.
