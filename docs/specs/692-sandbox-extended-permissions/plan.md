# #692: Sandbox extended permissions — Implementation Plan

> Status: **Draft**. Stage 3 for [spec.md](spec.md).

This plan sets the order in which [spec.md](spec.md) gets built.

- It ships as **one PR** containing both phases, following design.md's Delivery section:
  - **Phase 1** (iterations 1–7) adds the guard and package installation, and closes #692.
  - **Phase 2** (iterations 8–10) adds language runtimes.
  - Phase 2 is small and was built on the same branch as phase 1's follow-up fixes, so splitting it into its own PR
    would mean rewriting history for no review benefit.
- Each phase ends with its own tests gate and its own docs-and-skills sync.
- Unit tests land with the component they cover, which is the repo convention.
- Each iteration leaves the branch working, with `cd ak-py && uv run pytest tests/test_sandbox*.py` green.

All paths below are relative to `ak-py/src/agentkernel/` unless they start with `ak-py/`, `docs/`, `examples/` or
`.agents/`.

## Phase 1: permission guard and package installation

### Iteration 1: Models, errors and config

- **Goal:** All the new data shapes exist. Nothing reads them yet, so behaviour is unchanged.
- **Files:**
  - `sandbox/errors.py`
  - `sandbox/model.py`
  - `sandbox/__init__.py`
  - `core/config.py`
  - `ak-py/tests/test_sandbox.py`
- **Steps:**
  1. Add `SandboxPermissionDeniedError` (spec §Errors).
  2. Add `PackageInstallPolicy` and `SandboxPolicy.languages` / `.package_install` / `.effective_timeout()`.
     Then add `SandboxCapabilities.package_ecosystems`, `_derive_package_install` and `derive()` (spec §Wire and
     capability models).
  3. In `core/config.py`, add the following (spec §Config changes):
     - `_SandboxPolicyConfig.languages` / `.package_install`;
     - `_SandboxPackageInstallConfig`;
     - the `attached` validator on `_SandboxProfileConfig`;
     - the `_SandboxProviderPackageConfig` mixin, with its argv validator, on the docker, kubernetes, e2b and daytona
       blocks.
  4. Export `PackageInstallPolicy` (spec §Public exports).
- **Verify:**
  - The existing suite passes unchanged.
  - The new `test_sandbox.py` cases pass:
    - capability derivation, including the explicit `False` rejection and `derive()` re-validation;
    - config rejections: empty argv, `ecosystems: []`, `attached` with `package_install`;
    - `languages: []` loads;
    - the default `ecosystems` is `["python"]`.

### Iteration 2: Package validation

- **Goal:** `PackageInstaller` turns a request into a validated argv or command, and rules resolve at startup.
- **Files:**
  - `sandbox/packages.py` (new)
  - `sandbox/__init__.py`
  - `ak-py/tests/test_sandbox_packages.py` (new)
- **Steps:**
  1. Add the `PackageSpecRule` ABC, `PythonPackageSpecRule` and `NodePackageSpecRule`, with the spec's patterns
     and explicit rejections (spec §Package validation and installation).
  2. Add `PackageSpecRuleFactory.resolve` (built-in rule first, then bring-your-own) and `validate_config`.
  3. Add `PackageInstaller`: `from_config`, baseline, `validate`, `argv`, `command`. Error messages give the index
     and the rule only.
  4. Export `PackageSpecRule`.
- **Verify:** `uv run pytest ak-py/tests/test_sandbox_packages.py` passes, covering every case listed in the spec's
  Testing section.

### Iteration 3: Guard and worker

- **Goal:** The worker enforces permissions on every flavor. A raw `install_packages` request is now denied
  (behavioural change 1).
- **Files:**
  - `sandbox/permission.py` (new)
  - `sandbox/base.py`
  - `sandbox/broker/worker.py`
  - `sandbox/broker/thread.py`
  - `sandbox/broker/queue.py`
  - `ak-py/tests/test_sandbox_permissions.py` (new)
  - `ak-py/tests/test_sandbox_queue_broker.py`
- **Steps:**
  1. Add `SandboxPermissionGuard` and `PermissionAuditContext` (spec §SandboxPermissionGuard).
  2. Change the `Sandbox.install_packages` signature (spec §Sandbox ABC).
  3. Change `BrokerWorkerCore` (spec §BrokerWorkerCore changes):
     - the new `run()` order with the guard;
     - `_warn_capability_mismatch` with the tagged memo key;
     - the `process()` skip branch;
     - the effective timeout plus `BACKSTOP_GRACE_SECONDS`;
     - `_call_install` with the legacy shim.
  4. Add the `ThreadBroker._handle` skip branch. Change the queue client's ceiling check to use the effective
     timeout (spec §Thread and queue flavors).
