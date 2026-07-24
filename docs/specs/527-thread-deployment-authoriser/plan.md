# #527: Thread store deployment support and Authoriser support for serverless and ECS — Implementation Plan

Ordering of the [`spec.md`](./spec.md) build. Each iteration leaves the branch working and testable.
New unit tests land **with** the code they cover (repo convention: features ship with tests, and each
iteration stays verifiable); the dedicated Tests iteration is the full-suite + lint gate and the
changed-existing-test recap. Terraform iterations are verified with `terraform validate`/`plan`, not
pytest — they are exercised end to end by the weekly integration example.

## Iteration 1: Core Valkey thread store

- **Goal:** `thread.type: valkey` builds a working `ValkeyThreadStore`; the `valkey` extra stays
  optional.
- **Files:** `ak-py/src/agentkernel/core/config.py` (add `_ThreadValkeyConfig`, `valkey` field, extend
  `type` pattern); `ak-py/src/agentkernel/core/thread/store/valkey.py` (new); refactor the shared
  Redis/Valkey body per spec §"Core: Valkey thread store" rule 1; `ak-py/src/agentkernel/core/thread/store/base.py` (`Types.VALKEY` + guarded `build()` branch);
  tests `tests/test_thread_store_valkey.py` (new), plus `tests/test_thread_store.py` and
  `tests/test_config.py` (valkey assertions).
- **Steps:** 1) config changes; 2) factor `_RedisLikeThreadStore` base and derive both stores;
  3) builder enum + branch with `ImportError` hint; 4) tests.
- **Verify:** `cd ak-py && uv run pytest tests/test_thread_store_valkey.py tests/test_thread_store.py tests/test_config.py`.

## Iteration 2: ECS Authoriser mounting

- **Goal:** `ECSIOHandler.run(authoriser=...)` mounts a configured `ThreadRESTRequestHandler` in
  queue mode; `authoriser=None` preserves today's open behaviour.
- **Files:** `ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py`; test
  `tests/test_ecs_io_handler.py` (new).
- **Steps:** 1) add the optional param and build the handlers list gated on `AKConfig.get().thread`
  (spec §"Containerized (ECS): Authoriser mounting"); 2) test with `RESTAPI.run`/`ThreadRunner.run`
  patched.
- **Verify:** `cd ak-py && uv run pytest tests/test_ecs_io_handler.py`.

## Iteration 3: Lambda thread routes + authorization

- **Goal:** Serverless serves `GET /api/v1/threads` and `/api/v1/threads/{session_id}` when thread is
  configured, scoped by the gateway `APIGatewayAuthorizer` principal.
- **Files:** `ak-py/src/agentkernel/deployment/aws/serverless/core/router/thread_endpoints.py` (new
  `ThreadEndpointsHandler`); `.../core/router/rest_lambda.py` (cold-start registration + `dispatch()`
  thread pre-check); export as needed in `.../core/router/__init__.py`; tests
  `tests/test_lambda_thread_routes.py` (new) and `tests/test_lambda_router.py` (thread-disabled
  guard).
- **Steps:** 1) `ThreadEndpointsHandler` reusing `ConversationThreadManager` and reading
  `pathParameters`/`requestContext.authorizer` (spec §"Serverless (Lambda): thread REST routes" and
  §"…: authorization"); 2) register in `RESTLambdaRouter.__init__` only when thread configured;
  3) `dispatch()` pre-check on `event["resource"]`; 4) tests.
- **Verify:** `cd ak-py && uv run pytest tests/test_lambda_thread_routes.py tests/test_lambda_router.py`.

## Iteration 4: AWS serverless Terraform — DynamoDB thread table

- **Goal:** `create_dynamodb_thread_table = true` provisions the table, injects
  `AK_THREAD__TYPE=dynamodb` + `AK_THREAD__DYNAMODB__TABLE_NAME`, and grants scoped IAM on both Lambda
  roles.
- **Files:** `ak-deployment/ak-aws/serverless/variables.tf`, `state.tf`;
  `modules/request-handler/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf` (spec
  §"Serverless (Lambda) Terraform: DynamoDB thread table").
