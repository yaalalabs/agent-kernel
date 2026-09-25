# #689: Accept externally-provided security groups in the containerized and serverless AWS modules — Implementation Plan

## Iteration 1: `containerized/modules/rest-service`

- **Goal:** `rest-service` accepts `alb_security_group_id` / `ecs_service_security_group_id`; unset
  behaves exactly as today.
- **Files:** `ak-deployment/ak-aws/containerized/modules/rest-service/{main.tf,variables.tf,outputs.tf}`
- **Steps:**
  1. Add the two variables (spec.md § `containerized/modules/rest-service`).
  2. Add `count` to `aws_security_group.ecs_alb` and `aws_security_group.ecs_service`; add the two
     resolving `local`s.
  3. Update `ecs_service`'s ingress `security_groups`, `aws_lb.app.security_groups`, and the
     `ecs_service` submodule call's `security_group_ids` to read the locals.
  4. Update `outputs.tf`'s `security_group_id` / `alb_security_group_id` to return the locals.
- **Verify:** `terraform fmt -check` and `terraform validate` in this module directory; `terraform plan`
  in the containerized root (see Iteration 3) shows no diff when the new variables are unset.

## Iteration 2: `containerized/modules/agent-runner`

- **Goal:** `agent-runner` accepts `security_group_id`; unset behaves exactly as today.
- **Files:** `ak-deployment/ak-aws/containerized/modules/agent-runner/{main.tf,variables.tf,outputs.tf}`
- **Steps:**
  1. Add the variable (spec.md § `containerized/modules/agent-runner`).
  2. Add `count` to `aws_security_group.agent_runner`; add the resolving `local`.
  3. Update `aws_ecs_service.agent_runner.network_configuration.security_groups` and the
     `security_group_id` output to read the local.
- **Verify:** `terraform fmt -check` and `terraform validate` in this module directory.

## Iteration 3: `containerized` root wiring

- **Goal:** the three new SG fields are exposed at the root and reach the two modules above; new root
  outputs expose the effective IDs.
- **Files:** `ak-deployment/ak-aws/containerized/{variables.tf,rest_service.tf,queue_mode.tf,outputs.tf}`
- **Amended:** instead of three new flat root variables, the SG IDs are added as fields on the existing
  `rest_service`/`agent_runner` object variables (spec.md's containerized-root section, Amendment).
- **Steps:**
  1. Add `alb_security_group_id`/`ecs_service_security_group_id` fields to the `rest_service` object
     type in `variables.tf`, and `security_group_id` to the `agent_runner` object type (and its
     `default` block).
  2. Pass `var.rest_service.alb_security_group_id` / `var.rest_service.ecs_service_security_group_id`
     through in `rest_service.tf`'s `module "rest_service"` call (to that submodule's unchanged flat
     variables).
  3. Pass `var.agent_runner.security_group_id` through as `security_group_id` in `queue_mode.tf`'s
     `module "agent_runner"` call.
  4. Add the three new outputs to `outputs.tf`.
  5. Confirm `api_gateway.tf:24` needs no edit (it already reads `module.rest_service.alb_security_group_id`).
- **Verify:** `terraform fmt -check` and `terraform validate` at the containerized root; `terraform plan`
  with no new variables set shows zero diff (create-path unchanged); a `terraform plan` with a fake ID
  passed for each of the three new variables shows the matching `aws_security_group` resource dropping
  to 0 count and every consumer resolving to the fake ID instead of erroring (spec.md § Testing, item 2).

## Iteration 4: `serverless/state.tf`

- **Goal (amended, post-implementation):** `serverless` accepts three independent SG fields — one per
  Lambda pipeline stage — instead of one `security_group_id` shared by all five submodules. Unset
  behaves exactly as today (one SG created per stage, same rule content as the original shared SG).
