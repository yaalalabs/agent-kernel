# #527: Thread store deployment support — Implementation Plan

Ordering of the [`spec.md`](./spec.md) build. Each iteration leaves the branch working and testable.
Unit tests land **with** the code they cover; the dedicated Tests iteration is the full-suite + lint
gate. Terraform iterations are verified with `terraform validate`, not pytest — they are exercised end
to end by the weekly integration run of `examples/memory/dynamodb` (Iteration 5).

Iterations 1–2 are ordered deliberately: the refactor lands **before** the new backend, so the existing
Redis tests prove it behaviour-preserving on their own, without a new store in the picture to muddy a
failure.

## Iteration 1: Extract the shared Redis/Valkey thread store body

- **Goal:** `RedisThreadStore` behaves identically, but its body lives in a reusable base class ready
  for a second backend.
- **Files:** `ak-py/src/agentkernel/core/thread/store/redis_like.py` (new — `_RedisLikeThreadStore`);
  `ak-py/src/agentkernel/core/thread/store/redis.py` (reduced to `__init__`). No test changes.
- **Steps:** 1) move every method from `RedisThreadStore` into `_RedisLikeThreadStore`; 2) leave
  `RedisThreadStore.__init__` (logger + `thread.redis` + `RedisDriver`) behind, subclassing the base
  (spec §"Core: Valkey thread store", rule 1).
- **Verify:** `cd ak-py && uv run pytest tests/test_thread_store_redis.py` — **must pass with the test
  file untouched.** Any edit needed there means behaviour changed; stop and reconsider.

## Iteration 2: Valkey thread store + config + builder

- **Goal:** `thread.type: valkey` builds a working `ValkeyThreadStore`; the `valkey` extra stays
  optional.
- **Files:** `ak-py/src/agentkernel/core/config.py` (`_ThreadValkeyConfig`, `_ThreadStoreConfig.valkey`,
  `type` description); `ak-py/src/agentkernel/core/thread/store/valkey.py` (new);
  `ak-py/src/agentkernel/core/thread/store/base.py` (`_BUILTIN_THREAD_STORES`, `build()` branch +
  docstring); tests `tests/test_thread_store_valkey.py` (new), `tests/test_store_builders.py`,
  `tests/test_config.py`.
- **Steps:** 1) config classes/field/description; 2) `ValkeyThreadStore` subclassing the Iteration 1
  base; 3) `"valkey"` in `_BUILTIN_THREAD_STORES` (after `"redis"`) + `require_extra`-guarded `build()`
  branch; 4) tests (spec §Testing).
- **Verify:** `cd ak-py && uv run pytest tests/test_thread_store_valkey.py tests/test_store_builders.py tests/test_config.py tests/test_thread_store_redis.py`

## Iteration 3: AWS serverless Terraform — DynamoDB thread table

- **Goal:** `create_dynamodb_thread_table = true` provisions the table, injects `AK_THREAD__TYPE` +
  `AK_THREAD__DYNAMODB__TABLE_NAME`, and grants scoped IAM on both Lambda roles.
