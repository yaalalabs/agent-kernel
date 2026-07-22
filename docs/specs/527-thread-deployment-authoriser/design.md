# #527: Thread store deployment support and Authoriser support for serverless and ECS

Conversation Thread Support (`thread:` config block, #348) has no deployment story on AWS: no
Terraform-provisioned DynamoDB table, no `AK_THREAD__*` env injection, no IAM, and no way to mount
`ThreadRESTRequestHandler` with a pluggable `Authoriser` on Lambda or on ECS's queue-mode entrypoint.
This change adds a DynamoDB thread table module + flag + env vars + IAM to both AWS serverless and
ECS containerized Terraform (mirroring the existing session-memory table pattern), and adds the
missing Authoriser-mounting seam to `ECSIOHandler` (ECS) and native thread routes to the Lambda REST
router (serverless).

## Motivation

- Thread support ships with a pluggable `Authoriser` and a DynamoDB backend, but nothing outside the
  library wires either up on AWS:
  - `ThreadStoreBuilder.build()` raises unless `AKConfig.get().thread` is configured
    (`ak-py/src/agentkernel/core/thread/store/base.py:167-169`) — nothing sets `AK_THREAD__*` today.
  - `DynamoDBThreadStore` expects partition key `session_id` (S) + sort key `sk` (S), TTL attribute
    `expiry_time`, **no GSI** — `list_threads` filters via a full table `Scan`, not an indexed `Query`
    (`ak-py/src/agentkernel/core/thread/store/dynamodb.py:1-17`, `:207-241`).
  - The original design doc explicitly deferred this: *"Until an `Authoriser` is configured, any
    caller who knows a `session_id` can read or write its thread; deploy behind network-level access
    controls (VPC, API gateway) in the interim."* (`docs/specs/348-conversation-thread-support/design.md:81`).
- The session-memory table already has the exact Terraform shape thread needs to mirror:
  - `create_dynamodb_memory_table` flag → `dynamodb_memory` module → `AK_SESSION__DYNAMODB__TABLE_NAME`
    env var → IAM policy scoped to the table ARN, wired identically into both the serverless
    `request-handler`/`agent-runner` modules and the ECS `rest-service`/`agent-runner` modules
    (`ak-deployment/ak-aws/serverless/state.tf:297-313`, `:482-489`, `:535-540`;
    `ak-deployment/ak-aws/serverless/modules/request-handler/main.tf:32-59`, `:252-284`;
    `ak-deployment/ak-aws/containerized/modules/rest-service/main.tf:33-61`, `:185-189`;
    `ak-deployment/ak-aws/containerized/modules/agent-runner/main.tf:123-154`).
  - ECS containerized has **no** multimodal DynamoDB wiring at all (`grep -rl multimodal
    ak-deployment/ak-aws/containerized` — no hits) — thread is scoped to mirror the *session* table
    pattern specifically, not multimodal's.
- **Critical divergence from the session pattern**: session's `type` field is declared in the
  committed `config.yaml` (e.g. `examples/memory/dynamodb/config.yaml:2` has `session: {type:
  dynamodb}`), and Terraform only overrides the connection detail
  (`AK_SESSION__DYNAMODB__TABLE_NAME`) — it never sets `AK_SESSION__TYPE`. Thread's `type` field
  defaults to `"memory"` when unset (`ak-py/src/agentkernel/core/config.py:248`), and
  `ThreadStoreBuilder.build()` reads `thread_config.type` directly
  (`ak-py/src/agentkernel/core/thread/store/base.py:171`). Per the issue: *"the presence of any
  AK_THREAD__* variable turns the feature on at runtime"* — since `thread:` itself is
  `Optional[_ThreadStoreConfig] = None` with no `default_factory`
  (`ak-py/src/agentkernel/core/config.py:393-396`), setting only
  `AK_THREAD__DYNAMODB__TABLE_NAME` would populate `thread.dynamodb.table_name` while
  `thread.type` silently stays `"memory"` — the feature turns on but silently uses the wrong,
  non-durable backend. **Terraform must set `AK_THREAD__TYPE=dynamodb` explicitly alongside the
  table name** — this is *not* optional the way it is for session.
- Authoriser mounting has two independently-broken paths:
  - **ECS containerized, queue mode**: `ECSIOHandler.run()` hardcodes
    `RESTAPI.run(handlers=[ECSQueueRequestHandler()])` with no parameters at all
    (`ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py:29-51`). `RESTAPI.run()`
    already auto-mounts an *open* `ThreadRESTRequestHandler` whenever `AKConfig.get().thread is not
    None` and no handler in the list is already one (`ak-py/src/agentkernel/api/http.py:96-104`), but
    `ECSIOHandler` gives the caller no way to pass a configured `Authoriser` through. Confirmed via
    `examples/aws-containerized/openai-dynamodb-scalable/app_rest_service.py` (queue mode, uses
    `ECSIOHandler.run`, no params).
  - **ECS containerized, non-queue mode** (e.g. `examples/aws-containerized/openai-dynamodb/app.py`)
    calls `RESTAPI.run` directly and can already pass `handlers=[..., ThreadRESTRequestHandler(authoriser=...)]`
    itself — same as `examples/api/thread-openai/app.py`. **No gap here.**
  - **AWS serverless (Lambda)**: `RESTLambdaRouter` never registers thread routes at all — its only
    routes come from `DefaultEndpointsHandler.get_routes()` (chat endpoint variants)
    (`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py:38-74`). `dispatch()`
    does an **exact string match** on `event.get("path")` against the registered route table
    (`:354-388`) — there is no path-parameter routing, so `/api/v1/threads/{session_id}` cannot be
    registered/matched as-is today.
- API Gateway's `gateway_endpoints` mechanism already supports up to 3 path segments
  (`mainpath/subpath/childpath`, each a literal `path_part`) via
  `ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf:1-34` — `threads` (1 segment) and
  `threads/{session_id}` (2 segments) both fit; AWS API Gateway treats a `path_part` of the literal
  string `{session_id}` as a genuine path-parameter segment, so no Terraform module change is needed
  for path depth.
- The integration test matrix (`.github/integration-test-config.yaml:34-71`) has a `weekly.tests`
  entry format (`type: aws-serverless, path, deploy_dir: deploy`) that a new
  `examples/aws-serverless/thread-openai` entry must follow.

## Requirements

### AWS serverless (Lambda) Terraform — DynamoDB thread table

- Add a `create_dynamodb_thread_table` boolean variable to `ak-deployment/ak-aws/serverless/variables.tf`,
  default `false`, alongside the existing `create_dynamodb_memory_table` /
  `create_dynamodb_multimodal_memory_table` variables.
- Add a `dynamodb_thread` module invocation in `serverless/state.tf` mirroring `dynamodb_memory`
  (`state.tf:297-313`):
  - `attributes = [{name = "session_id", type = "S"}, {name = "sk", type = "S"}]`
  - `hash_key = "session_id"`, `range_key = "sk"`
  - `ttl_enabled = true`, `ttl_attribute_name = "expiry_time"`
  - `table_name = "ak-agent-threads"` (matches the Python-side default in
    `_ThreadDynamoDBConfig.table_name`, `ak-py/src/agentkernel/core/config.py:220-223`)
  - **No global secondary index** — `list_threads` does a full-table `Scan`, not an indexed `Query`
    (`ak-py/src/agentkernel/core/thread/store/dynamodb.py:207-241`); do not copy the
    `dynamodb_response_store` GSI pattern.
  - `count = var.create_dynamodb_thread_table == true ? 1 : 0`
- Thread the table ARN/name through to both `request_handler` and `agent_runner` module blocks in
  `state.tf`, following the exact `dynamodb_memory_table_arn`/`_name` local + pass-through pattern
  (`state.tf:22-25`, `:482-489`, `:535-540`).
- **Env vars — inject only when the flag is true** (both `request-handler/main.tf` and
  `agent-runner/main.tf` environment-merge blocks):
  - `AK_THREAD__TYPE = "dynamodb"`
  - `AK_THREAD__DYNAMODB__TABLE_NAME = <table_name>`
  - Both must be set together — setting only the table name leaves `thread.type` at its `"memory"`
    default (see Motivation). No other `AK_THREAD__*` var is Terraform-managed for the DynamoDB path.
- **IAM**: add a scoped policy (both Lambda roles: request-handler and agent-runner) granting
  `dynamodb:DescribeTable/GetItem/PutItem/UpdateItem/DeleteItem/Query/Scan` on the thread table ARN
  only (no `/index/*` — there is no GSI), mirroring
  `lambda_dynamodb_describe_policy`/`_attachment` (`request-handler/main.tf:32-59`) and the
  agent-runner equivalent.
- Add `create_dynamodb_thread_table`, `dynamodb_thread_table_arn`, `dynamodb_thread_table_name`
  variables to `serverless/modules/request-handler/variables.tf` and
  `serverless/modules/agent-runner/variables.tf`, matching the existing memory-table variable shape.

### AWS serverless (Lambda) — thread REST routes + Authoriser

- Register `GET /api/v1/threads` and `GET /api/v1/threads/{session_id}` on `RESTLambdaRouter`
  automatically when `AKConfig.get().thread is not None`, reusing `ConversationThreadManager`
  directly (not re-implementing its logic) — same data path as `ThreadRESTRequestHandler`
  (`ak-py/src/agentkernel/api/thread.py`), translated into Lambda handler functions.
- `RESTLambdaRouter.dispatch()` needs path-parameter support for the `{session_id}` segment — it
  currently only exact-matches `event.get("path")` (`rest_lambda.py:354-388`). Resolve using API
  Gateway's `event["pathParameters"]` (present for REST API v1 proxy integrations when the resource
  template contains `{session_id}`) rather than re-parsing the literal path.
