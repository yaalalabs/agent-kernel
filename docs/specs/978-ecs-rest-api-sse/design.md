# #978: ECS — replace the API Gateway HTTP API with a REST API so SSE can stream

ECS REST traffic enters through an API Gateway **HTTP API**, which buffers a whole response before
sending it, so `execution.mode: rest_sync` + `message_type: delta` (SSE) cannot stream on ECS. This
change replaces that HTTP API with a **Regional REST API** built from an OpenAPI document, with
`responseTransferMode: STREAM` and a direct private integration to the existing ALB. All changes are
Terraform under `ak-deployment/ak-aws/containerized/`; `gateway_endpoints` and the module outputs keep
their current shape.

## Motivation

- One HTTP API fronts **every** non-WebSocket ECS deployment (`api_gateway.tf:1`), proxying each
  endpoint over a VPC link to the ALB **listener** ARN (`:34`), one route per endpoint (`:43`), on an
  `auto_deploy` stage named `agents` (`:58`).
- The ALB and the ECS task forward chunks as they arrive. Only the HTTP API holds them.
- AWS now allows what it did not: `responseTransferMode: STREAM` on a REST API's private integration,
  and REST-to-ALB directly over VPC link V2 (announced 2025-11-21), removing the NLB a REST API used to
  need — likely why this module chose an HTTP API originally. Both are external claims, unverified in
  this repo; see `research/aws-claims-to-verify.md`.
- Reusable as is: `aws_apigatewayv2_vpc_link.ecs_alb` (`api_gateway.tf:21`), and `alb_arn` /
  `alb_dns_name` already on `modules/rest-service/outputs.tf:21`, `:26`. No new module output needed.

### Of five gates between a user and SSE, two must survive

| # | Gate | Location | Disposition |
| --- | --- | --- | --- |
| 1 | `ECSIOHandler.run` raised for `rest_sync` + `delta` | `deployment/aws/containerized/ecs_io_handler.py` | **Already gone** — #962 deleted the file |
| 2 | `terraform plan` validation `!(queue_mode && rest_sync && delta)` | `variables.tf:284-287` | **Removed here** |
| 3 | `message_type` description asserting SSE is rejected | `variables.tf:278` | **Removed here** |
| 4 | `IOHandler` startup: SSE needs a chunk-streaming store | `pipeline/io_handler.py:238` | **Kept** — about the store, not the gateway |
| 5 | `RequestHandler._reject_unroutable` 400s SSE on such a store | `pipeline/request_handler.py:561-569` | **Kept** — same reason |

Gate 1's reason was not the gateway — "its REST container has no SSE route" — and it is already
gone: **#962 has landed** (`184345298`), moving ECS onto the shared `IOHandler`. No ECS-specific chat
request handler remains, so `rest_sync` now runs the shared `RequestHandler`, which has an SSE route.
"No Python changes needed" is therefore settled fact rather than a dependency on unmerged work.

### Two things the module cannot currently do

- **Supply a response store that streams.** `modules/rest-service/main.tf:39` injects a DynamoDB table;
  Redis and Valkey go in as the **session** store only (`:5`, `:8`), and neither URL is a module output.
  Blocker B5 (`docs/specs/remove-direct-mode/research/blockers.md:13`) names Redis or Valkey as the
  requirement. So removing gate 2 alone just trades a plan-time error for a runtime one at gate 5.
- **Hold a connection open through a silent gap.** `aws_lb.app` (`modules/rest-service/main.tf:219`)
  sets no `idle_timeout`, so it takes the AWS default of 60 s and cuts a long tool call whatever the
  gateway allows.

## Requirements

### Resource topology

| Today | Becomes | Note |
| --- | --- | --- |
| `aws_apigatewayv2_api` | `aws_api_gateway_rest_api` | `types = ["REGIONAL"]`, built from an OpenAPI `body`. Edge-optimized keeps a 30 s streaming idle cap and would silently undo the change |
| `aws_apigatewayv2_integration` (per endpoint) | `x-amazon-apigateway-integration` | inline in the body |
| `aws_apigatewayv2_route` (per endpoint) | an OpenAPI path | |
| `aws_apigatewayv2_stage` (`auto_deploy`) | `aws_api_gateway_deployment` + `aws_api_gateway_stage` | stage keeps the name `agents`; redeployment triggers on a hash of the body |
| `default_route_settings` throttling | `aws_api_gateway_method_settings` | |
| `aws_apigatewayv2_vpc_link.ecs_alb` | **kept as is** | V2 links serve REST APIs; replacing it would recreate the link for nothing |