- **Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf,outputs.tf}`
- **Steps:**
  1. Add `security_group_id = optional(string, null)` to the `request_handler`, `agent_runner`, and
     `response_handler` object variables (not a new flat root variable — the object-field convention
     Iteration 3 already established for `containerized`).
  2. Replace `aws_security_group.lambda` with three resources (`request_handler`, `agent_runner`,
     `response_handler`), each `count`-gated on its own object field being `null` only (not on
     `queue_mode`/`enable_api_gateway` — see spec.md's Amendment for why that would break the resolving
     `local`). Replace the single shared local with three: `request_handler_security_group_id`,
     `agent_runner_security_group_id`, `response_handler_security_group_id`.
  3. Rewire the five submodule call sites: `authorizer` and `ws_connection_handler` →
     `local.request_handler_security_group_id` (both share the request-handling front door);
     `request_handler` → `local.request_handler_security_group_id`; `agent_runner` →
     `local.agent_runner_security_group_id`; `response_handler` →
     `local.response_handler_security_group_id`.
  4. Replace the single `security_group_id` output with three: `request_handler_security_group_id`
     (unconditional), `agent_runner_security_group_id` and `response_handler_security_group_id` (both
     `null` when `queue_mode = false`, matching this file's existing convention for other
     agent-runner/response-handler outputs).
- **Verify:** `terraform fmt -check` and `terraform validate` at the serverless root; same two-sided
  `terraform plan` check as Iteration 3 (unset → zero diff; a fake ID set on one of the three fields
  drops only that field's SG resource to 0 count and resolves every consumer of that field's local to
  the fake ID, while the other two SGs still get created).

## Iteration 5: Tests

From spec.md § Testing — this repo has no Terraform unit-test framework, so "tests" here means the
static/plan checks already named per-iteration above, run together as a final pass once all four
modules are wired:

- `terraform fmt -check -recursive` across `ak-deployment/ak-aws/containerized` and
  `ak-deployment/ak-aws/serverless`.
- `terraform validate` in all four touched module directories plus both root modules.
- Manual `terraform plan` review (both roots, unset and provided-ID cases) as described in Iterations
  3–4.
- No change to `.github/workflows/integration-test-weekly.yaml` — its existing `aws-containerized` /
  `aws-serverless` matrix entries already exercise the unset (`null`) path via bring-your-own-VPC
  (`--vpc-id`/`--private-subnet-ids`, `integration-test-weekly.yaml:291-293`) and continue to run
  unmodified. Extending that matrix to also pass a pre-created SG id is optional follow-up, not part of
  this plan (spec.md § Testing, item 3).

## Iteration 6: Sync docs and skills

- **`ak-deployment/ak-aws/containerized/modules/README.md`**: add the two new `rest-service` variables
  near its "Input Variables" block (`README.md:118-132`) and the one new `agent-runner` variable near
  its "Input Variables" block (`README.md:212-232`) — both currently only document the nested
  `rest_service`/`agent_runner` config objects, not the flat SG variables sitting alongside them, so this
  needs a short added note rather than a table edit.
- **`ak-deployment/ak-aws/containerized/README.md`**: document `alb_security_group_id` /
  `ecs_service_security_group_id` as fields on the `rest_service` object and `security_group_id` as a
  field on the `agent_runner` object (amended — these are object fields, not root variables), in both
  the "Configuration" object examples and the "Security Groups" section (`README.md:195-352` region).
- **`ak-deployment/ak-aws/serverless/README.md`** (amended): remove the single `security_group_id` root
  input row; add a `security_group_id` row to each of the `request_handler`/`agent_runner`/
  `response_handler` object-structure tables; add a "Security Groups" section (mirroring
  `containerized/README.md`'s) documenting the three fields, their independence, and which Lambdas each
  one covers; replace the single `security_group_id` output row with the three new output rows.
- **`docs/docs/deployment/aws-containerized.md`** and **`docs/docs/deployment/aws-serverless.md`**:
  checked for an existing "bring your own VPC" prose section to extend in parallel — neither has one
  (verified: `vpc_id` appears only inside an example code comment in the containerized doc, and not at
  all in the serverless doc's prose). No prose section exists to extend, so no edit needed beyond what
  `ak-dev-sync-docs-from-branch` (below) independently flags.
- **`.agents/skills/ak-dev-architecture/SKILL.md`**: checked — its "agent-runner" / "rest-service"
  mentions describe process/deployment topology (ECS vs. Lambda process roles), not Terraform variable
  interfaces. No update needed.
- Before merge, run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the
  branch's actual diff to catch anything this plan missed.
