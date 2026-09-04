# #716: Reuse security groups in the weekly AWS integration test pipeline — Implementation Plan (Phase 1: AWS Serverless)

Phase 2 (AWS containerized) is not planned here — it will get its own iterations once designed.

## Iteration 1: Base deployment exposes its security group ID

- **Goal:** `examples/aws-serverless/openai/deploy` outputs the SG ID it already creates, so it's
  readable via `terraform output` exactly like `vpc_id`/`private_subnet_ids` already are.
- **Files:** `examples/aws-serverless/openai/deploy/outputs.tf`
- **Steps:**
  1. Add the `security_group_id` output (spec.md § Base deployment).
- **Verify:** `terraform validate` in this deploy dir (after `python3 scripts/deploy/inject_dependencies.py`
  so the module source resolves locally); `terraform output -raw security_group_id` against the
  base's existing remote state returns a non-empty SG ID.

## Iteration 2: Example projects accept a reusable security group

- **Goal:** each of the 9 weekly `aws-serverless` matrix examples can accept an externally-provided
  SG ID and forward it into its own module call; unset behaves exactly as today (module still
  creates its own SG).
- **Files:** `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,schedule-openai}/deploy/{variables.tf,main.tf}`,
  `examples/memory/{redis,valkey,dynamodb}/deploy/{variables.tf,main.tf}`
- **Steps:**
  1. Add the nullable `security_group_id` variable to each `variables.tf` (spec.md § Example
     projects).
  2. Add `security_group_id = var.security_group_id` to each `main.tf`'s `module
     "serverless_agents"` block, at the file-specific line noted in spec.md's insertion table,
     matching that file's existing alignment style.
- **Verify:** `terraform validate` in each of the 9 deploy dirs (after `inject_dependencies.py`);
  `terraform plan` with no `security_group_id` set shows zero diff (create-path unchanged) in at
  least one representative example (`adk`).

## Iteration 3: `get_base_outputs.py` retrieves the security group ID

- **Goal:** the script that already surfaces `vpc_id`/`private_subnet_ids` to `$GITHUB_OUTPUT` does
  the same for `security_group_id`.
- **Files:** `.github/scripts/get_base_outputs.py`
- **Steps:**
  1. Add the `terraform output -raw security_group_id` retrieval, print line, and `$GITHUB_OUTPUT`
     write (spec.md § `get_base_outputs.py`).
- **Verify:** run the script directly against the base deployment's existing state
  (`python3 .github/scripts/get_base_outputs.py --base-path examples/aws-serverless/openai
  --deploy-dir deploy`, with `GITHUB_OUTPUT` unset so it just prints); confirm `Security Group ID:
  <sg-id>` prints alongside the existing VPC/subnet lines. Depends on Iteration 1's output existing.

## Iteration 4: `run_single_test.py` threads the security group ID into Terraform

- **Goal:** a new `--security-group-id` CLI flag sets `TF_VAR_security_group_id` for both deploy and
  destroy, exactly like `--vpc-id` already does.
- **Files:** `.github/scripts/run_single_test.py`
- **Steps:**
  1. Add the `--security-group-id` argparse entry in `main()` (spec.md § `run_single_test.py`).
  2. Add the fourth `security_group_id` parameter and `TF_VAR_security_group_id` injection block to
     `deploy_aws_resources` and `destroy_aws_resources`.
  3. Update both call sites in `main()` to pass `args.security_group_id` through.
- **Verify:** `python3 -c "import ast; ast.parse(open('.github/scripts/run_single_test.py').read())"`
  parses cleanly; manually invoke
  `run_single_test.py --type aws-serverless --path examples/aws-serverless/adk --action deploy
  --vpc-id <base vpc> --private-subnet-ids '<base subnets>' --security-group-id <base sg>` against a
  scratch/dev deployment and confirm the log prints `TF_VAR_security_group_id=<base sg>` and the
  resulting `terraform plan`/`apply` shows `aws_security_group.lambda` at 0 count with the module's
  Lambda submodules resolving to the provided SG. Depends on Iteration 2 (example accepts the var).

## Iteration 5: Wire the workflow end-to-end

- **Goal:** the weekly pipeline's `get-base-outputs` job exposes `security_group_id`, and Deploy/Destroy
  steps pass `--security-group-id` for `aws-serverless` matrix entries only.
- **Files:** `.github/workflows/integration-test-weekly.yaml`
- **Steps:**
  1. Add `security_group_id` to the `get-base-outputs` job's `outputs:` map (spec.md § workflow).
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
  9 examples).
- The manual dry run from Iterations 3-4 (deploy + destroy against a real `aws-serverless` example
  with the base's actual outputs).
- A full `workflow_dispatch` run of `integration-test-weekly.yaml` (`keep_resources_on_failure: true`
  for easier first-run debugging), confirming:
  - Every `aws-serverless` matrix job's Deploy step log shows `TF_VAR_security_group_id=<base sg>`.
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
- No module README changes — `ak-deployment/ak-aws/serverless` itself is unchanged (#689 already
  landed it); this plan only touches CI scripts/workflow and example `deploy/` dirs, none of which
  have their own README documenting `vpc_id`-equivalent inputs.
- Before merge, run `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` against the
  branch's actual diff to catch anything this plan missed.
