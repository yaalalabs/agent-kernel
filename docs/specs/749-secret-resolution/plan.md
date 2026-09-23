# #749: Resolve secrets from the environment, falling back to a managed store — Implementation Plan

Ordering only; the *how* lives in [`spec.md`](spec.md). Nine iterations, each leaving the branch
green. The capability lands before the cloud backend, the cloud backend before Terraform, and
Terraform before the examples that consume it.

Repo-wide gates that run at the end of every iteration:

```bash
cd ak-py && uv run pytest        # no regressions
make lint-check-all
```

## Iteration 1: Configuration block

- **Goal:** `AKConfig.get().secret` exists with its defaults and reads `AK_SECRET__*`; nothing
  consumes it yet.
- **Files:** `ak-py/src/agentkernel/core/config.py`, `ak-py/tests/test_config.py`
- **Steps:**
  1. Add `_SecretProviderConfig` and `_SecretConfig` after `_SandboxConfig` (`config.py:786`), per
     spec.md § Config changes.
  2. Add the `secret` field to `AKConfig` between `sandbox` (`:919`) and `execution` (`:920`).
  3. Add the `test_config.py` cases for the defaults, the three `AK_SECRET__*` variables, and a
     negative `AK_SECRET__CACHE_TTL` rejected at load.
- **Verify:** `uv run pytest tests/test_config.py`

## Iteration 2: Capability core — provider ABC, cache, manager, factory, `env` provider

- **Goal:** `SecretManager.current().get("OPENAI_API_KEY")` resolves through environment → cache →
  provider — a set, non-empty variable always wins, `""` is a miss — with the default `env` provider
  or a dotted-path one. No cloud dependency anywhere in
  the package.
- **Files:** new `ak-py/src/agentkernel/secret/{__init__,base,errors,cache,manager,factory}.py`,
  `secret/providers/{__init__,env}.py`; new `ak-py/tests/test_secret_manager.py`,
  `ak-py/tests/test_secret_factory.py`
- **Steps:**
  1. `errors.py`, then `base.py` (the `SecretProvider` ABC only), then `cache.py` — spec.md
     §§ `secret/errors.py`, `secret/base.py`, `secret/cache.py`.
  2. `providers/env.py`.
  3. `factory.py` — `SecretProviderFactory` with the `env` branch and the dotted-path branch; leave
     the `aws_ssm` branch for Iteration 4. No manager factory.
  4. `manager.py` — the concrete `SecretManager`: `from_config`, `current()`/`reset()` reading
     `AKConfig.get().secret`, key validation, the lock-free environment → cache → provider `_resolve`
     (provider called outside any lock; `SecretCache` owns the write lock),
     `invalidate`/`clear`. No `inject` — the manager never writes `os.environ`.
  5. `__init__.py` exports (no `AWSSMSecretProvider`, no `testing`).
  6. Tests: the test-local `_DictSecretProvider`, then everything in spec.md § Testing for
     `test_secret_manager.py` (order, key-carried-through, grammar, sentinel, `get` never writes `os.environ`, cache TTL
     boundaries, `invalidate`/`clear`, concurrent cold reads, no lock across the provider call,
     re-entrancy, singleton) and the non-`aws_ssm` half of
     `test_secret_factory.py` (including `noop`/`in_memory`/`awssm` rejected as unknown).
- **Verify:** `uv run pytest tests/test_secret_manager.py tests/test_secret_factory.py`

## Iteration 3: Provider contract suite

- **Goal:** The reusable provider conformance suite exists and the dependency-free providers pass it —
  so the cloud backend in Iteration 4 is written *against* the contract, not retrofitted to it.
- **Files:** new `ak-py/src/agentkernel/secret/testing.py`, new
  `ak-py/tests/test_secret_providers.py`
- **Steps:**
  1. `SecretProviderContract` with the one declared flag (`reads_environment`), per spec.md
     § `secret/testing.py`. No manager contract suite.
  2. Subclass for `env` (declares `reads_environment`, seeds via `monkeypatch.setenv`) and for the
     test-local `_DictSecretProvider`.
- **Verify:** `uv run pytest tests/test_secret_providers.py`

## Iteration 4: `aws_ssm` provider

- **Goal:** `secret.provider.type: aws_ssm` resolves `OPENAI_API_KEY` from
  `/ak/{prefix}/openai_api_key`.
- **Files:** new `ak-py/src/agentkernel/secret/providers/aws_ssm.py`,
  `ak-py/src/agentkernel/secret/factory.py`, `ak-py/tests/test_secret_providers.py`,
  `ak-py/tests/test_secret_factory.py`
