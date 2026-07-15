# Sandbox Capability Specification

Status: draft for review · Date: 2026-07-14 · Owner: @amithad

Research backing this spec: [.agents/skills/ak-dev-sandbox-research/](../../.agents/skills/ak-dev-sandbox-research/SKILL.md)
(provider landscape, prior-art framework abstractions, AK codebase patterns).

## 1. Summary

Add a generic, pluggable **sandbox capability** to Agent Kernel: a framework-agnostic core
interface for executing agent-generated code and commands inside an isolation boundary, with
built-in backends across three deployment models (local Docker, cloud sandbox SaaS,
cloud-provider native), an open registration mechanism so users can bring their own backend
without any change to Agent Kernel, and a first-class **permission boundary** (RBAC) applied to
every execution.

Vendor lock-in is the primary design constraint: switching backends must be a config change, not
a code change.

## 2. Terminology

| Term | Meaning |
|---|---|
| **Sandbox** | A live, isolated execution environment (a running microVM, container, cloud session, or attached runtime) exposed through the `Sandbox` interface. |
| **Provider** | The pluggable backend implementation (`SandboxProvider` subclass) that provisions, attaches to, and destroys sandboxes for one technology (Docker, E2B, ...). |
| **Principal** | The identity under which an execution runs: the **agent's own** identity or the **invoking user's assumed** identity. |
| **Policy** | Declarative constraints on an execution: filesystem access, network egress, resource limits, timeout. |
| **Capabilities** | A typed declaration by each provider of which optional operations and policy dimensions it supports. |
| **Scope** | The lifecycle binding of a sandbox: `per_call` (created and destroyed around one execution) or `per_session` (reused across turns of one AK `Session`). |

## 3. Goals and Non-Goals

### Goals (v1)

1. **Code-execution tool mode** — agents get tools to run LLM-generated Python/shell code inside
   the sandbox.
2. **Workspace mode** — a per-session persistent sandbox where an agent reads/writes files,
   installs packages, and works across turns.
3. **Attach mode** — connect to an already-running execution environment (v1: a Kubernetes
   cluster — exec into existing pods or provision Jobs) instead of provisioning isolated compute.
4. **Permission boundary on every mode** — dual identity model (agent-own / user-assumed),
   policy enforcement that **fails closed** when a backend cannot enforce a requested constraint.
5. **Four built-in providers**: `docker`, `e2b`, `bedrock_agentcore`, `kubernetes`.
6. **Bring-your-own provider** via a public base class plus dotted-path config registration —
   zero Agent Kernel code changes required.
7. **Contributor path**: a step-by-step dev skill (`ak-dev-new-sandbox-provider`) and a reusable
   provider contract test suite.

### Non-Goals (v1 — explicitly deferred)

- Streaming execution output (interface reserves room; see §14).
- Port exposure / preview URLs / tunnels.
- Sandbox pause/resume/snapshot APIs (backends may use them internally for `per_session` scope,
  but no public API surface).
- Azure Container Apps dynamic sessions and Google Vertex AI providers (fast-follow candidates;
  the core interface is validated against Azure/Bedrock's narrow "code-only" contract so adding
  them later requires no interface change).
- GPU selection, computer-use/desktop sandboxes, browser automation.
- Running the *agent process itself* inside a sandbox (infra concern; out of scope for the
  framework).

## 4. Architecture Placement

- New package: `ak-py/src/agentkernel/sandbox/` — a framework-agnostic core capability, sibling
  to `guardrail/` and `knowledgebase/`. No imports from `framework/`, `integration/`,
  `deployment/`, or `api/` (coupling direction preserved: core never depends on them).
- Instantiation is config-driven through a factory (guardrail pattern: lazy per-provider imports,
  actionable `ImportError` naming the extras group, raise on unknown type, inert when disabled).
- Agent exposure follows the multimodal pattern: system tools auto-registered on agents when the
  capability is enabled.
- Per-session state (the sandbox identifier for reconnection) lives in the AK `Session`
  (`nv_cache`), not in provider memory — mirroring ADK's `CodeExecutorContext` externalized-state
  model, so workspace mode survives process restarts wherever the session store does.

## 5. Core Interfaces

Normative for names, signatures, and semantics. Bodies shown are illustrative.
All I/O-performing methods are `async` (AK core is async-first; prior art: AutoGen 0.4's
async `CodeExecutor` redesign).

