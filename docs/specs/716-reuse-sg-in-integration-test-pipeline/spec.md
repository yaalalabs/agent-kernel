# #716: Reuse security groups in the weekly AWS integration test pipeline — Implementation Spec (Phase 1: AWS Serverless)

Implements `design.md`'s Phase 1 section in this directory: thread the base `aws-serverless`
deployment's Lambda security group ID through the weekly integration test pipeline the same way
`vpc_id`/`private_subnet_ids` already flow today, so the 9 weekly `aws-serverless` matrix jobs stop
creating their own SG and reuse the base's. Phase 2 (AWS containerized) is out of scope for this
spec and will be added to this same document once designed.

**Amendment (post-implementation):** per `design.md`'s own Amendment, #689's serverless module was
later split into three per-tier SGs (`request_handler`, `agent_runner`, `response_handler`) instead
of one shared `security_group_id`. This spec is amended in place: every `security_group_id` name
below becomes `request_handler_security_group_id` (variable, output, CLI flag, `TF_VAR_*`), since
the base deployment never runs in `queue_mode` and so only ever has the request handler tier's SG
to share. The two queue-mode weekly examples (`scalable-openai`, `schedule-openai`) keep creating
their own `agent_runner`/`response_handler` SGs — nothing changes for those two tiers.

**Amendment 2 (post-implementation):** the base deployment (`examples/aws-serverless/openai`) is
converted to `queue_mode = true`, so it now exposes `agent_runner_security_group_id`/
`response_handler_security_group_id` too (previously always `null`). See `design.md`'s own
Amendment 2 and `## Requirements — Amendment 2` for the full design; this spec's Phase 1 sections
below (request-handler-tier-only reuse across all 9 examples) are unchanged and still accurate —
Amendment 2 only adds two more SG IDs, threaded the same way, and scoped to `scalable-openai`/
`schedule-openai` specifically (the only two examples with those tiers).

## Design

### Base deployment (`examples/aws-serverless/openai/deploy/outputs.tf`)

Add a third output, alongside the existing `vpc_id`/`private_subnet_ids`:

```hcl
output "request_handler_security_group_id" {
  description = "Request handler security group ID used for the deployment (also used by the authorizer and WebSocket connection handler Lambdas)"
  value       = module.serverless_agents.request_handler_security_group_id
}
```

No change to `main.tf` or `variables.tf` in this deploy dir — the base always creates its own SGs
(same as it always creates its own VPC/subnets);
`module.serverless_agents.request_handler_security_group_id` already resolves to the created SG's
ID today (per #689's amendment, `ak-deployment/ak-aws/serverless/outputs.tf`, since
`inject_dependencies.py` points this module block at the local, on-branch source during CI — see
design.md Motivation). The base never
sets `queue_mode = true`, so its module's `agent_runner_security_group_id`/
`response_handler_security_group_id` outputs are always `null` — nothing to expose for those tiers.

### `.github/scripts/get_base_outputs.py`

Add a third `terraform output` retrieval, mirroring `vpc_id`'s exactly:

```python
# Retrieve request_handler_security_group_id
result = subprocess.run(
    ["terraform", "output", "-raw", "request_handler_security_group_id"],
    cwd=str(deploy_path),
    check=True,
    capture_output=True,
    text=True,
)
request_handler_security_group_id = result.stdout.strip()
```

placed after the existing `private_subnet_ids` retrieval and before the
`json.loads(private_subnet_ids)` validation line.

Add it to the print block and the `$GITHUB_OUTPUT` write block:

```python
print(f"VPC ID: {vpc_id}")
print(f"Private Subnet IDs: {private_subnet_ids}")
print(f"Request Handler Security Group ID: {request_handler_security_group_id}")

github_output = os.environ.get("GITHUB_OUTPUT", "")
if github_output:
    with open(github_output, "a") as f:
        f.write(f"vpc_id={vpc_id}\n")
        f.write(f"private_subnet_ids={private_subnet_ids}\n")
        f.write(f"request_handler_security_group_id={request_handler_security_group_id}\n")
    print("Outputs written to $GITHUB_OUTPUT")
```

No new CLI arguments — `--base-path`/`--deploy-dir` (already generic) are unchanged.

### `.github/workflows/integration-test-weekly.yaml`

**`get-base-outputs` job** — add a third entry to `outputs:` (alongside `vpc_id`, `private_subnet_ids`):