- **Steps:**
  1. `AWSSMSecretProvider`: prefix normalization and validation, `_compose_path`, lazy
     `Lock`-guarded client, the `ClientError`/`BotoCoreError` mapping in spec.md § Exception scope.
  2. Add the `aws_ssm` factory branch inside `require_extra("aws", "secret.provider.type: aws_ssm")`.
  3. `TestAWSSMProviderContract` against a fake boto3 client, plus the direct addressing,
     error-mapping and lazy-client cases.
  4. Factory cases: the `aws`-extra `ImportError` (and that it fires *before* the empty-prefix
     `AKConfigError`), and that `env` and a dotted-path provider build with an empty prefix.
- **Verify:** `uv run pytest tests/test_secret_providers.py tests/test_secret_factory.py`

## Iteration 5: Terraform — AWS serverless

- **Goal:** `ssm_enabled = true` injects `AK_SECRET__PREFIX` and grants `ssm:GetParameter` on all
  four Lambda tiers; `false` produces a byte-for-byte unchanged plan.
- **Files:** `ak-deployment/ak-aws/serverless/{variables.tf,state.tf,README.md}` and, under
  `serverless/modules/`, `request-handler`, `agent-runner`, `response-handler`,
  `ws-connection-handler` (`main.tf` + `variables.tf` each)
- **Steps:**
  1. Root `ssm_enabled` variable (`variables.tf`, beside `enable_scheduling` at `:181`); pass it into
     the four module blocks (`state.tf:521`, `:544`, `:628`, `:694`).
  2. Per module: `ssm_enabled` variable, the `AK_SECRET__PREFIX` conditional in the env merge, and
     the `count`-gated policy + attachment — spec.md § Deployment changes. `ws-connection-handler`
     additionally needs its `main.tf:9` assignment turned into a `merge(...)`.
  3. README variables-table row (mirroring `README.md:471`).
- **Verify:** `terraform init -backend=false && terraform validate` in `serverless/`; `terraform plan`
  on an existing deployment with `ssm_enabled` unset shows no diff.

## Iteration 6: Terraform — AWS containerized

- **Goal:** the same, for the two ECS tiers. Separate from Iteration 5 because the submodule set and
  the IAM attachment mechanism differ.
- **Files:** `ak-deployment/ak-aws/containerized/{variables.tf,rest_service.tf,queue_mode.tf,README.md}`
  and, under `containerized/modules/`, `rest-service`, `agent-runner` (`main.tf` + `variables.tf` each)
- **Steps:**
  1. Root `ssm_enabled` variable (beside `enable_scheduling` at `variables.tf:137`); pass it into
     `rest_service.tf:4` and `queue_mode.tf:23`.
  2. `rest-service`: `AK_SECRET__PREFIX` in `locals.rest_service_environment`, policy resource, and an
     `SSMSecret` entry in the `tasks_iam_role_policies` map (`main.tf:328-338`).
  3. `agent-runner`: `AK_SECRET__PREFIX` in `locals.agent_runner_environment`, policy resource, and a
     `count`-gated attachment to `aws_iam_role.agent_runner_task_role` (`main.tf:62`).
  4. README variables-table row (mirroring `README.md:368`).
- **Verify:** `terraform init -backend=false && terraform validate` in `containerized/`; empty plan
  with the flag unset.

## Iteration 7: Examples

- **Goal:** one serverless and one containerized example resolve their key from SSM when
  `openai_api_key` is left empty, and behave exactly as today when it is set, as #749's acceptance
  criteria require.
- **Files:** `examples/aws-serverless/openai/{config.yaml,lambda_agent_runner.py,README.md,deploy/main.tf,deploy/variables.tf}`;
  `examples/aws-containerized/openai-dynamodb-scalable/{config.yaml,app_agent_runner.py,README.md,deploy/main.tf,deploy/variables.tf}`
- **Steps:**
  1. Per example: `ssm_enabled = true`; **keep** the `OPENAI_API_KEY = var.openai_api_key` entries and
     give `openai_api_key` `default = ""`; add the `secret:` block with `provider.type: aws_ssm`; and
     call `set_default_openai_key(SecretManager.current().get("OPENAI_API_KEY"))` at the top of the
     agent-runner entrypoint, so an SSM-resolved key reaches the SDK in memory, never via
     `os.environ` — spec.md § Examples and docs.
  2. READMEs: make the `TF_VAR_openai_api_key` step optional and document both paths — set it
     (environment wins) or leave it unset after `aws ssm put-parameter` — show the
     `OPENAI_API_KEY` → `/ak/<prefix>/openai_api_key` correspondence, and document rotation.
  3. No CI matrix edit: the integration workflows already export `TF_VAR_openai_api_key`, so both
     examples stay green on the environment path.
- **Verify:** `make lint-check-all`; both `deploy/main.tf` files `terraform validate` **after** the
  module version pin is bumped by the release flow (spec.md § Examples and docs — the examples pin
  published modules at `0.9.1`, so this step cannot be validated end to end before that release);
  then deploy each example twice — variable set, variable empty — and confirm the agent answers both
  times.

