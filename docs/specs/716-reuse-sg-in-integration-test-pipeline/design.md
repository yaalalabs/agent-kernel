# #716: Reuse security groups in the weekly AWS integration test pipeline

The weekly integration test pipeline already reuses one shared VPC/subnet pair (created by the
`aws-serverless` base deployment) across every AWS matrix job instead of letting each job create
its own. Following #689 (already implemented on this branch — see
`docs/specs/689-security-group-from-outside/`), the AWS Terraform modules now also accept an
externally-provided security group ID instead of always creating one. This change makes the
pipeline do for security groups what it already does for VPC/subnets: read the base deployment's
SG ID via `terraform output` and thread it through Deploy/Destroy for AWS matrix jobs, so those
jobs stop creating their own SGs.

**This document covers Phase 1 (AWS serverless) only.** Phase 2 (AWS containerized) will be added
to this same document as a separate section once Phase 1 is settled — containerized has three
independently-toggleable SGs (`alb_security_group_id`, `ecs_service_security_group_id`,
`agent_runner_security_group_id`, per `docs/specs/689-security-group-from-outside/design.md`
§ `containerized` root) instead of serverless's one, so it needs its own requirements pass and is
deliberately out of scope here.

## Motivation

- The weekly pipeline (`.github/workflows/integration-test-weekly.yaml`) already has a working
  VPC/subnet-reuse path to mirror:
  - `deployment_base` in `.github/integration-test-config.yaml:5-8` names one base deployment
    (`aws-serverless`, `examples/aws-serverless/openai`) that is deployed once per run and never
    destroyed by this pipeline (the `deploy-openai` job has no destroy step).
  - `get-base-outputs` job (`integration-test-weekly.yaml:158-193`) runs
    `.github/scripts/get_base_outputs.py`, which does `terraform output -raw vpc_id` /
    `terraform output -json private_subnet_ids` against the base deployment
    (`get_base_outputs.py:49-67`) and writes them to `$GITHUB_OUTPUT`
    (`get_base_outputs.py:76-81`); the job exposes them as job outputs
    (`integration-test-weekly.yaml:161-163`).
  - `run-tests`'s Deploy and Destroy steps pass `--vpc-id`/`--private-subnet-ids` into
    `run_single_test.py` for every `aws-*` matrix entry
    (`integration-test-weekly.yaml:288-294` deploy, `330-335` destroy).
  - `run_single_test.py`'s `deploy_aws_resources`/`destroy_aws_resources`
    (`run_single_test.py:572-686`) turn those into `TF_VAR_vpc_id`/`TF_VAR_private_subnet_ids`
    env vars for `terraform init`/`apply`/`destroy`.
  - Every `aws-serverless` example in the weekly matrix already declares `vpc_id` /
    `private_subnet_ids` input variables and forwards them into its own
    `module "serverless_agents"` call (verified identical shape — variable block at
    `variables.tf:32-40`, pass-through in `main.tf` — across all 9 weekly `aws-serverless` matrix
    entries: `adk`, `crewai`, `langgraph`, `scalable-openai`, `openai-auth`, `schedule-openai`,
    `memory/redis`, `memory/valkey`, `memory/dynamodb`; see
    `.github/integration-test-config.yaml:59-85`). The base itself (`examples/aws-serverless/openai`)
    declares neither — it always creates its own VPC/subnets, which is what the other jobs reuse.
- #689 already lands the serverless side of "bring your own SG" on this branch:
  - `ak-deployment/ak-aws/serverless/variables.tf:110-114` — new `security_group_id` (`string`,
    default `null`, "If not provided, a new one will be created"), one ID shared by all five Lambda
    submodules.
  - `ak-deployment/ak-aws/serverless/state.tf:92-93` — `aws_security_group.lambda` gets
    `count = var.security_group_id == null ? 1 : 0`.
  - `ak-deployment/ak-aws/serverless/state.tf:14` — `local.security_group_id` resolves to the
    provided ID or the created resource.
  - `ak-deployment/ak-aws/serverless/outputs.tf:43-46` — new `security_group_id` output exposing
    `local.security_group_id`.
  - None of the five submodule call sites needed changes (they already read `local.security_group_id`).
