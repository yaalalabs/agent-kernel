# #716: Reuse security groups in the weekly AWS integration test pipeline — Implementation Spec (Phase 1: AWS Serverless)

Implements `design.md`'s Phase 1 section in this directory: thread the base `aws-serverless`
deployment's Lambda security group ID through the weekly integration test pipeline the same way
`vpc_id`/`private_subnet_ids` already flow today, so the 9 weekly `aws-serverless` matrix jobs stop
creating their own SG and reuse the base's. Phase 2 (AWS containerized) is out of scope for this
spec and will be added to this same document once designed.

## Design

### Base deployment (`examples/aws-serverless/openai/deploy/outputs.tf`)

Add a third output, alongside the existing `vpc_id`/`private_subnet_ids` (`outputs.tf:6-14`):

```hcl
output "security_group_id" {
  description = "Security group ID used for the deployment"
  value       = module.serverless_agents.security_group_id
}
```

No change to `main.tf` or `variables.tf` in this deploy dir — the base always creates its own SG
(same as it always creates its own VPC/subnets); `module.serverless_agents.security_group_id`
already resolves to the created SG's ID today (per #689, `ak-deployment/ak-aws/serverless/outputs.tf:43-46`,
since `inject_dependencies.py` points this module block at the local, on-branch source during CI —
see design.md Motivation).

### `.github/scripts/get_base_outputs.py`

Add a third `terraform output` retrieval, mirroring `vpc_id`'s exactly (`get_base_outputs.py:49-57`):

```python
# Retrieve security_group_id
result = subprocess.run(
    ["terraform", "output", "-raw", "security_group_id"],
    cwd=str(deploy_path),
    check=True,
    capture_output=True,
    text=True,
)
security_group_id = result.stdout.strip()
```

placed after the existing `private_subnet_ids` retrieval (currently ending at line 67) and before
the `json.loads(private_subnet_ids)` validation line (line 70).

Add it to the print block (currently lines 72-73) and the `$GITHUB_OUTPUT` write block (currently
lines 76-81):

```python
print(f"VPC ID: {vpc_id}")
print(f"Private Subnet IDs: {private_subnet_ids}")
print(f"Security Group ID: {security_group_id}")

github_output = os.environ.get("GITHUB_OUTPUT", "")
if github_output:
    with open(github_output, "a") as f:
        f.write(f"vpc_id={vpc_id}\n")
        f.write(f"private_subnet_ids={private_subnet_ids}\n")
        f.write(f"security_group_id={security_group_id}\n")
    print("Outputs written to $GITHUB_OUTPUT")
```

No new CLI arguments — `--base-path`/`--deploy-dir` (already generic) are unchanged.

### `.github/workflows/integration-test-weekly.yaml`

**`get-base-outputs` job** — add a third entry to `outputs:` (currently `vpc_id`, `private_subnet_ids`
at lines 161-163):

```yaml
outputs:
  vpc_id: ${{ steps.base-outputs.outputs.vpc_id }}
  private_subnet_ids: ${{ steps.base-outputs.outputs.private_subnet_ids }}
  security_group_id: ${{ steps.base-outputs.outputs.security_group_id }}
```

**`run-tests` job, Deploy step** (currently lines 288-294) — add a second, narrower conditional so
the new flag is only ever passed for `aws-serverless` matrix entries (containerized's root module
has no matching singular `security_group_id` variable — Phase 2 scope):

```bash
ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action deploy)
# AWS deploys need the base VPC/subnets injected as terraform vars.
if [[ "${{ matrix.type }}" == aws-* ]]; then
  ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
fi
# aws-serverless deploys also reuse the base's Lambda security group (Phase 1 of #716;
# aws-containerized needs three separate SG variables and is Phase 2, not wired here).
if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
  ARGS+=(--security-group-id "${{ needs.get-base-outputs.outputs.security_group_id }}")
fi
python .github/scripts/run_single_test.py "${ARGS[@]}"
```

