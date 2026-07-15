# Agent Kernel Sandbox Capability — Specification

Status: **draft for review** · Author: yaalalabs · Date: 2026-07-14

This spec proposes a generic, pluggable **sandbox capability** for Agent Kernel: a
framework-agnostic way for agents to execute code and commands, work in an isolated
workspace, or attach to an existing runtime — behind one interface, with no vendor lock-in,
and with a permission boundary as a first-class concern.

Design decisions here are grounded in three research references in this directory; where a
decision cites prior art, the citation points at one of them:

- [references/ak-codebase-patterns.md](references/ak-codebase-patterns.md) — how AK's existing
  pluggable capabilities are built (the patterns this spec follows).
- [references/provider-landscape.md](references/provider-landscape.md) — the backend survey and
  cross-cutting capability matrix (why the interface is shaped the way it is).
- [references/framework-abstractions.md](references/framework-abstractions.md) — prior art from 9
  agent frameworks (the interface-design lessons applied here).

---

## 1. Motivation

Agents increasingly need to run code (data analysis, computation, tool-building), operate in a
persistent workspace (multi-step file editing, package installation), or act against an existing
system (a Kubernetes controller host, a data platform) under a controlled permission boundary.

Today AK has **no sandbox/code-execution surface at all** — this is greenfield
([ak-codebase-patterns §1](references/ak-codebase-patterns.md)). Where users want code execution,
they configure a native framework executor on the underlying agent themselves (smolagents
`executor_type`, CrewAI `allow_code_execution`, ADK `code_executor`), which AK neither exposes nor
abstracts. That reproduces exactly the vendor lock-in AK exists to avoid: swapping E2B for a local
Docker sandbox, or for AWS Bedrock AgentCore, means rewriting agent wiring rather than changing a
config value.

This capability makes the sandbox a pluggable AK component — like guardrails, tracing, and
knowledge bases — selected by configuration, extensible by third parties, and uniform across the
supported agent frameworks.

---

## 2. Goals and non-goals

### 2.1 Goals

- **G1** — Provide a single framework-agnostic `Sandbox` interface that AK code and agents use
  regardless of the concrete backend.
- **G2** — Support three usage modes behind that one interface: (a) code-execution tool, (b)
  persistent sandboxed workspace, (c) attach-to-existing-runtime (see §4).
- **G3** — Make the **permission boundary** a first-class, cross-cutting concern for all three
  modes, supporting both **agent-own identity** and **user-assumed identity** (see §8).
- **G4** — Ship a small set of well-supported first-party backends spanning cloud SaaS,
  self-hosted, and cloud-provider-native deployment models (see §11).
- **G5** — Let third parties register their own backend with **no code change in AK** (see §10).
- **G6** — Follow AK's established pluggable-capability conventions (factory + `AKConfig` section +
  optional-dependency extras + internal implementation with a public BYO base class), so the
  capability is consistent with guardrails/multimodal/knowledgebase
  ([ak-codebase-patterns §3](references/ak-codebase-patterns.md)).
- **G7** — Be async-first, matching AK's async core (`Runner.run`, `Runtime.run`).

### 2.2 Non-goals

- **N1** — Not a general VM/container orchestration platform; AK provisions and drives sandboxes,
  it does not schedule cluster capacity.
- **N2** — Not a replacement for AK's deployment adapters (Lambda/ECS/Azure Functions). A sandbox
  is where *agent-invoked code* runs, not where the *agent process* is deployed.
