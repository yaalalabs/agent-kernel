---
name: ak-dev-new-sandbox-provider
description: >
  Step-by-step guide for adding a new sandbox provider to Agent Kernel.
  Use this skill when you need to integrate a new code-execution backend for the sandbox
  capability (beyond local_subprocess, docker, kubernetes, e2b, daytona, and ec2_ssm). Covers implementing
  the Sandbox / SandboxProvider ABCs, declaring capabilities honestly, factory registration,
  configuration, the contract test suite, and examples.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Adding a New Sandbox Provider

This guide walks through adding a new sandbox provider to Agent Kernel. Use the shipped
`local_subprocess` (`ak-py/src/agentkernel/sandbox/providers/local_subprocess.py`) and
`docker` (`ak-py/src/agentkernel/sandbox/providers/docker.py`) implementations as reference.

## Existing Providers

| Provider | `type` value | Isolation | Extra |
|---|---|---|---|
| Local subprocess | `local_subprocess` | `none` (no isolation; dev/test) | — (stdlib) |
| Docker | `docker` | `container` | `agentkernel[sandbox-docker]` |
| E2B | `e2b` | `micro_vm` | `agentkernel[e2b]` |
| Daytona | `daytona` | `container` | `agentkernel[daytona]` |
| EC2 via SSM | `ec2_ssm` | `none` (attach-only to an existing instance) | `agentkernel[aws]` |
| Kubernetes | `kubernetes` | `container` | `agentkernel[kubernetes]` |

Planned in later iterations: `bedrock_agentcore`.

Reference implementations by pattern: `docker.py` (sync SDK via `to_thread`), `e2b.py`
(native async SDK + native idle timeout passthrough), `daytona.py` (sync SDK + native
auto-stop + configurable base image/snapshot/env_vars + resource mapping), `ec2_ssm.py`
(attach-only provider with user-identity
mapping: `sts:AssumeRole` + `run_as`), `kubernetes.py` (sync SDK via `to_thread` with plain
dict manifests, exec over the WebSocket stream API (the caller's RBAC needs BOTH `create`
and `get` on `pods/exec`), user identity via cached per-subject RBAC-impersonation clients,
and the instance-level capability override, below). Providers with a native auto-stop take
the profile's `idle_timeout` as a second constructor argument, passed by their factory
branch; `kubernetes` takes it too, sizing the pod's `activeDeadlineSeconds` orphan ceiling.

