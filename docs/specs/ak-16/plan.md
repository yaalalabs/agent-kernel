# Execution plan: Valkey session store with AWS deployment support (AK-16)

Plan for implementing [spec.md](./spec.md). The work splits into four phases that can largely be
executed in order, with Phase 2 (Terraform) having an external dependency (publishing a new
`yaalalabs/ak-common/aws` release) that gates the final verification of Phases 3–4.

## Phase overview and sequencing

| Phase | Tasks (spec) | Depends on | Verification |
|---|---|---|---|
| 1. Python backend | Tasks 1–5 | — | Unit tests, local Valkey container |
| 2. Terraform module | Task 6 | — (parallel with Phase 1) | `terraform validate`, module publish |
| 3. Deployment wiring | Tasks 7–8 | Phase 2 published release | `terraform validate` / `plan` |
| 4. Example + docs | Tasks 9–10 | Phases 1–3 | Local run + AWS deploy of example |

Phases 1 and 2 are independent and can be done in parallel. Phase 3 can be *written* before the
`ak-common` release exists (the version bump is a one-line change at the end), but `terraform plan`
against the registry will only pass after publish.

---

## Phase 1 — Python backend (`ak-py`)

### Step 1.1: Configuration schema (spec Task 2)

**File:** `ak-py/src/agentkernel/core/config.py`

Do config first — the store reads it, and the tests need it.

1. Add `_ValkeyConfig` (url `valkey://localhost:6379`, ttl `604800`, prefix `ak:sessions:`)
   immediately after `_RedisConfig` (config.py:22).
2. In `_SessionStoreConfig` (config.py:71):
   - extend the `type` pattern to `^(in_memory|redis|valkey|dynamodb|cosmosdb|firestore)$`
   - add `valkey: Optional[_ValkeyConfig] = None` next to the `redis` field (config.py:73).
3. Do **not** touch the response-store config (`_ResponseStoreConfig`, config.py:237) or the
   multimodal/task-store patterns — Valkey is session-store only in this CR.

### Step 1.2: `ValkeySessionStore` (spec Task 1)

**File:** `ak-py/src/agentkernel/core/session/valkey.py` (new)

1. Read `ak-py/src/agentkernel/core/session/redis.py` in full and clone it:
   - `ValkeyDriver`: reads `AKConfig.get().session.valkey.{url,prefix,ttl}`; lazy `client`
     property with `ping()` health check; reconnect on `valkey.ValkeyError`; `_connect()` via
     `valkey.from_url(url, decode_responses=False, socket_connect_timeout=5)` with 3 retries /
     2-second back-off; helpers `key()`, `hset()`, `hget()`, `expire()`, `hkeys()`, `exists()`,
     `clear_prefix()`.
   - `ValkeySessionStore(SessionStore)`: `new`/`load`/`store`/`clear`, hash-per-session at
     `{prefix}{session_id}`, `"__init__"` sentinel field, `BinarySerde` from `serde.py`,
     `store()` persists `session.get_all(volatile=False)` and refreshes TTL when `ttl != 0`,
     optional `SessionCache` injected by the builder.
2. Only substantive deltas from the redis file: `import valkey`, exception type
   (`valkey.ValkeyError`), config block (`session.valkey`), class/log names. Anything else that
   diverges is a bug.
3. No changes to `core/base.py` or `core/session/base.py`.

### Step 1.3: Builder + optional dependency (spec Tasks 3–4)

**Files:** `ak-py/src/agentkernel/core/builder.py`, `ak-py/pyproject.toml`

1. `builder.py`: add `VALKEY = "VALKEY"` to `SessionStoreBuilder.Types` and a lazy-import branch
   in `build()` (mirror the redis branch at builder.py:134):
   `from .session.valkey import ValkeySessionStore; return ValkeySessionStore(cache=SessionCacheBuilder.build())`.
   Confirm the `ImportError` path when the package is missing produces a message pointing at
   `pip install agentkernel[valkey]` (match how other optional backends phrase it).
2. `pyproject.toml`: add `valkey = ["valkey>=6.0.0"]` under `[project.optional-dependencies]`,
   next to the `redis` extra (pyproject.toml:60). Add `valkey` to the dev/test extras group if the
   repo's test environment installs backends that way (check how `redis` is pulled into CI).

### Step 1.4: Unit tests (spec Task 5)

**Files:** `ak-py/tests/test_config.py`, `ak-py/tests/test_runtime.py`,
`ak-py/tests/test_sessions_valkey.py` (new)

Consult the `ak-dev-testing-conventions` skill before writing these.