```python
# agentkernel/sandbox/base.py

class SandboxCapabilities(BaseModel):
    """Declared per provider. Every flag defaults to False; providers opt in honestly."""
    shell: bool = False                 # execute_command supported
    languages: list[str] = ["python"]   # languages accepted by execute_code
    files: bool = False                 # upload_file / download_file supported
    package_install: bool = False       # install_packages supported
    stateful: bool = False              # variables persist across execute_code calls in one sandbox
    attach: bool = False                # attach-to-existing supported
    principal_user: bool = False        # user-assumed identity supported
    policy_network: bool = False        # network egress policy enforceable
    policy_filesystem: bool = False     # filesystem policy enforceable
    policy_resources: bool = False      # cpu/memory limits enforceable
    isolation: IsolationTier            # declared, not defaulted — see below


class IsolationTier(str, Enum):
    """'Sandboxed' is a spectrum, not a checkbox — surfaced so operators can see what they get."""
    NONE = "none"                # e.g. a hypothetical local subprocess provider
    OS_POLICY = "os_policy"      # seccomp/Seatbelt/bubblewrap-style confinement
    CONTAINER = "container"      # shared-kernel namespaces (Docker, K8s pod)
    SYSCALL_FILTER = "syscall_filter"  # gVisor-style user-space kernel
    MICRO_VM = "micro_vm"        # Firecracker/libkrun/managed VM (E2B, Bedrock)
    WASM = "wasm"                # in-process WASM runtime


class SandboxResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0                  # non-zero exit is a RESULT, not an exception
    output_files: list[SandboxFile] = []
    provider_data: dict[str, Any] = {}  # escape hatch for provider-specific extras


class Sandbox(ABC):
    """Handle to one live sandbox. Created by a SandboxProvider, never constructed directly."""

    id: str                             # provider-scoped identifier, stable across attach/reconnect

    @abstractmethod
    async def execute_code(self, code: str, language: str = "python",
                           timeout: float | None = None) -> SandboxResult: ...

    async def execute_command(self, command: str,
                              timeout: float | None = None) -> SandboxResult:
        raise SandboxCapabilityError("shell")     # override when capabilities.shell

    async def upload_file(self, path: str, content: bytes) -> None:
        raise SandboxCapabilityError("files")

    async def download_file(self, path: str) -> bytes:
        raise SandboxCapabilityError("files")

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        raise SandboxCapabilityError("package_install")

    @abstractmethod
    async def close(self) -> None:
        """Idempotent. Releases the live handle; for per_session scope this must NOT
        destroy backend state needed for a later attach()."""


class SandboxProvider(ABC):
    """One per configured backend. Constructed by the factory from config; long-lived."""

    capabilities: ClassVar[SandboxCapabilities]

    def __init__(self, config: BaseModel): ...   # provider-specific Pydantic config model

    @abstractmethod
    async def create(self, *, principal: SandboxPrincipal,
                     policy: SandboxPolicy) -> Sandbox: ...

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal,
                     policy: SandboxPolicy) -> Sandbox:
        raise SandboxCapabilityError("attach")

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """Permanently dispose backend state for the sandbox. Idempotent; unknown ids are a no-op."""
```

Semantics:

- `execute_code` **must** be supported by every provider for at least `language="python"` — the
  lowest common denominator satisfiable even by code-interpreter-style services (Bedrock, and
  later Azure) that cannot run arbitrary shell.
- A failing *program* (compile error, exception, non-zero exit) returns a `SandboxResult` with
  `exit_code != 0` and diagnostics in `stderr`. Exceptions are reserved for failures of the
  *sandbox machinery* (§11).
- Unsupported optional operations raise `SandboxCapabilityError` naming the missing capability.
- `create` vs `attach` are distinct entry points by design (provision new vs. connect to
  existing); a provider supporting attach declares `capabilities.attach = True`.
