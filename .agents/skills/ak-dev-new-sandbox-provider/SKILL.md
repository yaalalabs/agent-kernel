---
name: ak-dev-new-sandbox-provider
description: >
  Step-by-step guide for adding a new sandbox provider to Agent Kernel.
  Use this skill when you need to integrate a new code-execution backend for the sandbox
  capability (beyond local_subprocess and docker). Covers implementing the Sandbox /
  SandboxProvider ABCs, declaring capabilities honestly, factory registration, configuration,
  the contract test suite, and examples.
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

Planned in later iterations: `e2b`, `daytona`, `kubernetes`, `bedrock_agentcore`, `ec2_ssm`.

## Architecture Overview

The sandbox capability (`ak-py/src/agentkernel/sandbox/`) is config-driven and pluggable:

- **`SandboxProvider`** (`base.py`) — one long-lived instance per configured profile backend.
  Implements `create()`/`destroy()` (abstract), `attach()` when `capabilities.attach` is declared
  (the base default raises `SandboxCapabilityError`), and declares a `capabilities` class attribute.
- **`Sandbox`** (`base.py`) — a handle to one live sandbox. Implements the two abstract methods
  `execute_code()` (`language="python"`) and `close()`, and optionally `execute_command()`,
  `upload_file()`, `download_file()`, `install_packages()` (each raises `SandboxCapabilityError`
  in the base until overridden).
- **`SandboxCapabilities`** (`model.py`) — the honest declaration of what the provider supports
  (isolation tier, shell, languages, files, package_install, stateful, attach, principal_user,
  policy_network/filesystem/resources). The manager/worker consult it before routing an operation;
  an operation a provider didn't declare raises `SandboxCapabilityError`.
- **`SandboxProviderFactory`** (`factory.py`) — resolves a profile's `type` to a provider. Built-in
  short names are `if/elif` branches with real lazy imports; anything with a dot is treated as a
  dotted path to a `SandboxProvider` subclass (bring-your-own, no code change needed).
- **`BrokerWorkerCore`** (`broker/worker.py`) — enforces principal and policy fail-closed against
  the declared capabilities, then calls the provider.

**Key principle — declare capabilities honestly.** Only claim what the backend truly enforces.
If you declare `policy_network=True` but can't actually restrict egress, you've created a false
security guarantee. Under-declaring is safe (the operation raises a clear capability error);
over-declaring is a security bug.

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
        if language not in <declared languages>:
            raise SandboxCapabilityError(self.__class__.__name__, f"language:{language}")
        ...
        return SandboxResult(stdout=..., stderr=..., exit_code=...)

    # Override ONLY the optional operations your capabilities declare. The base ABC raises
    # SandboxCapabilityError for execute_command / upload_file / download_file / install_packages
    # when not overridden — that is capability honesty in action.

    async def close(self) -> None:
        # Idempotent. For per_session scope this must NOT destroy state needed for a later
        # attach() — only destroy() permanently disposes backend state.
        ...
```

Sync SDKs must be wrapped in `asyncio.to_thread` (see `docker.py`), since the sandbox runs on an
event loop. Enforce `timeout` with `asyncio.wait_for` when the backend has no native timeout.

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
        package_install=False,
        stateful=False,
        attach=True,
        principal_user=False,                # True only if you enforce a user identity
        policy_network=False,                # True only if you actually restrict egress
        policy_filesystem=False,
        policy_resources=False,
    )

    def __init__(self, config) -> None:
        super().__init__(config)             # config is the provider's Pydantic config block
        # Create SDK clients lazily (first use), not here — keep import/constructor cheap.

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
class _Sandbox<Provider>Config(BaseModel):
    # provider-specific fields, e.g. image, region, api_key_env, attach_to
    ...

# on _SandboxProfileConfig AND _SandboxConfig:
<provider>: Optional[_Sandbox<Provider>Config] = Field(default=None, description="Configuration for the '<provider>' provider")
```

The factory's `_require_block` raises `SandboxConfigError` when a built-in's config block is
missing, so the block must exist even if all fields have defaults (`<provider>: {}`).

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
  idempotent close/destroy, result-vs-exception discipline, attach honesty).
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

## Checklist

- [ ] `ak-py/src/agentkernel/sandbox/providers/<provider>.py` with `Sandbox` + `SandboxProvider` subclasses
- [ ] `capabilities` declared honestly (only what the backend truly enforces)
- [ ] Factory `if/elif` real-import branch + name in `_BUILTIN_PROVIDER_NAMES` (`factory.py`)
- [ ] `_Sandbox<Provider>Config` block on `_SandboxProfileConfig` and `_SandboxConfig` (`config.py`)
- [ ] Optional dependency extra in `pyproject.toml` (if the SDK isn't stdlib/boto3)
- [ ] `SandboxProviderContract` subclass + provider-specific tests in `tests/test_sandbox_providers.py`
- [ ] Factory resolution test in `tests/test_sandbox.py`
- [ ] Example profile in `examples/sandbox/`
- [ ] Documentation: provider table row in `docs/docs/advanced/sandbox.md` + extra in `ak-py/README.md`
