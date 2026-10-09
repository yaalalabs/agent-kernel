# #749 (phase 2): Resolve secrets from Kubernetes Secrets mounted into the pod — Implementation Plan

Ordering only; the *how* lives in [`spec.md`](spec.md). Seven iterations, each leaving the branch
green. The config lands before the provider, the provider before the factory exposes it, and the
chart before the example that consumes both.

Repo-wide gates at the end of every iteration:

```bash
cd ak-py && uv run pytest        # no regressions
make lint-check-all
```

## Iteration 1: Configuration block

- **Goal:** `AKConfig.get().secret.provider.kubernetes.mount_path` exists with its default and reads
  `AK_SECRET__PROVIDER__KUBERNETES__MOUNT_PATH`; nothing consumes it yet.
- **Files:** `ak-py/src/agentkernel/core/config.py`, `ak-py/tests/test_config.py`
- **Steps:**
  1. Add `_SecretKubernetesConfig` before `_SecretProviderConfig` (`config.py:902`) and the
     `kubernetes` field on `_SecretProviderConfig` — spec.md § Config changes.
  2. Update the `provider.type` and `prefix` descriptions.
  3. `test_config.py`: default, env override, empty env var keeps the default — spec.md § Testing.
- **Verify:** `uv run pytest tests/test_config.py`

## Iteration 2: `KubernetesSecretProvider`

- **Goal:** the provider resolves keys from a multi-Secret directory and passes the contract; not yet
  reachable from config.
- **Files:** new `ak-py/src/agentkernel/secret/providers/kubernetes.py`;
  `ak-py/tests/test_secret_providers.py`
- **Steps:**
  1. Constructor validation (no I/O), key re-check, `_find_candidates`, `_read` — spec.md
     § `secret/providers/kubernetes.py`, rules 1–9.
  2. `TestKubernetesProviderContract` seeding across two Secret directories.
  3. Provider-specific cases: kubelet symlink layout and re-pointed `..data`, top-level key,
     duplicates, dot-entry skip, depth, directory named `KEY`, empty file, `mount_path` errors,
     unreadable dir, invalid UTF-8 `from None`, vanished file, key guard, `__init__` laziness,
     re-discovery — spec.md § Testing.
- **Verify:** `uv run pytest tests/test_secret_providers.py`

## Iteration 3: Factory branch and export

- **Goal:** `secret.provider.type: kubernetes` builds the provider; `agentkernel.secret` exports it
  with no SDK import.
- **Files:** `ak-py/src/agentkernel/secret/factory.py`, `ak-py/src/agentkernel/secret/__init__.py`,
  `ak-py/tests/test_secret_factory.py`, `ak-py/tests/test_secret_providers.py`
- **Steps:**
  1. `kubernetes` branch next to `env` (no `require_extra`); extend `_BUILTIN_SECRET_PROVIDERS` —
     spec.md § `secret/factory.py`.
  2. Export `KubernetesSecretProvider` — spec.md § `secret/__init__.py`.
  3. Factory tests (default and overridden `mount_path`, unknown-name message, empty-prefix
     parametrize, never reads `AKConfig`, empty `mount_path` → `AKConfigError`) and the
     fresh-interpreter `test_kubernetes_needs_no_sdk`.
- **Verify:** `uv run pytest tests/test_secret_factory.py tests/test_secret_providers.py`

## Iteration 4: Helm chart `secretStore`

- **Goal:** `secretStore.enabled` mounts each listed Secret into the one agent-executing tier; invalid
  values fail the render; defaults render exactly as before.
- **Files:** `ak-deployment/ak-k8s/chart/values.yaml`, `templates/_helpers.tpl`,
  `templates/configmap-env.yaml`, `templates/deployment-agent-runner.yaml`,
  `templates/deployment-io.yaml`, `.github/workflows/chart-test.yaml`
