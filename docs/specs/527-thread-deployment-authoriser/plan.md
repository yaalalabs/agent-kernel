# #527: Thread store deployment support and Authoriser support for serverless and ECS — Implementation Plan

> **Note:** `design.md` is **not yet reviewed/approved**. `design.md`, `spec.md`, and `plan.md` are
> being revised together in this pass following informal pre-review feedback (see `design.md`'s Open
> Questions for what changed and why). This iteration ordering assumes the design as currently
> written; re-check it here if `design.md` changes further before implementation begins.

Ordering of the [`spec.md`](./spec.md) build. Each iteration leaves the branch working and testable.
New unit tests land **with** the code they cover (repo convention: features ship with tests, and each
iteration stays verifiable); the dedicated Tests iteration is the full-suite + lint gate and the
changed-existing-test recap. Terraform iterations are verified with `terraform validate`/`plan`, not
pytest — they are exercised end to end by the weekly integration example.

## Iteration 1: Core Valkey thread store

- **Goal:** `thread.type: valkey` builds a working `ValkeyThreadStore`; the `valkey` extra stays
  optional.
- **Files:** `ak-py/src/agentkernel/core/config.py` (add `_ThreadValkeyConfig`, `valkey` field, add
  `valkey` to the `type` field description); `ak-py/src/agentkernel/core/thread/store/valkey.py`
  (new); refactor the shared Redis/Valkey body per spec §"Core: Valkey thread store" rule 1;
  `ak-py/src/agentkernel/core/thread/store/base.py` (`"valkey"` in `_BUILTIN_THREAD_STORES` +
  `require_extra`-guarded `build()` branch); tests `tests/test_thread_store_valkey.py` (new, store
  behaviour) and `tests/test_store_builders.py` (valkey builder-dispatch), plus `tests/test_config.py`
  (valkey assertions).
- **Steps:** 1) config changes; 2) factor `_RedisLikeThreadStore` base and derive both stores;
  3) `_BUILTIN_THREAD_STORES` entry + `require_extra`-guarded branch; 4) tests.
- **Verify:** `cd ak-py && uv run pytest tests/test_thread_store_valkey.py tests/test_store_builders.py tests/test_config.py`.

## Iteration 2: ECS Authoriser mounting

- **Goal:** `ECSIOHandler.run(authoriser=...)` mounts a configured `ThreadRESTRequestHandler` in
  queue mode; `authoriser=None` preserves today's open behaviour.
- **Files:** `ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py`; test
  `tests/test_ecs_io_handler.py` (new).
- **Steps:** 1) add the optional param and build the handlers list gated on `AKConfig.get().thread`
  (spec §"Containerized (ECS): Authoriser mounting"); 2) test with `RESTAPI.run`/`ThreadRunner.run`
  patched.
- **Verify:** `cd ak-py && uv run pytest tests/test_ecs_io_handler.py`.

## Iteration 3: Generic Lambda path-parameter routing

- **Goal:** `RESTLambdaRouter.dispatch()` can match a route registered with a `{param}` segment (e.g.
  `Lambda.register("/threads/{session_id}", method="GET")`) against a real request — a general
  Lambda platform capability, independent of thread, that today silently 500s. Every existing static
  route continues to dispatch exactly as before.
- **Files:** `ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py`
  (`dispatch()` only — `register()` is untouched); test `tests/test_lambda_router.py` (changed).
- **Steps:** 1) add the additive fallback lookup keyed on `event["resource"]`, tried only when the
  existing `event["path"]`-based lookup misses (spec §"Serverless (Lambda): generic path-parameter
  routing"); 2) tests — a new case registering a synthetic `{param}` route and dispatching a
  synthetic event with both `path` (concrete) and `resource` (template) set, asserting the handler
  fires with `event["pathParameters"]` intact; 3) a full regression pass confirming every existing
  static-route/default-chat-path scenario in this test file is unchanged.
- **Verify:** `cd ak-py && uv run pytest tests/test_lambda_router.py`.

## Iteration 4: Lambda thread handler + authorization

- **Goal:** A deployer can wire working thread list/detail endpoints, at path names of their choosing
  (including a `{session_id}` path parameter on detail, matching ECS's shape), into their own
  `lambda.py` via the existing `Lambda.register` decorator, scoped by the gateway
  `APIGatewayAuthorizer` principal. Depends on Iteration 3 landing first.
- **Files:** `ak-py/src/agentkernel/deployment/aws/serverless/akthreadhandler.py` (new
  `ThreadLambdaHandler`); `deployment/aws/serverless/__init__.py` and `deployment/aws/__init__.py`
  (export it alongside `Lambda`); test `tests/test_lambda_thread_routes.py` (new).
- **Steps:** 1) `ThreadLambdaHandler` reusing `ConversationThreadManager` and reading
  `event["pathParameters"]["session_id"]`/`requestContext.authorizer` (spec §"Serverless (Lambda):
  thread REST routes" and §"…: authorization"); 2) export the class; 3) tests, **including the
  risk-flagged edge case** — `requestContext.authorizer` present but `principalId` missing/falsy must
  be an explicit, named test case distinct from "no authorizer attached" (spec §"Serverless (Lambda):
  authorization" Risk callout) — this is the trickiest part of the change and needs deliberate
  coverage, not incidental coverage from the no-authorizer test.
- **Verify:** `cd ak-py && uv run pytest tests/test_lambda_thread_routes.py`.

## Iteration 5: AWS serverless Terraform — DynamoDB thread table

- **Goal:** `create_dynamodb_thread_table = true` provisions the table, injects
  `AK_THREAD__TYPE=dynamodb` + `AK_THREAD__DYNAMODB__TABLE_NAME`, and grants scoped IAM on both Lambda
  roles. No new Terraform variables for Redis/Valkey (manual, per design.md Non-goals), and no route
  auto-attach — route exposure is the deployer's own `gateway_endpoints` entries (Iteration 8).
- **Files:** `ak-deployment/ak-aws/serverless/variables.tf`, `state.tf`;
  `modules/request-handler/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf` (spec
  §"Serverless (Lambda) Terraform: DynamoDB thread table").
- **Steps:** 1) variable; 2) `dynamodb_thread` module + locals (no GSI); 3) pass-through to both
  modules; 4) env vars (both, flag-gated, TYPE+NAME together); 5) IAM policy + attachment.