- **Verify:**
  - The worker-side cases of `test_sandbox_permissions.py` pass:
    - each deny rule logs exactly one line;
    - the generic-warning skips work, and `_enforce_policy`/`_check_principal` keep their warning;
    - the mismatch warning fires once per (provider, profile);
    - the shim;
    - effective timeout and backstop.
  - `test_sandbox_queue_broker.py` passes: the denied error round-trips by name, and the install-timeout ceiling
    case is rejected.

### Iteration 4: Providers

- **Goal:** `docker`, `kubernetes`, `e2b` and `daytona` install through `PackageInstaller`, and handles check the
  instance's capabilities. Timed-out managed handles are killed without needing `pkill`.
- **Files:**
  - `sandbox/providers/process.py` (new)
  - `sandbox/providers/docker.py`
  - `sandbox/providers/kubernetes.py`
  - `sandbox/providers/e2b.py`
  - `sandbox/providers/daytona.py`
  - `sandbox/providers/ec2_ssm.py`
  - `sandbox/testing.py`
  - `ak-py/tests/test_sandbox_providers.py`
- **Steps:**
  1. Add `ProcessKiller`, which skips PID 1 and `$$` (spec §ProcessKiller).
  2. Each provider's `__init__` builds its `PackageInstaller`. Its instance capabilities come from one `derive()`
     call, and on kubernetes that same call also does the `policy_network` flip.
  3. Pass the new handle arguments at all eight construction sites, including `kill_enabled = not
     config.attach_to` for docker and kubernetes.
  4. Change the handles (spec §Provider changes):
     - language checks read the instance capabilities, at five sites including `ec2_ssm`;
     - an undeclared ecosystem raises `SandboxCapabilityError`;
     - docker and kubernetes install through `installer.argv`, and e2b and daytona through `installer.command`
       plus the timeout;
     - docker and kubernetes `_exec` kill on `TimeoutError` and on `CancelledError`, with the kill bounded by
       `KILL_TIMEOUT_SECONDS`.
  5. Add the contract check for an undeclared ecosystem in `SandboxProviderContract` (spec §Testing).
- **Verify:**
  - The existing install assertions pass unchanged: `test_sandbox_providers.py:327-328`, `950-951`, `1276-1277`
    and `1638-1642`.
  - The kill assertions at `:346` and `:1675`, and the fake cluster's handler at `:1422`, now use the
    `ProcessKiller` argv.
  - The new cases pass: kill on cancellation, no kill when `attach_to` is set, and `node` declared on the instance.

### Iteration 5: Agent side

- **Goal:** An agent can install packages end to end on a permitting profile. A denied or malformed request fails
  before anything is submitted.
- **Files:**
  - `sandbox/manager.py`
  - `sandbox/tools.py`
  - `sandbox/broker/queue_worker.py`
  - `ak-py/tests/test_sandbox_permissions.py`
  - `ak-py/tests/test_sandbox.py`
  - `ak-py/tests/test_sandbox_queue_broker.py`
- **Steps:**
  1. Change `ExecutionManager` (spec §Consumer changes):
     - `_policy_from` copies the new fields;
     - add `install_packages`;
     - reorder `_submit_op` so that the guard, then `_validate_payload`, run before `_resolve_session`;
     - `_installer_for`;
     - `_warn_permission_config` in `__init__`.
  2. Change the tools:
     - add the `install_packages` tool function and register it only when some profile permits installs;
     - update the guidance in `_profiles_text` and the tool list;
     - call `PackageSpecRuleFactory.validate_config` in `get_sandbox_tools()`.
  3. Call `validate_config` in `QueueBrokerWorker._validated_broker`.
- **Verify:**
  - The manager cases pass:
    - an agent-side denial never calls `submit` and never tears down an idle session;
    - each of the three config warnings fires once per profile.
  - The tool-registration and guidance cases pass, including `func.__name__` matching the tool name.
  - A worker and an agent each fail at startup on an unresolvable rule.
  - An end-to-end install over the embedded, thread and `in_memory` queue flavors works with a test-local
    package-capable fake provider.

### Iteration 6: Tests gate

- **Goal:** Phase 1's test coverage is complete and the full suite is green.
- **Files:**
  - `ak-py/tests/test_sandbox_egress_live.py` (new)
  - any gaps found against spec §Testing
- **Steps:**
  1. Walk spec §Testing line by line and confirm every listed case exists in the named file.
  2. Add the env-gated live egress test, following the `test_transport_contract_live.py` pattern. It is skipped
     unless `AK_TEST_SANDBOX_EGRESS=1` and the provider API key are set.
  3. Run it once against `e2b` and once against `daytona`. Record the result in the PR: it decides whether
     `allowlist` joins the hardening recipe.
- **Verify:**
  - `cd ak-py && uv run pytest` passes.
  - `make lint-check-all` passes.
  - Live run: `AK_TEST_SANDBOX_EGRESS=1 uv run pytest tests/test_sandbox_egress_live.py`.

### Iteration 7: Sync docs and skills (phase 1)