```yaml
outputs:
  vpc_id: ${{ steps.base-outputs.outputs.vpc_id }}
  private_subnet_ids: ${{ steps.base-outputs.outputs.private_subnet_ids }}
  request_handler_security_group_id: ${{ steps.base-outputs.outputs.request_handler_security_group_id }}
```

**`run-tests` job, Deploy step** — add a second, narrower conditional so the new flag is only ever
passed for `aws-serverless` matrix entries (containerized's root module has no matching field —
Phase 2 scope):

```bash
ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action deploy)
# AWS deploys need the base VPC/subnets injected as terraform vars.
if [[ "${{ matrix.type }}" == aws-* ]]; then
  ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
fi
# aws-serverless deploys also reuse the base's request handler security group (Phase 1 of #716;
# also shared by the authorizer/WebSocket connection handler tier. The agent runner and response
# handler tiers still create their own SG per job, since the base deployment doesn't run in
# queue_mode and so has none to share. aws-containerized needs its own SG variables and is Phase 2,
# not wired here).
if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
  ARGS+=(--request-handler-security-group-id "${{ needs.get-base-outputs.outputs.request_handler_security_group_id }}")
fi
python .github/scripts/run_single_test.py "${ARGS[@]}"
```

**`run-tests` job, Destroy step** — identical second conditional, same placement, `--action destroy`:

```bash
ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action destroy)
if [[ "${{ matrix.type }}" == aws-* ]]; then
  ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
fi
if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
  ARGS+=(--request-handler-security-group-id "${{ needs.get-base-outputs.outputs.request_handler_security_group_id }}")
fi
python .github/scripts/run_single_test.py "${ARGS[@]}"
```

No change to the `deploy-openai` job (the base deployment) — it doesn't receive `--vpc-id`/
`--private-subnet-ids` today either, since it's the one creating them.

### `.github/scripts/run_single_test.py`

**`main()` argparse** — add, next to `--vpc-id`/`--private-subnet-ids`:

```python
parser.add_argument('--request-handler-security-group-id', default=None,
                     help='Request handler security group ID from base deployment; sets TF_VAR_request_handler_security_group_id (used for aws-serverless jobs)')
```

**`deploy_aws_resources`** — new fourth parameter and injection block, mirroring the existing
`vpc_id` handling exactly:

```python
def deploy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None,
                          private_subnet_ids: str = None, request_handler_security_group_id: str = None) -> bool:
    ...
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        print("\n✅ Injecting VPC configuration as Terraform variables:")
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if request_handler_security_group_id:
        tf_env['TF_VAR_request_handler_security_group_id'] = request_handler_security_group_id
        print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")
    if private_subnet_ids:
        ...
```

**`destroy_aws_resources`** — same fourth parameter, same injection block shape, placed alongside
the existing `if vpc_id:` block:

```python
def destroy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None,
                           private_subnet_ids: str = None, request_handler_security_group_id: str = None) -> bool:
    ...
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if request_handler_security_group_id:
        tf_env['TF_VAR_request_handler_security_group_id'] = request_handler_security_group_id
        print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")
    if private_subnet_ids:
        ...
```

**`main()` call sites** — pass the new argument through:

```python
# deploy:
success = deploy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.request_handler_security_group_id)
# destroy:
success = destroy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.request_handler_security_group_id)
```

Both functions stay type-agnostic (as `vpc_id`/`private_subnet_ids` already are, shared across
`aws-containerized` and `aws-serverless` calls to the same two functions) — Phase 1 relies entirely
on the workflow only ever passing `--request-handler-security-group-id` for `aws-serverless` matrix
entries. For `aws-containerized` jobs, `args.request_handler_security_group_id` stays `None` (the
workflow never sets it for that type in Phase 1), so `TF_VAR_request_handler_security_group_id` is
never set and neither function's behavior changes for containerized jobs.

**`_resolve_lambda_sg_ids`** — amended: its naming list changes from the single
`{product_alias}-{env_alias}-lambda-sg` to the three per-tier names, so the destroy-time ENI
pre-sweep still finds the `agent_runner`/`response_handler` SGs that `scalable-openai`/
`schedule-openai` keep self-creating every run (the `request_handler` name simply won't match for a
job whose request-handler tier is externally-provided, same no-op-by-name-mismatch behavior the
original design relied on):

```python
sg_names = [
    f"{product_alias}-{env_alias}-request-handler-sg",
    f"{product_alias}-{env_alias}-agent-runner-sg",
    f"{product_alias}-{env_alias}-response-handler-sg",
]
```