- **Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf}`;
  `modules/request-handler/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf`
  (spec §"AWS serverless (Lambda) Terraform").
- **Steps:** 1) variable; 2) locals + `dynamodb_thread` module (`table_name = "thread_store"`, no GSI);
  3) pass-through to both modules — **not** gated on `queue_mode`, unlike the memory flags; 4) env vars
  in both env-merge blocks, gated on `dynamodb_thread_table_arn != null`, TYPE + NAME together;
  5) IAM policy + attachment on both roles, table ARN only.
- **Verify:** `terraform init && terraform validate` in `ak-deployment/ak-aws/serverless`.

## Iteration 4: AWS containerized Terraform — DynamoDB thread table

- **Goal:** Same table/env/IAM on the ECS stack, across the rest-service and agent-runner task roles.
- **Files:** `ak-deployment/ak-aws/containerized/{variables.tf,state.tf}`;
  `modules/rest-service/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf`
  (spec §"AWS containerized (ECS) Terraform").
- **Steps:** mirror Iteration 3 against the ECS modules, with one difference: `tasks_iam_role_policies`
  must **merge** the new policy alongside the existing `DynamoDB` entry rather than replace it, and the
  thread policy drops session's `/index/*` grant.
- **Verify:** `terraform init && terraform validate` in `ak-deployment/ak-aws/containerized`.

## Iteration 5: GCP Terraform — Firestore thread wiring

- **Goal:** `create_firestore_thread_collection = true` wires the Firestore-backed thread store on both
  GCP dirs, reusing the existing database. No new IAM (already project-scoped).
- **Files:** `ak-deployment/ak-gcp/serverless/{variables.tf,cloud_function.tf}`;
  `ak-deployment/ak-gcp/containerized/{variables.tf,cloud_run.tf}` (spec §"GCP Terraform").
- **Steps:** 1) flag on both dirs; 2) extend each firestore env block with the four `AK_THREAD__*` vars,
  gated on `local.firestore_db_name != null && var.create_firestore_thread_collection` — the collection
  name is supplied literally, **not** from `module.firestore[0].collection_name` (that output is the
  session collection).
- **Verify:** `terraform init && terraform validate` in both GCP dirs. No live `plan`/`apply` — no GCP
  credentials available to this project.

## Iteration 6: Examples

- **Goal:** A deployed stack proves thread provisioning works end to end.
- **Files:** `examples/memory/dynamodb/{config.yaml,deploy/main.tf,lambda_test.py}`;
  `examples/gcp-serverless/openai-firestore/{config.yaml,deploy/}`. No matrix change — the AWS example is
  already in `weekly.tests`.
- **Steps:** 1) add the `thread:` block and `create_dynamodb_thread_table = true` to the AWS example;
  2) **update `lambda_test.py` to send `user_id` on every chat request** — thread support makes it
  required, and this is the one change that silently breaks the example if missed (spec §"Docs and
  example"); 3) same treatment for the GCP example.
- **Verify:** `cd examples/memory/dynamodb && ./build.sh && uv run pytest` locally; then the weekly
  integration workflow.

## Iteration 7: Tests and lint gate

- **Goal:** Whole suite green and formatted.
- **Steps:** recap of the surface added in Iterations 1–2 — `tests/test_thread_store_valkey.py` (new),
  `tests/test_store_builders.py` + `tests/test_config.py` (changed), `tests/test_thread_store_redis.py`
  (**unchanged — the refactor's regression gate**). Run the full suite and linters.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`. Note: three failures in
  `tests/test_cli_tester.py` are pre-existing on this branch (Ragas judge tests needing live LLM
  credentials) and unrelated to this change.

## Iteration 8: Sync docs and skills

- **Goal:** Reference surfaces match the shipped change.
- **Files/lines:**
  - `.agents/skills/ak-dev-architecture/SKILL.md:210` — add a `Valkey | ValkeyThreadStore |
    store/valkey.py | …` row to the thread Store Backends table (between the Redis and DynamoDB rows).
  - `.agents/skills/ak-dev-architecture/SKILL.md:219` — add `valkey` to the thread `type` comment list
    and show a `thread.valkey` block.
  - `.agents/skills/ak-dev-architecture/SKILL.md:199` — **pre-existing error worth fixing while here:**
    it places `ThreadStoreBuilder` in `store/__init__.py`; it lives in `store/base.py:130`.
  - `docs/docs/advanced/threads.md:176-208` — add a `# Valkey` block to the Storage Backends YAML
    examples, beside the Redis one.
  - `docs/docs/core-concepts/configuration.md` — add `valkey` to the thread `type` comment list.
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md` — add `valkey` to the thread backend
    lists (two `type:` comment lines).
  - Deployment docs/READMEs under `ak-deployment/ak-aws/*` and `ak-deployment/ak-gcp/*` — document
    `create_dynamodb_thread_table` / `create_firestore_thread_collection`, and the mandatory
    `AK_THREAD__TYPE` + connection-vars pairing (the silent-misconfiguration risk).
- **Verify:** run the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows before
  merge.