- **Four of these are not new decisions** — they match the REST API the serverless module already
  runs (`serverless/modules/api-gateway/main.tf`): `REGIONAL` endpoint type (`:40`), the stage named
  `agents` (`:160`), a separate `aws_api_gateway_deployment` + `aws_api_gateway_stage` (`:128`,
  `:157`), and redeployment driven by a hash in `triggers` (`:130`). This change follows that module
  rather than inventing conventions. It diverges on exactly two points, each with its own reason: the
  OpenAPI body (decision 6) and gateway-side CORS (Route translation).
- **Do not confuse the VPC links.** The module has both: `aws_api_gateway_vpc_link.ws`
  (`api_gateway_ws.tf:32`) is V1, targets the **NLB**, and is WebSocket-only. V1 links accept only an
  NLB — exactly the limitation this change avoids. "A REST API needs a V1 VPC link" is the old rule.
- Per-route integration fields:
  - `type = "http_proxy"`, `connectionType = "VPC_LINK"`, `connectionId` = the existing VPC link id.
  - `integrationTarget` = `module.rest_service.alb_arn` — the **load balancer** ARN, not the listener ARN
    the v2 integration used.
  - `responseTransferMode = "STREAM"`.
  - `uri = "http://<alb_dns_name><overwrite_path>"`.
  - `timeoutInMillis` = `var.gateway_integration_timeout * 1000`. **Not optional** — see Stream
    duration below.
- No `aws_apigatewayv2_api`, `_integration`, `_route` or `_stage` remains outside WebSocket mode.
  `aws_apigatewayv2_vpc_link.ecs_alb` is the deliberate exception and stays; `api_gateway_ws.tf` is
  untouched entirely.

### Route translation (`state.tf`)

- `local.gateway_endpoints_map` (`state.tf:66`) is rendered into OpenAPI paths. The inputs feeding it
  are unchanged; its `path` field is normalised to the full external path in every branch, because the
  user and MCP branches store a relative one today (`state.tf:55`, `:61`) while a `paths` object must
  be keyed by one shape. Nothing in the module reads that field, so the change is invisible — and it
  removes a divergence from GCP, which already normalises
  (`ak-gcp/containerized/state.tf:116`, `:126`).
