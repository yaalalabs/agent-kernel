# #978: ECS — replace the API Gateway HTTP API with a REST API so SSE can stream — Implementation Plan

Orders [`spec.md`](spec.md). Everything is Terraform under `ak-deployment/ak-aws/containerized/`; there
are no Python changes, so there is no `ak-py` test iteration.

Iteration 3 is the irreversible one — it deletes the v2 API and creates the REST API in the same
commit, because `outputs.tf` cannot reference both. Iterations 1, 2, 4 and 5 are each additive or
inert on their own and can be applied and reviewed independently.

**Static verification, used by every iteration below**, run from
`ak-deployment/ak-aws/containerized/`:

```bash
terraform fmt -recursive -check
terraform init -backend=false
terraform validate
```

## Iteration 1: `state.tf` — one meaning for `path`, and the poll route as data

- **Goal:** `local.rest_endpoints_map` exists and every entry's `path` is the full external path.
  Nothing consumes it yet, so the module behaves exactly as before.
- **Files:** `ak-deployment/ak-aws/containerized/state.tf`
- **Steps:**
  1. Add `local.user_endpoint_paths`, then read it from both the key and the `path` field of
     `user_gateway_map` so the two cannot drift (spec.md §1.1).
  2. Set `mcp_gateway_map`'s `path` to `local.mcp_endpoint_path`.
  3. Add `local.poll_gateway_endpoint` and `local.rest_endpoints_map` (spec.md §1.2).