- **N3** — Not a guarantee of uniform security across backends. Isolation is a spectrum (shared-
  kernel namespaces → syscall interception → microVM → WASM); each backend **declares** its
  isolation tier, and AK never implies backends are interchangeable on security grounds
  ([provider-landscape §E](references/provider-landscape.md), "sandboxed is a spectrum, not a
  checkbox").
- **N4** — This spec does **not** define the Google Vertex AI backend; that provider was not
  researched ([provider-landscape §G](references/provider-landscape.md)) and is explicitly deferred
  (see §14).

---

## 3. Design principles (alignment with AK architecture)

Per `ak-dev-architecture`, this capability MUST:

- **P1** — Live in its own subpackage `ak-py/src/agentkernel/sandbox/` (top-level, alongside
  `guardrail/` and `knowledgebase/`). The framework-agnostic core (`agentkernel/core/`) MUST NOT
  import from it; the sandbox package MAY import from core.
- **P2** — Contain **no framework-specific imports**. Backends talk to provider SDKs, never to
  `framework/openai`, `framework/crewai`, etc.
- **P3** — Be governed entirely by `AKConfig` (a new `sandbox:` section, §9), env-overridable via
  the `AK_SANDBOX__…` prefix. No module-level constants or ad-hoc `os.environ` reads outside the
  config layer.
- **P4** — Be instantiated through a **factory** (`SandboxFactory`, §10), not `if/else` chains in
  core. Disabled-by-default; a no-op/absent capability when `sandbox.enabled` is false.
- **P5** — Keep concrete backends internal; expose publicly only what a third party must subclass
  or construct — the `Sandbox` base class, the request/result/policy/identity data types, the
  capability enum, and the factory registration entry point
  ([ak-codebase-patterns §5](references/ak-codebase-patterns.md)).
- **P6** — Respect the session lifecycle: sandbox state that must survive across requests is
  persisted through AK's `Session` (`nv_cache`), not held on module globals (§7).

---

## 4. Usage modes

The interface MUST serve all three modes; a design that serves only mode 1 is insufficient (G2).

- **Mode 1 — Code-execution tool.** An agent calls a tool to run LLM-generated code/commands
  safely. Sandbox may be per-call or per-session. This is the common "code interpreter" shape.
- **Mode 2 — Sandboxed workspace.** A persistent isolated environment bound to a `Session`: the
  agent reads/writes files, installs packages, and works across turns. Requires a stateful,
  reconnectable sandbox.
- **Mode 3 — Attach to existing runtime.** Instead of provisioning an isolated sandbox, AK
  connects to an already-running execution environment (e.g. a Kubernetes controller host of a
  distributed system) under a tightly controlled permission boundary. Requires the backend to
  support **attach** (§6.4) and is the mode where RBAC (§8) matters most.

The mode is a function of configuration (`sandbox.lifecycle` + whether `attach_to` is set), not a
separate interface per mode.

---

## 5. Core interface

Async ABC, modeled on the closest usable prior art — Microsoft AutoGen 0.4's `CodeExecutor`
(async, `start`/`stop`, `CancellationToken`, async context manager), which is a deliberate async
redesign of an older sync interface, so its choices reflect lessons learned
([framework-abstractions §2b, §Synthesis](references/framework-abstractions.md)).

```python
class Sandbox(ABC):
    """A pluggable code/command execution environment.

    Concrete backends subclass this. The only REQUIRED operation is `execute`; every
    richer operation (files, network policy, ports, snapshots, reset, streaming) is an
    OPTIONAL capability declared via `capabilities` and, if unsupported, raises
    SandboxCapabilityError from the base implementation.
    """

    # --- identity & introspection -------------------------------------------------
    @property
    @abstractmethod
    def capabilities(self) -> "SandboxCapabilities": ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...

    # --- lifecycle ----------------------------------------------------------------
    @abstractmethod
    async def start(self) -> None:
        """Provision a new sandbox, or attach to an existing one when the backend is
        configured with an `attach_to` target (see §6.4). Idempotent."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear down (provisioned) or disconnect from (attached) the sandbox. Idempotent."""

    async def __aenter__(self) -> "Sandbox":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    # --- the one required operation ----------------------------------------------
    @abstractmethod
    async def execute(self, request: "SandboxExecRequest") -> "SandboxExecResult":
        """Run code (or a shell command, as `language="bash"`) and return the result.

        Raises SandboxTimeoutError on timeout, SandboxPolicyError if the active policy
        cannot be enforced, SandboxError for backend failures."""

    # --- optional operations (default: declare unsupported) ----------------------
    async def reset(self) -> None:
        """Reset in-sandbox state (variables/kernel) without full teardown.
        Requires capabilities.resettable."""
        raise SandboxCapabilityError(self.backend_name, "reset")

    async def upload(self, files: "list[SandboxFile]", dest: str = ".") -> None:
        """Requires capabilities.filesystem."""
        raise SandboxCapabilityError(self.backend_name, "upload")

    async def download(self, paths: "list[str]") -> "list[SandboxFile]":
        """Requires capabilities.filesystem."""
        raise SandboxCapabilityError(self.backend_name, "download")

    async def install_packages(self, packages: "list[str]", *, language: str = "python") -> None:
        """Requires capabilities.package_install."""
        raise SandboxCapabilityError(self.backend_name, "install_packages")

    async def expose_port(self, port: int) -> str:
        """Expose a port, returning a preview URL. Requires capabilities.port_exposure."""
        raise SandboxCapabilityError(self.backend_name, "expose_port")

    async def snapshot(self) -> "SandboxSnapshot":
        """Requires capabilities.snapshot."""
        raise SandboxCapabilityError(self.backend_name, "snapshot")

    def execute_stream(self, request: "SandboxExecRequest") -> "AsyncIterator[SandboxStreamChunk]":
        """Streaming variant. Requires capabilities.streaming."""
        raise SandboxCapabilityError(self.backend_name, "execute_stream")
```

Rationale for a single required method: the required surface must be satisfiable by the narrowest
important backends. AWS Bedrock AgentCore and Azure Container Apps dynamic sessions — both
first-party targets (§11) — **structurally cannot** offer a general shell, ports, or pause/resume;
they only "POST code, get JSON back" ([provider-landscape §D](references/provider-landscape.md)).
Every framework in the survey that defines a real abstraction converges on the same minimal core
plus optional extras ([framework-abstractions §Synthesis](references/framework-abstractions.md)).
Shell access is unified into `execute` by treating it as `language="bash"`, the lowest-common-
denominator shape ([provider-landscape §D](references/provider-landscape.md)).

---

## 6. Data types

All data types are Pydantic `BaseModel`s (per code-quality conventions) except where a frozen
dataclass reads better.

### 6.1 Request / result

```python
class SandboxFile(BaseModel):
    path: str
    content: bytes            # base64 on the wire; bytes in memory
    mime_type: str = "application/octet-stream"

class SandboxExecRequest(BaseModel):
    code: str
    language: str = "python"          # "python" | "bash" | "javascript" | ...
    input_files: list[SandboxFile] = []
    env: dict[str, str] = {}
    timeout: float | None = None      # seconds; None => backend/policy default
    stateful: bool | None = None      # None => backend/config default (see §7)

class SandboxExecResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    output_files: list[SandboxFile] = []
    artifacts: list[SandboxArtifact] = []   # rich outputs: images, dataframes, plots
    timed_out: bool = False
    provider_data: dict[str, Any] = {}       # backend-specific escape hatch

class SandboxArtifact(BaseModel):
    kind: Literal["image", "html", "json", "table", "other"]
    mime_type: str
    data: bytes

class SandboxStreamChunk(BaseModel):
    stream: Literal["stdout", "stderr"]
    data: str
```

`provider_data` is a deliberate escape-hatch bag for backend-specific fields that don't fit the
common schema, borrowed from the OpenAI Agents SDK
([framework-abstractions §4](references/framework-abstractions.md)); it MUST NOT be required for
correct operation of framework-agnostic callers.

### 6.2 Capabilities

Every backend MUST declare its capabilities. No framework surveyed does formal capability
negotiation; they lean on duck typing or a single flag. AK uses a **typed flags object** because
it is more discoverable than duck typing and every backend — even the narrow Azure/Bedrock
contract — can declare its flags honestly
([framework-abstractions §Synthesis](references/framework-abstractions.md)).

```python
class IsolationTier(str, Enum):
    NONE = "none"                 # in-process / same host, not a security boundary
    NAMESPACE = "namespace"       # shared-kernel containers (Docker/Podman)
    SYSCALL_FILTER = "syscall"    # gVisor-style user-space kernel / seccomp
    MICROVM = "microvm"           # Firecracker/Kata/libkrun hardware isolation
    WASM = "wasm"                 # WebAssembly, no ambient syscalls

class SandboxCapabilities(BaseModel):
    isolation: IsolationTier
    filesystem: bool = False
    package_install: bool = False
    network_policy: bool = False   # can ENFORCE an egress policy (see §8.3)
    port_exposure: bool = False
    snapshot: bool = False
    resettable: bool = False
    streaming: bool = False
    stateful_sessions: bool = False
    attachable: bool = False       # supports mode 3 (attach to existing runtime)
    languages: list[str] = ["python"]
```

### 6.3 Snapshot handle

```python
class SandboxSnapshot(BaseModel):
    id: str
    backend: str
    provider_data: dict[str, Any] = {}
```

### 6.4 Provision vs. attach

The framework survey found that "provision new" and "connect to an identifier of one that already
exists" are distinct operations conflated by most tools; ADK's `VertexAiCodeExecutor`
(`resource_name`) and OpenHands' `RemoteRuntime.connect()` hint at separating them
([framework-abstractions §6, §8a, §Synthesis](references/framework-abstractions.md)).

AK models this at configuration time, not with two constructors: a backend config MAY carry an
`attach_to` identifier. When set, `start()` attaches to the existing runtime (mode 3) and MUST NOT
provision new compute; the backend MUST declare `capabilities.attachable == True` or `start()`
raises `SandboxCapabilityError`. When unset, `start()` provisions.

---

## 7. State and lifecycle

### 7.1 Lifecycle binding

`sandbox.lifecycle` config (§9) selects when a sandbox is created and destroyed:

- `call` — a fresh sandbox per tool invocation; torn down after. Cheapest to reason about; fits
  mode 1 with stateless backends. Note: recreate-per-call is the documented cause of the "Docker
  is slow" complaints across AutoGen and CrewAI
  ([framework-abstractions §2, §5](references/framework-abstractions.md)), so it is not the default.
- `session` (**default**) — one sandbox per AK `Session`, reused across turns, reconnected on
  subsequent requests. Fits modes 2 and 3.
- `runtime` — a shared/pooled sandbox for the process lifetime. For stateless high-throughput
  mode-1 use.

### 7.2 Persisting sandbox state across requests

Following Google ADK's `CodeExecutorContext` insight — externalize the execution *session* into
the host framework's own session store rather than the executor object's memory
([framework-abstractions §6, §Synthesis](references/framework-abstractions.md)) — AK persists the
handle needed to reconnect (sandbox id, or serialized `session_bytes` for backends that use the
client-held-state model like `langchain-sandbox`) in the AK `Session.nv_cache`. The backend is
therefore not responsible for owning session storage; it rides on whatever session store AK is
already configured with (in-memory/Redis/DynamoDB/…).

Three state models exist in the wild and AK MUST accommodate all three behind one interface
([provider-landscape §D](references/provider-landscape.md),
[framework-abstractions §Synthesis](references/framework-abstractions.md)):

1. server-held session-by-identifier (E2B/Daytona/Modal, Azure, Bedrock) — persist the id;
2. client-held serialized state (`langchain-sandbox` `session_bytes`) — persist the blob;
3. no state (WASM per-call) — `stateful` requests either simulate via (2) or raise
   `SandboxCapabilityError` if `stateful_sessions` is false.

### 7.3 Cleanup discipline

`session`/`runtime`-bound sandboxes MUST be torn down deterministically. smolagents has multiple
issues about orphaned Docker containers from missing finalizers
([framework-abstractions §1](references/framework-abstractions.md)); AK MUST NOT repeat this. The
`SandboxManager` (§12) registers teardown via the session's close path and a process-level
`atexit`/signal fallback for `runtime`-bound sandboxes.

---

## 8. Permission boundary (RBAC) — the differentiating requirement

This is a first-class, cross-cutting requirement for **all** modes (G3). No framework or provider
surveyed models it as part of the sandbox interface
([provider-landscape §F.3](references/provider-landscape.md),
[framework-abstractions §Synthesis pt 5](references/framework-abstractions.md)) — this is original
design.

### 8.1 Identity: two modes

```python
class IdentityMode(str, Enum):
    AGENT = "agent"   # the agent has its own scoped identity/role
    USER = "user"     # the agent assumes the invoking user's identity for the execution

class SandboxIdentity(BaseModel):
    mode: IdentityMode
    subject: str                       # agent name, or resolved user id
    roles: list[str] = []
    claims: dict[str, Any] = {}        # arbitrary identity claims (e.g. tenant, groups)
```

- **Agent-own** (`agent`, default): the identity/roles come from the agent's configuration.
- **User-assumed** (`user`): the invoking user's identity is resolved from the AK `Session` /
  `ToolContext` at execution time. If mode is `user` but no user identity is available on the
  session, execution MUST fail closed (`SandboxPolicyError`), never silently fall back to a
  broader identity.

### 8.2 Credential resolution

Backends need concrete credentials for the resolved identity. Rather than hardcoding one cloud SDK
credential type, AK uses a small injected resolver Protocol — the shape borrowed from Azure's
`TokenProvider`, the one prior-art seam that comes closest
([framework-abstractions §2b, §Synthesis pt 5](references/framework-abstractions.md)):

```python
class CredentialResolver(Protocol):
    async def resolve(self, identity: SandboxIdentity, backend: str) -> "SandboxCredentials": ...
```

Each backend maps the resolved identity+credentials to its native mechanism:

- Docker/Podman → container `user` (UID/GID), dropped Linux capabilities, seccomp profile,
  read-only mounts.
- Kubernetes (attach, mode 3) → impersonation headers (`user`) or a scoped ServiceAccount token
  (`agent`).
- AWS Bedrock AgentCore → an assumed IAM role scoped to the identity.
- Azure dynamic sessions → an Entra bearer token scoped to the session pool + role assignment.

### 8.3 Policy: what the execution may do

```python
class NetworkPolicy(BaseModel):
    default: Literal["deny", "allow"] = "deny"   # deny-by-default
    allow_domains: list[str] = []
    allow_cidrs: list[str] = []
    deny_domains: list[str] = []
    deny_cidrs: list[str] = []

class FilesystemPolicy(BaseModel):
    allow_read: list[str] = []
    deny_read: list[str] = []
    allow_write: list[str] = []
    deny_write: list[str] = []

class ResourceLimits(BaseModel):
    max_runtime_seconds: float | None = None
    max_memory_mb: int | None = None
    max_processes: int | None = None

class SandboxPolicy(BaseModel):
    network: NetworkPolicy = NetworkPolicy()
    filesystem: FilesystemPolicy = FilesystemPolicy()
    resources: ResourceLimits = ResourceLimits()
```

Network egress control is near-universal among serious backends but with incompatible shapes
(E2B CIDR, Modal CIDR+domain, Daytona CIDR, Runloop policies, Anthropic srt proxy allowlist)
([provider-landscape §F.5](references/provider-landscape.md)); `NetworkPolicy` is the normalized
form each backend maps to its native mechanism. Egress control is security-relevant, not cosmetic:
public research has demonstrated DNS-exfiltration/credential-extraction against AWS AgentCore's
*default* network mode ([provider-landscape §A3, §E](references/provider-landscape.md)).

### 8.4 Fail-closed enforcement

If a `SandboxPolicy` is set that a backend **cannot enforce** (e.g. a `NetworkPolicy` on a backend
with `capabilities.network_policy == False`), `start()`/`execute()` MUST raise `SandboxPolicyError`
— never silently ignore the policy. A non-default policy against an unenforcing backend is a
configuration error, surfaced loudly.

### 8.5 Composition at execution time

Identity + policy are resolved per-run from config defaults overlaid with anything the
`ToolContext`/`Session` supplies, then passed to the backend at `start()` (for provisioning-time
enforcement) and carried on each `execute()` (for per-call enforcement where the backend supports
it).

---

## 9. Configuration

A new `sandbox:` section on `AKConfig`, registered near the other capability sections
([ak-codebase-patterns §3d](references/ak-codebase-patterns.md)). Backend selection is a single
`backend` key; each backend has its own optional sub-model, and the factory raises if the selected
backend's sub-block is missing (mirroring `_MultimodalConfig`/`storage_type`).

```yaml
sandbox:
  enabled: false                 # disabled by default (P4)
  backend: local_docker          # built-in short name OR dotted path "mypkg.MySandbox" (§10)
  lifecycle: session             # call | session | runtime
  default_language: python
  expose_as_tool: true           # auto-register the code-execution SystemTool (§11-agent-surface)

  identity:
    mode: agent                  # agent | user

  policy:
    network:
      default: deny
      allow_domains: []
    filesystem:
      allow_write: ["/workspace"]
    resources:
      max_runtime_seconds: 120

  # backend sub-models (only the selected one is required)
  local_docker:
    image: "python:3.12-slim"
    runtime: docker              # docker | podman
    attach_to: null              # set for mode 3 attach
  e2b:
    api_key_env: E2B_API_KEY
    template: base
  aws_bedrock_agentcore:
    region: us-east-1
    network_mode: sandbox
  azure_dynamic_sessions:
    pool_management_endpoint: "https://…"
  kubernetes:
    attach_to: "cluster/namespace"   # mode 3
    image: "python:3.12-slim"
```

All keys are env-overridable via `AK_SANDBOX__…` (e.g. `AK_SANDBOX__E2B__API_KEY`,
`AK_SANDBOX__POLICY__NETWORK__DEFAULT`). Secrets are referenced by env-var name
(`api_key_env`) rather than embedded, consistent with code-quality conventions (no secrets in
config).

---

## 10. Factory and third-party registration

`SandboxFactory.get()` reads `AKConfig.get().sandbox`, and:

1. returns a disabled/no-op state when `sandbox.enabled` is false (P4);
2. resolves `backend`:
   - a **built-in short name** (`local_docker`, `e2b`, `aws_bedrock_agentcore`,
     `azure_dynamic_sessions`, `kubernetes`, `local_subprocess`) → lazy import of the first-party
     module, raising an actionable `ImportError` naming the extra to install if the optional
     dependency is absent (the guardrail/AG2 pattern,
     [framework-abstractions §2a](references/framework-abstractions.md));
   - otherwise a **dotted import path** (`"mypkg.MySandbox"`) → import and use it.
3. validates the selected backend's config sub-block is present, raising `ValueError` if not
   ([ak-codebase-patterns §3b](references/ak-codebase-patterns.md)).

The dotted-path branch is the key no-vendor-lock-in mechanism (G5): a third party ships
`pip install ak-sandbox-mything`, sets `backend: "ak_sandbox_mything.MySandbox"`, and needs **no
change in AK**. This is a deliberate step beyond AK's existing closed-enum guardrail factory,
adopting AutoGen 0.4's open `Component`/dotted-path idea — judged the single strongest pattern in
the survey for avoiding lock-in
([framework-abstractions §Synthesis pt 2](references/framework-abstractions.md)). Built-in short
names are retained purely for convenience.

A third-party backend MUST: subclass `Sandbox`, implement `execute`/`start`/`stop`/`capabilities`/
`backend_name`, declare its `SandboxCapabilities` honestly, and accept its config as a Pydantic
model. It SHOULD implement whichever optional operations its capabilities advertise.

---

## 11. Exposure to agents and first-party backends

### Agent surface

The sandbox reaches agents two ways, both framework-agnostic:

- **As a `SystemTool`** (default when `expose_as_tool: true`), auto-registered on all agents when
  the capability is enabled — mirroring how multimodal auto-registers `AnalyzeAttachmentsTool`
  ([ak-codebase-patterns §3c](references/ak-codebase-patterns.md)). It exposes `run_code(code,
  language)` and, where the backend supports it, file operations. Serves mode 1.
- **As a session-scoped workspace** reachable from any tool via `ToolContext` (`Sandbox.current()`
  analogous to `Session.current()`), for authors writing their own tools against the workspace.
  Serves modes 2 and 3.

The `SystemTool` wiring point is where multimodal/guardrail factories are constructed in
`core/runtime.py` ([ak-codebase-patterns §3c](references/ak-codebase-patterns.md)).

### First-party backends (spanning all three deployment models, G4)

| Backend key | Model | Isolation | Modes | Notes |
|---|---|---|---|---|
| `local_docker` | Self-hosted | namespace | 1,2,3 | Docker/Podman; the OSS default. Attach via `attach_to`. |
| `e2b` | Cloud SaaS | microVM | 1,2 | Reference cloud backend; rich files/network/snapshot. |
| `aws_bedrock_agentcore` | Cloud-native | managed container | 1 | Narrow POST-code contract; aligns with AK's AWS adapters. |
| `azure_dynamic_sessions` | Cloud-native | Hyper-V | 1 | Narrow contract; code-only, 220s cap. |
| `kubernetes` | Self-hosted / attach | namespace (or runtime-class) | 3 | Headline mode-3 backend: attach to an existing cluster under RBAC. |
| `local_subprocess` | Local dev only | **none** | 1 | Explicitly labeled *not a security boundary*; for tests/dev only, refuses to run untrusted input without opt-in. |

Suggested phasing (non-binding): Phase 1 `local_docker` + `e2b` + `local_subprocess`; Phase 2
`aws_bedrock_agentcore` + `kubernetes`; Phase 3 `azure_dynamic_sessions`. Google Vertex AI is
deferred pending research (§14, N4).

`local_subprocess` exists as the honestly-labeled unsafe baseline (like ADK's
`UnsafeLocalCodeExecutor` / smolagents' `LocalPythonExecutor`, both of which carry explicit
"not a security boundary" disclaimers) — it MUST declare `IsolationTier.NONE` and MUST log a
prominent warning on construction. AK MUST NOT default to it.

---

## 12. `SandboxManager`

A high-level façade (like `AttachmentStorageManager`,
[ak-codebase-patterns §3b](references/ak-codebase-patterns.md)) that AK code and the SystemTool use
instead of talking to backends directly. It owns: resolving the configured backend via the factory,
lifecycle binding (§7.1), session persistence/reconnect (§7.2), identity+policy composition (§8.5),
and teardown registration (§7.3). Backends stay small; the manager holds the cross-cutting logic.

---

## 13. Error handling

Typed exception hierarchy in `sandbox/errors.py`:

- `SandboxError(Exception)` — base.
- `SandboxCapabilityError(SandboxError)` — an operation the backend doesn't support (carries
  backend name + operation).