**`run-tests` job, Destroy step** (currently lines 330-335) — identical second conditional, same
placement, `--action destroy`:

```bash
ARGS=(--type ${{ matrix.type }} --path ${{ matrix.path }} --deploy-dir ${{ matrix.deploy_dir }} --action destroy)
if [[ "${{ matrix.type }}" == aws-* ]]; then
  ARGS+=(--vpc-id "${{ needs.get-base-outputs.outputs.vpc_id }}" --private-subnet-ids '${{ needs.get-base-outputs.outputs.private_subnet_ids }}')
fi
if [[ "${{ matrix.type }}" == "aws-serverless" ]]; then
  ARGS+=(--security-group-id "${{ needs.get-base-outputs.outputs.security_group_id }}")
fi
python .github/scripts/run_single_test.py "${ARGS[@]}"
```

No change to the `deploy-openai` job (the base deployment) — it doesn't receive `--vpc-id`/
`--private-subnet-ids` today either, since it's the one creating them.

### `.github/scripts/run_single_test.py`

**`main()` argparse** (currently lines 752-763) — add, next to `--vpc-id`/`--private-subnet-ids`:

```python
parser.add_argument('--security-group-id', default=None,
                     help='Security group ID from base deployment (aws-serverless only in Phase 1)')
```

**`deploy_aws_resources`** (`run_single_test.py:637-686`) — new fourth parameter and injection
block, mirroring the existing `vpc_id` handling exactly (currently lines 656-661):

```python
def deploy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None,
                          private_subnet_ids: str = None, security_group_id: str = None) -> bool:
    ...
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        print("\n✅ Injecting VPC configuration as Terraform variables:")
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if security_group_id:
        tf_env['TF_VAR_security_group_id'] = security_group_id
        print(f"   TF_VAR_security_group_id={security_group_id}")
    if private_subnet_ids:
        ...
```

**`destroy_aws_resources`** (`run_single_test.py:572-634`) — same fourth parameter, same injection
block shape, placed alongside the existing `if vpc_id:` block (currently lines 590-594):

```python
def destroy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None,
                           private_subnet_ids: str = None, security_group_id: str = None) -> bool:
    ...
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if security_group_id:
        tf_env['TF_VAR_security_group_id'] = security_group_id
        print(f"   TF_VAR_security_group_id={security_group_id}")
    if private_subnet_ids:
        ...
```

**`main()` call sites** — pass the new argument through:

```python
# line 771 (deploy):
success = deploy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.security_group_id)
# line 781 (destroy):
success = destroy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.security_group_id)
```

Both functions stay type-agnostic (as `vpc_id`/`private_subnet_ids` already are, shared across
`aws-containerized` and `aws-serverless` calls to the same two functions) — Phase 1 relies entirely
on the workflow only ever passing `--security-group-id` for `aws-serverless` matrix entries. For
`aws-containerized` jobs, `args.security_group_id` stays `None` (the workflow never sets it for
that type in Phase 1), so `TF_VAR_security_group_id` is never set and neither function's behavior
changes for containerized jobs.

No changes to `_resolve_lambda_sg_ids`, `_delete_lambda_functions_on_sgs`, or
`_start_lambda_eni_sweeper` (`run_single_test.py:496-569`) — see Behavioural changes.

### Example projects (9 `aws-serverless` weekly-matrix examples)

Applies identically to: `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,
schedule-openai}/deploy` and `examples/memory/{redis,valkey,dynamodb}/deploy`. Verified byte-for-byte
identical `vpc_id`/`private_subnet_ids` variable block (`variables.tf:32-40`) across all 9.

`variables.tf` — add, immediately after the existing `private_subnet_ids` block:

```hcl
variable "security_group_id" {
  description = "Security group ID for Lambda deployment"
  type        = string
  default     = null
}
```

`default = null` — unlike `vpc_id`/`private_subnet_ids` (no default, required inputs today), so this
new variable doesn't add a third mandatory input to a project run standalone without the CI harness
(see Behavioural changes, item 4).