- Provide a way for the end user to supply an `Authoriser` instance at Lambda cold start — the
  existing precedent is the `@Lambda.register(route, method)` decorator called at module import time
  before `handler = Lambda.handler` is bound (`examples/aws-serverless/openai/lambda.py:33-44`). The
  exact mechanism is an open question below.
- Extend `ak-deployment/ak-aws/serverless/state.tf`'s `local.complete_gateway_endpoints` (currently
  `local.chat_endpoint` + `var.gateway_endpoints`, `state.tf:68-72`) to also append the two thread
  paths when thread routes are enabled, gated the same way as the DynamoDB flag (exact gating
  mechanism is an open question below) — only when `local.rest_api_enabled` (thread REST reads do not
  apply to websocket-mode serverless deployments; see Non-goals).

### AWS containerized (ECS) Terraform — DynamoDB thread table

- Same shape as the serverless section: `create_dynamodb_thread_table` variable on
  `ak-deployment/ak-aws/containerized/variables.tf`, a `dynamodb_thread` module in `state.tf`
  (mirrors `dynamodb_memory`, `containerized/state.tf:112-118`), table/ARN locals, and pass-through
  into both `rest-service` and `agent-runner` modules (`containerized/rest_service.tf:24-26`,
  `containerized/queue_mode.tf:44-46`).
