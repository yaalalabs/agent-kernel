# Release notes draft: #692 sandbox extended permissions

Paste-ready material for the GitHub release that ships #692. The capability lands over two PRs
(`plan.md` phases 1 and 2). **Shipped so far: phase 1**: the permission guard, per-profile language
and package-install permissions, and the `install_packages` tool. Phase 2 (operator-declared language
runtimes for `docker` and `kubernetes`) follows.

## New: per-profile language and package-install permissions

A sandbox profile's `policy` now also says **what agents may do** in that profile, not only which
resources they get:

```yaml
sandbox:
  enabled: true
  profiles:
    builder:
      type: docker
      policy:
        languages: [python]          # run_code allowlist; omitted = whatever the provider declares; [] = no run_code
        package_install:             # omitted = installs denied
          ecosystems: [python, node] # default [python]
          timeout: 300               # an install's own wall clock; omitted = policy.timeout
      docker:
        image: my-org/agent-runtime:1
        package_installers:          # ecosystem -> installer argv prefix the image provides
          python: [pip, install]     # the default; declaring package_installers replaces the map
          node: [npm, install]
```

What ships with it:

- **`install_packages` tool.** Agents get a ninth sandbox tool, `install_packages(packages, ecosystem,
  sandbox_session_id, profile)`, only when at least one profile permits installs. The injected
  guidance lists what each profile permits.
- **Installs are off by default.** Only a profile that declares `package_install` permits them, and
  only for its `ecosystems`. `package_install` on an `environment: attached` profile is rejected at
  config load.
- **Configurable installers.** `docker`, `kubernetes`, `e2b` and `daytona` take `package_installers`
  (the installer argv per ecosystem, default `pip install`) and `package_rules` (ecosystem → dotted
  path of a `PackageSpecRule`).
- **Validated package specs.** Every request is checked before it is submitted, and again in the worker:
  no installer options, URLs, local paths, VCS specs or archive files. `python` accepts registry
  names with extras and version specifiers. `node` accepts `name` or `@scope/name`, optionally
  `@version`. A bring-your-own `PackageSpecRule` (`from agentkernel.sandbox import PackageSpecRule`)
  can narrow a built-in grammar, for example to a package-name allowlist, but never loosen it.
  Rules are resolved at startup, so a missing or broken rule stops the process, not a request.
- **Permission denials are explicit and audited.** A request a profile does not permit fails with
  `SandboxPermissionDeniedError` and is logged once as a `WARNING` on `ak.sandbox.broker`
  (operation, profile, agent and session ids, reason; never code or package names). A request the
  profile permits but the provider does not support still fails with `SandboxCapabilityError`.
- **Startup warnings** when installs are permitted on a `per_runtime` profile, with
  `network_egress: deny`, or on `docker`/`kubernetes` with a filesystem policy (read-only root
  filesystem).

See [Sandbox → Package installation](https://kernel.yaala.ai/docs/advanced/sandbox#package-installation)
for the posture table (offline installs, read-only root filesystems, non-root images).

## Behaviour changes

- **Raw `install_packages` requests are now denied** unless the profile declares `package_install`.
  Before, a request that reached the worker ran with no permission check.
- **Timed-out work is now killed.** On `docker` and `kubernetes`, a timed-out or cancelled
  `run_code`, `run_command` or install is killed together with its child processes. The kill uses an
  environment marker and a `/proc` scan, so it works on images without `pkill` (including the default
  `python:3.12-slim`, where the old kill did nothing). It no longer touches same-named processes
  from earlier executions. It never runs in an `attach_to` container or pod. `local_subprocess` now
  reliably kills its process group, and `ec2_ssm` cancels its command, because the worker's own timer
  now fires 10 seconds after the handle's (below).
- **The worker's timer is now a backstop.** Each operation's handle enforces its effective timeout
  (`package_install.timeout` for installs, otherwise `policy.timeout`). The broker worker's outer timer
  fires at that timeout plus 10 seconds. A hung handle is therefore reported up to 10 seconds later
  than before.
- **`e2b` and `daytona` installs now have a timeout**, passed to the SDK's native command timeout.
  Before, they had none. Their install command is now built with `shlex.join`, which gives the same
  string as before for any valid spec.
- **The queue flavor checks `worker_timeout_ceiling` against the operation's own timeout**, so an
  install whose `package_install.timeout` exceeds the ceiling is rejected at submit.

## Upgrade order (queue flavor)

**Upgrade queue workers before agent pods.** The worker enforces the permissions the agent side
sends.

- An **older worker** ignores `package_install` and would run any permitted install as `pip install`,
  without the install timeout.
- An **older agent** sends no permissions, so a newer worker denies its install requests. The older
  agent reports the denial as a generic `ExecutionBrokerError`.

## Migration: bring-your-own `Sandbox` subclasses

`Sandbox.install_packages` now takes `(packages, ecosystem="python", timeout=None)`. Update overrides
to the new signature. Raise `SandboxCapabilityError` for an ecosystem the provider does not declare
(in `capabilities.package_ecosystems`), and honor `timeout`.

A subclass that still overrides `install_packages(self, packages)` keeps working for `python`
installs **for one minor release**. The worker calls it through a compatibility shim and logs one
deprecation warning per class. Any other ecosystem fails with `SandboxCapabilityError`, and the
worker's backstop is the only timer. The shim is removed in the following minor release. The
`SandboxProviderContract` test suite already requires the new signature.

Instance capability overrides should use `SandboxCapabilities.derive(...)` instead of
`model_copy(update=...)`, which skips the new `package_ecosystems` validator.

## Known limits

- **`network_egress: allowlist` on `e2b` and `daytona` is not yet verified as a hard limit** for
  registry domains such as `pypi.org`. For a hard limit, use `deny` plus a package mirror or
  pre-baked packages. A live gate (`ak-py/tests/test_sandbox_egress_live.py`, run with
  `AK_TEST_SANDBOX_EGRESS=1`) decides whether `allowlist` joins the hardening recipe.
- **The kill is best-effort.** A process that clears its own environment escapes it, and the kill
  itself is time-bounded.
- **Permissions gate Agent Kernel's sandbox operations, not the environment.** `run_command`, or a
  subprocess inside `run_code`, can still reach any installer the image contains. Hard containment
  remains the isolation tier, `network_egress`, the filesystem policy and the image.
- **On `docker` with a filesystem policy, only pure-Python packages can be installed into the
  workdir.** The writable workdir is a `noexec` tmpfs, so compiled extensions fail to import.