See Behavioural changes for the full reasoning.

### Example projects (9 `aws-serverless` weekly-matrix examples)

Applies identically to: `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,
schedule-openai}/deploy` and `examples/memory/{redis,valkey,dynamodb}/deploy`. Verified byte-for-byte
identical `vpc_id`/`private_subnet_ids` variable block across all 9.

`variables.tf` — add, immediately after the existing `private_subnet_ids` block:

```hcl
variable "request_handler_security_group_id" {
  description = "Request handler security group ID for Lambda deployment (also shared by the authorizer and WebSocket connection handler Lambdas)"
  type        = string
  default     = null
}
```

`default = null` — unlike `vpc_id`/`private_subnet_ids` (no default, required inputs today), so this
new variable doesn't add a third mandatory input to a project run standalone without the CI harness
(see Behavioural changes, item 4).

`main.tf` — **amended**: add `security_group_id = var.request_handler_security_group_id` **inside**
the `request_handler = { ... }` block (not as a top-level `module "serverless_agents"` argument —
the original design's `security_group_id = var.security_group_id` top-level line no longer applies,
since #689's amendment removed the module's top-level `security_group_id` variable entirely in
favor of a nested field per Lambda tier). For all 9 files, this lands as one new line inside the
existing `request_handler = { ... }` block, matching that block's own alignment style. For
`scalable-openai` and `schedule-openai` (`queue_mode = true`), only the `request_handler` block
gets this line — their `agent_runner`/`response_handler` blocks are untouched, since the base has
no SG to offer for those tiers (Design § Requirements, Example projects).

`memory/redis` and `memory/valkey`: this only threads the **request handler** tier's SG through
(also covering the authorizer and WebSocket connection handler Lambdas that share it). Their own
ElastiCache/Valkey security groups (`ak-deployment/ak-aws/common/modules/redis`, `.../valkey`) are
untouched — out of scope in #689 and unaffected here.

### Consumer changes

| File | Change |
|---|---|
| `examples/aws-serverless/openai/deploy/outputs.tf` | + `request_handler_security_group_id` output |
| `.github/scripts/get_base_outputs.py` | + `request_handler_security_group_id` retrieval, print, `$GITHUB_OUTPUT` write |
| `.github/workflows/integration-test-weekly.yaml` | `get-base-outputs` job: + `request_handler_security_group_id` output; `run-tests` Deploy/Destroy steps: + `aws-serverless`-scoped `--request-handler-security-group-id` arg |
| `.github/scripts/run_single_test.py` | + `--request-handler-security-group-id` CLI flag; `deploy_aws_resources`/`destroy_aws_resources` gain a 4th param and `TF_VAR_request_handler_security_group_id` injection; both call sites in `main()` updated; `_resolve_lambda_sg_ids`'s naming list amended to the three per-tier names |
| `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,schedule-openai}/deploy/{variables.tf,main.tf}` | + nullable `request_handler_security_group_id` variable; passed into the `request_handler` object (nested field, not a top-level module argument) |
| `examples/memory/{redis,valkey,dynamodb}/deploy/{variables.tf,main.tf}` | same as above |
| `ak-deployment/ak-aws/serverless/*` | **unchanged** — #689 (amended) already implemented this (design.md Motivation) |
| `.github/scripts/validate_integration_config.py`, `.github/integration-test-config.yaml`, `.github/scripts/generate_test_matrix.py` | **unchanged** — no new YAML schema field; the base's SG ID flows through job outputs and CLI flags only, the same mechanism `vpc_id`/`private_subnet_ids` already use |
| `examples/aws-containerized/*`, any `aws-containerized` workflow branch | **unchanged** — Phase 2 |
| Azure/GCP example projects and workflow branches | **unchanged** — out of scope |

### Config changes

None to `AKConfig`, any `config.yaml`, or any `AK_*` environment variable injected into the
deployed application containers/Lambdas — this change is entirely CI-pipeline plumbing and
Terraform input variables:

- New Terraform input variable `request_handler_security_group_id` (`string`, default `null`) on 9
  example deploy dirs, following the exact shape of `ak-deployment/ak-aws/serverless/variables.tf`'s
  own `request_handler.security_group_id` field that it forwards to.
- New CLI flag `--request-handler-security-group-id` on `.github/scripts/run_single_test.py`,
  following the exact shape of the existing `--vpc-id` flag.