- Env vars on both `rest-service/main.tf` and `agent-runner/main.tf` environment-merge blocks
  (`rest-service/main.tf:2-20`, `agent-runner/main.tf:4-17`): `AK_THREAD__TYPE=dynamodb` +
  `AK_THREAD__DYNAMODB__TABLE_NAME=<name>`, injected only when the flag is true — same rule as
  serverless.
- IAM: task-role policy (both rest-service task role and agent-runner task role) scoped to the thread
  table ARN only, mirroring `dynamodb_policy`/`tasks_iam_role_policies`
  (`rest-service/main.tf:33-61`, `:185-189`) and
  `agent_runner_dynamodb_memory_policy`/`_attachment` (`agent-runner/main.tf:123-154`).

### AWS containerized (ECS) — Authoriser mounting

- `ECSIOHandler.run()` gains an optional `authoriser: Optional[Authoriser] = None` parameter
  (`ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py:29-51`), forwarded into
  `RESTAPI.run(handlers=[ECSQueueRequestHandler(), ThreadRESTRequestHandler(authoriser=authoriser)])`
  — passing `ThreadRESTRequestHandler` explicitly (rather than relying on `RESTAPI.run`'s auto-mount)
  so the caller's `Authoriser` is honored, and `RESTAPI.run`'s own `isinstance` check skips
  auto-mounting a second, open one (`api/http.py:96-104`).
- Only mount it when `AKConfig.get().thread is not None`, matching `RESTAPI.run`'s existing gate —
  don't unconditionally add thread routes when the feature is off.
- Non-queue-mode ECS (direct `RESTAPI.run(handlers=[...])`, e.g.
  `examples/aws-containerized/openai-dynamodb/app.py`) needs **no change** — the caller already
  controls the handlers list and can pass a configured `ThreadRESTRequestHandler` itself, same as
  `examples/api/thread-openai/app.py`.

### Docs and example

- New deployable example `examples/aws-serverless/thread-openai`, registered under `weekly.tests` in
  `.github/integration-test-config.yaml` (format per lines 34-71), exercising: deploy →
  chat → thread read → rename → destroy, per the issue's acceptance criteria.
- Document the `AK_THREAD__TYPE` + `AK_THREAD__DYNAMODB__TABLE_NAME` pairing requirement prominently
  — this is the one place thread's env-var story diverges from every other AK_* store (session,
  response store, multimodal), and it is easy to silently misconfigure (feature "on", wrong backend).
