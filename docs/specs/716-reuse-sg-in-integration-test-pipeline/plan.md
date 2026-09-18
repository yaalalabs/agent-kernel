# #716: Reuse security groups in the weekly AWS integration test pipeline — Implementation Plan (Phase 1: AWS Serverless)

Phase 2 (AWS containerized) is not planned here — it will get its own iterations once designed.

**Amendment (post-implementation):** per `design.md`/`spec.md`'s own Amendments, #689's serverless
module split into three per-tier SGs; every `security_group_id` reference below is amended to
`request_handler_security_group_id`, and Iteration 2's file-specific insertion point moves from a
top-level module argument to a line inside each file's `request_handler = { ... }` block.

## Iteration 1: Base deployment exposes its security group ID

- **Goal:** `examples/aws-serverless/openai/deploy` outputs the request-handler-tier SG ID it
  already creates, so it's readable via `terraform output` exactly like `vpc_id`/`private_subnet_ids`
  already are.
- **Files:** `examples/aws-serverless/openai/deploy/outputs.tf`
- **Steps:**
  1. Add the `request_handler_security_group_id` output (spec.md § Base deployment).
- **Verify:** `terraform validate` in this deploy dir (after `python3 scripts/deploy/inject_dependencies.py`
  so the module source resolves locally); `terraform output -raw request_handler_security_group_id`
  against the base's existing remote state returns a non-empty SG ID.

## Iteration 2: Example projects accept a reusable security group

- **Goal:** each of the 9 weekly `aws-serverless` matrix examples can accept an externally-provided
  request-handler-tier SG ID and forward it into its own module call's `request_handler` block;
  unset behaves exactly as today (module still creates its own SG for that tier).
- **Files:** `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,schedule-openai}/deploy/{variables.tf,main.tf}`,
  `examples/memory/{redis,valkey,dynamodb}/deploy/{variables.tf,main.tf}`