- New GitHub Actions job output `request_handler_security_group_id` on the `get-base-outputs` job.

### Behavioural changes

1. **New optional Terraform input, default-preserving.** All 9 examples' new
   `request_handler_security_group_id` variable defaults to `null`. A `terraform plan`/`apply` run
   without it set (any standalone use outside this pipeline) shows no diff — same SG-creation
   behavior as today, since the underlying module's own `request_handler.security_group_id == null`
   branch is unchanged (#689, already implemented).
2. **New capability**: the 9 weekly `aws-serverless` matrix jobs stop creating their own
   request-handler-tier SG and instead reuse the base (`examples/aws-serverless/openai`)
   deployment's — mirroring the existing VPC/subnet-reuse behavior exactly. Up to 9 jobs that
   previously each created one SG for this tier now share the one SG the base already created; net
   request-handler-tier SG count for a full weekly run's serverless portion drops from up to 10
   (base + 9) to 1. The two queue-mode examples (`scalable-openai`, `schedule-openai`) still create
   their own `agent_runner`/`response_handler` SGs every run — unaffected by this change, since the
   base has none of those to share (Design § Base deployment).
3. **`_resolve_lambda_sg_ids`/`_delete_lambda_functions_on_sgs`/`_start_lambda_eni_sweeper` change
   behavior per-tier, not uniformly**: `_resolve_lambda_sg_ids`'s naming list is amended to the
   three per-tier names. For the 9 jobs' `request_handler` tier (now externally-provided), no SG is
   created under `{product_alias}-{env_alias}-request-handler-sg`, so that name simply doesn't
   match and the sweep is a no-op for it — not a regression, since `terraform destroy` never
   attempts to delete a SG it doesn't own either way (same reasoning the original design used for
   the single shared SG). For `scalable-openai`/`schedule-openai`'s `agent_runner`/
   `response_handler` tiers, those SGs are still self-created every run, so the sweeper still finds
   and sweeps them under their own per-tier names — this is *new* useful coverage the original
   design's single `-lambda-sg` name never provided for those two tiers specifically (that name
   matched all five Lambdas' one shared SG, so it worked for every tier by construction; the amended
   three-name list restores equivalent per-tier coverage). The base deployment (which owns the
   request-handler-tier SG) is never destroyed by this pipeline (`deploy-openai` job has no destroy
   step) — the optimization stays relevant there, unaffected by this change.
4. **No new mandatory input.** The 9 examples' existing `vpc_id`/`private_subnet_ids` variables have
   no default (required) today; this design's new `request_handler_security_group_id` variable is
   nullable, so these examples remain deployable with the exact same required-input surface as
   before this change, whether or not a caller supplies it.
5. **`aws-containerized` matrix jobs are entirely unaffected.** The workflow's new
   `--request-handler-security-group-id` conditional is scoped to `matrix.type == "aws-serverless"`
   only; no containerized example, workflow branch, or `run_single_test.py` call path changes.

