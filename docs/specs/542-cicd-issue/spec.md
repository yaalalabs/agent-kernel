# #542: Fail loudly when integration tests can't use the branch-built agentkernel wheel — Implementation Spec

This spec details the change **as implemented and tested** on `bugfix/542-cicd`. It supersedes the
earlier plan (broad per-script normalization of every example `deploy.sh`/`build.sh`), which was
reverted during implementation in favour of a centralized fix in the integration harness. See
[`design.md`](./design.md) for requirements and rationale; [`research/issue_findings.md`](./research/issue_findings.md)
holds the original investigation.

The change is confined to CI/CD assets and deployment infrastructure — no `ak-py` source,
`AKConfig`, factory, or public-API changes. It spans four surfaces:

1. **Guard 1** — `fail-on-cache-miss: true` on six `actions/cache/restore@v5` steps across three
   workflows.
2. **Guard 2** — `.github/scripts/run_single_test.py`: install the branch wheel into the AWS test
   client's venv before `pytest`, and run `pytest` under `uv run --no-sync`; plus `--no-cache-dir`
   (replacing `|| true`) on the canonical `deploy.sh` template in the docs.
3. **Dependency fixes** — `examples/memory/valkey/pyproject.toml` + `uv.lock`.
4. **Guard 3** — API Gateway access logging made opt-in via `enable_api_gateway_logs` across the
   AWS serverless Terraform.

## Guard 1 — `fail-on-cache-miss` on the restore steps

`actions/cache/restore@v5` accepts a `fail-on-cache-miss` input; when `true` the step fails
immediately on a cache miss instead of continuing with `path` absent. One line is added inside the
`with:` block of each of the six restore steps that restore `ak-py/dist`:

```yaml
      - name: Restore ak-py build
        uses: actions/cache/restore@v5
        with:
          path: ak-py/dist
          key: ak-py-${{ github.sha }}          # or ${{ inputs.checkout_ref }} in test-reusable
          fail-on-cache-miss: true
```

Locations:

| Workflow | Restore steps (`with:` block) |
|---|---|
| `.github/workflows/integration-test.yaml` | 2 steps (`fail-on-cache-miss` added at `:91`, `:200`) |
| `.github/workflows/integration-test-weekly.yaml` | 2 steps |
| `.github/workflows/test-reusable.yaml` | 2 steps |

The `actions/cache/save@v5` steps in the build jobs are **not** changed — `fail-on-cache-miss` is a
restore-only input and saving must still succeed on a first build.

## Guard 2 — the AWS test client runs against the branch wheel

### `run_single_test.py` (`test_aws_deployment`)

The AWS deployment tests deploy from the local wheel but then run `pytest` from a **separate test
client venv**, which `uv run` re-syncs from `uv.lock` — pulling `agentkernel` from PyPI. Two edits
in `test_aws_deployment` close this:

1. **Force-reinstall the branch wheel into the client venv before testing.** After the endpoint is
   ready and before `pytest`, run `./build.sh local` in the example directory. `build.sh local`
   force-reinstalls `agentkernel` from `../../../ak-py/dist`, mirroring how `deploy.sh local` builds
   the deployment package:

   ```python
   # Install the LOCAL agentkernel wheel into the test client's venv before
   # running pytest. Without this, `uv run pytest` resolves agentkernel from
   # PyPI via uv.lock ...
   if not run_command(
       ['./build.sh', 'local'],
       cwd=path,
       description=f"Building {path} with local agentkernel",
       env=CREWAI_DISABLE_TRACE_ENV,
   ):
       return False
   ```

2. **Run `pytest` under `uv run --no-sync`.** `--no-sync` prevents `uv run` from re-syncing the venv
   from `uv.lock`, which would revert the force-reinstalled branch wheel back to the PyPI `0.6.1`
   (same version string, so a re-sync swaps it silently):

   ```python
   return run_command(
       ['uv', 'run', '--no-sync', 'pytest', '-s', '--junitxml=pytest-report.xml',
        '--ignore-glob=dist*', '--ignore-glob=.terraform'],
       cwd=path,
       description=f"Testing {path}",
       env=test_env,
   )
   ```

`run_command` runs every subprocess with `check=True`, so a failed `build.sh local` returns non-zero
and fails the step — the client never proceeds to `pytest` against a wrong or missing wheel.

### Canonical `deploy.sh` template (docs)