**Attach-only backends** (environments the framework connects to but never owns) subclass
`AttachedEnvironmentProvider` instead of `SandboxProvider`: it fixes `create` (binds to the
config's `attach_to`, never provisions) and `destroy` (no-op) once, so only `attach` is
implemented. The handle subclasses `AttachedEnvironment` (not `Sandbox` directly), which fixes
`close()` as a no-op and keeps the class name honest (e.g. `EC2SSMEnvironment`). Declare
`provisions=False, attaches_external=True` — the factory validates the profile's
`environment: managed | attached` mode against these flags at startup (attach-only providers
are rejected under `managed`, and `attached` requires `attaches_external` plus an `attach_to`
target), and the worker never self-heal-provisions or disposes an attached environment.

## Architecture Overview

The sandbox capability (`ak-py/src/agentkernel/sandbox/`) is config-driven and pluggable:

- **`SandboxProvider`** (`base.py`) — one long-lived instance per configured profile backend.
  Implements `create()`/`destroy()` (abstract), `attach()` when `capabilities.attach` is declared
  (the base default raises `SandboxCapabilityError`), and declares a `capabilities` class attribute.
- **`Sandbox`** (`base.py`) — a handle to one live sandbox. Implements the two abstract methods
  `execute_code()` (`language="python"`) and `close()`, and optionally `execute_command()`,
  `upload_file()`, `download_file()`, `install_packages(packages, ecosystem="python", timeout=None)`
  (each raises `SandboxCapabilityError` in the base until overridden). An `install_packages` override
  raises `SandboxCapabilityError(<handle>, "package_ecosystem:<e>")` for an ecosystem the instance
  does not declare, and honors `timeout` (the install's effective timeout).
- **`SandboxCapabilities`** (`model.py`) — the honest declaration of what the provider supports
  (isolation tier, shell, languages, files, package_ecosystems, stateful, attach, principal_user,
  policy_network/filesystem/resources). `package_ecosystems` is the source of truth for installs;
  `package_install` is derived from it by a validator. The manager/worker consult it before routing
  an operation; an operation a provider didn't declare raises `SandboxCapabilityError`. What a
  profile *permits* (`policy.languages`, `policy.package_install`) is decided separately by
  `SandboxPermissionGuard`; providers never read the policy's permission fields.
- **`SandboxProviderFactory`** (`factory.py`) — resolves a profile's `type` to a provider. Built-in
  short names are `if/elif` branches with real lazy imports; anything with a dot is treated as a
  dotted path to a `SandboxProvider` subclass (bring-your-own, no code change needed).
- **`BrokerWorkerCore`** (`broker/worker.py`) — enforces principal and policy fail-closed against
  the declared capabilities, then calls the provider.

**Key principle — declare capabilities honestly.** Only claim what the backend truly enforces.
If you declare `policy_network=True` but can't actually restrict egress, you've created a false
security guarantee. Under-declaring is safe (the operation raises a clear capability error);
over-declaring is a security bug.

**Instance-level capability override** (#503): when a capability's enforcement depends on
operator-asserted infrastructure the provider cannot detect, keep the class declaration honest
(`False`) and flip it per instance in `__init__` via
`self.capabilities = type(self).capabilities.derive(...)` behind an explicit config flag.
Use `derive()`, never `model_copy(update=...)`: `model_copy` skips the validator that keeps
`package_install` consistent with `package_ecosystems`. Compose every override into **one**
`derive()` call. The reference is the `kubernetes` provider: its `network_policy: true` (the
operator asserts the cluster CNI enforces NetworkPolicy), its `language_runtimes` keys and its
`package_installers` keys go into the same
`derive(languages=list(runtimes), package_ecosystems=eco, policy_network=True)`. `derive()` keeps the two
package fields consistent: updating `package_ecosystems` re-derives `package_install` (so `[]` means no installs),
and `package_install=False` clears the ecosystems.
Consumers read `provider.capabilities` on the instance, so attribute shadowing is sufficient.

## Step-by-Step

### 1. Create the Provider File

Create `ak-py/src/agentkernel/sandbox/providers/<provider>.py` with a `Sandbox` subclass and a
`SandboxProvider` subclass.

### 2. Implement the Sandbox Handle

```python
from agentkernel.sandbox import Sandbox
from agentkernel.sandbox.errors import SandboxCapabilityError
from agentkernel.sandbox.model import SandboxResult


class <Provider>Sandbox(Sandbox):
    def __init__(self, sandbox_id: str, ...) -> None:
        self.id = sandbox_id            # provider-scoped id, stable across attach/reconnect

    async def execute_code(self, code: str, language: str = "python", timeout: float | None = None) -> SandboxResult:
        # language="python" is MANDATORY. A failing program (non-zero exit) is a RESULT
        # (SandboxResult with exit_code != 0), NOT an exception. Raise only on machinery failure.
        if language not in self._capabilities.languages:   # the instance's, not the class attribute
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        ...
        # An argv-exec provider (docker, kubernetes) runs the configured interpreter prefix:
        #   return await self._exec([*self._runtimes[language], code], timeout)
        return SandboxResult(stdout=..., stderr=..., exit_code=...)

    # Override ONLY the optional operations your capabilities declare. The base ABC raises
    # SandboxCapabilityError for execute_command / upload_file / download_file / install_packages
    # when not overridden — that is capability honesty in action.

    # A provider that installs packages: check the instance's declared ecosystems, then let the
    # injected PackageInstaller validate the specs and build the argv (or command string).
    async def install_packages(self, packages: list[str], ecosystem: str = "python", timeout: float | None = None) -> SandboxResult:
        if ecosystem not in self._capabilities.package_ecosystems:
            raise SandboxCapabilityError(self.__class__.__name__, f"package_ecosystem:{ecosystem}")
        return await self._exec(self._installer.argv(packages, ecosystem), timeout)  # or installer.command(...)

    async def close(self) -> None:
        # Idempotent. For per_session scope this must NOT destroy state needed for a later
        # attach() — only destroy() permanently disposes backend state.
        ...
```

Sync SDKs must be wrapped in `asyncio.to_thread` (see `docker.py`), since the sandbox runs on an
event loop. Enforce `timeout` with `asyncio.wait_for` when the backend has no native timeout.

Handles receive the provider **instance's** `capabilities` (and its `PackageInstaller`) as
constructor keywords and check those, never the class attribute, so instance overrides count.
A handle that execs processes inside a container should kill a timed-out or cancelled exec:
`ProcessKiller` (`providers/process.py`) tags each exec with an environment marker and builds a
procps-free `/proc` scan that kills exactly that exec and its children (see `docker.py`,
`kubernetes.py`). Never kill in an environment the framework does not own (`attach_to`).
For every operation whose handle is passed a timeout (code, commands, installs), the worker's own
timer is only a backstop at `timeout + BrokerWorkerCore.BACKSTOP_GRACE_SECONDS`; when it fires, the
worker logs one warning per handle class, so that warning means your handle ignored the `timeout`
it was passed. File transfers get no timeout argument, so the worker enforces the bare timeout there.

### 3. Implement the Provider

```python
from agentkernel.sandbox import Sandbox, SandboxProvider
from agentkernel.sandbox.errors import SandboxGoneError
from agentkernel.sandbox.model import IsolationTier, SandboxCapabilities, SandboxPolicy, SandboxPrincipal


class <Provider>SandboxProvider(SandboxProvider):
    capabilities = SandboxCapabilities(
        isolation=IsolationTier.CONTAINER,   # declare the REAL boundary
        shell=True,
        languages=["python"],
        files=True,
        package_ecosystems=[],               # e.g. ["python"]; empty = no installs (package_install is derived)
        stateful=False,
        attach=True,
        provisions=True,                     # False for attach-only backends (never create)
        attaches_external=False,             # True only if attach_to can bind to something you didn't create
        principal_user=False,                # True only if you enforce a user identity
        policy_network=False,                # True only if you actually restrict egress
        policy_filesystem=False,
        policy_resources=False,
    )

    def __init__(self, config) -> None:
        super().__init__(config)             # config is the provider's Pydantic config block
        # Create SDK clients lazily (first use), not here — keep import/constructor cheap.
        # A provider that installs packages builds its installer from its own config block and
        # declares the configured ecosystems on the instance:
        #   self._installer = PackageInstaller.from_config(config)
        #   self.capabilities = type(self).capabilities.derive(package_ecosystems=self._installer.ecosystems)
        # and passes capabilities=self.capabilities, installer=self._installer to every handle.
        # A provider that execs an interpreter argv also declares its language_runtimes keys, in
        # the same derive() call, and passes runtimes=self._runtimes to every handle:
        #   self._runtimes = dict(config.language_runtimes)
        #   self.capabilities = type(self).capabilities.derive(languages=list(self._runtimes), package_ecosystems=..., ...)

    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        # Provision a new sandbox. Map `policy` onto the backend's real controls here; if a
        # declared-enforceable dimension can't be honored for this request, raise SandboxPolicyError.
        ...

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox:
        # Reconnect to an existing sandbox. Raise SandboxGoneError when the target is gone —
        # that is the self-heal signal the worker uses to recreate under the same session id.
        ...

    async def destroy(self, sandbox_id: str) -> None:
        # Permanently dispose. Idempotent; unknown ids are a no-op.
        ...
```

Policy mapping and principal mapping (for `principal_user=True`) belong in `create`/`attach`.
See `docker.py` for the policy mapping pattern (`network_egress: deny` → `network_mode: none`,
cpu/memory → container limits, filesystem → read-only rootfs + writable workdir).

### 4. Register with the Factory

Add an `if/elif` branch to `SandboxProviderFactory._build` in
`ak-py/src/agentkernel/sandbox/factory.py`, and append the short name to
`_BUILTIN_PROVIDER_NAMES` (this is the #541 house pattern: real lazy imports, no registry map):

```python
if type_name == "<provider>":
    config_block = cls._require_block(profile_name, profile, type_name)
    with require_extra("<extra>", "sandbox provider '<provider>'"):   # skip the wrap if stdlib-only
        from .providers.<provider> import <Provider>SandboxProvider
    return <Provider>SandboxProvider(config_block)
```

```python
_BUILTIN_PROVIDER_NAMES = ["local_subprocess", "docker", "<provider>"]   # add your name
```

`require_extra` produces the friendly `pip install "agentkernel[<extra>]"` message when the SDK
is missing. A bring-your-own provider needs none of this — a dotted-path `type` resolves via
`resolve_dotted` automatically.

### 5. Add the Config Block

In `ak-py/src/agentkernel/core/config.py`, add a `_Sandbox<Provider>Config` Pydantic model and
wire it as an `Optional` field on **both** `_SandboxProfileConfig` and `_SandboxConfig` (the
latter for single-backend sugar), mirroring `_SandboxDockerConfig`:

```python
class _Sandbox<Provider>Config(BaseModel):   # or _SandboxProviderPackageConfig, see below
    # provider-specific fields, e.g. image, region, api_key_env, attach_to
    ...

# on _SandboxProfileConfig AND _SandboxConfig:
<provider>: Optional[_Sandbox<Provider>Config] = Field(default=None, description="Configuration for the '<provider>' provider")
```

The factory's `_require_block` raises `SandboxConfigError` when a built-in's config block is
missing, so the block must exist even if all fields have defaults (`<provider>: {}`).

A provider that installs packages subclasses `_SandboxProviderPackageConfig` instead of
`BaseModel`, as `docker`, `kubernetes`, `e2b` and `daytona` do. That mixin adds
`package_installers` (ecosystem → installer argv prefix, default `{python: [pip, install]}`;
declaring it replaces the default) and `package_rules` (ecosystem → dotted path of a
`PackageSpecRule`), and `PackageSpecRuleFactory.validate_config` resolves its rules at agent and
worker startup. So on the `queue` flavor, a custom rule module must be importable in the agent
image as well as the worker image. Don't add your own installer fields.

A provider that runs code by exec'ing an interpreter argv (as `docker` and `kubernetes` do) also
subclasses `_SandboxProviderRuntimeConfig`. That mixin adds `language_runtimes` (language →
interpreter argv prefix, default `{python: [python, -c]}`; declaring it replaces the default), with
validators requiring a `python` key and non-empty argv prefixes. Its keys are the instance's
`languages`, and `execute_code` runs `[*runtimes[language], code]`. A provider whose SDK picks the
interpreter (`e2b`'s template kernel, `daytona`'s per-sandbox language) does not use it and keeps
declaring `languages=["python"]`. Don't add your own runtime fields.

### 6. Add the Optional Dependency Extra

If the provider needs an SDK, add an extra to `ak-py/pyproject.toml` (or reuse `aws` for boto3):

```toml
[project.optional-dependencies]
<extra> = ["provider-sdk>=x.y.z"]
```

### 7. Add Tests

Add to `ak-py/tests/test_sandbox_providers.py`:

- **Contract suite** — subclass the public `SandboxProviderContract` (from
  `agentkernel.sandbox.testing`) with a `provider` fixture returning your provider against a
  mocked SDK. It asserts the ABC semantics (mandatory `execute_code`, capability honesty,
  idempotent close/destroy, result-vs-exception discipline, attach honesty). When the provider
  declares `package_install`, the contract also checks that an undeclared ecosystem raises
  `SandboxCapabilityError`, so the handle needs the `install_packages(packages, ecosystem, timeout)`
  signature.
- **Provider specifics** — create/attach/execute/destroy call shapes, policy/principal mapping
  arguments, `to_thread` usage for sync SDKs, timeout behavior.

Mock the SDK (no real network/daemon). Add a factory test in `ak-py/tests/test_sandbox.py`
asserting the real-import branch resolves and the missing-extra path raises the friendly error.

### 8. Add an Example

Add a profile to an `examples/sandbox/` example (or a new subfolder) showing the provider in
a `config.yaml`, and note any required services (daemon, API key, cloud creds) in the README.
`examples/sandbox/docker/` is the reference: a full subfolder for an isolating provider,
including a profile that demonstrates enforced policy and sentinel-based deterministic tests.

### 9. Add Documentation

- Add a row to the provider table in `docs/docs/advanced/sandbox.md` (with the honest isolation
  tier and the extra), and to the "Installation" extras in `ak-py/README.md`.
- If the provider supports `principal_user`, document its identity mapping (how `agent`/`user`
  mode resolves to backend credentials).
- Landing page inventories (`docs/src/components/*/data.tsx`): a tile in the **Cloud &
  infrastructure** row of `IntegrationsMarquee/data.tsx` (role `Sandbox`, `href` to the
  provider's setup anchor in `docs/docs/advanced/sandbox.md`, logo or `react-icons/si` glyph),
  and the provider in the **Sandboxed Execution** card's `tags` and `description` under the
  Scale tab in `FeatureExplorer/data.tsx`. Logo sourcing and the build check are in
  `ak-dev-sync-docs-from-branch`, *Docs-Site Landing and Features Pages*.
- Features page (`docs/src/pages/features.tsx`): the provider-name highlight on the Sandboxed
  Code Execution card and the provider count in the sandbox entry of `FEATURE_PAGE_MAP`. Grep
  `docs/src/pages/*.tsx`, `docs/docs/intro.md`, and `docs/src/components/SandboxFlowDiagram`
  for the provider roll call and the count.

## Checklist

- [ ] `ak-py/src/agentkernel/sandbox/providers/<provider>.py` with `Sandbox` + `SandboxProvider` subclasses
- [ ] `capabilities` declared honestly (only what the backend truly enforces); instance overrides via `derive()`
- [ ] If it installs packages: config subclasses `_SandboxProviderPackageConfig`, handle uses `PackageInstaller` and raises for undeclared ecosystems
- [ ] If it execs an interpreter argv: config subclasses `_SandboxProviderRuntimeConfig`; instance `languages` = `language_runtimes` keys
- [ ] Factory `if/elif` real-import branch + name in `_BUILTIN_PROVIDER_NAMES` (`factory.py`)
- [ ] `_Sandbox<Provider>Config` block on `_SandboxProfileConfig` and `_SandboxConfig` (`config.py`)
- [ ] Optional dependency extra in `pyproject.toml` (if the SDK isn't stdlib/boto3)
- [ ] `SandboxProviderContract` subclass + provider-specific tests in `tests/test_sandbox_providers.py`
- [ ] Factory resolution test in `tests/test_sandbox.py`
- [ ] Example profile in `examples/sandbox/`
- [ ] Documentation: provider table row in `docs/docs/advanced/sandbox.md` + extra in `ak-py/README.md`
- [ ] Landing page inventories: marquee tile (`IntegrationsMarquee/data.tsx`), Sandboxed Execution card tags (`FeatureExplorer/data.tsx`)
- [ ] Provider inventories on `docs/src/pages/features.tsx` (sandbox card highlight and `FEATURE_PAGE_MAP` count) and `SandboxFlowDiagram`