- `SandboxPolicyError(SandboxError)` — a policy cannot be enforced (§8.4) or was violated.
- `SandboxTimeoutError(SandboxError)` — execution exceeded its timeout.
- `SandboxProvisionError(SandboxError)` — provisioning/attach failed.

Failures MUST surface meaningfully (no silent `except: pass`), resources MUST be released in
`finally`, and unenforceable policy MUST fail closed (§8.4).

---

## 14. Testing

Per `ak-dev-testing-conventions`, in a consolidated `ak-py/tests/test_sandbox.py`:

- **Fake backend** — an in-memory `Sandbox` implementation used across tests (no Docker, no
  network), analogous to the in-memory attachment store. Declares a full capability set so optional
  operations are exercised.
- **Capability-matrix tests** — every optional operation raises `SandboxCapabilityError` on a
  backend that declares it unsupported; succeeds where declared supported.
- **Policy enforcement** — a non-default `NetworkPolicy` against a backend with
  `network_policy=False` raises `SandboxPolicyError` (§8.4); `identity.mode=user` with no user on
  the session fails closed (§8.1).
- **Factory resolution** — built-in short name lazy-imports; missing extra raises an actionable
  `ImportError`; dotted path resolves a third-party class; missing config sub-block raises
  `ValueError`; disabled config yields the no-op state.
