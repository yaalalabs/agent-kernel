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
independently-toggleable SGs (`rest_service.alb_security_group_id`,
`rest_service.ecs_service_security_group_id`, `agent_runner.security_group_id`, nested fields on
the `rest_service`/`agent_runner` object variables per
`docs/specs/689-security-group-from-outside/design.md` § `containerized` root) instead of
serverless's one, so it needs its own requirements pass and is deliberately out of scope here.

**Amendment (post-implementation):** #689's serverless design (referenced throughout this document
as "one shared SG") was itself later amended — see
`docs/specs/689-security-group-from-outside/design.md`'s own Amendment — to split into **three**
per-tier SGs (`request_handler`, `agent_runner`, `response_handler` object fields, mirroring
`containerized`'s per-service split) instead of one root-level `security_group_id` shared by all
five Lambdas. This document's Phase 1 scope is unaffected in shape: the base deployment
(`examples/aws-serverless/openai`) never runs in `queue_mode`, so it only ever has a
`request_handler_security_group_id` to expose (its `agent_runner`/`response_handler` outputs are
`null` per #689's amended `outputs.tf`) — Phase 1 therefore reuses the request handler tier only
(also covering the authorizer and WebSocket connection handler Lambdas, which share that tier's SG).
The two queue-mode weekly examples (`scalable-openai`, `schedule-openai`) still create their own
`agent_runner`/`response_handler` SGs each run — there is nothing from the base to reuse for those
tiers. Every `security_group_id` name below is amended to `request_handler_security_group_id`
throughout (variable, output, CLI flag, env var) to make this scoping explicit; the underlying
plumbing shape (base output → job output → CLI flag → `TF_VAR_*`) is otherwise unchanged from the
original Phase 1 design.

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
- #689 already lands the serverless side of "bring your own SG" on this branch — **amended**
  post-implementation (see this document's own Amendment above) to three per-tier fields instead of
  one shared variable:
  - `ak-deployment/ak-aws/serverless/variables.tf` — `security_group_id = optional(string, null)`
    fields on the `request_handler`, `agent_runner`, and `response_handler` object variables ("If
    not provided, a new one will be created" per field).
  - `ak-deployment/ak-aws/serverless/state.tf` — three `aws_security_group` resources
    (`request_handler`, `agent_runner`, `response_handler`), each `count`-gated on its own field
    being `null`, replacing the single `aws_security_group.lambda`.
  - `ak-deployment/ak-aws/serverless/state.tf` — three locals
    (`request_handler_security_group_id`, `agent_runner_security_group_id`,
    `response_handler_security_group_id`) each resolve to their field's provided ID or their own
    created resource, replacing the single `local.security_group_id`.
  - `ak-deployment/ak-aws/serverless/outputs.tf` — three outputs
    (`request_handler_security_group_id` unconditional; `agent_runner_security_group_id` and
    `response_handler_security_group_id` both `null` when `queue_mode = false`) replace the single
    `security_group_id` output.
  - The five submodule call sites *were* rewired by #689's amendment (`authorizer` and
    `ws_connection_handler` → `local.request_handler_security_group_id`; `request_handler` → same;
    `agent_runner` → `local.agent_runner_security_group_id`; `response_handler` →
    `local.response_handler_security_group_id`) — unlike the original design, where no rewiring was
    needed since every call site read one shared local.
- **Every example project's `main.tf` pulls the module from the Terraform Registry**
  (`source = "yaalalabs/ak-serverless/aws"`, `version = "0.9.0"` — verified identical in all 9
  weekly `aws-serverless` matrix entries' `deploy/main.tf`), not from `ak-deployment/` directly.
  Registry version `0.9.0` predates #689 — the published `0.9.0` module has neither the original
  shared `security_group_id` variable nor the amended per-tier fields.
  - **CI is unaffected by this**: `scripts/deploy/inject_dependencies.py`, run as the "Inject
    dependencies" step in every job that touches an AWS/Azure/GCP deploy dir, rewrites every
    `module` block's `source = "yaalalabs/ak-serverless/aws"` to a relative path into
    `ak-deployment/ak-aws/serverless` and comments out its `version` line. Every CI deploy therefore
    already runs against the local, on-branch module source — including #689's amendment — regardless
    of the registry-published version.
  - **A real user is affected**: someone who clones the repo and runs an example's `deploy.sh`
    directly (without `inject_dependencies.py`) resolves the module from the registry at whatever
    version is pinned in that example's `main.tf`. Adding
    `security_group_id = var.request_handler_security_group_id` inside an example's
    `request_handler` block while `version = "0.9.0"` is still pinned would break `terraform init`
    for that path (`Unsupported argument` — the pinned module's `request_handler` object type
    doesn't declare the field), even though the same file works fine in CI. See Open questions.
- `run_single_test.py`'s `destroy_aws_resources` has a Lambda-SG ENI pre-sweep optimization:
  `_resolve_lambda_sg_ids` looks up SG IDs by the module's naming convention — amended to the three
  per-tier names (`{product_alias}-{env_alias}-{request-handler,agent-runner,response-handler}-sg`,
  read from that job's own `terraform.tfvars`) instead of the single `-lambda-sg` name — then
  `_delete_lambda_functions_on_sgs`/`_start_lambda_eni_sweeper` pre-delete Lambda functions and
  sweep detached ENIs so a SG isn't left blocking a `terraform destroy` waiting on ENI detachment.
  For a job whose request-handler tier is externally-provided, that name simply doesn't match
  (no `aws_security_group.request_handler[0]` exists in that job's state to delete), so the sweep is
  a no-op for that tier — expected, not a regression, exactly as the original design reasoned for
  the single shared SG. The two queue-mode examples' `agent_runner`/`response_handler` SGs are still
  self-created every run (Amendment above), so the sweeper still does useful work for those two
  tier names on every weekly run, unlike Phase 1's original all-tiers-reused assumption. See
  Non-goals.
- Issue benefits restated from #716: fewer SGs created per run, lower AWS account SG-limit risk
  (relevant because up to 9 serverless jobs currently each create their own Lambda SG concurrently),
  faster teardown, and CI validation of #689's serverless bring-your-own-SG path end-to-end.

## Requirements — Phase 1: AWS Serverless

**All `security_group_id` naming below is amended to `request_handler_security_group_id`** per this
document's Amendment — variable, output, CLI flag, and `TF_VAR_*` env var alike.

### `examples/aws-serverless/openai/deploy` (base deployment)

- `outputs.tf` gets a new output, alongside the existing `vpc_id`/`private_subnet_ids` outputs:
  ```hcl
  output "request_handler_security_group_id" {
    description = "Request handler security group ID used for the deployment (also used by the authorizer and WebSocket connection handler Lambdas)"
    value       = module.serverless_agents.request_handler_security_group_id
  }
  ```
- No change to the base's `main.tf` or `variables.tf` — the base always creates its own SGs (same as
  it always creates its own VPC/subnets today); it only needs to expose the request-handler tier's
  created SG ID. The base never sets `queue_mode = true`, so its module's
  `agent_runner_security_group_id`/`response_handler_security_group_id` outputs are always `null` —
  nothing to expose for those two tiers.

### `.github/scripts/get_base_outputs.py`

- Add a third retrieval alongside `vpc_id`/`private_subnet_ids`:
  `terraform output -raw request_handler_security_group_id` against the base deploy path.
- Write it to `$GITHUB_OUTPUT` alongside the other two:
  `request_handler_security_group_id=<value>`.
- Same script, same base deployment — no new CLI arguments needed (it already takes
  `--base-path`/`--deploy-dir`, generic to any output).

### `.github/workflows/integration-test-weekly.yaml`

- `get-base-outputs` job's `outputs:` map gets a third entry:
  `request_handler_security_group_id: ${{ steps.base-outputs.outputs.request_handler_security_group_id }}`.
- **Scoped to `aws-serverless` only** — unlike `--vpc-id`/`--private-subnet-ids`, which are passed
  for every `aws-*` matrix type (both serverless and containerized already accept `vpc_id`/
  `private_subnet_ids` per #689), the new `--request-handler-security-group-id` flag must be gated
  to `matrix.type == 'aws-serverless'` specifically: containerized's root module has no matching
  field (out of scope, Phase 2). Add a second, narrower conditional alongside the existing `aws-*`
  one, in both the Deploy step and the Destroy step:
  ```bash
  ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action deploy)
  if [[ "${{ matrix.type }}" == aws-* ]]; then
    ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
  fi
  if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
    ARGS+=(--request-handler-security-group-id "${{ needs.get-base-outputs.outputs.request_handler_security_group_id }}")
  fi
  python .github/scripts/run_single_test.py "${ARGS[@]}"
  ```
  (same pattern in the Destroy step, `--action destroy`).
- No change to the `deploy-openai` job (the base deployment) — it never receives `--vpc-id` /
  `--private-subnet-ids` today either, since it's the one creating them.

### `.github/scripts/run_single_test.py`

- `main()`'s argparse: add
  `parser.add_argument('--request-handler-security-group-id', default=None, help='Request handler security group ID from base deployment; sets TF_VAR_request_handler_security_group_id (used for aws-serverless jobs)')`,
  next to `--vpc-id`/`--private-subnet-ids`.
- `deploy_aws_resources`/`destroy_aws_resources` gain a fourth parameter,
  `request_handler_security_group_id: str = None`, mirroring the existing `vpc_id`/
  `private_subnet_ids` handling exactly:
  ```python
  if request_handler_security_group_id:
      tf_env['TF_VAR_request_handler_security_group_id'] = request_handler_security_group_id
      print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")
  ```
  placed alongside the existing `if vpc_id:` block in each function.
- `main()`'s calls to these two functions pass `args.request_handler_security_group_id` as the new
  fourth argument.
- These two functions stay type-agnostic (as they already are for `vpc_id`/`private_subnet_ids`,
  shared across `aws-containerized` and `aws-serverless`): Phase 1 relies entirely on the workflow
  only ever passing `--request-handler-security-group-id` for `aws-serverless` matrix entries
  (previous section) — `args.request_handler_security_group_id` stays `None` for
  `aws-containerized` jobs in Phase 1, so `TF_VAR_request_handler_security_group_id` is never set
  for them and nothing about containerized deploys changes.
- `_resolve_lambda_sg_ids`'s naming list is amended from the single `{product_alias}-{env_alias}-
  lambda-sg` to the three per-tier names — see Motivation.

### Example projects (`aws-serverless` weekly matrix entries)

Applies identically to all 9: `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,
openai-auth,schedule-openai}/deploy` and `examples/memory/{redis,valkey,dynamodb}/deploy`.

- `variables.tf`: add, alongside the existing `vpc_id`/`private_subnet_ids` block:
  ```hcl
  variable "request_handler_security_group_id" {
    description = "Request handler security group ID for Lambda deployment (also shared by the authorizer and WebSocket connection handler Lambdas)"
    type        = string
    default     = null
  }
  ```
  `default = null` (unlike `vpc_id`/`private_subnet_ids`, which have no default and are always
  supplied by the pipeline) — matches the underlying module's own nullable convention for this
  field (`ak-deployment/ak-aws/serverless/variables.tf`, `request_handler.security_group_id`) and
  keeps these examples deployable stand-alone (without the CI harness) without requiring a value.
- `main.tf`: add `security_group_id = var.request_handler_security_group_id` **inside** the
  `request_handler = { ... }` block (amended from the original design's top-level
  `security_group_id = var.security_group_id` module argument, since the underlying module no
  longer has a top-level field — the field now lives nested on `request_handler`, per #689's
  amendment).
- `memory/redis` and `memory/valkey` specifically: this only threads the **request handler** tier's
  SG through (also covering the authorizer and WebSocket connection handler Lambdas that share it).
  Their own ElastiCache/Redis or Valkey security groups (`ak-deployment/ak-aws/common/modules/redis`,
  `.../valkey`) are unaffected — #689 explicitly kept those out of scope, and this change doesn't
  touch them either.
- `scalable-openai` and `schedule-openai` specifically (both `queue_mode = true`): only their
  `request_handler` block gets the new field. Their `agent_runner`/`response_handler` blocks are
  unchanged — the base deployment has no SG to offer for those tiers (Amendment above), so those two
  Lambdas keep creating their own SG every weekly run, same as before this change.
- `vpc_id`/`private_subnet_ids` on these 9 examples have **no** default and are **required** inputs
  today, so a standalone `deploy.sh` run (e.g. a developer running it locally without the CI
  harness) already requires `-var vpc_id=... -var 'private_subnet_ids=[...]'` or equivalent today,
  with or without this change. This new `request_handler_security_group_id` variable is nullable
  specifically so it does **not** add a third mandatory input on top of the two that already exist.

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
- **The Lambda-SG ENI pre-sweep optimization in `run_single_test.py`** — amended to a one-line name
  update only (the three per-tier SG names replace the single `-lambda-sg` name, per Motivation);
  no change to its no-op-for-externally-provided-SGs behavior.
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
   There is no migration to avoid: Phase 1's flag maps 1:1 to one Lambda tier's SG, and Phase 2
   targets a structurally different module with different variable names (`rest_service.
   alb_security_group_id`, `rest_service.ecs_service_security_group_id`,
   `agent_runner.security_group_id`) — those will be new, additive flags in Phase 2 that don't touch
   or replace this one. A JSON-map flag would only trade a plain string CLI arg for one needing
   JSON-encoding/quoting (replicating the same fragility the pipeline already works around for
   `--private-subnet-ids`'s single-quoted `'${{ ... }}'`), for a migration risk that doesn't
   actually exist.
   **Amended premise, same conclusion**: at the time this was resolved, serverless itself had one
   shared `security_group_id` (per #689's original design). #689 was later amended to three per-tier
   fields, but Phase 1 here still only ever reuses one of them (`request_handler`, per this
   document's Amendment) — the flag stays singular either way, since the other two tiers
   (`agent_runner`, `response_handler`) have nothing to reuse from a `queue_mode = false` base.
3. ~~Should `memory/redis`/`memory/valkey` be in scope for Phase 1?~~ Yes, confirmed in scope —
   this only reuses their **request handler** tier's SG (amended from "the one all five serverless
   submodules share" per #689's original design — now one of three per-tier SGs, per this
   document's Amendment); their ElastiCache/Valkey infrastructure SGs are untouched (already noted
   in Requirements and Motivation).

No open questions remain. `spec.md`/`plan.md` are amended in place to match (see each document's own
Amendment note) rather than re-drafted from scratch.