- **Steps:** 1) variable; 2) `dynamodb_thread` module + locals (no GSI); 3) pass-through to both
  modules; 4) env vars (both, flag-gated, TYPE+NAME together); 5) IAM policy + attachment.
- **Verify:** `terraform init && terraform validate` in the module; full plan runs in Iteration 7's
  example.

## Iteration 5: AWS containerized Terraform — DynamoDB thread table

- **Goal:** Same table/env/IAM on the ECS stack (rest-service + agent-runner task roles).
- **Files:** `ak-deployment/ak-aws/containerized/variables.tf`, `state.tf`;
  `modules/rest-service/{main,variables}.tf`; `modules/agent-runner/{main,variables}.tf` (spec
  §"Containerized (ECS) Terraform: DynamoDB thread table").
- **Steps:** mirror Iteration 4 against the ECS modules.
- **Verify:** `terraform validate` in the module.

## Iteration 6: GCP Firestore + Azure Cosmos Terraform

- **Goal:** Thread env wiring on GCP (reusing the Firestore database) and a thread table in the
  existing Cosmos account on Azure.
- **Files:** GCP `ak-gcp/serverless` + `ak-gcp/containerized` (`create_firestore_thread_collection`,
  `AK_THREAD__FIRESTORE__*` env — spec §"GCP Terraform"); Azure `ak-azure/serverless` +
  `ak-azure/containerized` (`create_cosmosdb_thread_table`, second `azurerm_cosmosdb_table` in the
  existing `module.cosmos` account, `AK_THREAD__COSMOSDB__*` env — spec §"Azure Terraform"; resolve
  the module-vs-sibling-resource choice noted there before starting).
- **Steps:** 1) GCP flag + env block; 2) Azure flag + thread table resource/output + env block.
- **Verify:** `terraform validate` for each of the four dirs.

## Iteration 7: Example + integration test

- **Goal:** A deployable `thread-openai` serverless example proving deploy → chat → list → history →
  unauthorized.
- **Files:** `examples/aws-serverless/thread-openai/**` (structured like `openai-auth`);
  `.github/integration-test-config.yaml` (new `weekly.tests` entry).
- **Steps:** 1) app + auth Lambda + `config.yaml` (`thread:` block, type omitted); 2) `deploy/` with
  `create_dynamodb_thread_table = true` and the two thread paths in `gateway_endpoints` behind the
  authorizer; 3) `lambda_test.py` flow; 4) register in the matrix (spec §"Docs and example").
- **Verify:** `./build.sh` + the example's `lambda_test.py`; weekly integration workflow.

## Iteration 8: Tests and lint gate

- **Goal:** Whole suite green and formatted.
- **Steps:** recap of test surface added/changed in Iterations 1–3 —
  `tests/test_thread_store_valkey.py`, `tests/test_ecs_io_handler.py`,
  `tests/test_lambda_thread_routes.py` (new); `tests/test_thread_store.py`, `tests/test_config.py`,
  `tests/test_lambda_router.py` (changed patch targets/guards). Run the full suite and linters.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`.

## Iteration 9: Sync docs and skills

- **Goal:** Reference surfaces match the shipped change.
- **Files/lines:**
  - `.agents/skills/ak-dev-architecture/SKILL.md:210` — add a `Valkey | ValkeyThreadStore |
    store/valkey.py | …` row to the thread Store Backends table.
  - `.agents/skills/ak-dev-architecture/SKILL.md:219` — add `valkey` to the thread `type` comment list
    and show the `thread.valkey` block. (Optional: correct the prose that places `ThreadStoreBuilder`
    in `store/__init__.py` — it lives in `store/base.py`.)
  - Deployment docs under `docs/` — document the `create_dynamodb_thread_table` /
    `create_firestore_thread_collection` / `create_cosmosdb_thread_table` flags and the mandatory
    `AK_THREAD__TYPE` + connection-vars pairing.
  - Confirm no other `.agents/skills/*` file references the changed router/ECS surfaces (grep verified:
    only `ak-dev-architecture` does).
- **Verify:** run the `ak-dev-sync-docs-from-branch` / `ak-dev-sync-skills-from-branch` flows before
  merge.