- **Steps:**
  1. Add the nullable `request_handler_security_group_id` variable to each `variables.tf` (spec.md
     § Example projects).
  2. Add `security_group_id = var.request_handler_security_group_id` **inside** each `main.tf`'s
     `request_handler = { ... }` block (not a top-level `module "serverless_agents"` argument —
     amended from the original design, since the underlying module's top-level `security_group_id`
     variable no longer exists per #689's amendment), matching that block's existing alignment
     style. For `scalable-openai`/`schedule-openai`, only their `request_handler` block gets this
     line — their `agent_runner`/`response_handler` blocks are untouched.
- **Verify:** `terraform validate` in each of the 9 deploy dirs (after `inject_dependencies.py`);
  `terraform plan` with no `request_handler_security_group_id` set shows zero diff (create-path
  unchanged) in at least one representative example (`adk`).

## Iteration 3: `get_base_outputs.py` retrieves the security group ID

- **Goal:** the script that already surfaces `vpc_id`/`private_subnet_ids` to `$GITHUB_OUTPUT` does
  the same for `request_handler_security_group_id`.
- **Files:** `.github/scripts/get_base_outputs.py`
- **Steps:**
  1. Add the `terraform output -raw request_handler_security_group_id` retrieval, print line, and
     `$GITHUB_OUTPUT` write (spec.md § `get_base_outputs.py`).
- **Verify:** run the script directly against the base deployment's existing state
  (`python3 .github/scripts/get_base_outputs.py --base-path examples/aws-serverless/openai
  --deploy-dir deploy`, with `GITHUB_OUTPUT` unset so it just prints); confirm `Request Handler
  Security Group ID: <sg-id>` prints alongside the existing VPC/subnet lines. Depends on
  Iteration 1's output existing.

## Iteration 4: `run_single_test.py` threads the security group ID into Terraform

- **Goal:** a new `--request-handler-security-group-id` CLI flag sets
  `TF_VAR_request_handler_security_group_id` for both deploy and destroy, exactly like `--vpc-id`
  already does; the Lambda-SG ENI sweeper's naming list is updated to the three per-tier names.
- **Files:** `.github/scripts/run_single_test.py`
- **Steps:**
  1. Add the `--request-handler-security-group-id` argparse entry in `main()` (spec.md §
     `run_single_test.py`).
  2. Add the fourth `request_handler_security_group_id` parameter and
     `TF_VAR_request_handler_security_group_id` injection block to `deploy_aws_resources` and
     `destroy_aws_resources`.
  3. Update both call sites in `main()` to pass `args.request_handler_security_group_id` through.
  4. Amend `_resolve_lambda_sg_ids`'s `sg_names` list from the single `-lambda-sg`/
     `-authorizer-lambda-sg` pair to the three per-tier names (`-request-handler-sg`,
     `-agent-runner-sg`, `-response-handler-sg`), so the ENI sweeper still covers
     `scalable-openai`/`schedule-openai`'s self-created `agent_runner`/`response_handler` SGs.
- **Verify:** `python3 -c "import ast; ast.parse(open('.github/scripts/run_single_test.py').read())"`
  parses cleanly; manually invoke
  `run_single_test.py --type aws-serverless --path examples/aws-serverless/adk --action deploy
  --vpc-id <base vpc> --private-subnet-ids '<base subnets>' --request-handler-security-group-id
  <base sg>` against a scratch/dev deployment and confirm the log prints
  `TF_VAR_request_handler_security_group_id=<base sg>` and the resulting `terraform plan`/`apply`
  shows `aws_security_group.request_handler` at 0 count with the request handler (plus
  authorizer/`ws_connection_handler`) submodules resolving to the provided SG. Depends on
  Iteration 2 (example accepts the var).

## Iteration 5: Wire the workflow end-to-end

- **Goal:** the weekly pipeline's `get-base-outputs` job exposes
  `request_handler_security_group_id`, and Deploy/Destroy steps pass
  `--request-handler-security-group-id` for `aws-serverless` matrix entries only.
- **Files:** `.github/workflows/integration-test-weekly.yaml`
- **Steps:**
  1. Add `request_handler_security_group_id` to the `get-base-outputs` job's `outputs:` map
     (spec.md § workflow).
  2. Add the `aws-serverless`-scoped conditional to the Deploy step, alongside the existing `aws-*`
     one.
  3. Add the same conditional to the Destroy step.
- **Verify:** covered by Iteration 6's full CI run — this iteration has no meaningful standalone
  check beyond YAML validity (`yamllint` or a GitHub Actions workflow syntax check), since it only
  composes pieces already verified in Iterations 1-4.

## Iteration 6: Tests

From spec.md § Testing — no Terraform unit-test framework and no pytest suite covers
`.github/scripts/`, so verification is the static/manual/full-run checks named per-iteration above,
run together as a final pass once all five iterations are wired:

- `terraform validate` (with `inject_dependencies.py` applied) in all 10 touched deploy dirs (base +
  9 examples). Done during implementation: 9/10 validated cleanly (only pre-existing deprecation
  warnings from the AWS provider, unrelated to this change); `memory/redis` hit a local
  provider-cache miss for a pinned `aws` version unrelated to this change's correctness.
- The manual dry run from Iterations 3-4 (deploy + destroy against a real `aws-serverless` example
  with the base's actual outputs), including the `scalable-openai`/`schedule-openai`
  agent_runner/response_handler-still-self-created check from spec.md § Testing.
- A full `workflow_dispatch` run of `integration-test-weekly.yaml` (`keep_resources_on_failure: true`
  for easier first-run debugging), confirming:
  - Every `aws-serverless` matrix job's Deploy step log shows
    `TF_VAR_request_handler_security_group_id=<base sg>`.
  - Every `aws-containerized` matrix job's Deploy step log shows **no** such line (confirms the
    type-scoping excludes them, per spec.md Behavioural changes item 5).
  - All `aws-serverless` jobs' Test and Destroy steps succeed exactly as they do today (no
    functional regression).

## Iteration 7: Sync docs and skills

- **`.agents/skills/ak-dev-testing-conventions/SKILL.md`**: checked (`grep` for
  `vpc_id`/`private_subnet_ids`/`integration-test-weekly`) — its `integration-test-weekly.yaml`
  entry (SKILL.md:396) and surrounding notes (399-407) describe workflow structure, step
  separation, and known infra-flakiness mitigations (GCP staggering, ECS wait-stable); none
  describe the base-deployment VPC/subnet-reuse mechanism this change extends to security groups.
  No update needed.
- **`docs/docs/deployment/aws-containerized.md`**: checked — its one `vpc_id`/`private_subnet_ids`
  mention (line 374) is an unrelated **containerized** example code comment, not prose about the CI
  pipeline. No update needed (and out of scope — containerized is Phase 2).