- **Steps:**
  1. `secretStore` block in `values.yaml` — spec.md § Deployment changes.
  2. Helpers: mount path, `secretStoreTier`, `secretStoreValidate`, volumes, volume mounts.
  3. Include the validate helper at the top of `configmap-env.yaml`.
  4. Volume/mount insertions: agent-runner on `secretStore.enabled`; io on tier `io`.
  5. *Render every flavor and mode*: the two-Secret runner render, the single-process io render,
     the ws-gateway exclusion, every `expect_fail`, and the no-mount assertion in the per-flavor
     loop — spec.md § Examples and docs, CI.
- **Verify:** the render step's script locally against the chart; `ct lint --config
  ak-deployment/ak-k8s/ci/ct.yaml`; the byte-identical default-render diff from spec.md § Testing →
  Verify.

## Iteration 5: Example and kind-smoke CI

- **Goal:** `examples/k8s/openai-queue-mode` reads the OpenAI key from the mounted
  `openai-credentials` Secret, and CI's `dev` flavor proves it end to end while `baremetal`/`eks`
  keep covering the environment-first path.
- **Files:** `examples/k8s/openai-queue-mode/{config.nats.yaml,config.kafka.yaml,ak-values.yaml,app_agent_runner.py,README.md,deploy/deploy.sh}`;
  `.github/workflows/chart-test.yaml`; `ak-deployment/ak-k8s/README.md` (`ct install` command)
- **Steps:**
  1. Example config, values, entrypoint and README per spec.md § Examples and docs (including key
     naming, local run, rotation-needs-restart for this example, and the upgrade migration note).
  2. *Install chart* creates both `openai` and `openai-credentials` on every flavor.
  3. Apply the resolved spec.md § Open decision to the `ct install` command in the k8s README.
- **Verify:** `kind-smoke` passes for `dev`, `baremetal` and `eks`; the README's `local` flow works
  on a kind cluster. The published (non-`local`) flow is verified only after the release bumps the
  chart and `agentkernel` pins — spec.md § Release sequencing.

## Iteration 6: Tests

- **Goal:** the cross-component assertions and a clean full run.
- **Files:** `ak-py/tests/test_secret_manager.py`
- **Steps:**
  1. Environment wins over a seeded `KubernetesSecretProvider` with zero `os.scandir` calls.
  2. Missing `mount_path` with `default="x"` re-raises `SecretError`.
  3. Run the one-off Verify from spec.md § Testing (byte-identical default renders, all three
     `kind-smoke` flavors green).
- **Verify:** `cd ak-py && uv run pytest`, `make lint-check-all`, `ct lint`, all clean.

## Iteration 7: Sync docs and skills

Run `ak-dev-sync-skills-from-branch` and `ak-dev-sync-docs-from-branch` before merge. The surfaces
are listed, with lines, in spec.md § Examples and docs → *Docs surfaces*:

- **Docs site:** `docs/docs/advanced/secrets.md` (new `### kubernetes` subsection: layout, key
  compatibility, `mount_path`, `secretStore` and tier rule, rotation, security, local development),
  `docs/docs/core-concepts/configuration.md`, `docs/docs/agent-skills.md`.
- **Deployment / package READMEs:** `ak-deployment/ak-k8s/README.md` (*Secrets* section),
  `ak-py/README.md`.
- **Dev skills:** `ak-dev-architecture`, `ak-dev-new-secret-provider` (Existing Providers + Helm
  note in step 6), `ak-dev-testing-conventions`.
- **Bundled user skills:** `ak-add-capabilities`, `ak-cloud-deploy` (the `secretStore` alternative
  to `extraEnv`).

**Verified, no update needed**

- `ak-add-capabilities/evals/evals.json`, `ak-cloud-deploy/evals/evals.json` — their cases test AWS
  flows only.
- `docs/docs/examples/overview.md` — has no entry for `examples/k8s/openai-queue-mode`.
- `docs/sidebars.js` — no new page.
- `docs/versioned_docs/` — frozen.
- `examples/sandbox/broker-*` — keep `secretKeyRef` (design.md Non-goals).