`main.tf` — add `security_group_id = var.security_group_id` to the `module "serverless_agents"`
block, immediately after the existing `private_subnet_ids = var.private_subnet_ids` line. Exact
insertion point per file (verified):

| File | Line to insert after |
|---|---|
| `examples/aws-serverless/adk/deploy/main.tf` | line 13 (`private_subnet_ids   = var.private_subnet_ids`) |
| `examples/aws-serverless/crewai/deploy/main.tf` | line 13 |
| `examples/aws-serverless/langgraph/deploy/main.tf` | line 13 |
| `examples/aws-serverless/scalable-openai/deploy/main.tf` | line 15 |
| `examples/aws-serverless/openai-auth/deploy/main.tf` | line 14 |
| `examples/aws-serverless/schedule-openai/deploy/main.tf` | line 16 |
| `examples/memory/redis/deploy/main.tf` | line 14 |
| `examples/memory/valkey/deploy/main.tf` | line 14 |
| `examples/memory/dynamodb/deploy/main.tf` | line 14 |

Each insertion uses that file's own existing alignment spacing for the `=` (they differ slightly —
e.g. `vpc_id               = var.vpc_id` in `adk` vs. `vpc_id                       = var.vpc_id` in
`memory/dynamodb`); match the surrounding block's alignment, don't introduce a new style.