- **`docs/docs/deployment/aws-serverless.md`**: checked — no `vpc_id`/`private_subnet_ids`/pipeline
  mention exists to extend in parallel (confirmed by the earlier `grep`, which found no hits in this
  file). No update needed.
- **Example README changes** — `ak-deployment/ak-aws/serverless` itself is amended by #689, not by
  this change, but three of the example READMEs already documented the original single-SG reuse
  flow and are amended in place to the per-tier name:
  `examples/aws-serverless/{crewai,langgraph,openai-auth}/README.md` walk the reader through
  `terraform output vpc_id` / `private_subnet_ids` on the `openai` deployment and
  `export TF_VAR_vpc_id=...`; the `terraform output security_group_id` /
  `export TF_VAR_security_group_id=<SG_FROM_OPENAI>` lines each already had are renamed to
  `terraform output request_handler_security_group_id` /
  `export TF_VAR_request_handler_security_group_id=<SG_FROM_OPENAI>`.
  `examples/memory/valkey/README.md` tells the reader to set `vpc_id`/`private_subnet_ids` in
  `terraform.tfvars`; its `security_group_id` mention is renamed to
  `request_handler_security_group_id`. Per `ak-dev-sync-docs-from-branch`, example READMEs are a
  required docs surface when an example's inputs change.
- Before merge, run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the
  branch's actual diff to catch anything this plan missed.

## Iteration 8: Amendment 2 — convert the base to queue mode, reuse all three tiers

Per `design.md`'s Amendment 2 / `## Requirements — Amendment 2` and `spec.md`'s Amendment 2.

- **Goal:** the base deployment stops being the one `aws-serverless` example with only a request
  handler tier, so `scalable-openai`/`schedule-openai` can reuse its `agent_runner`/
  `response_handler` SGs too, the same way every `aws-serverless` example already reuses its request
  handler SG.
- **Files:**
  - `examples/aws-serverless/openai/{lambda_request_handler.py,lambda_agent_runner.py,
    lambda_response_handler.py,config.yaml,pyproject.toml,.gitignore,README.md}` (new/changed;
    `lambda.py` removed) and `deploy/{main.tf,outputs.tf,deploy.sh,Dockerfile.request_handler,
    Dockerfile.agent_runner,Dockerfile.response_handler}` (`Dockerfile` removed).
  - `.github/scripts/get_base_outputs.py`, `.github/scripts/run_single_test.py`,
    `.github/workflows/integration-test-weekly.yaml`.
  - `examples/aws-serverless/{scalable-openai,schedule-openai}/deploy/{variables.tf,main.tf}`.
- **Steps:**
  1. Convert the base to `queue_mode = true` with the three-Lambda split (Requirements —
     Amendment 2, base deployment).
  2. Add the two new outputs to the base's `outputs.tf`.
  3. Add the two new retrievals/prints/`$GITHUB_OUTPUT` writes to `get_base_outputs.py`.
  4. Add the two new job outputs to `get-base-outputs`, and the `matrix.path`-scoped conditional to
     the Deploy and Destroy steps in `integration-test-weekly.yaml`.
  5. Add the two new CLI flags and function parameters to `run_single_test.py`
     (`_resolve_lambda_sg_ids` needs no change — already amended in Iteration 4).
  6. Add the two new nullable variables to `scalable-openai`/`schedule-openai`'s `variables.tf` and
     wire `security_group_id` into their `agent_runner`/`response_handler` blocks.
- **Verify:** `terraform validate` (with `inject_dependencies.py` applied, then reverted) in the
  base + `scalable-openai` + `schedule-openai` deploy dirs — done during implementation, all three
  validate cleanly (same pre-existing provider deprecation warnings as Iteration 6, unrelated to
  this change). `python3 -c "import ast; ast.parse(...)"` on both touched scripts. A full
  `workflow_dispatch` run (`keep_resources_on_failure: true`) is still needed to confirm against
  real AWS credentials: the base's `terraform apply` succeeds with the new three-Lambda/queue shape,
  `get_base_outputs.py` prints non-null values for both new outputs, and `scalable-openai`/
  `schedule-openai`'s Deploy steps show `TF_VAR_agent_runner_security_group_id`/
  `TF_VAR_response_handler_security_group_id` pointing at the base's SGs rather than creating new
  ones (0 count for `aws_security_group.agent_runner`/`.response_handler` in their plans).