- Three cases, each testable against an existing example:
  - `POST /api/v1/chat` → a path object with a lowercased method key.
  - `ANY` → `x-amazon-apigateway-any-method`; OpenAPI has no `any` key.
  - `$request.path.<name>` in `overwrite_path`, bare or braced → `{<name>}` in the integration `uri`,
    **plus** a method-level `parameters` entry and an integration `requestParameters` mapping
    `integration.request.path.<name>` to `method.request.path.<name>`. The HTTP API's `overwrite:path`
    inferred all this from the string; a REST API does not. Not copyable from the serverless module:
    its `{task_id}` support (#935) rides `AWS_PROXY` to Lambda, which forwards the raw event.
    - Separately, every `{<name>}` in the **external** path needs its own `parameters` entry whether or
      not `overwrite_path` references it: API Gateway rejects an import whose path template declares a
      parameter the operation does not list.
  - **`$request.header.*` and `$request.querystring.*` are translated too**, by the same rule with a
    different source. HTTP API parameter mapping accepts all three in `overwrite:path`, so all three
    work today. Each becomes a `{<name>}` segment in the integration `uri`, a method-level
    `parameters` entry with the matching `in` (`header` or `query`), and a `requestParameters` line
    mapping `integration.request.path.<name>` to `method.request.header.<name>` or
    `method.request.querystring.<name>`.
    - Translated rather than rejected because the capability exists in REST, and these modules are
      published to the Terraform registry: `gateway_endpoints` is a public input, so a deployment
      relying on header rewriting is invisible to this repo. Rejecting would force those users to
      read the header in application code — a code change delivered as a deployment upgrade.
    - Left untranslated the expression reaches the container as literal text and 404s with no error
      anywhere, which is the current GCP behaviour (`ak-gcp/containerized/api_gateway.tf:54`) and not
      a model to copy.
  - No `$default` case: `variables.tf:60` matches `upper(ep.method)` against a lowercase `"$default"`,
    so no spelling passes validation. The dead entry is pre-existing and left alone.
- `api_gateway_async.tf` is deleted; its `rest_async` `GET` poll route becomes a `"get"` **method on
  the default chat path object**, not a new path, on the same condition
  (`var.queue_mode && var.execution_mode == "rest_async"`).
  - That path is `local.default_endpoint_path` (`state.tf:29`) — `/{api_base_path}/{api_version}/
    {agent_endpoint}` — the same path the default `POST` uses, **not** the literal `/api/v1/chat`.
    `/api/v1/chat` is the *backend* path, the hardcoded `overwrite:path` of the integration
    (`api_gateway_async.tf:16`), and stays on the integration side. With `api_base_path = "service"`
    and `agent_endpoint = "ask"` the route is `GET /service/v1/ask`, which a literal reading would
    have missed entirely.
  - So the renderer groups methods per path rather than emitting one path per route key. This is the
    one structural trap GCP calls out in the same situation
    (`ak-gcp/containerized/api_gateway.tf:7-9`, `openapi_paths_block`).
- Binary uploads: the root declares `x-amazon-apigateway-binary-media-types: ["multipart/form-data"]`.
  Without it `/chat-multipart` bodies are corrupted silently.
- CORS: a REST API has no `cors_configuration`, so preflight needs a declared `OPTIONS` method — but
  **only on paths that do not already use `x-amazon-apigateway-any-method`**, which accepts every
  verb including `OPTIONS`. Where one is needed it is **proxied to the container, not a mock**:
  FastAPI's `CORSMiddleware` already answers preflight (`ak-py/src/agentkernel/api/http.py:55-61`),
  and a mock built from `cors_*` would contradict the container on every non-preflight response.
  - This mirrors the GCP module exactly, which proxies its preflight operation to Cloud Run and
    builds one only for non-`ANY` paths (`ak-gcp/containerized/api_gateway.tf:47-58`, `:73-74`).
  - Consequence: `var.enable_cors` and the `cors_*` variables stop affecting ECS. They are already
    inert for actual responses once the gateway stops rewriting them; this makes that honest. #1006
    makes the container's own policy configurable, which is the actual fix.

### ALB

- Set `idle_timeout` on `aws_lb.app` (`modules/rest-service/main.tf:219`), replacing the current
  implicit 60 s, so a silent gap in an SSE stream does not close the connection.
- **A new module variable `alb_idle_timeout`, default 300.** How long an agent may stay silent is a
  property of the user's workload, not of AWS, and every other request-path timeout in the repo is a
  variable with a default: `backend_deadline` and `timeout` on GCP containerized
  (`ak-gcp/containerized/variables.tf:81-91`), `backend_deadline` on GCP serverless (`:93-97`), the
  Lambda `timeout`s in `ak-aws/serverless/variables.tf:317`, `:334`, `:354`, and the Helm chart's
  `websocket.requestTimeout` (`ak-k8s/chart/values.yaml:322-323`), which is `0s` for exactly this
  reason — "agent streams are long-lived".
  - The description states the relationship the operator needs: the gateway's own idle limit caps it,
    so raising this alone does not extend a stream past what API Gateway allows. GCP documents the
    same pairing ("Must be <= Cloud Run timeout").
- The **default** follows the measured REST API idle limit if testing contradicts the documented
  300 s.
- Accepted cost: an abandoned connection (closed laptop, killed tab) is now held for the timeout
  rather than 60 s before the ALB reaps it, so a higher value holds idle connections longer.

### Stream duration

There are **two configurable** caps on the request path and they limit different things. The ALB's
bounds a silent gap; the gateway's bounds the whole integration. A stream that emits a chunk every two
seconds for ten minutes never trips the ALB and is killed by the gateway. The gateway's own fixed
5-minute idle cap is the third, and is covered under ALB above.

- **`timeoutInMillis` must be set on every integration.** Left unset it takes AWS's documented default
  range ceiling of 29 s, which caps every SSE stream at 29 seconds and silently defeats this change —
  the same failure the HTTP API had, from a different cause.
- **A second new module variable, `gateway_integration_timeout`** (seconds, default 900), multiplied
  by 1000 in the renderer. A variable for the same reason `alb_idle_timeout` is one, and GCP
  containerized is the precedent for a target exposing *two* request-path timeouts rather than one
  (`backend_deadline` and `timeout`, `ak-gcp/containerized/variables.tf:81-91`).
- **The default is the least certain number in this design.** AWS documents it twice and
  inconsistently: the streaming guide says the integration timeout is configurable "up to 15 minutes"
  and its own worked example sets `timeoutInMillis: 900000`, while the same page says that switching
  an integration to `STREAM` *removes* a customised timeout because "API Gateway streams your response
  for up to 5 minutes". 900 follows the example; claim 4b measures which is true.
- `alb_idle_timeout`'s 300 s default is **not** affected. The 5-minute figure is documented as an
  idle limit after all — the streaming page states it separately from the 15-minute maximum
  duration: "for Regional or private endpoints, the timeout is 5 minutes". 300 s matches the cap
  the gateway applies anyway, so a higher value changes nothing for traffic through the gateway.
  Only `gateway_integration_timeout` waits on claim 4b.

### Response store

SSE needs a store that can stream chunks. **Both** of these are required; neither covers the other's
case.

- **(a) Wire the connection detail** — inject `AK_EXECUTION__RESPONSE_STORE__REDIS__URL` (and the
  Valkey equivalent) from the cluster the module already creates, and add `redis_url` / `valkey_url`
  outputs. Without it, a user who set everything up correctly still fails: `_RedisConfig.url` defaults
  to `redis://localhost:6379` (`core/config.py:25`), so a task selecting `type: redis` silently points
  at its own loopback. Nothing reports a missing URL.
- **(b) Warn at plan time — a `check` block, not a `validation`.** Under
  `queue_mode && rest_sync && delta`, assert `create_redis_cluster || create_valkey_cluster` and emit
  a **warning** naming the fix. Without it a user who created no cluster applies cleanly and learns
  from a CloudWatch crash-loop minutes later.
  - A hard rejection would be wrong in both directions, because Terraform never sees which store
    `config.yaml` selected — the module injects the URL only, never the type. It would **block** a
    valid deployment pointing at an external Redis with no module cluster, and **pass** one that
    created a cluster but selects `dynamodb`.
  - A `check` block warns without blocking, and this module already uses one — `check
    "scheduling_requires_queue_mode"` (`eventbridge.tf:6-11`). Follow its shape: a named check, one
    `assert`, and an `error_message` opening `[IMPORTANT]`. Enforcement stays at gate 4, which reads
    the resolved config at startup and is the only place the real answer exists.
- Terraform injects the **connection detail only**, never
  `AK_EXECUTION__RESPONSE_STORE__TYPE`; `config.yaml` selects the backend, as with `thread.type`.
- The env var and the source are not new: both GCP modules already inject
  `AK_EXECUTION__RESPONSE_STORE__REDIS__URL = local.redis_url`
  (`ak-gcp/containerized/queue_mode.tf:30`, `ak-gcp/serverless/queue_mode.tf:30`). This brings AWS
  containerized in line with them.
- **The REST service tier only — not the agent runner.** The store is wired and IAM-granted solely to
  the REST service (`iam.tf:40-62`, `:116-119`; `rest_service.tf:55`); `modules/agent-runner/` has no
  response-store variable at all. Correct, and not to be "fixed": the runner fans chunks onto the
  output queue, while both the writer and the reader live in the IO container.
  - A deliberate divergence from GCP, which hands the same `queue_env` block to both its service and
    its runner (`ak-gcp/containerized/cloud_run.tf:161`, `queue_mode.tf:82`). That is a consequence of
    sharing one env block, not a requirement; the runner never reads the store. Harmless there,
    unnecessary here.
- Gates 4 and 5 stay as they are and must still fire for a non-streaming store.

### Access logging and the account-level CloudWatch role

REST API access logging needs the account-level CloudWatch role, which HTTP APIs did not. **The module
already owns that resource** for WebSocket mode, so REST mode joins an existing arrangement.

- `aws_api_gateway_account.this` (`api_gateway_ws.tf:95`), `aws_iam_role.apigw_cloudwatch` (`:73`) and
  its policy attachment (`:89`) are all gated `local.is_websocket_mode && var.enable_api_gateway_logs`.
  **Relax that to `var.enable_api_gateway_logs` alone.** Each is a single `count = 0/1` resource, so
  a deployment still creates at most one of each however many stages consume it — the relaxation does
  not rely on the modes being mutually exclusive, which #985 would make untrue by serving a REST stage
  beside the WebSocket one. The state addresses do not move: no `terraform state mv` for existing
  WebSocket users.
- `aws_api_gateway_stage.agents` takes the same `depends_on = [aws_api_gateway_account.this]` the
  WebSocket stage already carries (`:109`); the role must exist before a stage turns logging on.
- The CloudWatch log group stays per deployment and per mode, unchanged.
- The singleton hazard is unchanged in kind, only in who meets it — WebSocket deployments before, REST
  ones with logging on as well now. See Compatibility.

### Removing the ECS SSE rejection

- Delete the `message_type` validation added by #962 (gate 2).
- Reword the `message_type` description to drop "SSE is rejected with queue_mode = true" (gate 3).
- Reword "HTTP API" in variable descriptions where it names the gateway type
  (`variables.tf:47`, `:181`, `:184`, `:240`).

### Compatibility

- `gateway_endpoints` keeps its current type and semantics for `ANY` and path parameters. Verified
  against `examples/aws-containerized/openai-schedule/deploy/main.tf:72-83` (`ANY` plus
  `$request.path.task_id`) and `examples/aws-containerized/crewai/deploy/main.tf:18-29` (two plain
  `GET` routes).
- **Known incompatibility: a greedy route no longer catches method misses on an explicit path.** A
  user-supplied `path = "{proxy+}"` with `method = "ANY"` passes validation today and becomes
  `ANY /api/v1/{proxy+}`. An HTTP API matches method and path together, so `GET /api/v1/chat` misses
  the default `POST /api/v1/chat` and falls through to it. A REST API matches the path first, selects
  the explicit `/api/v1/chat` resource, finds no `GET` method and returns 403 — the greedy sibling is
  never reached.
  - Documented, not worked around. Giving every explicit resource a fallback method would turn
    today's clean method-not-allowed into a silent catch-all, which is worse than the gap.
  - Nothing in `examples/` or `e2e/` uses `{proxy+}`, and it is not documented as supported.
- **The ALB's idle timeout rises from an implicit 60 s to 300 s on every containerized
  deployment**, not only SSE ones, because `aws_lb.app` sets no `idle_timeout` today. Long-running
  non-streaming requests that the ALB used to cut at 60 s now survive, and an abandoned connection
  is held five times longer before it is reaped. Set `alb_idle_timeout = 60` to keep the old
  behaviour.
- Output names and types are unchanged, repointed at the new resources: `api_gateway_id`,
  `api_gateway_stage`, `agent_invoke_url`, and the two log-group outputs. `e2e/app/deploy/outputs.tf:2`
  builds `https://<id>.execute-api.<region>.amazonaws.com/<stage>` from the first two; a REST API's
  invoke URL has that same shape, so only the id changes.
- Access logging: the log format gains `$context.resourcePath` and **keeps** `$context.routeKey`,
  matching the serverless REST API's format, which logs both
  (`serverless/modules/api-gateway/main.tf:177-178`).
- **`cors_*` stops having any effect on ECS**, so a deployment that narrowed origins is no longer
  narrowed — the container answers every origin, with credentials (#1006). Nothing breaks: the
  variables default to `["*"]` (`variables.tf:186`), so only a deliberately restricted deployment
  changes. AWS documents both halves — an HTTP API "ignores CORS headers returned from your backend
  integration", while a REST API's proxy integration leaves the backend "responsible for returning
  the `Access-Control-Allow-Origin` ... headers".
- **`aws_api_gateway_account` now also reaches REST deployments.** A REST-mode deployment with
  `enable_api_gateway_logs = true` joins a known hazard: the role is a singleton per account and
  region, concurrent deployments "will contend over this resource", and disabling the toggle
  "**destroys** the account role, which can affect other REST APIs in the account"
  (`serverless/modules/api-gateway/README.md:76-77`). WebSocket deployments have always had this; the
  change widens who meets it. The containerized README's claim that the HTTP API does **not** need the
  role (`README.md:293`) becomes false and must be corrected.
- **Breaking on upgrade:** the API id and invoke URL change. Every registered webhook (Slack, WhatsApp,
  Messenger, …) points at the old URL and must be re-registered. How this is communicated is specified
  under Documentation below.

### Configuration

- **No new `AKConfig` fields.** Nothing in `ak-py` changes; `execution.mode` and `execution.message_type`
  already express everything this feature needs.
- The only new Terraform-injected variable is an existing `AKConfig` field's env var
  (`AK_EXECUTION__RESPONSE_STORE__REDIS__URL`), reusing `_ResponseStoreRedisConfig`
  (`ak-py/src/agentkernel/core/config.py:658`) whole. No new model, no new selector.
- **Two new Terraform input variables: `alb_idle_timeout`** (number, default 300) and
  **`gateway_integration_timeout`** (number, default 900), both in seconds. Nothing existing expresses
  either — the module has no request-path timeout of any kind today — and between them they match the
  two GCP containerized already exposes. The response-store requirement adds none, being expressed
  through the existing `create_redis_cluster` / `create_valkey_cluster` flags.
- No `enabled` flag is added: `execution_mode` + `message_type` already select SSE.

### House patterns

House Patterns 1 (pluggable by default) and 3 (classes, not scripts) describe Python components and do
not apply — this change adds no Python. Pattern 2 (reuse existing configuration) does apply and is met:
no new `AKConfig` field, and the response-store option reuses an existing model and env var.

### Verification

Verified on a deployed stack once the implementation is written.

- **First, because the change depends on them** (methods in `research/aws-claims-to-verify.md`): that
  `STREAM` delivers chunks incrementally rather than in one burst, and that a REST API reaches the ALB
  over VPC link V2 with no NLB. The same run measures the real idle timeout, which sets the ALB
  constant. Use a Redis or Valkey store — DynamoDB would fail for an unrelated reason and hide the
  result.
- **Then the acceptance criteria:** SSE streams under `rest_sync` + `delta` and the plan rejection is
  gone; `rest_sync`, `rest_async` and MCP all deploy behind the Regional REST API; `/chat-multipart`,
  CORS preflight, throttling and access logs behave as before; an existing WebSocket deployment with
  logging on still plans clean with no state move; the weekly integration tests and the e2e messaging
  harness pass.

### Documentation

These assert that ECS queue mode refuses SSE and must be corrected: `ak-cloud-deploy/SKILL.md:50`,
`:860`, `:1161`; `docs/docs/deployment/aws-containerized.md:18`;
`docs/docs/advanced/queue-mode-guide.md:536`, `:740`; containerized `README.md:411`;
`docs/specs/remove-direct-mode/research/blockers.md:13` (B5) and the #870 design's "SSE on ECS"
non-goal.

Two caveats:

- Containerized `README.md:293` and the notes at `:289-291` state the HTTP API does **not** need the
  account-level CloudWatch role. That becomes false — a correction, not a reword.
- `queue-mode-guide.md:546` (the store-capability table) is gate 4 and stays. Where these pages
  describe SSE in the single-container topology, that wording belongs to the direct-mode removal and
  is **not** edited here.

#### Announcing the breaking URL change

There is no dedicated breaking-change channel, so it rides the two surfaces that exist:

- **The PR title is the release note** — release bodies are generated from merged PR titles, so the
  title must say the ECS invoke URL changes.
- **An "Upgrading" section in `docs/docs/deployment/aws-containerized.md`**, naming webhook
  re-registration as a step.
- `docs/docs/whats-new.md` gets the capability entry; it is not a migration surface.
- Not revived: `README.md:684` points at three migration files that do not exist. Pre-existing, out of
  scope.

## Non-goals

- **Direct mode** (`queue_mode = false`). It is being removed; its SSE behaviour and the docs describing
  it are that work's concern, not this change's.
- **WebSocket mode.** `api_gateway_ws.tf` keeps its own v2 API and NLB, untouched.
- **The serverless (Lambda) module**, which already uses a REST API.
- **The GCP modules.** They already build their gateway from an OpenAPI document and have no SSE
  restriction — `message_type: delta` is documented for `rest_sync` with no rejection
  (`ak-gcp/containerized/variables.tf:310-315`). Read as precedent, not edited.
- **An SSE heartbeat in the server.** Only needed if raising the ALB idle timeout proves insufficient; a
  separate issue if so.
- **A2A / MCP on ECS queue mode**, which remains blocked on #780 follow-up work.
- Changing the response store's **default** backend for non-SSE ECS deployments.
- **CORS parity on actual responses.** Making the container honour `cors_allow_origins` needs CORS
  fields in `AKConfig`, which has none. A separate issue.

## Decisions taken

Each was an open choice during drafting; the requirements above state the outcome.

1. **Response store: wire the URL *and* warn at plan time.** They catch different mistakes — the user
   who set Redis up correctly and still hits the localhost default, and the user who created no
   cluster. Neither covers the other. One env var, two outputs, one `check` block. A `check` rather
   than a `validation` because Terraform cannot see which store `config.yaml` selects, so a hard
   rejection would block valid external-Redis deployments.
2. **Both request-path timeouts are variables: `alb_idle_timeout` (300 s) and
   `gateway_integration_timeout` (900 s).** Variables rather than constants because every sibling
   deployment exposes its request-path timeout that way, and because the right values depend on how
   long the user's agent goes quiet and how long it runs. Rejected: hardcoded constants, which would
   make ECS the only target where this cannot be tuned; and a single variable covering both, which
   would conflate a silent gap with a total duration. **Both defaults are provisional** and are set
   from claim 4's measurements — AWS's documentation contradicts itself on the streaming cap.
3. **The ~3.5× per-request cost is accepted** — immaterial beside the model call on the same request.
   Supporting both API types behind a variable would double this module's surface permanently.
4. **The unconfirmed AWS behaviours are tested on the first deployment, not proven up front.** The one
   failure with no workaround — the provider lacking the two fields — is already ruled out. Accepted
   cost: if `STREAM` does not stream, the Terraform rewrite is wasted.
5. **The URL change is announced via the PR title and an Upgrading section.** No `terraform plan`
   warning: awkward to trigger reliably, easy to miss.
6. **The API is built from an OpenAPI `body`**, accepting the loss of per-route plan diffs. Discrete
   `aws_api_gateway_resource` / `_method` / `_integration` resources would keep those diffs, but REST
   APIs model a path as a tree, so `state.tf` would have to decompose arbitrary user paths into
   segments, dedupe shared prefixes and order `parent_id` references — and it adds ~23 resources where
   the body adds none (worked comparison in `research/aws-claims-to-verify.md`). The serverless module
   is that approach in this repo (`serverless/modules/api-gateway/main.tf:45-96`): a fixed
   `api → version → main → sub → child` ladder, which can express only three user-supplied segments.
   The body approach is also already in this repo — `ak-gcp/containerized/api_gateway.tf` renders the
   same `gateway_endpoints_map` into an OpenAPI document, mapping `ANY` to `x-google-allow` (`:13`)
   and routing with `x-google-backend` (`:53`). Same input, same technique, different vendor
   extensions.
7. **`aws_api_gateway_account` stays owned by this module; its gate widens to both modes.** Relaxing
   the count is the smallest change that follows the pattern already in the file. Rejected: declining
   to manage it, which would give REST mode a different arrangement from WebSocket mode in one module;
   and a module shared with the serverless stack, which cannot work while the two roots are applied
   from separate state.

## Open questions

- **None blocking.** The seven decisions are settled; what remains is empirical, not a reviewer's call.
- **Confirmed:** provider `6.70.0` exposes `response_transfer_mode` and `integration_target`, read
  from the provider schema locally. This was the only failure with no workaround.
- **Confirmed:** the same two settings exist as **extension keys** inside
  `x-amazon-apigateway-integration`, which is what decision 6's OpenAPI `body` actually needs — a
  different surface from the provider arguments above. The reference describes `integrationTarget` as
  "the ALB or NLB ARN to send the request to. Supported only for private integrations that use VPC
  links V2", which is claim 2's mechanism stated as documentation
  (`research/aws-claims-to-verify.md`, claim 5). The throwaway apply this needed is unnecessary.
- **Newly open, from that same reference:** whether `timeoutInMillis` is honoured under `STREAM`, and
  therefore what the two timeout defaults should be. AWS says both "configurable up to 15 minutes"
  and "removed, streams for up to 5 minutes" on one page. Measured as claim 4b; it changes two
  defaults, not the design.
- **Unconfirmed, tested on the first deployment:** that `STREAM` delivers chunks incrementally, and
  that a REST API reaches an ALB directly over VPC link V2. A negative result on either means the
  feature is not yet possible on AWS and the issue closes.
- Raise anything else in review and it moves back here.