`memory/redis` and `memory/valkey`: this only threads the shared **Lambda** SG through (the same
`security_group_id` all five Lambda submodules already share per #689). Their own ElastiCache/Valkey
security groups (`ak-deployment/ak-aws/common/modules/redis`, `.../valkey`) are untouched — out of
scope in #689 and unaffected here.

### Consumer changes

| File | Change |
|---|---|
| `examples/aws-serverless/openai/deploy/outputs.tf` | + `security_group_id` output |
| `.github/scripts/get_base_outputs.py` | + `security_group_id` retrieval, print, `$GITHUB_OUTPUT` write |
| `.github/workflows/integration-test-weekly.yaml` | `get-base-outputs` job: + `security_group_id` output; `run-tests` Deploy/Destroy steps: + `aws-serverless`-scoped `--security-group-id` arg |
| `.github/scripts/run_single_test.py` | + `--security-group-id` CLI flag; `deploy_aws_resources`/`destroy_aws_resources` gain a 4th param and `TF_VAR_security_group_id` injection; both call sites in `main()` updated |
| `examples/aws-serverless/{adk,crewai,langgraph,scalable-openai,openai-auth,schedule-openai}/deploy/{variables.tf,main.tf}` | + nullable `security_group_id` variable; passed into `module "serverless_agents"` |
| `examples/memory/{redis,valkey,dynamodb}/deploy/{variables.tf,main.tf}` | same as above |
| `ak-deployment/ak-aws/serverless/*` | **unchanged** — #689 already implemented this (design.md Motivation) |
| `.github/scripts/validate_integration_config.py`, `.github/integration-test-config.yaml`, `.github/scripts/generate_test_matrix.py` | **unchanged** — no new YAML schema field; the base's SG ID flows through job outputs and CLI flags only, the same mechanism `vpc_id`/`private_subnet_ids` already use |
| `.github/scripts/run_single_test.py`'s `_resolve_lambda_sg_ids`/`_delete_lambda_functions_on_sgs`/`_start_lambda_eni_sweeper` | **unchanged** — degrades to a no-op for bring-your-own-SG jobs (Behavioural changes) |
| `examples/aws-containerized/*`, any `aws-containerized` workflow branch | **unchanged** — Phase 2 |
| Azure/GCP example projects and workflow branches | **unchanged** — out of scope |

### Config changes

None to `AKConfig`, any `config.yaml`, or any `AK_*` environment variable injected into the
deployed application containers/Lambdas — this change is entirely CI-pipeline plumbing and
Terraform input variables:

- New Terraform input variable `security_group_id` (`string`, default `null`) on 9 example deploy
  dirs, following the exact shape of `ak-deployment/ak-aws/serverless/variables.tf:110-114`'s own
  `security_group_id` variable that it forwards to.
- New CLI flag `--security-group-id` on `.github/scripts/run_single_test.py`, following the exact
  shape of the existing `--vpc-id` flag.
- New GitHub Actions job output `security_group_id` on the `get-base-outputs` job.

### Behavioural changes

1. **New optional Terraform input, default-preserving.** All 9 examples' new `security_group_id`
   variable defaults to `null`. A `terraform plan`/`apply` run without it set (any standalone use
   outside this pipeline) shows no diff — same SG-creation behavior as today, since the underlying
   module's own `security_group_id == null` branch is unchanged (#689, already implemented).
2. **New capability**: the 9 weekly `aws-serverless` matrix jobs stop creating their own Lambda SG
   and instead reuse the base (`examples/aws-serverless/openai`) deployment's SG — mirroring the
   existing VPC/subnet-reuse behavior exactly. Up to 9 jobs that previously each created one SG now
   share the one SG the base already created; net SG count for a full weekly run's serverless
   portion drops from up to 10 (base + 9) to 1.
3. **`_resolve_lambda_sg_ids`/`_delete_lambda_functions_on_sgs`/`_start_lambda_eni_sweeper`
   (`run_single_test.py:496-569`) become a no-op for these 9 jobs' destroy runs**, with no code
   change needed: `_resolve_lambda_sg_ids` looks up SGs by that job's own
   `{product_alias}-{env_alias}-lambda-sg` naming convention (read from that job's own
   `terraform.tfvars`); once the job's SG is externally-provided, no such SG is created under that
   name, so the lookup returns `[]` and the sweep is skipped. This is not a regression: the SG
   deletion this optimization exists to unblock (`terraform destroy` blocking on ENI detachment
   before an owned SG can be deleted) no longer happens for these jobs either — they have no
   `aws_security_group.lambda[0]` resource in their own state to delete, since the reused SG isn't
   theirs to delete. Net effect on destroy time is expected to be neutral-to-faster, not slower.
   The base deployment (which does own the SG) is never destroyed by this pipeline (`deploy-openai`
   job has no destroy step) — the optimization stays relevant there, unaffected by this change.
4. **No new mandatory input.** The 9 examples' existing `vpc_id`/`private_subnet_ids` variables have
   no default (required) today; this design's new `security_group_id` variable is nullable, so
   these examples remain deployable with the exact same required-input surface as before this
   change, whether or not a caller supplies `security_group_id`.
5. **`aws-containerized` matrix jobs are entirely unaffected.** The workflow's new
   `--security-group-id` conditional is scoped to `matrix.type == "aws-serverless"` only; no
   containerized example, workflow branch, or `run_single_test.py` call path changes.

**Non-changes**: `ak-deployment/ak-aws/serverless/*` (already implements the underlying toggle per
#689); `.github/integration-test-config.yaml`'s schema; `generate_test_matrix.py`;
`validate_integration_config.py`; any Azure/GCP path; the `nightly` tier (no AWS infra deploy there).

## Error handling

- **Base's `security_group_id` output is empty or the base deployment's state doesn't have it yet**
  (e.g. base was deployed before this change, so its state predates the new output): `terraform
  output -raw security_group_id` returns an empty string rather than failing (Terraform's `-raw`
  behavior for a defined-but-not-yet-refreshed output is to compute it fresh via the `terraform
  init` already run in `get_base_outputs.py`, since outputs are derived from current state/config,
  not cached — so this only fails if the output block itself doesn't exist in the *code* being
  read, not if the base hasn't re-applied). No new error handling is added beyond what
  `get_base_outputs.py` already does for `vpc_id` (a `subprocess.run(..., check=True)` raises
  `CalledProcessError` and fails the job if the output doesn't exist at all) — matches existing
  practice.
- **Empty string passed as `--security-group-id`**: `run_single_test.py`'s `if security_group_id:`
  check treats an empty string as falsy (same as the existing `if vpc_id:` check), so
  `TF_VAR_security_group_id` is simply not set — matches existing `vpc_id` behavior byte-for-byte,
  no new edge case introduced.
- **Provided SG doesn't exist / wrong VPC**: not validated by this change, matches #689's own
  non-validation of `vpc_id`/`security_group_id` at the Terraform level — surfaces as a standard AWS
  API error at `terraform apply` (e.g. Lambda `vpc_config` creation fails with
  `InvalidSecurityGroupID.NotFound` or a similar AWS-reported error).
- **A matrix job's `terraform destroy` with an externally-provided SG**: no `aws_security_group`
  resource exists in that job's state for the SG, so `terraform destroy` simply never attempts to
  delete it — no error path, matches how `vpc_id`/`private_subnet_ids` reuse already behaves for
  the VPC/subnets today.

## Testing

This repo has no Terraform unit-test framework and `.github/scripts/*.py` has no existing pytest
suite (confirmed: no `.github/scripts/test_*.py` or similar exists) — verification here follows the
same pattern #689's spec used for its own (deferred) CI-matrix scenario:

1. **Static checks** (no AWS credentials needed):
   - `terraform fmt -check -recursive` and `terraform validate` are unaffected in
     `ak-deployment/ak-aws/serverless` (no changes there) — re-run only to confirm no accidental
     edits.
   - `terraform validate` in each of the 9 touched example `deploy/` directories, after running
     `python3 scripts/deploy/inject_dependencies.py` locally (so the module source resolves to
     `ak-deployment/ak-aws/serverless`, which already has `security_group_id` per #689) — confirms
     the new variable/pass-through is syntactically valid against the module that will actually run
     in CI.
   - `python3 -c "import ast; ast.parse(open('.github/scripts/run_single_test.py').read())"` (or
     equivalent) and `python3 -c "..."` for `get_base_outputs.py` — both files must still parse;
     no linter is configured for `.github/scripts/` today (not part of `make lint-check-all`'s
     `ak-py`/`examples` scope), so this is the practical syntax check available.
2. **Manual dry run** (needs AWS credentials against the dev account, matching how #689's spec
   deferred its own CI-matrix verification to a real run):
   - Run `get_base_outputs.py --base-path examples/aws-serverless/openai --deploy-dir deploy`
     against the existing base deployment's remote state; confirm `security_group_id` prints and is
     written to `$GITHUB_OUTPUT` (or stdout, if run outside Actions).
   - Run `run_single_test.py --type aws-serverless --path examples/aws-serverless/adk --action
     deploy --vpc-id <base vpc> --private-subnet-ids '<base subnets>' --security-group-id <base sg>`
     and confirm via `terraform plan`/`apply` output that `aws_security_group.lambda` shows 0 count
     for that job and every Lambda submodule's `vpc_config.security_group_ids` resolves to the
     base's SG ID, not a newly created one.
   - Run the matching `--action destroy` and confirm it completes without attempting to delete any
     `aws_security_group` resource (none exists in that job's state) and without needing the
     ENI-sweeper path (no SG name match — see Behavioural changes item 3 — this is the expected,
     not the erroring, path).
3. **Full CI run**: dispatch `integration-test-weekly.yaml` via `workflow_dispatch`
   (`keep_resources_on_failure: true` for easier debugging on first run) and confirm, per matrix
   job of type `aws-serverless`:
   - The Deploy step's log shows `TF_VAR_security_group_id=<base sg id>` printed (per the new
     `print(f"   TF_VAR_security_group_id={security_group_id}")` line).
   - The `aws-containerized` matrix jobs' logs show **no** `TF_VAR_security_group_id` line — confirms
     the type-scoping in the workflow conditional is correctly excluding them.
   - Test and Destroy steps for the `aws-serverless` jobs succeed as they do today (no functional
     regression from removing each job's own SG creation).