- **Goal:** Every documentation surface and skill matches phase 1's behaviour.
- **Files and changes:**
  - `docs/docs/advanced/sandbox.md` (all required by spec §Documentation):
    - **line 69:** "eight tools" becomes eight plus the conditional `install_packages`;
    - **the tools table near line 80:** add a row for the new tool;
    - **§Policy and permissions (line 198):**
      - the `languages` and `package_install` fields;
      - permission versus capability;
      - what permissions do not gate;
      - the hardening recipe;
      - per-provider `network_egress` enforcement;
    - **a new "Package installation" section:**
      - the per-posture table;
      - `package_installers` and `package_rules`, including the replace-not-merge rule;
      - grammars and a bring-your-own rule example;
      - install timeouts and the redelivery-window constraint;
      - kill limits, including attached environments;
    - **upgrade order:** workers before agents;
    - **migration for bring-your-own `Sandbox` subclasses** (the same text goes into the release notes);
    - **§Configuration reference (line 498):** the new fields.
  - `examples/sandbox/docker/README.md:11`, `examples/sandbox/daytona/README.md:12` and
    `examples/sandbox/broker-nats/README.md:134` all say `install_packages` is a plain `pip install`. Each gets the
    note that installs require a profile's `package_install`.
  - `.agents/skills/ak-dev-architecture/SKILL.md`:
    - **:802:** the new `install_packages` signature;
    - **:807:** add `package_ecosystems` to the capability list;
    - **:836:** the tool count, the guard and where it runs, and the conditional tool;
    - **the tree at :1065-1076:** add `permission.py`, `packages.py` and `providers/process.py`, and fix the tools
      comment (:1072).
  - `.agents/skills/ak-dev-new-sandbox-provider/SKILL.md`:
    - **:64, :117:** the `install_packages` signature and the undeclared-ecosystem rule;
    - **:67, :143:** use `package_ecosystems` instead of only the `package_install` flag;
    - **:81-84:** instance overrides go through `derive()`, not `model_copy` (spec §Wire and capability models);
    - **steps 2 and 5:** a provider that installs subclasses `_SandboxProviderPackageConfig` and uses
      `PackageInstaller`.
  - `.agents/skills/ak-dev-testing-conventions/SKILL.md:154-157`: update the sandbox rows, and add rows for
    `test_sandbox_permissions.py`, `test_sandbox_packages.py` and `test_sandbox_egress_live.py`.
  - `ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md:1321-1324`: update the tool list with the
    conditional `install_packages` and how to enable it.
  - `docs/src/components/FeatureExplorer/data.tsx:224-226`: add language and package-install permissions to the
    Sandbox Policy card's description.
  - **No example change is required by the spec.** At review, decide whether `examples/sandbox/policy` gains a
    `package_install` profile, per the PR guideline that new features ship an example.
- **Verify:**
  - Run the `ak-dev-sync-docs-from-branch` and `ak-dev-sync-skills-from-branch` flows on the branch before merge,
    and confirm they report nothing missing.
  - `cd docs && npm run build` passes.

## Phase 2: language runtimes

### Iteration 8: Runtime config and execution

- **Goal:** `docker` and `kubernetes` run `run_code` through the operator-declared `language_runtimes`, and their
  instance `languages` come from that map.
- **Files:**
  - `core/config.py`
  - `sandbox/providers/docker.py`
  - `sandbox/providers/kubernetes.py`
  - `ak-py/tests/test_sandbox.py`
  - `ak-py/tests/test_sandbox_providers.py`
- **Steps:**
  1. Add the `_SandboxProviderRuntimeConfig` mixin, with the `python`-key and argv validators, on the docker and
     kubernetes blocks (spec §Config changes).
  2. In each provider's `derive()` call, add `languages=list(language_runtimes)`. Pass the runtime map to the
     handles.
  3. `execute_code` builds `[*runtimes[language], code]` (spec §Provider changes, phase 2).
- **Verify:**
  - Config: a map without `python` is rejected.
  - Providers: a `node` runtime drives the exec argv and the instance `languages`, an undeclared language still
    raises, and the default map reproduces `["python", "-c", code]`.

### Iteration 9: Tests gate

- **Goal:** Phase 2's test coverage is complete and the full suite is green.
- **Steps:** Confirm the phase-2 cases in spec §Testing exist. Confirm the worker's mismatch warning fires for a
  `policy.languages` entry the runtime map lacks.
- **Verify:** `cd ak-py && uv run pytest` and `make lint-check-all` pass.

### Iteration 10: Sync docs and skills (phase 2)

- **Files and changes:**
  - `docs/docs/advanced/sandbox.md`:
    - a "Language runtimes" subsection: `language_runtimes`, `policy.languages`, and command-only profiles;
    - the configuration reference.
  - `.agents/skills/ak-dev-new-sandbox-provider/SKILL.md`: an argv-exec provider subclasses
    `_SandboxProviderRuntimeConfig`.
  - `.agents/skills/ak-dev-architecture/SKILL.md:807`: languages are instance-declared for `docker` and
    `kubernetes`.
- **Verify:** Run the same two sync flows, and the docs build passes.