**Non-changes**: `ak-deployment/ak-aws/serverless/*` (already implements the underlying toggle per
#689's amendment); `.github/integration-test-config.yaml`'s schema; `generate_test_matrix.py`;
`validate_integration_config.py`; any Azure/GCP path; the `nightly` tier (no AWS infra deploy there).

## Error handling

- **Base's `request_handler_security_group_id` output doesn't exist in the base deployment's state
  yet** (e.g. the base was applied before this change, so its state predates the new `outputs.tf`
  block): this isn't reachable in the pipeline, because the `get-base-outputs` job depends on
  `deploy-openai`, which re-applies the base — with the new `outputs.tf` in place — before
  `get_base_outputs.py` ever runs `terraform output`. This assumes the base apply succeeds. If the
  output were ever missing at read time regardless, `terraform output -raw
  request_handler_security_group_id` exits non-zero (`Output "request_handler_security_group_id"
  not found`), and matching the existing `vpc_id` handling, `get_base_outputs.py`'s
  `subprocess.run(..., check=True)` raises `CalledProcessError` and fails the `get-base-outputs`
  job — no new error handling needed.
- **Empty string passed as `--request-handler-security-group-id`**: `run_single_test.py`'s
  `if request_handler_security_group_id:` check treats an empty string as falsy (same as the
  existing `if vpc_id:` check), so `TF_VAR_request_handler_security_group_id` is simply not set —
  matches existing `vpc_id` behavior byte-for-byte, no new edge case introduced.
- **Provided SG doesn't exist / wrong VPC**: not validated by this change, matches #689's own
  non-validation of `vpc_id`/`security_group_id` at the Terraform level — surfaces as a standard AWS
  API error at `terraform apply` (e.g. Lambda `vpc_config` creation fails with
  `InvalidSecurityGroupID.NotFound` or a similar AWS-reported error).
- **A matrix job's `terraform destroy` with an externally-provided request-handler-tier SG**: no
  `aws_security_group.request_handler` resource exists in that job's state for the SG, so
  `terraform destroy` simply never attempts to delete it — no error path, matches how
  `vpc_id`/`private_subnet_ids` reuse already behaves for the VPC/subnets today. The
  `agent_runner`/`response_handler` resources are unaffected (still created, still deleted
  normally) for the two queue-mode examples.

## Testing

This repo has no Terraform unit-test framework and `.github/scripts/*.py` has no existing pytest
suite (confirmed: no `.github/scripts/test_*.py` or similar exists) — verification here follows the
same pattern #689's spec used for its own (deferred) CI-matrix scenario:

1. **Static checks** (no AWS credentials needed):
   - `terraform fmt -check -recursive` and `terraform validate` are unaffected in
     `ak-deployment/ak-aws/serverless` (no changes there) — re-run only to confirm no accidental
     edits.
   - `terraform validate` in each of the 9 touched example `deploy/` directories (and the base,
     `examples/aws-serverless/openai/deploy`), after running
     `python3 scripts/deploy/inject_dependencies.py` locally (so the module source resolves to
     `ak-deployment/ak-aws/serverless`, which already has the per-tier `security_group_id` fields
     per #689's amendment) — confirms the new variable/pass-through is syntactically valid against
     the module that will actually run in CI. Verified during implementation: all 10 dirs validate
     (one dir, `memory/redis`, hit an unrelated local provider-cache miss for a pinned `aws`
     provider version — not a validity failure of this change).
   - `python3 -c "import ast; ast.parse(open('.github/scripts/run_single_test.py').read())"` (or
     equivalent) and `python3 -c "..."` for `get_base_outputs.py` — both files must still parse;
     no linter is configured for `.github/scripts/` today (not part of `make lint-check-all`'s
     `ak-py`/`examples` scope), so this is the practical syntax check available.
2. **Manual dry run** (needs AWS credentials against the dev account, matching how #689's spec
   deferred its own CI-matrix verification to a real run):
   - Run `get_base_outputs.py --base-path examples/aws-serverless/openai --deploy-dir deploy`
     against the existing base deployment's remote state; confirm
     `request_handler_security_group_id` prints and is written to `$GITHUB_OUTPUT` (or stdout, if
     run outside Actions).
   - Run `run_single_test.py --type aws-serverless --path examples/aws-serverless/adk --action
     deploy --vpc-id <base vpc> --private-subnet-ids '<base subnets>'
     --request-handler-security-group-id <base sg>` and confirm via `terraform plan`/`apply` output
     that `aws_security_group.request_handler` shows 0 count for that job and the request handler
     (plus authorizer/`ws_connection_handler`) Lambda submodules' `vpc_config.security_group_ids`
     resolves to the base's SG ID, not a newly created one.
   - Repeat against `scalable-openai` or `schedule-openai` and confirm
     `aws_security_group.agent_runner`/`aws_security_group.response_handler` still show count 1
     (self-created) even with `--request-handler-security-group-id` set — only the request-handler
     tier reuses the base's SG.
   - Run the matching `--action destroy` and confirm it completes without attempting to delete the
     `aws_security_group.request_handler` resource (none exists in that job's state) and without
     needing the ENI-sweeper path for that name (no match — see Behavioural changes item 3 — this
     is the expected, not the erroring, path).
3. **Full CI run**: dispatch `integration-test-weekly.yaml` via `workflow_dispatch`
   (`keep_resources_on_failure: true` for easier debugging on first run) and confirm, per matrix
   job of type `aws-serverless`:
   - The Deploy step's log shows `TF_VAR_request_handler_security_group_id=<base sg id>` printed
     (per the new `print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")`
     line).
   - The `aws-containerized` matrix jobs' logs show **no**
     `TF_VAR_request_handler_security_group_id` line — confirms the type-scoping in the workflow
     conditional is correctly excluding them.
   - Test and Destroy steps for the `aws-serverless` jobs succeed as they do today (no functional
     regression from removing each job's own request-handler-tier SG creation).