- **Session round-trip** — a `session`-bound sandbox persists its reconnect handle in `nv_cache`
  and reconnects on a subsequent request; teardown fires on session close (§7.3).
- **Async correctness** — `pytest.mark.asyncio`, no blocking I/O in async paths, deterministic
  teardown.

No test may make real network calls or require a running Docker daemon; backend-specific
integration tests (if any) are marked and skipped by default.

---

## 15. Documentation and examples

- A user-facing docs page under `docs/docs/advanced/` describing the capability, config keys,
  backends, and the RBAC model.
- The new config section documented where configuration is described (`ak-py/README.md` and the
  docs site).
- At least one example under `examples/cli/sandbox/` per shipped backend that has no external
  paid dependency (at minimum `local_docker`).
- A contributor guide skill `ak-dev-new-sandbox-provider` (cloning the structure of
  `ak-dev-new-guardrail-provider`) once the interface lands, so adding a backend follows a
  documented checklist.

---

## 16. Open questions and deferrals

- **OQ1** — Google Vertex AI backend is unspecified pending research (N4,
  [provider-landscape §G](references/provider-landscape.md)).
- **OQ2** — Whether `execute_stream` should integrate with AK's existing token-streaming path
  (`PostHook.on_stream_chunk`) or remain a separate sandbox-output stream. Leaning separate, since
  sandbox stdout is not LLM tokens.