- **Verify:** static checks above, plus `terraform console`:
  - `local.rest_endpoints_map` — every entry's `path` starts with `/${api_base_path}/${api_version}`,
    including the user and MCP entries that were relative before.
  - With `queue_mode = true, execution_mode = "rest_async"`, the map carries
    `GET /api/v1/chat`; under `rest_sync` it does not.
  - `terraform plan` shows **zero diff** — nothing reads `.path` and the new local is unconsumed
    (spec.md §1.1 verifies this: `api_gateway.tf:30` and `:44` are the map's only consumers).

## Iteration 2: Request-path timeouts

- **Goal:** both caps are declared and the ALB one is wired. The gateway one is declared but unread
  until Iteration 3.
- **Files:** `variables.tf`, `rest_service.tf`, `modules/rest-service/{variables.tf,main.tf}`
- **Steps:**
  1. Declare `gateway_integration_timeout` on the root module only (spec.md §6). No `validation` block
     — the range claim 4b exists to establish.
  2. Declare `alb_idle_timeout` on the root module and on `modules/rest-service/`, same type, default
     and description (spec.md §6.1).
  3. Set `idle_timeout = var.alb_idle_timeout` on `aws_lb.app` (`modules/rest-service/main.tf:219`) and
     pass the variable through from `rest_service.tf`.
- **Verify:** static checks in the submodule directory and at the root. `terraform plan` on an existing
  stack shows `aws_lb.app` with `idle_timeout: 60 -> 300` and **no replacement** — an in-place attribute
  change. This is Behavioural change 2 and it lands on every containerized deployment, SSE or not.

## Iteration 3: The gateway swap

- **Goal:** the non-WebSocket gateway is an `aws_api_gateway_rest_api` built from a rendered OpenAPI
  document, streaming over the existing VPC link V2 to the existing ALB.
- **Files:** `api_gateway.tf` (rewritten), `api_gateway_async.tf` (deleted), `api_gateway_ws.tf`,
  `outputs.tf`
- **Steps:**
  1. In `api_gateway.tf`, delete lines 1–48 and 58–89. **Leave `aws_apigatewayv2_vpc_link.ecs_alb`
     (`:21-27`) byte for byte**, name included — a rename replaces the link this change exists to reuse.
  2. Build the renderer locals in order: `_param_re` and `_eps` (§2.1), `_ep_params` /
     `_ep_request_params` (§2.1), `_ep_operations` (§2.2), `_method_key` and `openapi_paths_block`
     (§2.3), `_non_any_by_path` and `_options_op` (§2.4), `openapi_spec` and `openapi_spec_json` (§2.5).
     Keys read from `local.rest_endpoints_map`, not `gateway_endpoints_map`.
  3. Add the four resources: `aws_api_gateway_rest_api`, `_deployment`, `_stage` (name `agents`),
     `_method_settings` (§3). Rename the log group resource to `.rest_api` keeping its AWS name string,
     and add the `moved` block (§3.1).
  4. Delete `api_gateway_async.tf` entirely (§5).
  5. Relax the three `count`s in `api_gateway_ws.tf` (`:74`, `:90`, `:96`) to `var.enable_api_gateway_logs`
     alone (§4). **Same iteration, not later:** the REST stage's `depends_on` and `access_log_settings`
     need that role to exist in REST mode. Nothing else in those blocks changes, so no state address moves.
  6. Repoint the four outputs and the two log-group outputs (spec.md § Consumer changes). Note
     `aws_api_gateway_stage`'s attribute is `stage_name`, not `name`, and that `agent_invoke_url`'s v2
     fallback expression goes away.
- **Verify:** static checks — `validate` is the first real test of the renderer, since one mismatched
  operation object across the map fails Terraform's type checker here rather than at apply. Then
  `terraform plan` + `terraform console` on `jsondecode(local.openapi_spec_json).paths` for each of the
  eleven cases in spec.md § Testing → Static. The two that matter most:
  - **`rest_async`** — exactly one path object for the default chat path, carrying both `post` and `get`.
  - **An existing WebSocket stack with `enable_api_gateway_logs = true`** — plans clean, no replacement
    of the role, attachment or account resource, no `terraform state mv`. Acceptance criterion
    `design.md:284`.

## Iteration 4: Response store wiring

- **Goal:** a module-created Redis or Valkey cluster is injected as the response store, and a plan
  against SSE settings with no cluster warns.
- **Files:** `modules/rest-service/main.tf`, `outputs.tf`, `checks.tf` (new)
- **Steps:**
  1. Add the two env vars to `local.rest_service_environment` under the existing
     `queue_mode && !websocket_mode` gate (§7.1). `var.redis_url` / `var.valkey_url` are already wired
     — no new plumbing. **Do not** add anything to `modules/agent-runner/`: the store's writer and
     reader both live in the IO container.
  2. Add the `redis_url` / `valkey_url` outputs (§7.2).
  3. Add `checks.tf` with `check "sse_requires_streaming_response_store"` (§7.3) — a `check`, not a
     `validation`, and the reasoning is in the spec so nobody "improves" it into a rejection.
- **Verify:** static checks. `terraform plan` with `create_redis_cluster = true` shows the task
  definition gaining `AK_EXECUTION__RESPONSE_STORE__REDIS__URL`; with neither cluster and
  `rest_sync` + `delta`, the plan emits the `[IMPORTANT]` warning and still succeeds.

## Iteration 5: Lift the SSE rejection

- **Goal:** `terraform plan` accepts `queue_mode = true` with `rest_sync` + `delta`.
- **Files:** `variables.tf`
- **Steps:**
  1. Delete the `message_type` validation at `:284-287` (gate 2) in full (§8).
  2. Reword the `message_type` description (`:278`) — drop the `SSE is rejected` sentence only.
  3. Reword "HTTP API" at `:47`, `:181`, `:184` and `:240`; the `enable_cors` and CORS-comment
     rewordings must say that the flag now controls only whether a preflight operation is emitted.
  4. Leave the unmatchable `"$default"` entry at `:60` / `:63` alone — pre-existing, out of scope.
- **Verify:** static checks, and `terraform plan` with `queue_mode = true, execution_mode = "rest_sync",
  message_type = "delta"` succeeds where it previously errored. Gates 4 and 5 in `ak-py` are untouched
  and must still reject a non-streaming store at startup and per request.

## Iteration 6: Tests

The module has no `.tftest.hcl` files and no Terraform unit-test framework, so "tests" is the static
matrix run as one pass, then a real deployment.

- **Static:** `terraform fmt -recursive -check` across the module, `terraform validate` at the root and
  in `modules/rest-service/`, and the eleven `terraform console` cases in spec.md § Testing → Static run
  together rather than per-iteration. The timeout case is the one to not skip: **every routed operation
  must carry `timeoutInMillis`**, and one without it is the 29-second bug (§0). Preflight operations
  deliberately carry neither it nor `responseTransferMode`.
- **The claims come first on a deployed stack** — they decide whether the rest is worth measuring
  (`research/aws-claims-to-verify.md`). Claim 5 is already settled from the AWS reference and needs no
  deployment.
  1. **Claim 3** — does `STREAM` stream? Redis or Valkey store, `curl -N`, timestamped arrivals,
     compared against the old stack.
  2. **Claim 2** — implied by the stack applying and serving one request end to end.
  3. **Claim 4a** — the real idle limit, with `alb_idle_timeout` at 900 so the ALB is not what is being
     measured.
  4. **Claim 4b** — the real total limit, at `gateway_integration_timeout` 900 then 120.
- **The two variable defaults are provisional until 4a and 4b report.** Both were chosen from
  documentation that contradicts itself (5 minutes vs 15 minutes for the same cap), so this iteration
  can end in an edit to `variables.tf` and to the two descriptions. Record the results in the research
  file's Results table.
- **Then the acceptance criteria** in spec.md § Testing → On a deployed stack, including the e2e
  messaging harness, which is the real test of Behavioural change 1: its webhook URLs are rebuilt from
  `api_gateway_id` and `api_gateway_stage` (`e2e/app/deploy/outputs.tf:2`), so a re-apply re-registers
  them.

## Iteration 7: Sync docs and skills

Per spec.md § Documentation changes. Every line below was verified against the branch while writing
this plan; the line numbers are from `develop`.

**These assert the ECS SSE rejection and are now false:**

- `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:50`, `:860`, `:1161`
- `docs/docs/deployment/aws-containerized.md:18`
- `docs/docs/advanced/queue-mode-guide.md:536`, **`:742`** (spec.md says `:740`; the "HTTP API buffers
  streamed responses" sentence is at `:742`)
- `ak-deployment/ak-aws/containerized/README.md:411`
- `docs/specs/remove-direct-mode/research/blockers.md:13` (B5), and the #870 design's "SSE on ECS"
  non-goal
- **`.agents/skills/ak-dev-architecture/SKILL.md:1553`** — the `IOHandler` row ends "`rest_sync` + `delta`
  (SSE) is rejected by `terraform plan` in queue mode (the HTTP API buffers streamed responses)".
  **Not in spec.md's list** — found while writing this plan, and the only dev skill affected.

**Corrections rather than rewordings, in `ak-deployment/ak-aws/containerized/README.md`:**

- `:293` — "the HTTP API … does **not** require the account-level `aws_api_gateway_account` CloudWatch
  role" becomes false (Behavioural change 5). `:290` names "the HTTP API stage" in the same bullet.
- `:296-300` — the "keeping logging on" upgrade note's `terraform state mv` snippet names
  `aws_cloudwatch_log_group.http_api`, which the `moved` block renames to `.rest_api`. The snippet is
  for an older upgrade and now reads against a resource address that no longer exists.
- `:483` — "API Gateway HTTP APIs cap a request body at 10 MB". The 10 MB cap still holds for a REST
  API, so this is a name fix, not a limit change.
- `:490` — "the HTTP API's V2 link is not created in these modes" — still true, name only.

**New material:**

- An **"Upgrading" section** in `docs/docs/deployment/aws-containerized.md` naming webhook
  re-registration as a step, and the ALB idle-timeout change.
- **`changelog.d/978.breaking.md`** for the invoke-URL change, and **`changelog.d/978.added.md`** for
  SSE becoming available in ECS queue mode. Release bodies are compiled from these fragments by
  towncrier, **not** from PR titles (`.github/workflows/publish.yaml:101-102`, `:249-252`). Both go in
  the **implementation** PR: a `docs:` PR needs no fragment, and one merged ahead of the code compiles
  into a release that does not contain it. Follow `changelog.d/870.breaking.md` (same ECS surface) and
  use no em or en dashes.
- `docs/docs/whats-new.md` capability entry (not a migration surface).
- `alb_idle_timeout`, `gateway_integration_timeout` and the two new outputs in the containerized
  `README.md` tables. **Document the two timeouts together** — the common mistake will be raising one
  and expecting it to extend a stream the other is cutting.

**Verified as needing no update:**

- `.agents/skills/ak-dev-testing-conventions/SKILL.md:154` mentions `rest_sync` + `delta` without a
  streaming store — that is gate 5, which stays. No edit.
- `ak-deployment/ak-aws/containerized/modules/README.md` — documents the submodule config objects;
  `alb_idle_timeout` is a flat submodule variable and needs a short added note, not a table edit (the
  pattern #689 established).
- `README.md:684`'s three missing migration files are pre-existing and out of scope.

Before merge, run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the
branch's actual diff to catch anything this plan missed.
