# #692: Sandbox extended permissions — config-gated languages and package installation

> Status: **Draft**

The sandbox (#494/#503) gains two capabilities, each usable only when the sandbox profile's configuration permits it:
- running code in additional languages and runtimes;
- installing packages and dependencies at runtime.

One permission guard checks each such action against the profile's policy. It blocks and audit-logs anything the
profile does not permit. The guard is authoritative in the broker worker, before any provider call, and the same
check also runs agent-side before a request is submitted.

## Motivation

- **Code execution is effectively Python-only, and nothing in config restricts languages.**
  - Every built-in provider except `local_subprocess` (`python`, `bash`) declares `languages=["python"]`, e.g.
    `ak-py/src/agentkernel/sandbox/providers/docker.py:129` and `kubernetes.py:180`.
  - `docker` and `kubernetes` hard-code the interpreter (`["python", "-c", code]`, `docker.py:56`, `kubernetes.py:77`).
    Yet the configured image is what decides which runtimes exist.
  - Handles check the *class* capability, so an instance cannot declare what its image contains (`docker.py:54`,
    `kubernetes.py:75`, `e2b.py:44`, `daytona.py:55`, `ec2_ssm.py:87`).
- **Package installation is plumbed through, but agents cannot reach it and it is not gated.**
  - What exists:
    - `Sandbox.install_packages` (`sandbox/base.py:63`);
    - `capabilities.package_install` (`sandbox/model.py:41`);
    - the `install_packages` broker operation (`sandbox/broker/base.py:17`);
    - worker dispatch (`sandbox/broker/worker.py:219-220`), which runs any such request with no permission check.
  - What is missing:
    - an `ExecutionManager` method: it has only `execute`, `upload` and `download` (`sandbox/manager.py:74-107`);
    - an agent tool: `sandbox/tools.py:350-357` registers eight tools, none of which installs.
  - Installers are pip only: `docker.py:64` and `kubernetes.py:85` use argv, `e2b.py:66` and `daytona.py:67` use a
    shell string (their SDKs accept only a command string).
  - `docker` and `kubernetes` run the installer with no timeout (`_exec(..., None)`). When the worker's outer
    `asyncio.wait_for` expires (`worker.py:230`), the installer keeps running in the sandbox and the per-session lock
    is released under it.
- **No configuration decides *what* an agent may do, only how it is contained.**
  - `_SandboxPolicyConfig` (`ak-py/src/agentkernel/core/config.py:724-736`) and its wire mirror `SandboxPolicy`
    (`sandbox/model.py:123`) cover network, filesystem, resources, timeout and strictness.
  - The worker already fails closed before any provider call (`_check_principal`, `_enforce_policy`, `worker.py:79-80`).
    That is the natural place for one more check.

## Requirements

### Permission semantics (both capabilities)

- **Package installation is off by default.** It is usable only when the profile's policy declares it.
  - Languages stay provider-declared, as today. Declaring a runtime in the provider config is what makes a language
    usable, and `policy.languages` can only narrow that set.
  - Defaults keep every existing YAML file and `AK_*` env var behaving as today, except for the behaviour changes
    listed below.
- **Checked before every action.** The policy is checked on every operation, not once per session.
  - In the worker, the check runs before the sandbox is created or attached and before any provider call.
- **A non-permitted action is always blocked and logged.**
  - **Blocked:** the guard raises `SandboxPermissionDeniedError`, a new subclass of `SandboxPolicyError`. Agent tools
    return their existing `{"error": ...}` JSON.
    - It lives in `sandbox/errors.py`, so the queue flavor re-raises it by name (`broker/queue.py:162`).
  - **Logged:** exactly one `WARNING` per denial on `ak.sandbox.broker`, wherever the guard runs (worker or agent side).
    - It names the operation, profile, agent, AK session id, sandbox session id and reason.
    - It never logs code bodies or package lists.
    - The broker's generic failure warnings skip `SandboxPermissionDeniedError` only, since the guard has already
      logged it. There are two: `BrokerWorkerCore.process()` (`worker.py:114`) and the thread flavor's `_handle`
      (`broker/thread.py:139`).
    - Other `SandboxPolicyError`s, from `_check_principal` and `_enforce_policy`, keep the generic warning, which is
      their only log line today.
    - The tools' own failure warning on `ak.sandbox.tools` (`tools.py:87`) is unchanged. "One per denial" is per
      logger.
  - There is no audit-only (log-and-allow) mode.
- **Permission and capability stay separate.**
  - "Not permitted" comes from the profile policy. It raises `SandboxPermissionDeniedError` and is logged.
  - "Permitted but the provider cannot do it" comes from provider capabilities. It raises `SandboxCapabilityError`
    under the existing honesty contract and is not audit-logged.
  - `ExecutionManager` warns once per profile when the policy permits something the provider instance does not
    declare. Examples are `package_install` on `local_subprocess` or `ec2_ssm`, or a `languages` entry the provider
    does not declare. Such a request would only ever fail with `SandboxCapabilityError`.
- **Permissions gate AK sandbox operations, not the environment.**
  - `run_command`, or `subprocess` inside `run_code`, can still reach any interpreter or installer present in the
    image. The docs say so explicitly.
  - With network egress, an agent can also provision new tooling itself. For example, it can `pip install
    playwright`, download Chromium and drive a headless browser, either through `install_packages` or
    `run_command`. Browser automation is not an AK capability (see Non-goals), so no AK permission limits it.
  - Hard containment remains the provider isolation tier plus `network_egress`, filesystem policy and image choice:
    a non-root image with a read-only root filesystem and no installer binaries.
    - Provider enforcement of `network_egress` differs:
      - `docker` enforces only `deny`; `allowlist` is unenforceable there and fails closed under `strict`
        (`docker.py:136`);
      - `e2b` and `daytona` enforce `deny` and `allowlist`;
      - `kubernetes` enforces it only with an operator-asserted network policy (`kubernetes.py:206`).
    - The docs give this as the hardening recipe for admins who want hard limits.
- **Trust model.** The worker enforces the policy the agent side resolved, as `_enforce_policy` does today.
  - These permissions constrain what the agent's LLM can do. They are not a boundary against a compromised agent pod;
    that boundary is provider isolation. Re-resolving the policy from the worker's own `AKConfig` would therefore add
    no protection this design claims, and would make the guard differ from `_enforce_policy`.
- **Agents see only what is permitted.**
  - The `install_packages` tool is registered only when at least one profile permits package installation.
  - The tool guidance lists what each profile permits, and tells the agent not to work around a denial with `run_command`.

### Permission guard

- New class `SandboxPermissionGuard`. Its single responsibility is to decide whether one `ExecutionRequest` is
  permitted by its profile's policy.
  - It reads only the request (`policy`, `operation`, `payload`), never `AKConfig` or provider capabilities.
    - A queue-flavor worker therefore enforces exactly what the agent side resolved.
    - Capability checks stay in the provider handles, which keeps the permission and capability checks separate.
  - It does not gate `execute_command`, `upload_file`, `download_file` or `destroy`.
- **Worker (authoritative):** `BrokerWorkerCore` invokes it after `_enforce_policy` and before the sandbox is acquired.
  It therefore covers every broker flavor (embedded, thread, queue) and bring-your-own `ExecutionManager` callers.
- **Agent side (defence in depth):** `ExecutionManager` runs the same guard before submitting a request.
  - This also protects against a new agent talking to an old worker during a rolling upgrade (see Wire compatibility).

### Configuration

- **Reuse the existing policy envelope.** Extend `_SandboxPolicyConfig` and `SandboxPolicy`.
  - There is no parallel `permissions` block and there are no `enabled` flags.
  - Package installation is a presence-enabled block: a declared block permits it, and an absent one (`None`)
    denies it.
- **New per-profile policy fields** (the *may* side). The guard and tool registration read each one:
  - `languages: Optional[list[str]] = None`: the allowlist for `run_code`.
    - `None` means whatever the provider declares, which keeps today's behaviour.
  - `package_install: Optional[PackageInstallPolicy] = None`, with `ecosystems: list[str] = ["python"]`.
  - `PackageInstallPolicy` is the wire model, and `_SandboxPackageInstallConfig` is its config mirror.
  - `ExecutionManager._policy_from` (`manager.py:331`) copies the new fields onto the wire policy.
- **New provider-side fields** (the *can* side: what the image contains).
  - The provider class cannot know these, because the operator's image decides them.
  - They live in two mixins that the provider config blocks subclass rather than copy.
  - `ProviderRuntimeConfig`, used by `docker` and `kubernetes`:
    - `language_runtimes: dict[str, list[str]] = {"python": ["python", "-c"]}` maps a language to an interpreter
      argv prefix.
    - Its keys become the instance's declared `languages`.
    - A validator requires a `python` key, because Python execution is mandatory under the provider contract
      (`sandbox/testing.py:162`).
  - `ProviderPackageConfig`, used by `docker`, `kubernetes`, `e2b` and `daytona`:
    - `package_installers: dict[str, list[str]] = {"python": ["pip", "install"]}` maps an ecosystem to an installer
      argv prefix. Its keys become the instance's declared package ecosystems.
    - A validator rejects an ecosystem that `PackageInstaller` has no validation rules for (see Capability 2), so
      no installer runs unvalidated specs.
  - SDK-native providers do not use `ProviderRuntimeConfig`, and keep declaring `["python"]`:
    - `e2b` runs code in a kernel chosen by the configured `template`. Other languages need the operator to say what
      the template contains, which is out of scope here;
    - `daytona`'s SDK fixes the code language per sandbox, not per call.
- **New capability field.** `SandboxCapabilities` gains `package_ecosystems: list[str] = []`.
- **Wire compatibility.** The codec code and `BrokerOperation` do not change. The schema does: `SandboxPolicy` gains
  fields, and the `install_packages` payload gains an `ecosystem` key.
  - **Old agent to new worker:** the new fields decode as absent, so package installation is denied.
  - **New agent to old worker:** the old worker silently drops the new policy fields, because the models use
    Pydantic's default `extra="ignore"`.
    - The agent-side guard keeps installs from running unchecked.
    - The old worker passes only `payload["packages"]` (`worker.py:220`) and ignores `ecosystem`, so a permitted
      non-`python` install would run as `pip install`.
  - **New worker to old agent:** a `SandboxPermissionDeniedError` completion degrades to `ExecutionBrokerError` on the
    old agent (`queue.py:162-165`). The request is still denied.
  - **Rollout rule:** upgrade queue workers before agent pods. The docs say so.

### Capability 1: code execution in additional languages

- `docker` and `kubernetes` run code through the configured `language_runtimes` argv instead of hard-coded `python -c`.
- All handles check the *instance* capabilities, not the class attribute.
  - This follows the existing per-instance override pattern (`kubernetes.py:206`).
- **Guard rule:** if `policy.languages` is set and does not contain the requested language, the action is denied.
  - The guard is the only place `policy.languages` is checked. The handle's capability check still raises
    `SandboxCapabilityError` for an undeclared language.
- **Agent surface:** the existing `run_code(code, language)` tool. No new tool.

### Capability 2: package installation

- `Sandbox.install_packages(packages, ecosystem="python", timeout=None)`.
  - An ecosystem the instance has not declared raises `SandboxCapabilityError`.
  - An installer failure is a `SandboxResult` with a non-zero `exit_code`, not an exception.
  - The worker passes the effective timeout. The handle applies it to the installer process itself, as
    `execute_code` does, so a timed-out install is killed (`_best_effort_kill`) before the session lock is released.
- New class `PackageInstaller`, shared by the four implementing providers. Its single responsibility is turning a
  package request into a safe installer invocation.
  - **Validation is per ecosystem.** Each ecosystem has its own rule set, and an ecosystem without one cannot be
    configured (see Configuration).
    - Every rule set rejects an empty list, empty entries, entries starting with `-` (so no smuggled `--index-url`),
      whitespace, NUL, URLs (`://`) and local paths (a leading `.`, `/` or `~`).
    - `python` (ships first) accepts registry package names, including version specifiers and extras. It also
      rejects VCS specs (`git+`), any `/`, and archive filenames (`.whl`, `.tar.gz`, `.zip`), so a relative path
      such as `dist/x.whl` or `sub/pkg` cannot install local code.
    - Other ecosystems (e.g. `node`, which must allow `@scope/name` but reject `user/repo`, `github:` and `file:`)
      each need their own rule set before they can be configured.
    - A rejected spec raises `ValueError`, which reaches the agent as error JSON. It is input validation, not a
      permission denial, so it is not audit-logged.
    - `ExecutionManager.install_packages` calls the validation before submitting, so a bad spec fails before any
      sandbox is acquired. The handle calls it again for bring-your-own callers.
  - **Invocation.** It builds the installer argv from `package_installers`, appending packages as separate arguments.
    - `docker` and `kubernetes` execute that argv directly.
    - `e2b` and `daytona` join it with `shlex.join`, replacing today's hand-built `shlex.quote` strings, because their
      SDKs accept only a command string.
- `local_subprocess` and `ec2_ssm` keep `package_install=False`.
- **Guard rules.** Each of these is denied:
  - the profile declares no `package_install` block;
  - the ecosystem is not in `package_install.ecosystems`.
- **Agent surface:**
  - `ExecutionManager.install_packages(...)`;
  - a new system tool `install_packages(packages, ecosystem, sandbox_session_id, profile)`. It has the same contract as
    the other sandbox tools (async, returns a JSON string, can be promoted to a pending task).
- `ExecutionManager` warns once per profile when it combines a `package_install` block with `network_egress: deny`.
  - It warns rather than errors, because an offline mirror in the image makes the combination legitimate.

### Behaviour changes

- A raw `install_packages` request, which today runs unchecked (`worker.py:219-220`), is denied unless the profile
  declares `package_install`.
- `Sandbox.install_packages` gains two parameters, `ecosystem: str = "python"` and `timeout: float | None = None`,
  which the worker passes by keyword.
  - Bring-your-own `Sandbox` subclasses that override the current one-argument signature must add them.
- A timed-out install on `docker` and `kubernetes` is now killed in the sandbox instead of running on after the
  worker gives up.
- `e2b` and `daytona` build install commands with `PackageInstaller` (`shlex.join`) instead of their own `shlex.quote`
  strings. The quoting is equivalent, but URL, VCS, path and archive specs are now rejected.
- On the async flavors and the thread flavor, guard denials (`SandboxPermissionDeniedError`) log the guard's warning
  instead of the generic task-failure warning. Other failures, including other `SandboxPolicyError`s, keep the
  generic warning.

### Testing and contract

- `SandboxProviderContract` already asserts that an undeclared language raises `SandboxCapabilityError`
  (`sandbox/testing.py:173`). It gains these checks:
  - an undeclared ecosystem raises `SandboxCapabilityError`;
  - declared `package_install` implies a non-empty `package_ecosystems`.
- Guard tests:
  - one for every deny rule above, each asserting the single audit log line;
  - allowed-path tests for each capability;
  - an agent-side denial before submit;
  - one warning per denial on the `process()` path and on the thread flavor, while `_enforce_policy` and
    `_check_principal` denials still log the generic warning.
- `PackageInstaller` tests cover every accept and reject rule of the `python` rule set, and the config-load rejection
  of an ecosystem without a rule set.
- Handle tests: a timed-out install on `docker` and `kubernetes` kills the installer process.
- `ExecutionManager` tests: the permission/capability mismatch warning and the `package_install` + `deny` warning each
  fire once per profile.

### Delivery

- One design, shipped as phased PRs against it:
  1. the guard (worker and agent side), the policy fields and package installation;
  2. language runtimes.
- Each policy and provider field is added in the phase that first reads it. The `python`-key validator ships with
  `language_runtimes` in phase 2.

## Component diagram

```mermaid
graph LR
    T["Sandbox system tools<br/>run_code · install_packages (new)"] --> M["ExecutionManager<br/>+ install_packages · agent-side guard check"]
    M -->|"ExecutionRequest<br/>carries resolved policy"| W["BrokerWorkerCore<br/>_check_principal → _enforce_policy"]
    W --> G["SandboxPermissionGuard (new)<br/>reads the request only"]
    G -->|denied| E["SandboxPermissionDeniedError<br/>one WARNING on ak.sandbox.broker"]
    G -->|permitted| H["Provider handle<br/>docker · kubernetes · e2b · daytona"]
    H --> RT["language_runtimes argv"]
    H --> PI["PackageInstaller (new)<br/>per-ecosystem validation"]
```

Worker pipeline, guard deny rules, the class model and per-capability sequence diagrams:
[`research/diagrams.md`](research/diagrams.md).

## Non-goals

- An audit-only (log-and-allow) mode.
- Parsing `run_command` or code contents to detect installers or interpreters. Permissions gate typed operations only.
- Package-name allowlists and denylists. Granularity is per ecosystem.
- Installing from URLs, VCS repositories, local paths or archive files.
- Turning `install_packages` into a general shell runner (#692 non-goal).
- Browser automation. It remains a #494 non-goal (`docs/specs/494-sandbox-capability/design.md:381`). An agent that
  installs a browser itself is contained only by `network_egress` and the image (see Permission semantics).
- Computer-use or desktop sandboxes.
- Protecting against a compromised agent pod (see Trust model).

## Open questions

- When a `package_install` block is declared without `ecosystems`, should it default to everything the provider
  declares rather than `["python"]`? This draft picks `["python"]`, so each ecosystem is an explicit opt-in.
- How should package installation interact with sandboxes the AK session does not own alone?
  - `environment: attached` (e.g. docker `attach_to`): an install changes an environment the framework explicitly
    does not own. Draft: reject a `package_install` block on such a profile at config load.
  - `scope: per_runtime`: an install changes a sandbox every AK session shares. Draft: allow it, with a once-per-profile
    warning.
- `install_packages` runs under `policy.timeout` (default 120s), which real installs can exceed. Should it get its own
  timeout, e.g. `package_install.timeout`?
- Is the delivery order right (packages first, which closes #692), or should languages land first?