The reference AWS serverless `deploy.sh` documented in
[`docs/docs/deployment/aws-serverless.md`](../../docs/deployment/aws-serverless.md) has its five
force-reinstall local-wheel lines changed from a swallowed install to a loud, cache-bypassing one —
in each of the five packaging functions (main handler, request handler, agent runner, response
handler, ws connection handler):

```diff
- uv pip install --force-reinstall --target=<TARGET> --find-links ../../../ak-py/dist agentkernel[<EXTRAS>] || true
+ uv pip install --force-reinstall --target=<TARGET> --find-links ../../../ak-py/dist agentkernel[<EXTRAS>] --no-cache-dir
```

`--no-cache-dir` forces uv to install the wheel from `--find-links` rather than a cached
same-version `0.6.1`; dropping `|| true` lets a failed install propagate a non-zero exit.

### What was NOT changed (reverted)

The earlier plan's per-script edits to all 27 example `deploy/deploy.sh` and all 64 example
`build.sh` were reverted to `develop` (commit "revert: restore examples build.sh/deploy.sh to
develop"). The per-script change matrix from the earlier spec no longer applies. The centralized
harness fix above covers the surface the integration tests actually exercise without touching what
each Lambda artifact ships.

## Dependency fixes — `examples/memory/valkey`

Once the branch wheel is used, the `valkey` example surfaced two real, previously-masked failures.
Both are fixed in `examples/memory/valkey/pyproject.toml`; `uv.lock` re-resolves to match.

```diff
 dependencies = [
-    "agentkernel[openai,valkey]>=0.6.1"
+    "agentkernel[openai,valkey]>=0.6.1",
+    # The published agentkernel 0.6.1 does not declare a `valkey` extra (added after release),
+    # so `agentkernel[valkey]` resolves to nothing from PyPI. Require valkey directly so it is
+    # always installed into the Lambda deployment package.
+    "valkey>=6.0.0",
 ]

 [dependency-groups]
 dev = [
     "agentkernel[test]>=0.6.1",
+    # ragas imports langchain_community.chat_models.vertexai, removed in langchain-community 0.4.2
+    "langchain-community==0.4.1",
     ...
 ]
```

- **`valkey>=6.0.0`** — published `agentkernel 0.6.1` has no `valkey` extra, so `agentkernel[valkey]`
  installs nothing from PyPI. Requiring `valkey` directly guarantees it is in the deployment package.
- **`langchain-community==0.4.1`** — `ragas` (via the `test` extra) imports
  `langchain_community.chat_models.vertexai.ChatVertexAI`, removed in `langchain-community 0.4.2`.
  Pinning `0.4.1` keeps the import resolvable. (This is the ragas/langchain-community incompatibility
  the earlier spec flagged as out-of-scope; it is fixed here because the branch wheel now makes the
  test collectible.)
- **`uv.lock`** — re-resolves accordingly, notably `aiohttp` `3.14.1` → `3.14.2` and the associated
  Python-version constraint updates. `requires-python` (`>=3.12`) and the `agentkernel` pins are
  unchanged.

## Guard 3 — API Gateway access logging is opt-in

API Gateway access logging depends on the account-level `aws_api_gateway_account` CloudWatch Logs
role — a singleton per AWS account + region — which is not provisioned in the CI account, blocking
the serverless deploys. A new toggle makes logging opt-in.

### Root serverless module

- **`ak-deployment/ak-aws/serverless/variables.tf`** — new variable:

  ```hcl
  variable "enable_api_gateway_logs" {
    type        = bool
    description = "When true, creates the API Gateway CloudWatch account role/log groups and enables access logging for the REST and WebSocket API Gateways. Off by default."
    default     = false
  }
  ```

- **`ak-deployment/ak-aws/serverless/state.tf`**:
  - `module "shared_api_gateway_resources"` gains `count = var.enable_api_gateway_logs ? 1 : 0`, so
    the account role is only provisioned when logging is requested.
  - `module "api_gateway"` and `module "websocket_api_gateway"` each receive
    `enable_api_gateway_logs = var.enable_api_gateway_logs`.

### REST `api-gateway` module

- **`variables.tf`** — new `enable_api_gateway_logs` (bool, default `false`).
- **`main.tf`**:
  - `aws_cloudwatch_log_group.api_gateway` gains `count = var.enable_api_gateway_logs ? 1 : 0`.
  - the stage's `access_log_settings` becomes a `dynamic` block
    (`for_each = var.enable_api_gateway_logs ? [1] : []`), referencing
    `aws_cloudwatch_log_group.api_gateway[0].arn`.
- **`outputs.tf`** — the log-group ARN/name outputs return `null` when logging is disabled.
- **`README.md`** — documents the input and the singleton/destroy caveat.

### `websocket-api-gateway` module

- **`variables.tf`** — new `enable_api_gateway_logs` (bool, default `false`).
- **`main.tf`** — `stage_access_log_settings` **and** `stage_default_route_settings` are set to the
  configured object only when enabled, else `null`:

  ```hcl
  stage_default_route_settings = var.enable_api_gateway_logs ? { ... } : null
  stage_access_log_settings    = var.enable_api_gateway_logs ? { create_log_group = true, ... } : null
  ```

  `null` (not `{}`) is required: the upstream `terraform-aws-modules/apigateway-v2` module treats a
  non-null object as "enabled" and defaults `create_log_group` to `true`.
- **`outputs.tf`** — the log-group ARN/name outputs return `null` when logging is disabled.
- **`README.md`** — documents the input, the `null`-vs-`{}` subtlety, and that the other logging
  inputs only take effect when `enable_api_gateway_logs` is `true`.

## Config changes

None to `ak-py`. No `AKConfig` field, YAML key, `AK_*` env var, `pyproject.toml` version, or
`agentkernel` pin/extras change. The only new configuration surface is the Terraform
`enable_api_gateway_logs` variable (default `false`, backward compatible with existing behaviour
being off).

## Behavioural changes

Each is intended.

1. **Cache miss now fails the deploy/test job at the restore step** in all three workflows
   (Guard 1).
2. **The AWS test client imports the branch `agentkernel`.** `run_single_test.py` force-reinstalls
   the local wheel into the client venv (`build.sh local`) and runs `pytest` under
   `uv run --no-sync`, so the client no longer silently tests against PyPI's `0.6.1` (Guard 2).
3. **A failed local-wheel install fails the step** instead of being swallowed: `build.sh local`
   under `check=True`, and `--no-cache-dir` (replacing `|| true`) on the documented `deploy.sh`
   template (Guard 2).
4. **`examples/memory/valkey` collects and runs**: `valkey` is installed directly and the
   ragas/`langchain-community` import resolves (Dependency fixes).
5. **API Gateway access logging is off by default.** With `enable_api_gateway_logs` unset, no
   CloudWatch log group, access logging, or `aws_api_gateway_account` role is created, so deploys
   succeed in accounts without that singleton role. Setting it `true` restores logging (Guard 3).

**Non-changes** (explicit): the cache `save` steps and cache keys; the example `build.sh`/`deploy.sh`
scripts (reverted to `develop`); `run_single_test.py`'s non-AWS test paths; `ak-py` source and
version; `agentkernel` pins/extras; default behaviour of existing deployments beyond logging now
being opt-in.

## Testing

There is no `pytest` surface for workflow YAML or Terraform, so verification is static assertions
plus the exercised integration run.

**Static checks:**

1. `fail-on-cache-miss: true` present on all six restore steps, absent from the three save steps:
   ```bash
   grep -rn "fail-on-cache-miss" .github/workflows/{integration-test,integration-test-weekly,test-reusable}.yaml   # expect: 6 hits
   ```
2. `run_single_test.py` runs `./build.sh local` before `pytest` and uses `uv run --no-sync` in
   `test_aws_deployment`.
3. The documented `deploy.sh` template carries `--no-cache-dir` and no `|| true` on its
   force-reinstall lines:
   ```bash
   grep -n "force-reinstall" docs/docs/deployment/aws-serverless.md | grep "|| true"   # expect: no output
   ```
4. `enable_api_gateway_logs` is declared in the root and both api-gateway module `variables.tf`,
   threaded in `state.tf`, and gates the log group / access logging in each `main.tf`.

**Dynamic check — `build.sh` / test client (performed and passing):** with `VIRTUAL_ENV` unset (as
in CI), rebuild `ak-py` (`cd ak-py && ./build.sh`) so `ak-py/dist` holds the branch wheel, then in
`examples/memory/valkey` run `rm -rf .venv && ./build.sh local` followed by
`uv run --no-sync pytest --co`. The installed `.venv/.../agentkernel/core/config.py` `session.type`
pattern **includes `valkey`** (the branch wheel), and collection proceeds past both the previous
`session.type: valkey` `ValidationError` and the ragas/`langchain-community` import error.

**Integration run:** `integration-test-config.yaml` has its per-environment test entries enabled so
the suite exercises these paths end-to-end.