- **Verify:** `terraform init && terraform validate` in the module; full plan runs in Iteration 8's
  example.

## Iteration 6: AWS containerized Terraform — DynamoDB thread table

- **Goal:** Same table/env/IAM on the ECS stack (rest-service + agent-runner task roles). Same as
  Iteration 5: no new Redis/Valkey Terraform variables, no route auto-attach — route exposure is the
  deployer's own `gateway_endpoints` entries.
- **Files:** `ak-deployment/ak-aws/containerized/variables.tf`, `state.tf`;
  `modules/rest-service/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf` (spec
  §"Containerized (ECS) Terraform: DynamoDB thread table").
- **Steps:** mirror Iteration 5 against the ECS modules.
- **Verify:** `terraform validate` in the module.

## Iteration 7: GCP Firestore Terraform

- **Goal:** Thread env wiring on GCP, reusing the Firestore database. Azure is dropped from this
  change entirely (see `design.md` Non-goals) — no Cosmos DB work in this iteration.
- **Files:** GCP `ak-gcp/serverless` + `ak-gcp/containerized` (`create_firestore_thread_collection`,
  `AK_THREAD__FIRESTORE__*` env — spec §"GCP Terraform").
- **Steps:** 1) `create_firestore_thread_collection` flag (both dirs); 2) env block extension.
- **Verify:** `terraform validate` for both GCP dirs. No `gcloud` credentials are available in this
  environment, so no live `plan`/`apply` — this is the same verification depth the AWS Terraform
  iterations get outside their one live integration example.

## Iteration 8: Example + integration test

- **Goal:** A deployable `thread-openai` serverless example proving deploy → chat → list → history →
  unauthorized, correctly demonstrating the manual `gateway_endpoints` + `Lambda.register` decorator
  pattern, including the `{session_id}` path-parameter detail route.
- **Files:** `examples/aws-serverless/thread-openai/**` (structured like `openai-auth`);
  `.github/integration-test-config.yaml` (new `weekly.tests` entry).
- **Steps:** 1) app + auth Lambda + `config.yaml` (`thread:` block, type omitted); 2) `lambda.py`
  imports `ThreadLambdaHandler` and wires `@Lambda.register("/threads", method="GET")` /
  `@Lambda.register("/threads/{session_id}", method="GET")` to it; 3) `deploy/` with
  `create_dynamodb_thread_table = true` **and** matching `gateway_endpoints` entries
  (`{ path = "threads", method = "GET" }`, `{ path = "threads/{session_id}", method = "GET" }`) behind
  the authorizer; 4) `lambda_test.py` flow — chat → list → detail via
  `GET /api/v1/threads/{session_id}` → rename → unauthorized; 5) register in the matrix (spec §"Docs
  and example").
- **Verify:** `./build.sh` + the example's `lambda_test.py`; weekly integration workflow.

## Iteration 9: Tests and lint gate

- **Goal:** Whole suite green and formatted.
- **Steps:** recap of test surface added/changed in Iterations 1–4 —
  `tests/test_thread_store_valkey.py`, `tests/test_ecs_io_handler.py`,
  `tests/test_lambda_thread_routes.py` (new); `tests/test_store_builders.py` (valkey dispatch),
  `tests/test_config.py`, `tests/test_lambda_router.py` (both changed — the latter for the new
  path-parameter fallback and its regression coverage). Run the full suite and linters.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`.

## Iteration 10: Sync docs and skills

- **Goal:** Reference surfaces match the shipped change.
- **Files/lines:**
  - `.agents/skills/ak-dev-architecture/SKILL.md:210` — add a `Valkey | ValkeyThreadStore |
    store/valkey.py | …` row to the thread Store Backends table.
  - `.agents/skills/ak-dev-architecture/SKILL.md:219` — add `valkey` to the thread `type` comment list
    and show the `thread.valkey` block. (Optional: correct the prose that places `ThreadStoreBuilder`
    in `store/__init__.py` — it lives in `store/base.py`.)
  - Deployment docs under `docs/` — document the `create_dynamodb_thread_table` /
    `create_firestore_thread_collection` flags, the mandatory `AK_THREAD__TYPE` + connection-vars
    pairing (manual for every backend — no Terraform flag automates it), and the
    `ThreadLambdaHandler` + `Lambda.register` + manual `gateway_endpoints` wiring pattern for
    serverless thread routes, using the `thread-openai` example as the canonical reference.
  - Document the new generic Lambda path-parameter routing capability (Iteration 3) on its own
    merits — it's reusable by any custom Lambda route, not just thread — likely alongside the
    existing `Lambda.register` documentation rather than folded into thread-specific docs.
  - Confirm no other `.agents/skills/*` file references the changed router surfaces (grep verified:
    only `ak-dev-architecture` does).
- **Verify:** run the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows before
  merge.