1. `test_config.py`: YAML parse of `session.type: valkey` + nested `valkey` block; default
   `session.valkey is None`; env overrides `AK_SESSION__TYPE=valkey`, `AK_SESSION__VALKEY__TTL`.
2. `test_runtime.py`: clone `test_runtime_instance_redis_when_config` — monkeypatched
   `AKConfig.get` with `session.type = "valkey"` asserts `SessionStoreBuilder.build()` returns a
   `ValkeySessionStore` (no live server; construction is lazy).
3. `test_sessions_valkey.py`: mocked/monkeypatched valkey client covering `new`/`load`/`store`/
   `clear`, `"__init__"` sentinel skipping on load, TTL applied when `ttl != 0` and skipped when
   `ttl == 0`, `load(strict=True)` on a missing session raising `KeyError`. Note there is no
   existing `test_sessions_redis.py` to clone — base the structure on
   `test_sessions_in_memory.py` plus the repo's monkeypatch conventions.

**Phase 1 verification**

- `cd ak-py && uv run pytest tests/test_config.py tests/test_runtime.py tests/test_sessions_valkey.py`
  then the full suite.
- Smoke test against a real server: `docker run -p 6379:6379 valkey/valkey`, a minimal script
  with `session.type: valkey` exercising `new → store → load → clear`.
- Run the repo's formatter/linter per `ak-dev-code-quality` before committing.

---

## Phase 2 — Terraform `valkey` module (spec Task 6)

**Directory:** `ak-deployment/ak-aws/common/modules/valkey/` (new:
`main.tf`, `variables.tf`, `outputs.tf`, `README.md`)

1. Clone `common/modules/redis/`. Deltas:
   - `aws_elasticache_cluster`: `engine = "valkey"`, `engine_version = var.engine_version`
     (default `"8.0"`), `parameter_group_name = var.parameter_group_name`
     (default `"default.valkey8"`), `node_type` default `cache.t4g.micro`.
   - Resources/SG/subnet-group renamed `redis` → `valkey`.
   - New variables `engine_version` and `parameter_group_name`; keep the rest identical
     (`product_alias`, `env_alias`, `module_name`, `tags`, `vpc_cidr`, `vpc_id`, `subnet_ids`,
     `node_type`, `node_count`, `port`).
   - Single output `url = "valkey://<address>:<port>"`.
2. README modeled on the redis module README — document only variables/outputs that exist.
3. Verify: `terraform init && terraform validate` in the module dir, `terraform fmt -check`.
4. **Release gate:** the module ships in the next `yaalalabs/ak-common/aws` registry release.
   Coordinate/cut that release; note the released version — Phases 3 and 4 pin it.

---

## Phase 3 — Deployment wiring

Can be authored before the ak-common release; the `version` bump lands last.

### Step 3.1: Containerized / ECS (spec Task 7)

**Files:** `ak-deployment/ak-aws/containerized/{variables.tf,state.tf}`,
`containerized/modules/rest-service/{main.tf,variables.tf}`,
`containerized/modules/agent-runner/{main.tf,variables.tf}`

1. `variables.tf`: `create_valkey_cluster` (bool, default `false`) next to
   `create_redis_cluster` (variables.tf:108). Optionally `valkey_node_type` pass-through.
2. `state.tf`: mirror the redis pattern —
   `local.valkey_url = var.create_valkey_cluster == true ? module.valkey[0].url : null`
   (cf. state.tf:10) and a count-gated `module "valkey"` sourcing
   `yaalalabs/ak-common/aws//modules/valkey` on the same VPC/subnets (cf. state.tf:66).
3. Submodules: add a `valkey_url` variable (default `null`) and inject the env var exactly as
   redis does today:
   - `modules/rest-service/main.tf:5` — add `AK_SESSION__VALKEY__URL` alongside
     `AK_SESSION__REDIS__URL` (respect the existing null-handling style in that file).
   - `modules/agent-runner/main.tf:12` — add
     `var.valkey_url != null ? { AK_SESSION__VALKEY__URL = var.valkey_url } : {}` to the merge.
4. Bump the pinned `ak-common` `version` once Phase 2 is published.

### Step 3.2: Serverless / Lambda (spec Task 8)

**Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf}`,
`serverless/modules/agent-runner/`, `serverless/modules/request-handler/`

1. `variables.tf`: `create_valkey_cluster` (bool, default `false`). Do **not** add a
   `create_valkey_response_store` — response store is explicitly out of scope.
2. `state.tf`: `local.valkey_url` + count-gated `module "valkey"` gated **only** on
   `var.create_valkey_cluster` (unlike redis at state.tf:270, which is also gated on the response
   store — do not copy that OR-condition). Pass `valkey_url` into `agent-runner` and
   `request-handler` alongside `redis_url`. Mirror the queue-mode nuance at state.tf:465
   (`redis_url = var.queue_mode ? null : local.redis_url`) for valkey so behavior stays parallel.
3. Submodules: add `valkey_url` variable and inject `AK_SESSION__VALKEY__URL` next to the
   existing `AK_SESSION__REDIS__URL` (agent-runner/main.tf:210, request-handler/main.tf:258),
   using the same null-handling those files use.
4. Bump the pinned `ak-common` `version`.

**Phase 3 verification**

- `terraform fmt -check` and `terraform init -upgrade && terraform validate` in both roots
  (after the ak-common release).
- A `terraform plan` with `create_valkey_cluster = true` in a sandbox workspace to confirm the
  module wires up and the env var lands in the task definition / Lambda environment.
- Confirm `create_redis_cluster` paths are untouched (`git diff` review: valkey additions only).

---

## Phase 4 — Example and documentation

### Step 4.1: Runnable example (spec Task 9)

**Directory:** `examples/memory/valkey/` (new)

1. Copy `examples/memory/redis/` (config.yaml, pyproject.toml, lambda.py, lambda_test.py,
   test-config.yaml, build.sh, deploy/, README.md; regenerate `uv.lock`, don't copy it).
2. Deltas: `config.yaml` → `session.type: valkey` + placeholder `session.valkey.url`;
   `pyproject.toml` → `agentkernel[openai,valkey]`; `deploy/main.tf` →
   `create_valkey_cluster = true` and the new serverless module version; README rewritten for
   Valkey (local `valkey/valkey` container, `valkey://localhost:6379`, `valkeys://` for SSL).
3. Verify locally against a local Valkey container, then end-to-end via `deploy/deploy.sh` on
   AWS (create, exercise a session across two invocations, destroy).

### Step 4.2: Documentation (spec Task 10)

**Files:** `docs/docs/core-concepts/session.md`, `docs/docs/core-concepts/configuration.md`,
`docs/docs/deployment/aws-containerized.md`, `docs/docs/deployment/aws-serverless.md`,
`ak-deployment/ak-aws/containerized/README.md`, `ak-deployment/ak-aws/serverless/README.md`

1. `session.md`: add Valkey to the backend list + a "Valkey Storage" section (env vars, TTL,
   `valkeys://`, caching) placed next to the Redis section, matching its structure.
2. `configuration.md`: YAML/JSON examples + `AK_SESSION__VALKEY__*` env-var reference.
3. Deployment docs + both deployment READMEs: document `create_valkey_cluster` in the
   quick-start/variables tables.
4. Leave `docs/versioned_docs/` untouched (frozen snapshots).
5. Before the PR, run the `ak-dev-sync-skills-from-branch` / `ak-dev-sync-docs-from-branch`
   flows so skills and docs surfaces match the implementation.

---

## Definition of done

- [ ] Full `ak-py` test suite green, including the three new/updated test files.
- [ ] `session.type: valkey` works against a live local Valkey container (new/load/store/clear,
      TTL, strict-load `KeyError`).
- [ ] Base install unaffected: importing `agentkernel` without the `valkey` extra works; selecting
      `session.type: valkey` without it raises an actionable `ImportError`.
- [ ] `terraform validate` passes for the valkey module and both deployment roots; redis paths
      byte-identical to before.
- [ ] New `ak-common` release published and pinned in both roots and the example.
- [ ] Example deploys and runs on AWS with `create_valkey_cluster = true`.
- [ ] Docs updated per Step 4.2; no versioned docs touched.
- [ ] Commits/PR follow `ak-dev-code-quality` conventions; PR targets `develop`.

## Risks and notes

- **ak-common release is the critical path** for Phases 3–4 verification. Author everything
  first, then bump versions once published, so the release doesn't block coding.
- **Serverless gating differs from redis on purpose**: the redis module count is
  `create_redis_cluster || response-store`; valkey is session-store only. Copying the redis
  condition verbatim would silently create clusters for a response store that doesn't exist.
- **valkey-py drift**: valkey-py is a drop-in redis-py fork, but confirm the exception hierarchy
  (`valkey.ValkeyError`) and `from_url` kwargs against the installed `valkey>=6.0.0` rather than
  assuming redis-py parity.
- **Both stores enabled**: `create_redis_cluster` and `create_valkey_cluster` can both be true;
  only the `session.type` baked into the image decides which is used. Worth one sentence in the
  deployment docs to prevent confusion.