- **Every example project's `main.tf` pulls the module from the Terraform Registry**
  (`source = "yaalalabs/ak-serverless/aws"`, `version = "0.9.0"` — verified identical in all 9
  weekly `aws-serverless` matrix entries' `deploy/main.tf`), not from `ak-deployment/` directly.
  Registry version `0.9.0` predates #689 (`security_group_id` was added to
  `ak-deployment/ak-aws/serverless` in commit `97072383`, after the `0.9.0` version-bump commit
  `9c8fc424`) — the published `0.9.0` module does not have a `security_group_id` variable.
  - **CI is unaffected by this**: `scripts/deploy/inject_dependencies.py`, run as the "Inject
    dependencies" step in every job that touches an AWS/Azure/GCP deploy dir
    (`integration-test-weekly.yaml:122`, `190`, `265`), rewrites every `module` block's
    `source = "yaalalabs/ak-serverless/aws"` to a relative path into
    `ak-deployment/ak-aws/serverless` and comments out its `version` line
    (`inject_dependencies.py:262-319`). Every CI deploy therefore already runs against the local,
    on-branch module source — including whatever #689 changes are on the branch — regardless of
    the registry-published version.
  - **A real user is affected**: someone who clones the repo and runs an example's `deploy.sh`
    directly (without `inject_dependencies.py`) resolves the module from the registry at whatever
    version is pinned in that example's `main.tf`. Adding
    `security_group_id = var.security_group_id` to an example's `module "serverless_agents"` block
    while `version = "0.9.0"` is still pinned would break `terraform init` for that path (`Unsupported
    argument` — the pinned module doesn't declare the variable), even though the same file works
    fine in CI. See Open questions.
- `run_single_test.py`'s `destroy_aws_resources` (`run_single_test.py:572-634`) has a Lambda-SG ENI
  pre-sweep optimization: `_resolve_lambda_sg_ids` (`run_single_test.py:496-515`) looks up SG IDs by
  the module's naming convention (`{product_alias}-{env_alias}-lambda-sg`, read from that job's own
  `terraform.tfvars`), then `_delete_lambda_functions_on_sgs`/`_start_lambda_eni_sweeper`
  (`517-569`) pre-delete Lambda functions and sweep detached ENIs so the SG isn't left blocking a
  `terraform destroy` waiting on ENI detachment. Once a job's SG is externally-provided, that job's
  own `terraform destroy` never attempts to delete an SG at all (no `aws_security_group.lambda[0]`
  in that job's state), so this optimization's `_resolve_lambda_sg_ids` naturally returns `[]` for
  such jobs (no SG matches `{this-job's-product_alias}-{this-job's-env_alias}-lambda-sg`, since no
  such SG is created) and the sweep is skipped as a no-op — this is expected, not a regression: the
  SG deletion the sweeper exists to unblock no longer happens for that job either. See Non-goals.
- Issue benefits restated from #716: fewer SGs created per run, lower AWS account SG-limit risk
  (relevant because up to 9 serverless jobs currently each create their own Lambda SG concurrently),
  faster teardown, and CI validation of #689's serverless bring-your-own-SG path end-to-end.

## Requirements — Phase 1: AWS Serverless

### `examples/aws-serverless/openai/deploy` (base deployment)

- `outputs.tf` gets a new output, alongside the existing `vpc_id`/`private_subnet_ids` outputs
  (`outputs.tf:6-14`):
  ```hcl
  output "security_group_id" {
    description = "Security group ID used for the deployment"
    value       = module.serverless_agents.security_group_id
  }
  ```
- No change to the base's `main.tf` or `variables.tf` — the base always creates its own SG (same as
  it always creates its own VPC/subnets today); it only needs to expose the created SG's ID.

### `.github/scripts/get_base_outputs.py`

- Add a third retrieval alongside `vpc_id`/`private_subnet_ids` (`get_base_outputs.py:49-67`):
  `terraform output -raw security_group_id` against the base deploy path.
- Write it to `$GITHUB_OUTPUT` alongside the other two (`get_base_outputs.py:76-81`):
  `security_group_id=<value>`.
- Same script, same base deployment — no new CLI arguments needed (it already takes
  `--base-path`/`--deploy-dir`, generic to any output).

### `.github/workflows/integration-test-weekly.yaml`