- `Sandbox` instances are **not** thread-safe or event-loop-portable: an instance must be used
  only from the event loop that created it, with at most one in-flight `execute_*` call. AK
  guarantees this in practice because `Runtime.run()` holds the session lock for the duration of
  a turn. (Lesson from AutoGen issue #6395 — cross-loop cancellation corrupts executor state.)
- Both `Sandbox` and `SandboxProvider` are **public API**, exported from `agentkernel.sandbox`,
  since BYO providers subclass them.

## 6. Permission Boundary (RBAC)

### 6.1 Principal

```python
class SandboxPrincipal(BaseModel):
    mode: Literal["agent", "user"]
    subject: str                        # agent name, or user identifier
    credentials: dict[str, Any] = {}    # provider-interpreted (tokens, role ARNs, K8s user/groups)
    groups: list[str] = []
```

- `mode: agent` (default): executions run under the agent's own identity — the credentials in the
  provider's config section (API key, ServiceAccount, IAM role).
- `mode: user`: executions run under the invoking user's identity. The principal is resolved
  per-invocation by a **pluggable resolver**:

```python
class PrincipalResolver(ABC):
    @abstractmethod
    async def resolve(self, session: Session, agent: Agent) -> SandboxPrincipal: ...
```

- Default resolver: returns the agent-mode principal (subject = agent name).
- Applications supply their own resolver (public API) to map their authentication context —
  e.g. read a user token their API layer stored in `session.nv_cache` — into a principal.
  Configured via `sandbox.policy.principal_resolver` (dotted path).
- A provider that cannot honor `mode: user` declares `principal_user = False`; requesting a
  user-mode principal against it raises `SandboxCapabilityError` **before** any execution
  (fail closed — never silently fall back to the agent identity).

Provider mapping requirements (v1):

| Provider | `agent` mode | `user` mode |
|---|---|---|
| `kubernetes` | kubeconfig / in-cluster ServiceAccount | RBAC **impersonation** (`Impersonate-User` / `Impersonate-Group` headers from the principal) — the K8s API server then enforces the user's own RBAC |
| `bedrock_agentcore` | default boto3 credential chain | `sts:AssumeRole` using a role ARN supplied by the principal's credentials |
| `e2b` | workspace API key | not supported in v1 (`principal_user = False`) |
| `docker` | local daemon access | not supported in v1 (`principal_user = False`) |

### 6.2 Policy

```python
class SandboxPolicy(BaseModel):
    network_egress: Literal["allow", "deny", "allowlist"] = "allow"
    network_allow: list[str] = []       # domains and/or CIDRs, meaningful when egress="allowlist"
    fs_allow_read: list[str] = []       # empty = provider default
    fs_allow_write: list[str] = []
    cpu: float | None = None            # cores
    memory_mb: int | None = None
    timeout: float = 120.0              # per-execution wall clock, seconds
    strict: bool = True
```

Enforcement rules:

- Policy comes from config (`sandbox.policy`), is resolved once per sandbox creation, and is
  passed to `create()`/`attach()`. Providers map each dimension to their native mechanism
  (Docker: network mode + mounts + cgroup limits; E2B: sandbox network config; Kubernetes:
  Job/pod securityContext + resources; Bedrock: session network mode).
- **Fail closed**: if `strict` is true (default) and the policy requests a constraint the
  provider's capabilities declare unenforceable (e.g. `network_egress: allowlist` on a provider
  with `policy_network = False`), sandbox creation raises `SandboxCapabilityError`. With
  `strict: false`, creation proceeds and a warning is logged once per provider naming every
  unenforced dimension.
- `timeout` is always enforced: natively where the backend supports it, otherwise by the
  framework cancelling the call and raising `SandboxTimeoutError`.
- Default `network_egress` is `allow` (matching every surveyed provider's default and keeping
  `pip install` working out of the box); the documentation for this capability **must** show the
  locked-down configuration prominently.

## 7. Factory, Registration, and BYO Providers

```python
# agentkernel/sandbox/factory.py
class SandboxProviderFactory:
    @classmethod
    def get(cls) -> SandboxProvider | None: ...
```

- Returns `None` when `sandbox.enabled` is false (capability fully inert: no tools registered,
  no imports of provider SDKs).
- `sandbox.type` accepts:
  - a **built-in short name**: `docker`, `e2b`, `bedrock_agentcore`, `kubernetes` — resolved via
    lazy import of the corresponding module (guardrail pattern). Missing optional dependency
    raises `ImportError` with the exact `pip install "agentkernel[<extra>]"` remedy.
  - a **dotted path**: any importable `module.path.ClassName` whose class subclasses
    `SandboxProvider` — this is the open, no-registry BYO mechanism (AutoGen `Component`
    pattern). Its provider-specific config is taken from `sandbox.params` (free-form mapping,
    validated by the provider's own Pydantic config model).
- Unknown short name / unimportable path / class not subclassing `SandboxProvider` →
  `SandboxConfigError` naming the value.
- The factory constructs exactly one provider instance per process (singleton per config), and
  it is created lazily on first use, not at import time.

## 8. Lifecycle and Session Binding

- `sandbox.scope: per_session` (default) — first sandbox-tool invocation in a session creates the
  sandbox; its `id` (plus provider type) is stored in `session.nv_cache["sandbox"]`; subsequent
  turns `attach()` (providers without attach keep a live in-process handle and recreate when it
  is gone — acceptable for `docker`). The stored id is cleared when `destroy` succeeds or attach
  reports the sandbox no longer exists (in which case a fresh one is created transparently).
- `sandbox.scope: per_