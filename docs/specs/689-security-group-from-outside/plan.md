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

- **Goal:** the three new SG variables are exposed at the root and reach the two modules above; new
  root outputs expose the effective IDs.
- **Files:** `ak-deployment/ak-aws/containerized/{variables.tf,rest_service.tf,queue_mode.tf,outputs.tf}`
- **Steps:**
  1. Add `alb_security_group_id`, `ecs_service_security_group_id`, `agent_runner_security_group_id` to
     `variables.tf`, next to the existing `vpc_id`/`private_subnet_ids` block.
  2. Pass the two rest-service variables through in `rest_service.tf`'s `module "rest_service"` call.
  3. Pass `agent_runner_security_group_id` through as `security_group_id` in `queue_mode.tf`'s
     `module "agent_runner"` call.
  4. Add the three new outputs to `outputs.tf`.
  5. Confirm `api_gateway.tf:24` needs no edit (it already reads `module.rest_service.alb_security_group_id`).
- **Verify:** `terraform fmt -check` and `terraform validate` at the containerized root; `terraform plan`
  with no new variables set shows zero diff (create-path unchanged); a `terraform plan` with a fake ID
  passed for each of the three new variables shows the matching `aws_security_group` resource dropping
  to 0 count and every consumer resolving to the fake ID instead of erroring (spec.md § Testing, item 2).

## Iteration 4: `serverless/state.tf`

- **Goal:** `serverless` accepts one `security_group_id`, shared by all five Lambda submodules; unset
  behaves exactly as today.
- **Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf,outputs.tf}`
- **Steps:**
  1. Add `security_group_id` to `variables.tf`, next to the existing `vpc_id`/`private_subnet_ids` block.
  2. Add `count` to `aws_security_group.lambda`; change `local.security_group_id`'s definition to
     resolve from the variable or the created resource.
  3. Add the `security_group_id` output.
  4. Confirm no changes needed at the five submodule call sites (`authorizer`, `ws_connection_handler`,
     `request_handler`, `agent_runner`, `response_handler`) — they already read `local.security_group_id`.
- **Verify:** `terraform fmt -check` and `terraform validate` at the serverless root; same two-sided
  `terraform plan` check as Iteration 3 (unset → zero diff; fake ID set → SG resource drops to 0 count,
  all five submodule calls and the new output resolve to the fake ID).

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
- **`ak-deployment/ak-aws/containerized/README.md`**: add `alb_security_group_id`,
  `ecs_service_security_group_id`, `agent_runner_security_group_id` as new rows in the root variables
  table (`README.md:283-324` region). Note: this table does not currently document `vpc_id` /
  `private_subnet_ids` either (pre-existing gap, confirmed by grep — out of scope to backfill here); add
  the three new rows regardless, following the table's existing row format.
- **`ak-deployment/ak-aws/serverless/README.md`**: add one new row for `security_group_id` directly
  below the existing `vpc_id` / `private_subnet_ids` rows (`README.md:512-513`), matching their exact
  format.
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