- Azure/GCP thread provisioning is an explicit follow-up ticket (per issue) — not in scope here.

## Non-goals

- Azure Functions / Cosmos DB and GCP Cloud Run / Firestore thread provisioning (follow-up ticket per
  the issue).
- Thread REST read routes for serverless deployments running in websocket execution modes (`async`,
  `stream`) — those modes have no REST API Gateway at all
  (`local.rest_api_enabled = var.enable_api_gateway && !local.is_websocket_mode`,
  `serverless/state.tf:33-34`); adding one would be a separate, larger change.
- A rename/write REST route — renaming stays exclusively via the chat request's `thread_name` field,
  unchanged by this issue.
- Changing session/multimodal/response-store deployment wiring — those are done; thread mirrors their
  pattern but this issue doesn't touch them.
- Redis/Valkey thread store *provisioning* — per the issue, thread on Redis/Valkey reuses whatever
  cluster `create_redis_cluster`/`create_valkey_cluster` already provisions for session; no new
  cluster resource is created for thread.

## Open questions

- **How does the end user supply an `Authoriser` for the Lambda serverless path?** ECS has a natural
  seam (`ECSIOHandler.run(authoriser=...)`, a Python call site at container start). Lambda's
  `handler = Lambda.handler` is a bare function reference with no per-invocation construction point —
  the only precedent is the cold-start `@Lambda.register(...)` decorator. Candidates:
  - A new `Lambda.configure_thread_authoriser(authoriser: Authoriser)` classmethod called once at
    cold start (alongside `OpenAIModule([...])`), mirroring `@Lambda.register`'s cold-start timing.
  - Something config-driven (not possible for an arbitrary user subclass — `Authoriser` is inherently
    a code object, not a config value).
- **How is the thread routes' Terraform gate expressed for serverless?** `gateway_endpoints` is a
  static list baked at plan time; it can't react to whether `AK_THREAD__*` env vars are present at
  runtime. Does enabling thread REST routes ride on `create_dynamodb_thread_table`, or does it need
  its own boolean (since a Redis/Valkey-backed thread store, or `type: memory`, has no DynamoDB flag
  to key off)?
- **What is the exact Redis/Valkey thread-store opt-in shape?** The issue says wiring "reuses existing
  clusters," but doesn't specify how the deployer selects "thread on Redis" — a new
  `thread_store_backend` enum variable (`none | dynamodb | redis | valkey`), or overloading the
  existing `create_redis_cluster`/`create_valkey_cluster` booleans to also imply thread when combined
  with some other flag? Needs a decision before the Terraform variable surface is finalized.
- **Does `RESTLambdaRouter` path-parameter support (for `{session_id}`) generalize beyond thread**, or
  is a thread-specific special case (e.g. hardcoded prefix match on `/api/v1/threads/`) acceptable to
  avoid a broader router rewrite? Affects how much of `dispatch()` this change touches.