- `get-base-outputs` job's `outputs:` map (`integration-test-weekly.yaml:161-163`) gets a third
  entry: `security_group_id: ${{ steps.base-outputs.outputs.security_group_id }}`.
- **Scoped to `aws-serverless` only** — unlike `--vpc-id`/`--private-subnet-ids`, which are passed
  for every `aws-*` matrix type (both serverless and containerized already accept `vpc_id`/
  `private_subnet_ids` per #689), the new `--security-group-id` flag must be gated to
  `matrix.type == 'aws-serverless'` specifically: containerized's root module doesn't have a
  matching singular `security_group_id` variable (it has three — out of scope, Phase 2). Add a
  second, narrower conditional alongside the existing `aws-*` one, in both the Deploy step
  (`integration-test-weekly.yaml:288-294`) and the Destroy step (`330-335`):
  ```bash
  ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action deploy)
  if [[ "${{ matrix.type }}" == aws-* ]]; then
    ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
  fi
  if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
    ARGS+=(--security-group-id "${{ needs.get-base-outputs.outputs.security_group_id }}")
  fi
  python .github/scripts/run_single_test.py "${ARGS[@]}"
  ```
  (same pattern in the Destroy step, `--action destroy`).
- No change to the `deploy-openai` job (the base deployment) — it never receives `--vpc-id` /
  `--private-subnet-ids` today either, since it's the one creating them.

### `.github/scripts/run_single_test.py`

- `main()`'s argparse (`run_single_test.py:752-763`): add
  `parser.add_argument('--security-group-id', default=None, help='Security group ID from base deployment (aws-serverless only in Phase 1)')`,
  next to `--vpc-id`/`--private-subnet-ids` (`760-761`).
- `deploy_aws_resources`/`destroy_aws_resources` (`run_single_test.py:572-686`) gain a fourth
  parameter, `security_group_id: str = None`, mirroring the existing `vpc_id`/`private_subnet_ids`
  handling exactly:
  ```python
  if security_group_id:
      tf_env['TF_VAR_security_group_id'] = security_group_id
      print(f"   TF_VAR_security_group_id={security_group_id}")
  ```
  placed alongside the existing `if vpc_id:` block in each function (`590-594` destroy, `656-661`
  deploy).
- `main()`'s calls to these two functions (`771` deploy, `781` destroy) pass `args.security_group_id`
  as the new fourth argument.
- These two functions stay type-agnostic (as they already are for `vpc_id`/`private_subnet_ids`,
  shared across `aws-containerized` and `aws-serverless`): Phase 1 relies entirely on the workflow
  only ever passing `--security-group-id` for `aws-serverless` matrix entries (previous section) —
  `args.security_group_id` stays `None` for `aws-containerized` jobs in Phase 1, so
  `TF_VAR_security_group_id` is never set for them and nothing about containerized deploys changes.
- No change to `_resolve_lambda_sg_ids`/`_delete_lambda_functions_on_sgs`/
  `_start_lambda_eni_sweeper` (`496-569`) — per Motivation, this becomes a natural no-op for
  bring-your-own-SG jobs and needs no special-casing.

### Example projects (`aws-serverless` weekly matrix entries)

Applies identically to all 9: `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,
openai-auth,schedule-openai}/deploy` and `examples/memory/{redis,valkey,dynamodb}/deploy`.

- `variables.tf`: add, alongside the existing `vpc_id`/`private_subnet_ids` block
  (`variables.tf:32-40`, identical across all 9):
  ```hcl
  variable "security_group_id" {
    description = "Security group ID for Lambda deployment"
    type        = string
    default     = null
  }
  ```
  `default = null` (unlike `vpc_id`/`private_subnet_ids`, which have no default and are always
  supplied by the pipeline) — matches `security_group_id`'s own nullable convention in the
  underlying module (`ak-deployment/ak-aws/serverless/variables.tf:110-114`) and keeps these
  examples deployable stand-alone (without the CI harness) without requiring a value.
- `main.tf`: add `security_group_id = var.security_group_id` to the `module "serverless_agents"`
  block, alongside the existing `vpc_id = var.vpc_id` / `private_subnet_ids = var.private_subnet_ids`
  lines.
- `memory/redis` and `memory/valkey` specifically: this only threads the shared **Lambda** SG
  through (the same `security_group_id` the module already uses for all five Lambda submodules per
  #689). Their own ElastiCache/Redis or Valkey security groups
  (`ak-deployment/ak-aws/common/modules/redis`, `.../valkey`) are unaffected — #689 explicitly kept
  those out of scope, and this change doesn't touch them either.
- Every example keeps working with **no value supplied** (e.g. a developer running `deploy.sh`
  locally without the CI harness) exactly as it does today for `vpc_id`/`private_subnet_ids` when
  those aren't supplied — wait, `vpc_id`/`private_subnet_ids` on these 9 examples have **no**
  default and are **required** inputs today (`variables.tf:32-40` has no `default =` line), so a
  standalone `deploy.sh` run for these already requires `-var vpc_id=... -var
  'private_subnet_ids=[...]'` or equivalent today, with or without this change. This new
  `security_group_id` variable is nullable specifically so it does **not** add a third mandatory
  input on top of the two that already exist.

## Non-goals — Phase 1

- **AWS containerized** — entirely deferred to Phase 2 (three independent SG variables at the
  containerized root vs. serverless's one; separate requirements pass).
- **Azure / GCP** — out of scope; #689 and this issue are AWS-only.
- **Bumping the `yaalalabs/ak-serverless/aws` registry version pin** in any example's `main.tf`.
  That happens only through the existing `Publish` workflow (`.github/workflows/publish.yaml`:
  version bump → `sync-terraform.yaml` → registry publish → automated `chore: update terraform
  module versions to ...` bot commit across every example, per commit `9c8fc424` as precedent) —
  never hand-edited in a feature PR. See Open questions for the sequencing this implies.
- **Redis/Valkey infrastructure SGs** — out of scope, per #689; unaffected by this change (previous
  section).
- **The Lambda-SG ENI pre-sweep optimization in `run_single_test.py`** — no code changes; per
  Motivation, it degrades gracefully to a no-op for bring-your-own-SG jobs without needing any.
- **Validation that the base-provided SG ID is well-formed or reachable** — matches #689's own
  non-goal (no plan-time validation of `vpc_id`/`security_group_id`); a bad ID surfaces as a normal
  AWS API error at `terraform apply`.
- **`nightly` tier / non-AWS example types** — the `nightly` tier's `api`/`memory`/`cli` test types
  don't deploy AWS infra at all (`.github/integration-test-config.yaml:10-32`); untouched.

## Open questions

All three questions raised in the previous review cycle are now resolved:

1. ~~Registry-release sequencing?~~ Resolved as: proceed with Phase 1 as designed, don't gate
   these changes on a registry release. A new `yaalalabs/ak-serverless/aws` version (containing
   #689) will be published through the normal release process before this branch merges to
   `develop` regardless of this issue, so the window where an example's pinned registry version
   lacks `security_group_id` is not expected to reach `develop` in practice. CI itself was never
   affected either way (Motivation).
2. ~~Should Phase 1's `--security-group-id` flag be reshaped into a JSON-map flag now, to avoid a
   migration when Phase 2 adds containerized's three SG IDs?~~ No — kept as a singular flag.
   There is no migration to avoid: Phase 1's flag maps 1:1 to serverless's one shared
   `security_group_id` variable (confirmed one SG per #689), and Phase 2 targets a structurally
   different module with different variable names (`alb_security_group_id`,
   `ecs_service_security_group_id`, `agent_runner_security_group_id`) — those will be new,
   additive flags in Phase 2 that don't touch or replace this one. A JSON-map flag would only trade
   a plain string CLI arg for one needing JSON-encoding/quoting (replicating the same fragility the
   pipeline already works around for `--private-subnet-ids`'s single-quoted `'${{ ... }}'`), for a
   migration risk that doesn't actually exist.
3. ~~Should `memory/redis`/`memory/valkey` be in scope for Phase 1?~~ Yes, confirmed in scope —
   this only reuses their **Lambda** SG (the one all five serverless submodules share per #689);
   their ElastiCache/Valkey infrastructure SGs are untouched (already noted in Requirements and
   Motivation).

No open questions remain. Ready for `spec.md` once this design is confirmed as final.