- **OQ3** — Whether `local_subprocess` belongs in the shipped package at all, or only in test
  fixtures. Leaning: ship it, loudly labeled, because a zero-dependency dev backend materially
  lowers the barrier to trying the capability.
- **OQ4** — Exact `CredentialResolver` default implementations per cloud (deferred to each
  backend's implementation PR).
- **OQ5** — Pooling/warm-start for `runtime` lifecycle (a performance concern; deferred).

---

## 17. Requirements checklist

Extractable "must" statements for review/implementation tracking:

- [ ] Sandbox capability lives in `agentkernel/sandbox/`; core does not import it (P1, P2).
- [ ] `Sandbox` ABC with the exact required surface in §5 (`execute`, `start`, `stop`,
      `capabilities`, `backend_name`); optional operations raise `SandboxCapabilityError` by
      default.
- [ ] Data types per §6 (Pydantic), including `SandboxCapabilities` with `IsolationTier`.
- [ ] Provision-vs-attach via `attach_to` config; attach requires `capabilities.attachable` (§6.4).
- [ ] Three lifecycle bindings (`call`/`session`/`runtime`), default `session` (§7.1).
- [ ] Cross-request state persisted through AK `Session.nv_cache`; all three state models
      supported (§7.2).
- [ ] Deterministic teardown; no orphaned sandboxes (§7.3).
- [ ] `SandboxIdentity` with `agent`/`user` modes; `user` with no session identity fails closed
      (§8.1).
- [ ] `CredentialResolver` Protocol; backends map identity to native mechanism (§8.2).
- [ ] `SandboxPolicy` (network/filesystem/resources), deny-by-default network (§8.3).
- [ ] Unenforceable policy fails closed with `SandboxPolicyError` (§8.4).
- [ ] `sandbox:` `AKConfig` section per §9, env-overridable, secrets by env-var name.
- [ ] `SandboxFactory` with built-in-short-name lazy import **and** dotted-path third-party
      resolution; no-op when disabled; `ValueError` on missing sub-block (§10, G5).
- [ ] Agent surface: auto-registered `SystemTool` + session-scoped workspace (§11).
- [ ] First-party backends spanning all three deployment models (§11, G4).
- [ ] `local_subprocess` declares `IsolationTier.NONE`, warns on construction, is never the default
      (§11).
- [ ] `SandboxManager` façade holds cross-cutting logic (§12).
- [ ] Typed error hierarchy (§13).
- [ ] Tests per §14, including a fake backend, with no real network / no Docker requirement.
- [ ] Docs, example, and `ak-dev-new-sandbox-provider` contributor skill (§15).
- [ ] Only the public surface (base class, data types, factory registration) is exported; concrete
      backends stay internal (P5).