## Iteration 8: Cross-component tests and regression pass

- **Goal:** the assertions that need every provider present, plus a clean full-suite and lint run.
- **Files:** `ak-py/tests/test_secret_manager.py`, `ak-py/tests/test_secret_factory.py`
- **Steps:**
  1. The environment wins for **every** provider — `env`, `aws_ssm` seeded with a different value
     (the fake client records no `get_parameter` call), and a seeded dotted-path
     `_DictSecretProvider` (zero provider calls) — and a `""` variable reaches `aws_ssm`.
  2. `SecretProviderFactory.create(config)` never calls `AKConfig.get()`, asserted loudly (the
     `tests/test_pipeline_factory_seams.py` pattern).
  3. A dotted-path provider is built through its own `from_config` and receives the whole `secret`
     block, including `prefix`.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all`, both clean.

## Iteration 9: Sync docs and skills

Run `ak-dev-sync-skills-from-branch` and `ak-dev-sync-docs-from-branch` before merge; the surfaces
below are what this change invalidates, verified against the branch.

**Dev skills (`.agents/skills/`) — updates required**

| File / line | Change |
|---|---|
| `ak-dev-architecture/SKILL.md:45` | Add `SecretProvider` to the list of existing pluggable ABCs (`SecretManager` is concrete, not pluggable) |
| `ak-dev-architecture/SKILL.md:266` | Add `secret` to AKConfig's "Key sections" list |
| `ak-dev-architecture/SKILL.md:899-907` | Add a `secret/` block to the Directory Structure, after `schedule/` and before `cli/` |
| `ak-dev-architecture/SKILL.md` (new section) | A `## Secret Resolution (ak-py/src/agentkernel/secret/)` section beside `## Scheduling` (`:552`) and `## Sandbox` (`:643`) — key shape, fixed layer order, provider-owns-addressing, the `env`/`aws_ssm`/dotted-path provider types, config block |
| `ak-dev-testing-conventions/SKILL.md:145` | Add `test_secret_manager.py`, `test_secret_providers.py`, `test_secret_factory.py` to the test-file table |
| `.agents/skills/ak-dev-new-secret-provider/` (new) | A new dev skill, matching the eight existing `ak-dev-new-*` skills — every pluggable seam in this repo has one, and this change adds a seam |

**Dev skills — verified, no update needed**

- `ak-dev-code-quality/SKILL.md` — the classes-not-functions and config-field rules already cover this
  change; nothing in it names a file this change touches.

**Bundled user skills (`ak-py/src/agentkernel/skills/`)**

| File / line | Change |
|---|---|
| `ak-cloud-deploy/SKILL.md:241-262`, `:389`, `:855` | Add `ssm_enabled` beside `enable_scheduling` in the prose and the three tfvars blocks; note that Terraform does not create the parameters |
| `ak-cloud-deploy/evals/evals.json:138` | Update the fixture if the tfvars block it asserts on changes |
| `ak-add-capabilities/SKILL.md` | Add a secret-resolution section: `SecretManager.current().get(...)`, values never exported to the environment, pass the value to the SDK explicitly (e.g. `set_default_openai_key`). The `STARBURST_*` exports at `:411-414` are unchanged |
| `ak-init/SKILL.md` | Verify: the scaffolded `config.yaml` needs no `secret:` block, since the default is zero-configuration |

**Docs site (`docs/docs/`)**

| File / line | Change |
|---|---|
| `advanced/secrets.md` (new) | The capability page: key shape, resolution order, the resolution order (environment first, `""` is a miss), the provider types (`env`, `aws_ssm`, dotted path), `get`/`invalidate`/`clear`, that resolved values are never exported to the environment and are passed to the SDK explicitly, startup-not-hot-path with the uncached-miss cost, rotation |
| `sidebars.js:147` | Register the new page in the `advanced/` list |
| `core-concepts/configuration.md:610`, `:734` | An `AK_SECRET__*` subsection, and the `secret:` block in the Complete Configuration Reference |
| `deployment/aws-serverless.md:1212` | `ssm_enabled` row + prose, mirroring the `enable_scheduling` entry |
| `deployment/aws-containerized.md:262` | Same |

**Verified, no update needed**

- `AGENTS.md:28-49` repo map — deliberately partial; it already omits `sandbox/`, `schedule/` and
  `pipeline/`, so `secret/` does not belong there either.
- `docs/versioned_docs/` — frozen per `AGENTS.md:47`; never edited.
- `ak-deployment/ak-aws/{serverless,containerized}/README.md` — already updated in Iterations 5 and 6.
- The two example READMEs — already updated in Iteration 7.
