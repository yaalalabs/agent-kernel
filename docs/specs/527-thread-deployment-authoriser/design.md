# #527: Thread store deployment support and Authoriser support for serverless and ECS

Conversation Thread Support (`thread:` config block, #348) shipped with pluggable stores and an
`Authoriser`, but no deployment story: no cloud provisioning (AWS, GCP, or Azure) for the thread
store, and no way to protect thread routes on serverless or containerized deployments. This change
adds thread-store provisioning + env-var wiring + IAM to the AWS, GCP, and Azure Terraform (mirroring
each cloud's existing session-store pattern), native thread routes to the Lambda REST router
protected by the existing `APIGatewayAuthorizer`, and an `Authoriser`-mounting seam to ECS's
queue-mode entrypoint.

## Motivation

- **No cloud provisioning for the thread store.** Each cloud already provisions the *session* store
  behind a flag — `create_dynamodb_memory_table` (AWS,
  `ak-deployment/ak-aws/serverless/state.tf:297-313`), `create_firestore_database` (GCP,
  `ak-deployment/ak-gcp/serverless/variables.tf:169`), `create_cosmosdb_cluster` (Azure,
  `ak-deployment/ak-azure/serverless/variables.tf:101`) — but nothing provisions or wires the thread
  store's DynamoDB table / Firestore collection / Cosmos DB table, so `thread:` cannot be enabled on
  a deployed stack without hand-built infrastructure.
- **No Authoriser on serverless.** The Lambda REST router registers no thread routes at all and only
  exact-matches paths (`ak-py/src/agentkernel/deployment/aws/serverless/core/router/rest_lambda.py:354-388`),
  so `GET /api/v1/threads/{session_id}` cannot exist today.
- **No Authoriser on containerized queue mode.** `ECSIOHandler.run()` hardcodes
  `RESTAPI.run(handlers=[ECSQueueRequestHandler()])`
  (`ak-py/src/agentkernel/deployment/aws/containerized/ecs_io_handler.py:29-51`), so `RESTAPI.run`
  auto-mounts an *open* `ThreadRESTRequestHandler` (`ak-py/src/agentkernel/api/http.py:96-104`) with
  no way to pass a configured `Authoriser` — exactly the interim state the #348 design said to close
  (`docs/specs/348-conversation-thread-support/design.md:81`).

## Scope

- This change covers thread-store provisioning + env wiring across **all three clouds — AWS, GCP,
  and Azure** — plus the Authoriser work on AWS serverless and ECS. Issue #527 originally scoped
  GCP/Azure provisioning as a follow-up ticket; that scope was **intentionally expanded during design
  review** to land all three together (they share one env-var contract and mirror the existing
  session-store wiring). Issue #527 is being updated to match this expanded scope.
- Authoriser/route-authorization plumbing remains AWS-only (see Non-goals); the GCP/Azure work here
  is store provisioning + env wiring only.

## Architecture overview

```mermaid
flowchart TB
    Client([Client])

    subgraph sls["AWS serverless (Lambda)"]
        APIGW["API Gateway<br/>gateway_endpoints:<br/>threads<br/>threads/{session_id}"]
        AuthL["APIGatewayAuthorizer Lambda<br/>(user-supplied AuthValidator)"]
        AppL["RESTLambdaRouter<br/>thread routes (new)<br/>user id from authorizer context"]
        APIGW -.->|"authorize"| AuthL
        APIGW --> AppL
    end

    subgraph ecs["AWS containerized (ECS, queue mode)"]
        IOH["ECSIOHandler.run(authoriser=...)<br/>(new parameter)"]
        TRH["ThreadRESTRequestHandler<br/>(authoriser)"]
        IOH --> TRH
    end

    subgraph core["agentkernel core"]
        CTM["ConversationThreadManager"]
        TSB["ThreadStoreBuilder<br/>selects backend via AK_THREAD__TYPE"]
        CTM --> TSB
    end

    subgraph stores["Thread stores (Terraform-provisioned)"]
        DDB[("DynamoDB table<br/>create_dynamodb_thread_table<br/>(AWS)")]
        FS[("Firestore collection<br/>create_firestore_thread_collection<br/>(GCP, env wiring only)")]
        COS[("Cosmos DB table<br/>create_cosmosdb_thread_table<br/>(Azure)")]
        RV[("Redis / Valkey<br/>reuses session cluster<br/>(valkey: new in core)")]
    end

    Client --> APIGW
    Client --> IOH
    AppL --> CTM
    TRH --> CTM
    TSB --> DDB
    TSB --> FS
    TSB --> COS
    TSB --> RV
```

## Requirements

### Core — Valkey thread store

- Add `valkey` to the built-in backend set: the `_ThreadStoreConfig.type` field description
  (a description-only field post-#541, no regex pattern —
  `ak-py/src/agentkernel/core/config.py:254-257`) and `_BUILTIN_THREAD_STORES`
  (`core/thread/store/base.py:13`), plus a `_ThreadValkeyConfig` sub-config (URL + ttl + prefix,
  mirroring `_ThreadRedisConfig`, `config.py:220-223`).
- Add a `ValkeyThreadStore` and its `require_extra`-guarded `ThreadStoreBuilder` branch with the
  `agentkernel[valkey]` extra hint, mirroring how `SessionStoreBuilder` builds `ValkeySessionStore`
  (`ak-py/src/agentkernel/core/builder.py:108-112`). Valkey is Redis-protocol-compatible; the store
  should reuse the Redis thread store's logic with a valkey client, as the session stores do.
- Backend selection for thread is **always** via `thread.type` / `AK_THREAD__TYPE` — Redis/Valkey
  thread storage is chosen by setting `AK_THREAD__TYPE=redis|valkey` (plus the URL), not by any new
  Terraform enum.

### Env-var contract (all clouds)

- `AKConfig.thread` is `Optional[...] = None` with no `default_factory`
  (`ak-py/src/agentkernel/core/config.py:580`), so the presence of any `AK_THREAD__*` env var
  turns the feature on — but `thread.type` then defaults to `"memory"` (`config.py:254-257`) and
  `ThreadStoreBuilder.build()` reads it directly (`ak-py/src/agentkernel/core/thread/store/base.py:149-153`).
- Therefore every Terraform wiring below must inject `AK_THREAD__TYPE=<backend>` **together with** the
  backend's connection vars. Unlike session — where the committed `config.yaml` declares the type
  (e.g. `session: {type: dynamodb}` in `examples/memory/dynamodb/config.yaml`) and Terraform injects
  only the connection detail — thread is deployment-toggled with no `thread:` block in the committed
  config, so there is no declared type to fall back on: setting only the table name would silently
  run threads on the non-durable in-memory backend.

### AWS serverless (Lambda) Terraform — DynamoDB thread table

- New `create_dynamodb_thread_table` boolean (default `false`) in
  `ak-deployment/ak-aws/serverless/variables.tf`, alongside `create_dynamodb_memory_table`.
- New `dynamodb_thread` module invocation in `serverless/state.tf` mirroring `dynamodb_memory`
  (`state.tf:297-313`):
  - `attributes = [{session_id, S}, {sk, S}]`, `hash_key = "session_id"`, `range_key = "sk"`
  - `ttl_enabled = true`, `ttl_attribute_name = "expiry_time"`
  - `table_name = "ak-agent-threads"` (Python-side default, `config.py:220-223`)
  - **No GSI** — `list_threads` is a full-table `Scan`
    (`ak-py/src/agentkernel/core/thread/store/dynamodb.py:207-241`); do not copy the
    response-store GSI pattern.
- Thread the table ARN/name through to both `request_handler` and `agent_runner` module blocks
  (pattern: `state.tf:22-25`, `:482-489`, `:535-540`) with matching variables in each module's
  `variables.tf`.
- Env vars, injected only when the flag is true, in both modules' environment-merge blocks
  (`request-handler/main.tf:252-284` pattern): `AK_THREAD__TYPE=dynamodb` +
  `AK_THREAD__DYNAMODB__TABLE_NAME=<name>`.
- IAM: scoped policy on both Lambda roles granting
  `DescribeTable/GetItem/PutItem/UpdateItem/DeleteItem/Query/Scan` on the table ARN only (no
  `/index/*`), mirroring `lambda_dynamodb_describe_policy` (`request-handler/main.tf:32-59`).

### AWS serverless (Lambda) — thread REST routes + APIGatewayAuthorizer

- Register `GET /api/v1/threads` and `GET /api/v1/threads/{session_id}` on `RESTLambdaRouter`
  automatically when `AKConfig.get().thread is not None`, reusing `ConversationThreadManager` —
  the same data path as `ThreadRESTRequestHandler` (`ak-py/src/agentkernel/api/thread.py`),
  translated to Lambda handlers.
- Path-parameter handling for `{session_id}` is **thread-specific** — resolve via API Gateway's
  `event["pathParameters"]` for the thread detail route only; no general-purpose router rewrite of
  `dispatch()`'s exact-match table (`rest_lambda.py:354-388`).
- Authorization uses the existing `APIGatewayAuthorizer` gateway-level Lambda REQUEST authorizer, as
  in `examples/aws-serverless/openai-auth/lambda_auth.py` — a user-supplied `AuthValidator` returns
  `ValidationResult(subject=..., claims=...)`, which the authorizer forwards as `principalId` +
  string context on the policy (`ak-py/src/agentkernel/deployment/aws/serverless/akauthorizer.py:43-48`,
  `:75-92`). No in-Lambda `Authoriser` instance and no new cold-start configuration hook.
- The thread route handlers resolve the caller's user id from
  `event["requestContext"]["authorizer"]` (principal/claims injected by the gateway authorizer) and
  apply the same scoping as `ThreadRESTRequestHandler._resolve_user` — list scoped to that user,
  403 on ownership mismatch for the detail route.
- Exposure is via the existing `gateway_endpoints` variable. `gateway_endpoints` paths are
  **relative** to `/{api_base_path}/{api_version}` (the module prepends `api`/`v1`), so the deployer
  adds `threads` and `threads/{session_id}` — **not** `api/v1/threads` (which would deploy
  `/api/v1/api/v1/threads`). `threads/{session_id}` is 2 segments, within the module's 3-segment
  limit (`ak-deployment/ak-aws/serverless/modules/api-gateway/main.tf:1-16`), and API Gateway treats
  the literal `{session_id}` `path_part` as a path parameter. No auto-append logic or new gating flag
  in `state.tf`; the deployed example and docs show the exact endpoint entries.
- Routes registered via `gateway_endpoints` are protected by the deployment's configured `authorizer`
  variable (`serverless/variables.tf`), the same as any other endpoint.

### AWS containerized (ECS) Terraform — DynamoDB thread table

- Same shape as serverless: `create_dynamodb_thread_table` variable on
  `ak-deployment/ak-aws/containerized/variables.tf`, a `dynamodb_thread` module in `state.tf`
  (mirrors `dynamodb_memory`, `containerized/state.tf:112-118`), and pass-through into both
  `rest-service` and `agent-runner` modules.
- Env vars on both modules' environment-merge blocks (`rest-service/main.tf:2-20`,
  `agent-runner/main.tf:4-17`): `AK_THREAD__TYPE=dynamodb` + `AK_THREAD__DYNAMODB__TABLE_NAME`,
  injected only when the flag is true.
- IAM: task-role policy on both task roles scoped to the thread table ARN only, mirroring
  `dynamodb_policy`/`tasks_iam_role_policies` (`rest-service/main.tf:33-61`, `:185-189`) and
  `agent_runner_dynamodb_memory_policy` (`agent-runner/main.tf:123-154`).

### AWS containerized (ECS) — Authoriser mounting

- `ECSIOHandler.run()` gains an optional `authoriser: Optional[Authoriser] = None` parameter
  (`ecs_io_handler.py:29-51`), and when `AKConfig.get().thread is not None` passes
  `ThreadRESTRequestHandler(authoriser=authoriser)` explicitly in the handlers list so
  `RESTAPI.run`'s `isinstance` check skips auto-mounting a second, open one (`api/http.py:96-104`).
- Non-queue-mode ECS (direct `RESTAPI.run(handlers=[...])`, e.g.
  `examples/aws-containerized/openai-dynamodb/app.py`) needs no change — the caller already controls
  the handlers list, same as `examples/api/thread-openai/app.py`.

### AWS containerized (ECS) — route exposure

- Thread routes are exposed the same way as serverless: through the containerized HTTP API's
  `gateway_endpoints` variable (`ak-deployment/ak-aws/containerized/variables.tf:51-70`). By default
  only the chat endpoints exist (`containerized/state.tf`), so the deployer adds the thread entries.
- The containerized entry shape is `{path, method, overwrite_path}` (`overwrite_path` is **required**,
  unlike the serverless `{path, method}` shape). Paths are relative to `/{api_base_path}/{api_version}`;
  the HTTP API imposes no segment-depth limit, so `{session_id}` works as an HTTP API path variable.
  The detail route's `overwrite_path` must reference that variable so the id is forwarded to the ALB
  backend:
  - `{ path = "threads",              method = "GET", overwrite_path = "/api/v1/threads" }`
  - `{ path = "threads/{session_id}", method = "GET", overwrite_path = "/api/v1/threads/${request.path.session_id}" }`
- These entries are protected by the deployment's configured `authorizer`, and the mounted
  `ThreadRESTRequestHandler` applies the same principal scoping as serverless.

### GCP Terraform — Firestore thread wiring

- Thread reuses the Firestore database provisioned by `create_firestore_database`; Firestore
  collections are implicit, so no new database resource is needed — the thread store writes to its
  own collection (`ak-agent-threads` default, `config.py:227-231`; one document per session with a
  `messages` subcollection, `ak-py/src/agentkernel/core/thread/store/firestore.py:5-10`).
- New opt-in boolean (e.g. `create_firestore_thread_collection`, env-wiring only) on both
  `ak-gcp/serverless` and `ak-gcp/containerized`, requiring `create_firestore_database = true`.
- When enabled, extend the existing firestore env block (`serverless/cloud_function.tf:159-164`,
  `containerized/cloud_run.tf:160-164`) with `AK_THREAD__TYPE=firestore`,
  `AK_THREAD__FIRESTORE__COLLECTION_NAME`, `AK_THREAD__FIRESTORE__PROJECT_ID`,
  `AK_THREAD__FIRESTORE__DATABASE_ID` — same values/shape as the `AK_SESSION__FIRESTORE__*` block
  (GCP already sets `AK_SESSION__TYPE=firestore` explicitly, so thread matches the established GCP
  pattern).
- IAM: covered by the existing Firestore datastore access already granted to the service account for
  session storage (same database); verify and extend only if the existing binding is
  collection-scoped.

### Azure Terraform — Cosmos DB thread table

- Thread reuses the Cosmos DB cluster provisioned by `create_cosmosdb_cluster` but needs its own
  table (`akagentthreads` default, `config.py:236-238`) — new opt-in boolean (e.g.
  `create_cosmosdb_thread_table`) on both `ak-azure/serverless` and `ak-azure/containerized`,
  requiring `create_cosmosdb_cluster = true`, that provisions the additional table in the existing
  `module.cosmos` account.
- When enabled, extend the existing cosmosdb env block (`serverless/linux_function.tf:127-134`,
  `containerized/container_app.tf:106-108`) with `AK_THREAD__TYPE=cosmosdb`,
  `AK_THREAD__COSMOSDB__TABLE_NAME`, `AK_THREAD__COSMOSDB__CONNECTION_STRING` (connection string
  handled the same way as session's — Key Vault secret reference on containerized).

### Docs and example

- New deployable example `examples/aws-serverless/thread-openai`, registered under `weekly.tests` in
  `.github/integration-test-config.yaml` (format per lines 34-71): deploys with
  `create_dynamodb_thread_table = true`, an `APIGatewayAuthorizer` auth Lambda (per
  `examples/aws-serverless/openai-auth`), and `gateway_endpoints` including the two thread paths;
  exercises deploy → chat → thread list/read → destroy.
- Document the `AK_THREAD__TYPE` + backend-vars pairing requirement prominently — thread is the one
  `AK_*` store where Terraform must set the type explicitly, and it is easy to misconfigure (feature
  "on", silently wrong backend).

## Non-goals

- Thread REST routes for serverless deployments in websocket execution modes (`async`, `stream`) —
  no REST API Gateway exists in those modes (`local.rest_api_enabled`, `serverless/state.tf:33-34`).
- A rename/write REST route — renaming stays via the chat request's `thread_name` field.
- Redis/Valkey cluster *provisioning* for thread — thread on Redis/Valkey reuses whatever cluster
  `create_redis_cluster`/`create_valkey_cluster` already provisions; selection is purely
  `AK_THREAD__TYPE=redis|valkey` + the cluster URL. No new cluster resources.
- Changing session/multimodal/response-store deployment wiring — thread mirrors their patterns but
  does not touch them.
- GCP/Azure thread REST-route authorization plumbing beyond what their gateways already provide —
  this issue's Authoriser work targets AWS serverless (APIGatewayAuthorizer) and ECS
  (`ECSIOHandler`); GCP/Azure scope here is store provisioning + env wiring only.

## Open questions

- None — the Lambda authorization mechanism (gateway-level `APIGatewayAuthorizer`), thread-route
  exposure (`gateway_endpoints`), Redis/Valkey selection (`thread.type`, with valkey added to core),
  and path-parameter scope (thread-specific) were all settled during review.
