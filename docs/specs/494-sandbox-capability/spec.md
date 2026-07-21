# #494: Sandbox capability — Implementation Spec

> Status: **Approved** — spec review completed 2026-07-17 (PR #364). Stage 2 of the approved
> design ([design.md](design.md), review completed 2026-07-16). Both stages ship on this branch
> deliberately (fast-moving single-branch flow). Stage 3: [plan.md](plan.md).

This spec details the implementation of the sandbox capability approved in
[design.md](design.md): a new `agentkernel/sandbox/` package providing the `Sandbox`/
`SandboxProvider` interfaces, sandbox sessions, the RBAC permission boundary, the
queue-decoupled sandbox broker with workload-profile routing, seven first-party providers, and
the config/factory/tool wiring that follows AK's guardrail and multimodal precedents.
[design.md](design.md) is the requirements source; this document is the how.

One deviation from the original design was found while detailing and has been accepted into the
design (design.md updated, resolution logged 2026-07-16): the task-completion re-invocation does
**not** need a new core `AgentRequest` type. Completion events ride the existing `AgentRequestAny`
channel — `BaseRunRequest` allows extra fields (`core/model.py:226`) and
`RequestBuilder._attach_additional_context` already converts unknown body fields into
`AgentRequestAny` objects handled only by pre-hooks (`core/chat_service.py:117-130`). Core is
therefore touched only at the three established wiring points (config section, system-tool
factory, system pre-hook registration).

## Design

### Package layout

```
ak-py/src/agentkernel/sandbox/
├── __init__.py            # public exports (see rule 6)
├── model.py               # data types: capabilities, result, session, task, principal, policy
├── errors.py              # SandboxError hierarchy
├── base.py                # Sandbox ABC, SandboxProvider ABC
├── principal.py           # PrincipalResolver ABC + AgentPrincipalResolver default
├── manager.py             # SandboxManager (agent-side façade, singleton)
├── factory.py             # SandboxProviderFactory + broker-flavor resolution
├── hooks.py               # SandboxPreHook + SandboxPreHookFactory (task-completion ingestion)
├── tools.py               # system tools: run_code, run_command, write/read_sandbox_file, check_sandbox_task
├── testing.py             # FakeSandboxProvider + SandboxProviderContract (public, for BYO backends)
├── broker/
│   ├── __init__.py
│   ├── base.py            # SandboxBroker ABC + message models (request/completion)
│   ├── worker.py          # BrokerWorkerCore: profile routing, enforcement, execution (shared by all flavors)
│   ├── embedded.py        # EmbeddedBroker — direct in-process call
│   └── thread.py          # ThreadBroker — daemon thread + own event loop + in-memory queues
└── providers/
    ├── __init__.py
    ├── local_subprocess.py
    ├── docker.py
    ├── e2b.py
    ├── daytona.py
    ├── bedrock_agentcore.py
    ├── kubernetes.py
    └── ec2_ssm.py

ak-py/src/agentkernel/deployment/aws/sandbox/
├── __init__.py            # exports SandboxBrokerRunner (ECS container entry point)
├── sqs_broker.py          # SQSSandboxBroker — agent-side client for the sqs flavor
├── ecs_worker.py          # SandboxBrokerRunner(ECSSQSConsumer) — server-based worker
└── lambda_worker.py       # lambda_handler — serverless worker

ak-deployment/ak-aws/common/sandbox_broker/   # terraform module (see Provisioning)
```

Governing rules:

1. `sandbox/` imports only from `agentkernel.core` (plus stdlib/pydantic). Never from
   `framework/`, `integration/`, `deployment/`, or `api/` — including no static import of the
   AWS broker flavor. The `sqs` flavor short name resolves to the dotted path
   `agentkernel.deployment.aws.sandbox.sqs_broker.SQSSandboxBroker` and is imported lazily only
   when selected (same lazy-import discipline as `guardrail/guardrail.py:25-68`).
2. **Providers never read `AKConfig`.** Each provider is constructed with its own Pydantic
   config sub-model by the factory (the multimodal-storage rule,
   `core/multimodal/storage/storage_manager.py:33-84`). `AKConfig.get()` is read only by
   `factory.py`, `manager.py`, `hooks.py`, `tools.py`, and `broker/worker.py` — the worker reads
   the profile's `identity.mode` to enforce user identity fail-closed, where the routing table
   lives (providers themselves never read `AKConfig`).
3. All I/O-performing methods are `async`. Providers wrapping synchronous SDKs (`docker`,
   `daytona`, `kubernetes`, `boto3`) run SDK calls via `asyncio.to_thread` — never blocking the
   event loop.
4. Core touches the capability at exactly three wiring points, mirroring existing precedent:
   the `sandbox:` config section (`core/config.py`), the system-tool registration
   (`core/tool.py:165-179`), and the system pre-hook list (`core/runtime.py:49`).
5. Loggers follow the hierarchy: `ak.sandbox`, `ak.sandbox.broker`, `ak.sandbox.provider.<type>`.
6. Public API (exported from `agentkernel.sandbox`): `Sandbox`, `SandboxProvider`,
   `SandboxBroker`, `PrincipalResolver`, `SandboxManager` (the supported surface for custom
   tool authors — design.md's "reach the session's sandboxes from `ToolContext` without
   touching provider APIs": inside a tool, `SandboxManager.get()` + the current `ToolContext`
   session), and the data types (`SandboxCapabilities`, `IsolationTier`, `SandboxResult`,
   `SandboxFile`, `SandboxSession`, `SandboxTask`, `SandboxPrincipal`, `SandboxPolicy`), the
   `errors` module. `SandboxProviderContract`/`FakeSandboxProvider` are public but live in and
   are imported explicitly from `agentkernel.sandbox.testing` — deliberately **not** re-exported
   from `agentkernel.sandbox` so `import agentkernel.sandbox` stays free of a pytest dependency.
   `SandboxProviderFactory`, hooks, tools, and all concrete providers/brokers stay internal
   (guardrail/multimodal export precedent).

### Data types (`sandbox/model.py`)

All Pydantic `BaseModel`s. Sketches are normative for names, fields, and defaults.

```python
class IsolationTier(str, Enum):
    NONE = "none"                      # no isolation boundary (local_subprocess, ec2_ssm)
    OS_POLICY = "os_policy"            # seccomp/Seatbelt/bubblewrap confinement
    CONTAINER = "container"            # shared-kernel namespaces (docker, kubernetes, daytona)
    SYSCALL_FILTER = "syscall_filter"  # gVisor-style user-space kernel
    MICRO_VM = "micro_vm"              # Firecracker/managed VM (e2b, bedrock_agentcore)
    WASM = "wasm"                      # in-process WASM runtime

class SandboxCapabilities(BaseModel):
    isolation: IsolationTier            # mandatory, no default — declared honestly per provider
    shell: bool = False                 # execute_command supported
    languages: list[str] = Field(default_factory=lambda: ["python"])  # languages accepted by execute_code
    files: bool = False                 # upload_file / download_file supported
    package_install: bool = False       # install_packages supported
    stateful: bool = False              # variables persist across execute_code calls in one sandbox
    attach: bool = False                # attach-to-existing supported
    principal_user: bool = False        # user-assumed identity supported
    policy_network: bool = False        # network egress policy enforceable
    policy_filesystem: bool = False     # filesystem policy enforceable
    policy_resources: bool = False      # cpu/memory limits enforceable

class SandboxFile(BaseModel):
    path: str
    content: bytes                      # bytes in memory; base64 over the wire (pydantic default)
    mime_type: str = "application/octet-stream"

class SandboxResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0                  # non-zero exit is a RESULT, not an exception
    output_files: list[SandboxFile] = Field(default_factory=list)
    sandbox_session_id: str = ""        # stamped by the manager/worker before returning
    notice: str | None = None           # machinery advisory surfaced to the agent (idle reset, self-heal recreation)
    provider_data: dict[str, Any] = Field(default_factory=dict)  # provider-specific escape hatch; never required by callers

class SandboxSession(BaseModel):
    sandbox_session_id: str             # uuid4 hex, minted by SandboxManager
    name: str | None = None             # optional human-friendly label (listings only; addressing is by id)
    profile: str                        # workload profile that created it
    provider_type: str                  # resolved backend type (e.g. "docker")
    sandbox_id: str | None = None       # provider-scoped reconnect handle; None until created
    created_at: float                   # epoch seconds
    last_used_at: float                 # epoch seconds; drives idle timeout
    status: Literal["active", "closed"] = "active"

class SandboxTask(BaseModel):
    task_id: str                        # uuid4 hex
    sandbox_session_id: str
    profile: str
    status: Literal["pending", "succeeded", "failed", "timed_out"] = "pending"
    submitted_at: float
    consumed: bool = False              # completion delivered to the agent (dedup flag)

class SandboxPrincipal(BaseModel):
    mode: Literal["agent", "user"] = "agent"
    subject: str                        # agent name, or resolved user identifier
    credentials: dict[str, Any] = Field(default_factory=dict)    # provider-interpreted (role ARN, K8s user/groups, RunAs user)
    groups: list[str] = Field(default_factory=list)

class SandboxPolicy(BaseModel):
    network_egress: Literal["allow", "deny", "allowlist"] = "allow"
    network_allow: list[str] = Field(default_factory=list)       # domains and/or CIDRs when egress == "allowlist"
    fs_allow_read: list[str] = Field(default_factory=list)       # empty = provider default
    fs_allow_write: list[str] = Field(default_factory=list)
    cpu: float | None = None            # cores
    memory_mb: int | None = None
    timeout: float = 120.0              # per-execution wall clock, seconds
    strict: bool = True                 # fail closed on unenforceable dimensions
```

Result semantics: a failing *program* (compile error, exception, non-zero exit) returns a
`SandboxResult` with `exit_code != 0` and diagnostics in `stderr`. Exceptions are reserved for
failures of the sandbox *machinery* (see Error handling).

### `Sandbox` and `SandboxProvider` ABCs (`sandbox/base.py`)

```python
class Sandbox(ABC):
    """Handle to one live sandbox. Created by a SandboxProvider, never constructed directly."""

    id: str   # provider-scoped identifier, stable across attach/reconnect

    @abstractmethod
    async def execute_code(self, code: str, language: str = "python",
                           timeout: float | None = None) -> SandboxResult: ...

    async def execute_command(self, command: str, timeout: float | None = None) -> SandboxResult:
        raise SandboxCapabilityError(self.__class__.__name__, "shell")

    async def upload_file(self, path: str, content: bytes) -> None:
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def download_file(self, path: str) -> bytes:
        raise SandboxCapabilityError(self.__class__.__name__, "files")

    async def install_packages(self, packages: list[str]) -> SandboxResult:
        raise SandboxCapabilityError(self.__class__.__name__, "package_install")

    @abstractmethod
    async def close(self) -> None:
        """Idempotent. Releases the live handle; for per_session scope this must NOT
        destroy backend state needed for a later attach()."""


class SandboxProvider(ABC):
    """One per configured profile backend. Constructed by the factory; long-lived."""

    capabilities: ClassVar[SandboxCapabilities]

    def __init__(self, config: BaseModel): ...   # provider-specific config model, injected

    @abstractmethod
    async def create(self, *, principal: SandboxPrincipal, policy: SandboxPolicy) -> Sandbox: ...

    async def attach(self, sandbox_id: str, *, principal: SandboxPrincipal,
                     policy: SandboxPolicy) -> Sandbox:
        raise SandboxCapabilityError(self.__class__.__name__, "attach")

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """Permanently dispose backend state. Idempotent; unknown ids are a no-op."""
```

Semantics:

1. `execute_code` with `language="python"` is mandatory for every provider; requesting an
   undeclared language raises `SandboxCapabilityError` naming the language.
2. `attach()` for a sandbox the backend reports as gone raises `SandboxGoneError` (a
   `SandboxProvisionError` subclass) — the signal the manager/worker uses to self-heal by
   recreating under the same `sandbox_session_id`.
3. Timeout: the effective timeout is `min(request timeout or policy.timeout, flavor ceiling)`.
   Providers enforce natively where the backend supports it; otherwise the caller wraps the
   provider call in `asyncio.wait_for` and raises `SandboxTimeoutError` on expiry, then makes a
   best-effort kill of the running work (documented per provider below).
4. Concurrency: a `Sandbox` instance is used only from the event loop that created it, with at
   most one in-flight execute call. Enforcement: `SandboxManager` holds one `asyncio.Lock` per
   `sandbox_session_id` (embedded path); `BrokerWorkerCore` holds its own per-session lock dict
   (brokered path); the `ThreadBroker` confines all handles to its private loop.

### `PrincipalResolver` (`sandbox/principal.py`)

```python
class PrincipalResolver(ABC):
    @abstractmethod
    async def resolve(self, session: Session, agent: Agent) -> SandboxPrincipal: ...

class AgentPrincipalResolver(PrincipalResolver):
    """Default: agent-own identity; subject = agent.name; empty credentials."""
```

- Configured via `sandbox.principal_resolver` (dotted path); unset → `AgentPrincipalResolver`.
- Resolution happens agent-side in `SandboxManager` (it needs `Session` context); the resolved
  `SandboxPrincipal` travels in the broker request message; enforcement happens where the
  credentials live (worker side).
- Fail-closed rules (enforced in `BrokerWorkerCore`, before any provider call):
  - profile `identity.mode == "user"` and provider `capabilities.principal_user == False` →
    `SandboxCapabilityError("principal_user")`.
  - `identity.mode == "user"` and the resolver returned an agent-mode principal (no user
    identity available on the session) → `SandboxPolicyError`, never a silent fallback.

Provider principal mapping (v1):

| Provider | `agent` mode | `user` mode |
|---|---|---|
| `kubernetes` | kubeconfig / in-cluster ServiceAccount | impersonation headers (`Impersonate-User`/`Impersonate-Group` from `subject`/`groups`); K8s RBAC then decides |
| `bedrock_agentcore` | default boto3 chain | `sts:AssumeRole` on `credentials["role_arn"]` |
| `ec2_ssm` | default boto3 chain | `sts:AssumeRole` on `credentials["role_arn"]`; plus SSM `RunAs` when `credentials["run_as"]` set |
| `docker`, `e2b`, `daytona`, `local_subprocess` | provider config credentials | not supported (`principal_user = False`) |

### Policy enforcement

- Enforcement point: `BrokerWorkerCore`, once per sandbox creation/attach, before the provider
  call. For each policy dimension that is non-default, check the corresponding
  `capabilities.policy_*` flag: unenforceable + `strict: true` → `SandboxPolicyError` listing
  every unenforceable dimension; `strict: false` → proceed and log one `WARNING` per
  provider+profile (process-lifetime memo) naming the unenforced dimensions.
- `policy.timeout` is always enforceable (framework-side `asyncio.wait_for` fallback), so it is
  exempt from the capability check.
- Per-provider mapping is a provider concern (`create`/`attach` arguments), detailed in the
  provider table below.

### `SandboxManager` (`sandbox/manager.py`)

Process-wide singleton following `ConversationThreadManager` (`core/thread/manager.py`):
`SandboxManager.get()` returns the instance, or `None` when `sandbox.enabled` is false; guarded
by a class-level `RLock`; constructed lazily on first use (builds the broker client via the
factory, instantiates the principal resolver).

Responsibilities and API:

```python
class SandboxManager:
    @classmethod
    def get(cls) -> "SandboxManager | None": ...

    async def execute(self, *, code: str | None = None, command: str | None = None,
                      language: str = "python", profile: str | None = None,
                      sandbox_session_id: str | None = None,
                      wait: float | None = None) -> SandboxResult | SandboxTask: ...
    async def upload(self, path: str, content: bytes, *, profile=None, sandbox_session_id=None) -> None: ...
    async def download(self, path: str, *, profile=None, sandbox_session_id=None) -> bytes: ...
    async def task_status(self, task_id: str) -> SandboxTask | None: ...     # registry + broker.result()
    def new_session(self, profile: str | None = None, name: str | None = None) -> SandboxSession: ...  # mint + register (per_session only)
    async def destroy_session(self, sandbox_session_id: str) -> None: ...
    def list_sessions(self) -> list[SandboxSession]: ...                      # current AK session's registry
```

- **Registry layout** (`per_session`/`per_call` scopes): stored in the current AK session's
  non-volatile cache (`Session.current().get_non_volatile_cache()`), under key `"sandbox"`:
  `{"sessions": {sandbox_session_id: SandboxSession.model_dump()}, "tasks": {task_id:
  SandboxTask.model_dump()}}`. Plain dicts (not model instances) so the pickle-based session
  serde (`core/session/serde.py`) stays version-stable. `per_runtime` scope keeps its single
  shared entry in a class-level dict instead (process memory, by design).
- **`per_runtime` concurrency — no pooling in v1** (closing the design's deferred
  pooling/warm-start item): `per_runtime` maps to exactly one shared sandbox session per
  profile, and its executions are serialized by the per-session lock. Deployments needing
  parallel stateless throughput use `per_call` scope and scale broker workers horizontally
  instead. An N-sandbox pool behind the shared session (with warm-start) is a documented later
  optimization; v1 reserves no config surface for it.
- **Session resolution**: explicit `sandbox_session_id` → registry lookup, miss →
  `SandboxSessionNotFoundError`. Omitted → the scope's default session for the resolved profile
  (registry key `default:<profile>`), created on first use. `per_call` → fresh ephemeral entry,
  destroyed in `finally`, result still stamped with its id. Explicit non-default ids come into
  existence only through `new_session(profile, name)` (uuid4 hex, `per_session` scope only) —
  exposed to agents as the `new_sandbox_session` tool. `name` is an optional human-friendly
  label carried on `SandboxSession` and surfaced by `list_sessions`; addressing is always by id.
- **Namespace isolation**: lookups only ever read the current AK session's registry (or the
  process-level `per_runtime` entry), which structurally prevents cross-AK-session addressing.
- **Idle timeout**: every profile has `idle_timeout` (seconds). `last_used_at` is refreshed per
  operation. Enforcement is layered: providers with native auto-stop get it passed at create
  (e2b `timeout`, daytona `auto_stop_interval`); the manager opportunistically closes+destroys
  expired sessions when touched; the ECS broker worker runs a periodic sweep (see broker); and
  `atexit` closes everything the process still holds (`per_runtime` backstop).
- **Recreation is never silent** (added 2026-07-21): both silent-reset paths — the manager's
  idle-expiry destroy-on-touch and the worker's `SandboxGoneError` self-heal — stamp
  `SandboxResult.notice` explaining that the workspace state was discarded. The tools pass
  `notice` through in their JSON, the completion summary includes it, and the injected
  guidance instructs the agent to tell the user before continuing.

### Sandbox broker (`sandbox/broker/`)

Message models (`broker/base.py`) — the public wire contract:

```python
class SandboxBrokerRequest(BaseModel):
    task_id: str
    operation: Literal["execute_code", "execute_command", "install_packages",
                       "upload_file", "download_file", "destroy"]
    payload: dict[str, Any]                  # operation arguments
    profile: str
    principal: SandboxPrincipal
    policy: SandboxPolicy
    sandbox_session: SandboxSession          # includes the reconnect handle — self-sufficient
    ak_session_id: str                       # for completion routing
    agent: str                               # for completion routing
    wait_deadline: float | None = None       # epoch seconds; None = caller will not wait

class SandboxCompletion(BaseModel):
    task_id: str
    status: Literal["succeeded", "failed", "timed_out"]
    result: SandboxResult | None = None      # inline when small
    result_ref: dict[str, str] | None = None # {"bucket":..., "key":...} when offloaded
    error: str | None = None
    sandbox_session: SandboxSession          # updated handle (e.g. newly created sandbox_id)
```

```python
class SandboxBroker(ABC):
    @abstractmethod
    async def submit(self, request: SandboxBrokerRequest,
                     wait: float | None) -> SandboxResult | SandboxTask: ...
    @abstractmethod
    async def result(self, task_id: str) -> SandboxCompletion | None: ...
    async def close(self) -> None: ...
```

`BrokerWorkerCore` (`broker/worker.py`) — the flavor-independent execution engine, used by
embedded, thread, ECS, and Lambda flavors alike. Processing one request:

1. Resolve `profile` → provider via `SandboxProviderFactory` (unknown profile →
   `SandboxConfigError`).
2. Fail-closed checks: principal (see PrincipalResolver) and policy (see Policy enforcement).
3. Attach-or-create: `sandbox_session.sandbox_id` set → `provider.attach(...)`; `SandboxGoneError`
   → `create()` under the same `sandbox_session_id` (self-heal, surfaced as a
   `SandboxResult.notice` — see the manager's "recreation is never silent" rule); unset →
   `create()`.
4. Serialize per `sandbox_session_id` (worker-local `asyncio.Lock` dict).
5. Execute the operation under `asyncio.wait_for(effective_timeout)`.
6. Build `SandboxCompletion`; offload `result` to the object store when its serialized size
   exceeds the flavor's inline threshold (in-process flavors never offload).
7. Persist/deliver DB-first (flavor-specific, below), then emit the completion event if due.
8. Terminal guarantee: any exception in 1–6 produces a `failed`/`timed_out` completion — the
   worker never ends a task without a terminal completion.

Flavors:

- **`embedded`** (`broker/embedded.py`): `submit()` runs `BrokerWorkerCore` inline in the
  caller's loop and returns the result directly; `wait` is ignored (always synchronous).
  `result()` reads the manager registry. Opt-in per deployment; credentials live in the agent
  process — the documented trade.
- **`thread`** (`broker/thread.py`): default for CLI and REST API modes. Starts one daemon
  thread running its own event loop and an `asyncio.Queue` of requests. `submit()` enqueues via
  `loop.call_soon_threadsafe` and bridges the response future back with `asyncio.wrap_future`;
  `wait=None` awaits indefinitely, `wait=N` uses `asyncio.wait_for` and on expiry returns the
  `SandboxTask` (execution continues; completion resolves into the manager registry and, because
  the process is shared, pending-task results are served by `result()` from worker memory).
  All provider handles live only on the broker thread's loop (concurrency contract).
- **`sqs`** (`deployment/aws/sandbox/sqs_broker.py`, dotted-path resolved):
  - `submit()`: serialize `SandboxBrokerRequest` to JSON, `SQSHandler`-style send to
    `sandbox.broker.request_queue_url` with `task_id` as a message attribute. `wait > 0` →
    bounded async poll of the sandbox `ResponseStore` (reusing
    `ResponseStore.get_message_with_retry(async_mode=True)` semantics,
    `deployment/common/response_store.py:37-74`) until `wait_deadline`; hit → `SandboxResult`,
    miss → `SandboxTask`. `wait == 0` → `SandboxTask` immediately.
  - **Response DB**: the existing `ResponseStore` implementations
    (`deployment/aws/core/response_store/{redis,valkey,dynamodb}.py`) are reused as-is, keyed by
    `task_id`, configured by a `sandbox.broker.response_store` block with the same shape as
    `execution.response_store` (`_ResponseStoreConfig`, `core/config.py:295-301`). Records carry
    a TTL (`sandbox.broker.response_ttl`, default 86400 s).
  - **Broker-side session inventory** (the durable backing for the idle sweep): on every
    create/attach the worker upserts a record keyed `session:<sandbox_session_id>` into the same
    response store — `{provider_type, sandbox_id, profile, idle_timeout, last_used_at}` — and
    refreshes `last_used_at` on every operation; records carry TTL
    `max(2 × idle_timeout, response_ttl)` so a dead worker's records still expire. This
    inventory is broker-internal (the agent-side nv_cache registry remains the source of truth
    for addressing).
  - **Workers**: `SandboxBrokerRunner(ECSSQSConsumer)` (`ecs_worker.py`) — container entry point
    polling the request queue, exported from `agentkernel.deployment.aws`; and
    `lambda_worker.lambda_handler` — the serverless worker, wired to the request queue by the
    terraform module's event source mapping. Both delegate each message to `BrokerWorkerCore`.
    The ECS worker additionally runs the idle-session sweep: one pass per
    `sandbox.broker.sweep_interval` (default 300 s) enumerates the broker-side session inventory
    (below) via the store's native scan — DynamoDB `Scan` with `begins_with("session:")`,
    Redis/Valkey `SCAN` on the key prefix, implemented per backend in `ecs_worker.py` — destroys
    sandboxes idle past their `idle_timeout`, and deletes the inventory record; the agent-side
    registry self-heals on next touch via `SandboxGoneError`.
  - **Fail-fast timeout ceiling**: `submit()` (client-side) rejects with `SandboxPolicyError`
    any request whose effective timeout exceeds `sandbox.broker.worker_timeout_ceiling` when
    set — satisfying the design's "rejected at request time, not at execution death" without
    the client guessing the worker's compute form. The terraform module outputs the ceiling
    (840 s — one minute under the Lambda platform limit — in serverless mode; null in
    server_based mode) into `AK_SANDBOX__BROKER__WORKER_TIMEOUT_CEILING`.
  - **Completion delivery** (DB-first, in order): (a) write the `SandboxCompletion` to the
    response DB; (b) if `wait_deadline` is `None` or `now > wait_deadline`, emit the completion
    event to the **agent input queue** (`execution.queues.input.url`) as a `BaseRunRequest`-shaped
    JSON body — `{"prompt": "<one-line summary>", "session_id": <ak_session_id>, "agent":
    <agent>, "sandbox_task_completion": {<SandboxCompletion minus inline result>}}` with
    `request_id = task_id` as a message attribute — which the existing consumers process
    unchanged (`ECSAgentRunner.process_message` validates `BaseRunRequest`,
    `deployment/aws/containerized/akagentrunner.py:90`; extra fields survive via
    `model_config = ConfigDict(extra="allow")`, `core/model.py:226`).
  - **Payload offload**: request `input files` and completion `result` larger than
    `sandbox.broker.inline_payload_max_bytes` (default 131072) are written to
    `sandbox.broker.object_store.bucket` (S3, key prefix `sandbox/<task_id>/`) and replaced by
    `result_ref`/payload refs; the counterpart side downloads on access. Completion events never
    carry inline results.
- **Custom flavors**: `sandbox.broker.flavor` accepts a dotted path to any `SandboxBroker`
  subclass (same BYO mechanism as providers).

### Task-completion ingestion (`sandbox/hooks.py`)

`SandboxPreHook(PreHook)`, registered as a system pre-hook after the multimodal hook
(`core/runtime.py:49` becomes
`[InputGuardrailFactory.get(), MultimodalPreHookFactory.get(), SandboxPreHookFactory.get()]`);
`SandboxPreHookFactory.get()` returns a no-op `PreHook` when `sandbox.enabled` is false
(guardrail-factory shape, `guardrail/guardrail.py:25-45`).

`on_run` behavior (session lock already held by `Runtime.run`, `core/runtime.py:198`):

1. Scan `requests` for `AgentRequestAny(name="sandbox_task_completion")`; none → pass through.
2. Load the task registry from `nv_cache`. Task unknown, or `consumed == True` → return
   `AgentReplyText(text="Duplicate or unknown sandbox task completion ignored.")` — halting the
   run (at-least-once dedup; the queued re-invocation ends as a no-op).
3. Otherwise: mark the task consumed and terminal (`status` from the completion), update the
   sandbox-session handle from `completion.sandbox_session`, strip the `AgentRequestAny`, and
   inject a bounded result summary (status, exit code, first
   `sandbox.tool_output_max_chars` of stdout/stderr, and the ref location when offloaded) into
   the last `AgentRequestText` — the multimodal injection precedent. The agent's turn then
   proceeds normally.

### System tools (`sandbox/tools.py`)

Registered in `SystemToolFactory.get_all()` (`core/tool.py:165-179`) behind
`AKConfig.get().sandbox.enabled`, with the lazy import + no-op-on-failure discipline of the
multimodal block. Async functions (ToolBuilder binds both sync and async, `core/tool.py:144-151`).
All of them return JSON strings; every result includes `sandbox_session_id`; machinery errors are
caught and returned as `{"error": ...}` strings — tools never raise into the framework.

- `run_code(code, language="python", sandbox_session_id=None, profile=None)` — delegates to
  `SandboxManager.execute`; on promotion returns
  `{"task_id":..., "status":"pending", "sandbox_session_id":...}`.
- `run_command(command, sandbox_session_id=None, profile=None)` — shell variant.
- `write_sandbox_file(path, content, sandbox_session_id=None, profile=None)` /
  `read_sandbox_file(path, sandbox_session_id=None, profile=None)` — the design's tool-level
  file operations (workspace mode): UTF-8 text content, delegating to
  `SandboxManager.upload`/`download`; reads capped at `tool_output_max_chars`.

- `check_sandbox_task(task_id)` — `SandboxManager.task_status`: registry first, then
  `broker.result()` (the response-DB lookup for suspend/resume recovery — "the user can come
  back and check").
- `new_sandbox_session(name=None, profile=None)` — `SandboxManager.new_session`: mints and
  registers a fresh (uuid4-hex) session and returns its id — the only way an explicit
  `sandbox_session_id` comes into existence (added 2026-07-21: without it, an agent asked
  for "a fresh environment" had no legitimate move and would invent ids). `name` is an
  optional human-friendly label. Restricted to `per_session` scope (`per_call` is ephemeral
  per execution; `per_runtime` is a single shared session by design).
- `list_sandbox_sessions()` — `SandboxManager.list_sessions`: the sessions existing in this
  conversation (id, name, profile, status, last_used_at). Added 2026-07-21: session ids are
  opaque and lived only in the model's conversational memory, so "go back to the uv project"
  had nothing to consult and agents minted duplicates instead of switching.
- `destroy_sandbox_session(sandbox_session_id)` — `SandboxManager.destroy_session`,
  idempotent; destroying the default session resets it (the next id-less call starts clean).

All eight tools register when the capability is enabled — registration is profile-agnostic
because the profile is chosen per call; invoking a file tool against a profile whose provider
lacks `files` returns the capability-error string like any other unsupported operation.
An optional `sandbox.agents` list (added 2026-07-21; `_MultimodalConfig` gained the same field)
restricts tool attachment and prompt injection to the named agents — enforced at agent wrap
time via `SystemToolFactory.get_all(agent_name)` / `get_system_prompt_suffix(agent_name)`;
omitted = all agents (current behavior). Anonymous callers with no agent context (the
LangGraph `ToolBuilder.bind` convenience injection) are not filtered.

Tool `description` strings must teach the model: results persist per `sandbox_session_id`;
reuse the id to continue in the same environment; omit it for the default; **session ids are
system-assigned, never invented — use `new_sandbox_session` (with a descriptive name) for a
clean environment, and consult `list_sandbox_sessions` to return to an earlier one instead of
minting a duplicate**; an `{"error": ...}` result means the operation failed and must be
reported as such, never as success; available workload profiles with their provider type and
scope (config-derived at registration time — provider capabilities/languages are **not**
rendered, since that would import providers at registration and break the lazy-import
discipline); stdout/stderr truncated at `tool_output_max_chars`.

The capability is **self-describing**: that guidance is injected into every agent's system
prompt through the existing system-tool injection chain
(`SystemToolFactory.get_system_prompt_suffix()` → `Agent._setup_system_prompt()` →
`override_system_prompt()`, the multimodal precedent), carried as one coherent section on the
first tool's `description` (the other tools carry empty descriptions; their LLM-facing schemas
come from the function docstrings at bind time). Agent authors never describe the sandbox
tools or their session/profile semantics in their own instructions.

### Factory (`sandbox/factory.py`)

The factory follows the **shared pluggable-backend pattern (#541)**. The helpers already exist in
`core/util/factory.py` and must be reused (do not reinvent them):
- `resolve_dotted(path, *, base, error=AKConfigError)` — import a dotted path, verify
  `issubclass(cls, base)`, raise `error` on any failure. Sandbox passes `error=SandboxConfigError`
  so failures stay in the `SandboxError` hierarchy.
- `require_extra(extra, feature)` — context manager wrapping a built-in import; on `ImportError`
  re-raises `ImportError` naming the exact `pip install "agentkernel[<extra>]"` remedy.

`SandboxProviderFactory.get(profile_name) -> SandboxProvider`:

1. `AKConfig.get().sandbox.enabled` false → `None` (callers treat the capability as absent).
2. Resolve the profile (unknown → `SandboxConfigError` naming it and the configured profiles).
3. Resolve `type`:
   - **Built-in short name** → an `if/elif` branch with a **real lazy import**
     `from .providers.<type> import <Provider>`, wrapped in `require_extra(<extra>, ...)`
     (skip the wrap for `local_subprocess`, which is stdlib-only). Landed branches are listed
     in `_BUILTIN_PROVIDER_NAMES`; **each provider iteration (7, 9, 10) adds its branch and
     appends its name to that list** — there is no registry map (removed 2026-07-21; a
     not-yet-landed short name fails as an unknown type until its iteration lands).
   - **Unknown non-dotted name** → `SandboxConfigError` naming the value and listing
     `_BUILTIN_PROVIDER_NAMES` (#541 shape).
   - **Dotted path** → `resolve_dotted(type, base=SandboxProvider, error=SandboxConfigError)`
     (the open, zero-registry BYO hook).
4. Construct with the profile's backend config block (missing block for a built-in →
   `SandboxConfigError`, multimodal-storage precedent; dotted-path providers get the profile's
   `params` mapping validated by their own `config_model`, else a permissive `_DottedParams`).
5. Cache one instance per (profile, type) in a class-level dict; created lazily on first use.

Broker-flavor resolution uses `resolve_dotted(dotted, base=SandboxBroker, error=SandboxConfigError)`
over the built-in map `_BUILTIN_BROKERS` (`{"embedded": ..., "thread": ...}`; iteration 8 adds
`"sqs": "agentkernel.deployment.aws.sandbox.sqs_broker.SQSSandboxBroker"` when the flavor lands).
Brokers stay on the `resolve_dotted`-over-map form (not `if/elif` real imports) because the `sqs`
flavor must remain a dotted path — it lives under `deployment/aws/` and core sandbox may not
import it.

### First-party providers (`sandbox/providers/`)

| Provider | SDK / extra | isolation | Key capabilities | create / attach | policy mapping |
|---|---|---|---|---|---|
| `local_subprocess` | stdlib / — | `none` | shell, files, attach, languages `[python, bash]` | temp dir per sandbox; attach reconnects to the workdir by path (same host) | resources/network/fs all False (strict non-default policy fails) |
| `docker` | `docker` / `sandbox-docker` | `container` | shell, files, package_install, attach | container (`sleep infinity`) per sandbox; attach by container id | `deny`→`network_mode="none"`; `allowlist` unenforceable; cpu/mem→container limits; fs→read-only rootfs + writable workdir |
| `e2b` | `e2b-code-interpreter` / `e2b` | `micro_vm` | stateful, shell, files, package_install, attach, policy_network | `AsyncSandbox.create` / `AsyncSandbox.connect(id)` | egress→E2B network config; timeout→native; cpu/mem unenforceable (tier-fixed) |
| `daytona` | `daytona` / `daytona` | `container` | shell, files, package_install, attach, policy_network, policy_resources | `daytona.create` / get-by-id (sync SDK via `to_thread`) | allowlist→CIDR allowlist; cpu/mem→`Resources`; idle→`auto_stop_interval` |
| `bedrock_agentcore` | `boto3` / `aws` | `micro_vm` | stateful, attach, principal_user | `start_code_interpreter_session` / reuse session id | egress→session network mode (`sandbox`/`public`); fs/resources unenforceable |
| `kubernetes` | `kubernetes` / `kubernetes` | `container` | shell, files, attach, principal_user, policy_resources | launch pod / exec into named pod (`attach_to`) | cpu/mem→pod resources; network unenforceable in v1 |
| `ec2_ssm` | `boto3` / `aws` | `none` | shell, attach, principal_user | attach-only: both `create` and `attach` bind to the configured/`attach_to` instance id; `create` never provisions | all policy flags False except timeout |

Provider notes (implementation-relevant specifics):

- **`local_subprocess`**: logs
  `WARNING: local_subprocess provides NO isolation — development/test use only` on construction.
  `execute_code` runs `sys.executable -c <code>` (or `bash -c` for shell) via
  `asyncio.create_subprocess_exec` with `cwd=<per-sandbox temp dir>`, `start_new_session=True`;
  timeout kills the process group. Files map onto the temp dir. Never the factory default.
  Declares `attach` (implemented as a same-host reconnect to the workdir path,
  `SandboxGoneError` when the directory is gone) — required for per-session reuse, since the
  worker re-acquires via `attach()` whenever the session already has a `sandbox_id`. There is
  no `attach_to` config: mode-3 attach to an external target does not apply.
  (Implementation correction 2026-07-21: the table originally declared `attach=False`, which
  would have broken every second operation in a session.)
- **`docker`**: sync SDK via `to_thread`. `execute_code` = `exec_run` of the language
  interpreter; files via `put_archive`/`get_archive`; `install_packages` = `pip install` exec.
  `close()` leaves the container running (reattachable); `destroy()` = `remove(force=True)`.
  Timeout: `asyncio.wait_for` + best-effort `kill` of the exec'd process.
- **`e2b`**: native async SDK; `stateful=True` (Jupyter-kernel model — variables persist);
  idle timeout passed as the sandbox `timeout` at create.
- **`daytona`**: `process.code_run` / `process.exec`; every SDK call in `to_thread`.
- **`bedrock_agentcore`**: `invoke_code_interpreter` with the `executeCode` tool; the AgentCore
  session id is the sandbox id; `languages=["python"]`, `shell=False`, `files=False` in v1
  (the narrow contract that keeps the required core surface honest).
- **`kubernetes`**: official sync client via `to_thread`; exec via
  `stream(connect_get_namespaced_pod_exec, ...)`. User mode sets impersonation headers on the
  `ApiClient`. `create` launches a pod from the profile's image in the configured namespace;
  `attach_to: <namespace>/<pod>` execs into an existing pod (mode 3).
- **`ec2_ssm`**: `ssm.send_command` (`AWS-RunShellScript`) + poll `get_command_invocation`;
  `execute_code(python)` wraps the code in a `python3 - <<'EOF'` heredoc. `destroy()` is a no-op
  (never owns the host).

### Consumer changes

- **`core/config.py`** — adds the classes in Config changes below and one root field. Nothing
  existing changes.
- **`core/tool.py`** — `SystemToolFactory.get_all(agent_name)` gains a sandbox block after the
  multimodal block, both gated by the per-capability `agents` filter (`_agent_allowed`):
  ```python
  sandbox_config = getattr(AKConfig.get(), "sandbox", None)
  if sandbox_config and sandbox_config.enabled and SystemToolFactory._agent_allowed(sandbox_config, agent_name):
      from ..sandbox.tools import get_sandbox_tools

      tools.extend(get_sandbox_tools())   # eight tools: execution, files, task poll, session lifecycle
  ```
- **`core/base.py`** — `Agent._setup_system_prompt()`/`_attach_system_tools()` pass `self.name`
  to the factory, so the `sandbox.agents` (and `multimodal.agents`) restriction is enforced at
  agent wrap time (added with the 2026-07-21 `agents`-scoping amendment).
- **`core/runtime.py`** — line 12 region gains
  `from ..sandbox.hooks import SandboxPreHookFactory` (mirroring the guardrail import) and the
  `_get_system_pre_hooks` list (`core/runtime.py:49`) appends `SandboxPreHookFactory.get()`.
- **`test/test.py`** — the built-in `Test` framework now keeps the launched CLI's **stderr on a
  separate pipe** (drained in the background) instead of merging it into stdout, so AK log output
  no longer pollutes captured agent responses under fuzzy/judge comparison. Behavioral change to
  a public consumer; documented under Behavioural changes.
- **`ak-py/pyproject.toml`** — the `sandbox-docker = ["docker>=7.0.0"]` extra ships now. The
  `e2b`/`daytona`/`kubernetes` extras land with their providers in iterations 9–10 (deferred
  during PR #364 review so an installable extra never precedes a usable provider).
  `bedrock_agentcore`, `ec2_ssm`, and the `sqs` broker flavor ride the existing `aws` extra
  (`boto3`).
- **`deployment/aws`** — new `sandbox/` subpackage (iteration 8; no changes to existing modules);
  `agentkernel.deployment.aws.__init__` additionally exports `SandboxBrokerRunner`.
- **Verified unchanged**: `core/model.py` (no new request type — the deviation note above),
  `core/chat_service.py`, `ECSAgentRunner`/`ServerlessAgentRunner`, guardrail and multimodal
  packages, session serde. (`core/base.py` and `test/test.py` moved out of this list above — both
  changed.)

### Config changes

New Pydantic classes in `core/config.py` (placed with the other capability configs, before
`class AKConfig` at `core/config.py:378`), and one root field
`sandbox: _SandboxConfig = Field(description="Sandbox capability configurations", default_factory=_SandboxConfig)`
registered on `AKConfig` (fields `core/config.py:379-405`).

```python
class _SandboxIdentityConfig(BaseModel):
    mode: str = Field(default="agent", pattern="^(agent|user)$")

class _SandboxPolicyConfig(BaseModel):
    network_egress: str = Field(default="allow", pattern="^(allow|deny|allowlist)$")
    network_allow: list[str] = Field(default_factory=list)
    fs_allow_read: list[str] = Field(default_factory=list)
    fs_allow_write: list[str] = Field(default_factory=list)
    cpu: Optional[float] = None
    memory_mb: Optional[int] = None
    timeout: float = 120.0
    strict: bool = True

class _SandboxBrokerConfig(BaseModel):
    flavor: str = Field(default="thread", description="embedded | thread | sqs | dotted path")
    wait_timeout: float = Field(default=60.0, description="Max seconds a synchronous wait blocks before promotion to a task (0 = always promote)")
    inline_payload_max_bytes: int = Field(default=131072)
    response_ttl: int = Field(default=86400)
    sweep_interval: int = Field(default=300)
    request_queue_url: Optional[str] = None            # sqs flavor (terraform output)
    object_store_bucket: Optional[str] = None          # sqs flavor (terraform output)
    worker_timeout_ceiling: Optional[float] = Field(
        default=None,
        description="Max effective execution timeout (s) the provisioned worker supports; terraform output — 840 in serverless mode, null in server_based. None = no ceiling.",
    )
    response_store: Optional[_ResponseStoreConfig] = None  # sqs flavor; reuses the existing model

class _SandboxProfileConfig(BaseModel):
    type: str                                           # short name or dotted path
    scope: str = Field(default="per_session", pattern="^(per_call|per_session|per_runtime)$")
    idle_timeout: int = Field(default=1800)
    identity: _SandboxIdentityConfig = Field(default_factory=_SandboxIdentityConfig)
    policy: _SandboxPolicyConfig = Field(default_factory=_SandboxPolicyConfig)
    params: dict[str, Any] = Field(default_factory=dict)                         # dotted-path providers
    local_subprocess: Optional[_SandboxLocalSubprocessConfig] = None
    docker: Optional[_SandboxDockerConfig] = None
    e2b: Optional[_SandboxE2BConfig] = None
    daytona: Optional[_SandboxDaytonaConfig] = None
    bedrock_agentcore: Optional[_SandboxBedrockAgentCoreConfig] = None
    kubernetes: Optional[_SandboxKubernetesConfig] = None
    ec2_ssm: Optional[_SandboxEC2SSMConfig] = None

class _SandboxConfig(BaseModel):
    enabled: bool = Field(default=False)
    agents: Optional[list[str]] = None                   # restrict tools + prompt to these agents; None = all
    default_profile: str = Field(default="default")
    principal_resolver: Optional[str] = None            # dotted path
    tool_output_max_chars: int = Field(default=8000)
    broker: _SandboxBrokerConfig = Field(default_factory=_SandboxBrokerConfig)
    profiles: dict[str, _SandboxProfileConfig] = Field(default_factory=dict)
    # single-backend sugar (synthesized into profiles["default"] by a model_validator
    # when profiles is empty and type is set):
    type: Optional[str] = None
    scope: Optional[str] = None
    # ... the same per-backend Optional blocks as _SandboxProfileConfig
```

Per-backend config blocks (each `Optional`, `SandboxConfigError` when the selected built-in's
block is missing): `_SandboxDockerConfig(image="python:3.12-slim", runtime="docker",
attach_to=None)`, `_SandboxE2BConfig(api_key_env="E2B_API_KEY", template="base")`,
`_SandboxDaytonaConfig(api_key_env="DAYTONA_API_KEY", target=None)`,
`_SandboxBedrockAgentCoreConfig(region=None, network_mode="sandbox")`,
`_SandboxKubernetesConfig(namespace="default", image="python:3.12-slim", attach_to=None,
kubeconfig=None)`, `_SandboxEC2SSMConfig(region=None, attach_to=None)`,
`_SandboxLocalSubprocessConfig(workdir=None)`. Secrets are referenced by env-var name
(`api_key_env`), never stored in config.

- Env override examples: `AK_SANDBOX__ENABLED`, `AK_SANDBOX__BROKER__FLAVOR`,
  `AK_SANDBOX__BROKER__REQUEST_QUEUE_URL` (the terraform-output handoff),
  `AK_SANDBOX__PROFILES__DEFAULT__TYPE`.
- Compatibility: the section is new; YAML files and `AK_*` env vars written before this change
  are unaffected. `sandbox.enabled` defaults false → the capability is inert (no tools, no
  hook behavior, no provider imports) unless explicitly enabled. Field descriptions (surfaced in
  generated docs) are required on every new field.

### Behavioural changes

All intentional; none reachable unless `sandbox.enabled: true` except 1–3:

1. `Runtime._system_pre_hooks` grows from two entries to three
   (`core/runtime.py:49`); with sandbox disabled the third is a no-op pass-through `PreHook`.
   Existing behavior of the guardrail and multimodal hooks (and their order) is unchanged.
2. `SystemToolFactory.get_all()` gains a config read of `AKConfig.get().sandbox` (returns no
   extra tools while disabled).
3. `AKConfig` gains the `sandbox` section — new keys appear in generated config docs.
   `_MultimodalConfig` and `_SandboxConfig` also gain an optional `agents` list (omitted =
   all agents), so `SystemToolFactory` now takes an `agent_name` and filters per capability.
4. **`Test` framework (`test/test.py`)**: the launched CLI's stderr is kept on a separate pipe
   (background-drained) rather than merged into stdout, so log output no longer contaminates
   captured responses. A consumer whose assertion relied on a logged (stderr) message now sees
   only stdout — surface such messages on stdout or assert the observable outcome.
5. With sandbox **enabled**: eight system tools (`run_code`, `run_command`,
   `write_sandbox_file`, `read_sandbox_file`, `check_sandbox_task`, `list_sandbox_sessions`,
   `new_sandbox_session`, `destroy_sandbox_session`) register on all agents — or only those
   named in `sandbox.agents` when set — and those agents' system prompts grow by the
   capability's guidance section.
6. With sandbox **enabled**: an inbound request body carrying a `sandbox_task_completion` extra
   field is intercepted by `SandboxPreHook` (consumed, deduped, or halted) instead of flowing to
   the agent as an ignored `AgentRequestAny`.

**Non-changes**: the `AgentRequest`/`AgentReply` unions and every model in `core/model.py`;
`RequestBuilder` and the queue consumers' message parsing; session serialization format
(registry entries are plain dicts inside the existing `nv_cache`); public exports of
`agentkernel.core`; guardrail/multimodal behavior and config; the `execution.*` config section
(the sandbox broker has its own queue/response-store config and does not reuse
`execution.queues`).

## Error handling

Hierarchy (`sandbox/errors.py`):

```python
class SandboxError(Exception): ...
class SandboxConfigError(SandboxError): ...           # unknown profile/type/flavor, missing config block
class SandboxCapabilityError(SandboxError): ...       # (provider, capability) — unsupported operation
class SandboxPolicyError(SandboxError): ...           # unenforceable (strict) or violated policy; user-identity fail-closed
class SandboxTimeoutError(SandboxError): ...          # effective timeout exceeded
class SandboxProvisionError(SandboxError): ...        # create/attach failed
class SandboxGoneError(SandboxProvisionError): ...    # attach target no longer exists (self-heal signal)
class SandboxSessionNotFoundError(SandboxError): ...  # unknown sandbox_session_id
class SandboxBrokerError(SandboxError): ...           # transport/delivery failure
```

Surfacing rules:

- **Tools never raise into the framework**: `run_code`/`run_command`/`check_sandbox_task` catch
  `SandboxError`, log at `WARNING` (`exception` for unexpected types), and return
  `{"error": "<message>"}` JSON so the LLM can react.
- **Program failure is data**: non-zero exit → `SandboxResult`, not an exception (§Data types).
- **Fail-closed paths raise before any execution**: policy (`SandboxPolicyError`) and identity
  (`SandboxCapabilityError`/`SandboxPolicyError`) checks run in `BrokerWorkerCore` step 2.
- **Provisioning failures** (`SandboxProvisionError`): providers wrap `create`/`attach`
  infrastructure failures in this type where they can (`SandboxGoneError` for a gone attach
  target). Known deviation (iterations 1–6): the shipped `local_subprocess`/`docker` providers
  do not yet wrap raw SDK/OS errors (a dead Docker daemon, a `mkdtemp` failure) — these surface
  as the underlying exception, caught by the tool layer into `{"error": ...}`. Typed-caller
  distinction via `SandboxProvisionError` is a provider-hardening follow-up.
- **Missing optional dependency**: the factory's `require_extra` raises `ImportError` naming the
  exact `pip install "agentkernel[<extra>]"` remedy. Provider SDK imports are deferred to first
  execution (registration imports nothing optional — `get_sandbox_tools` only builds the tool
  list), so this surfaces as the tool-level `{"error": ...}` on first use, not at registration.
- **Broker terminal guarantee**: worker exceptions become `failed` completions; the SQS worker's
  permanent-failure path (`on_permanent_failure`, after `max_receive_count` receives) writes a
  `failed` completion to the response DB and emits the completion event — the DLQ never
  swallows a task silently. `on_permanent_failure` catches its own exceptions
  (the `ECSSQSConsumer` contract).
- Resources are released in `finally` blocks throughout (`per_call` teardown, broker worker
  handle cleanup); no bare `except: pass` anywhere in the package. (The process-exit `atexit`
  backstop for `per_runtime` is deferred to a post-merge iteration — see plan.md.)

## Testing

New test files (all mock provider SDKs and AWS clients; no real network, no Docker daemon; the
only real subprocesses are `local_subprocess` tests running `sys.executable`):

- **`ak-py/tests/test_sandbox.py`** — the capability core:
  - Model/capability semantics: every optional `Sandbox` operation raises
    `SandboxCapabilityError` on a provider that doesn't declare it; declared operations succeed
    on `FakeSandboxProvider`.
  - Policy: non-default policy vs `policy_* = False` raises `SandboxPolicyError` when
    `strict`, warns once when not; `identity.mode=user` against `principal_user=False` and
    resolver-returned-agent-principal both fail closed.
  - Factory: each built-in short name lazy-imports (monkeypatched `importlib`); missing extra →
    `ImportError` naming the extra; dotted path resolves; non-subclass dotted path and missing
    config block → `SandboxConfigError`; disabled → `SandboxManager.get()` is `None`. Config via
    the `FakeCfg` + `monkeypatch.setattr("agentkernel.core.config.AKConfig.get", ...)` pattern
    (the `SessionStoreBuilder` test precedent), plus resetting the factory instance cache and
    `SandboxManager` singleton between tests.
  - Sandbox sessions: create → reuse by `sandbox_session_id` across two `Runtime.run` turns
    (nv_cache round-trip through `InMemorySessionStore`); two concurrent sessions isolated;
    unknown id → `SandboxSessionNotFoundError`; a second AK session cannot resolve the first's
    id; `per_call` destroys in `finally`; stale handle (`SandboxGoneError` on attach) recreates
    under the same id; idle-timeout expiry closes on next touch.
  - Single-backend config sugar synthesizes `profiles["default"]`.
  - Agent surface (system tools): `SystemToolFactory.get_all()` returns the eight sandbox tools
    when enabled and none when disabled; each tool's JSON contract (result echoes
    `sandbox_session_id`; promotion returns a task handle; machinery errors surface as
    `{"error": ...}` strings, never exceptions); file tools against a non-`files` profile
    return the capability-error string; `check_sandbox_task` resolves from the registry and
    from `broker.result()`.
- **`ak-py/tests/test_sandbox_broker.py`** — broker mechanics:
  - `embedded` and `thread` flavors end-to-end against `FakeSandboxProvider` (thread flavor:
    handles never touched from the caller loop — asserted via loop-identity capture).
  - Wait-policy promotion: `wait` expiry returns a `SandboxTask`; completion later lands in the
    registry; `check` path (`SandboxManager.task_status`) finds it.
  - Suspend/resume ingestion: a synthetic completion `BaseRunRequest` (extra field) through
    `Runtime.run` with a `DummyAgent` → summary injected, task marked consumed; the same
    completion again → run halts with the duplicate reply (dedup); unknown task id → halt.
  - DB-first recovery: fake `ResponseStore` — completion written before event emission
    (ordering asserted); a "missed notification" is recovered via `task_status`.
  - Fail-fast: effective timeout above the lambda flavor ceiling rejected at submit.
  - Payload offload: result above `inline_payload_max_bytes` goes to a fake object store and
    `result_ref` round-trips.
  - SQS flavor client/worker with stubbed boto3: request message schema, `request_id`/`task_id`
    attribute, completion-event emission rule (`wait_deadline` past vs future),
    `on_permanent_failure` → failed completion.
- **`ak-py/tests/test_sandbox_providers.py`** — `local_subprocess` end-to-end (real
  subprocess: stdout/stderr/exit-code capture, timeout kill, temp-dir file ops, construction
  warning asserted via `caplog`); the six SDK providers against mocked SDK clients
  (create/attach/execute/destroy call shapes, principal/policy mapping arguments, `to_thread`
  usage for sync SDKs).
- **`sandbox/testing.py` contract suite**: `SandboxProviderContract` — a pytest-importable
  class parameterized over a provider instance, asserting the ABC semantics (idempotent
  close/destroy, capability honesty, result-vs-exception discipline). `test_sandbox.py` runs it
  against `FakeSandboxProvider`; BYO backends import and subclass it (this satisfies the
  design's "reusable provider contract test suite").

Existing tests affected:

- **`ak-py/tests/test_runtime.py`** — the autouse reset fixture already sets
  `Runtime._system_pre_hooks = None` (`tests/test_runtime.py:19-22`); it keeps working
  unchanged. Any test that asserts the *composition* of the system pre-hook list must now
  expect three entries; a repo-wide grep found no such assertion today — verified, only the
  reset fixture touches `_system_pre_hooks`.
- No other existing test file's patch targets move (the three wiring points only add code).

Run: `cd ak-py && uv run pytest` (plus `make lint-check-all` per code-quality conventions).

## Documentation, examples, and provisioning deliverables

Ordered by `plan.md`; listed here for completeness:

- Docs page `docs/docs/advanced/sandbox.md`: capability overview, config reference (with the
  **locked-down policy example shown prominently** — the design's egress requirement), profile
  routing, broker flavors per deployment mode, RBAC model, isolation-tier table.
- Config documented in `ak-py/README.md` alongside the other sections.
- Example `examples/cli/sandbox/`: runnable demo using `local_subprocess` (zero dependency) and
  `docker` profiles; README explains switching backends by config only.
- Terraform module `ak-deployment/ak-aws/common/sandbox_broker/`: input
  `mode = "serverless" | "server_based"` selects Lambda vs ECS worker; provisions request
  queue, response store table, object-store bucket, worker compute + IAM (queue-restricted
  producers/consumers per the trust boundary); **outputs** `request_queue_url`,
  `response_store_table`, `object_store_bucket`, and `worker_timeout_ceiling` (840 in
  serverless mode, null in server_based) for the `AK_SANDBOX__BROKER__*` env handoff.
- New dev skill `.agents/skills/ak-dev-new-sandbox-provider/` cloned from
  `ak-dev-new-guardrail-provider`'s structure once the interface lands; the research skill's
  status metadata flips per its own maintenance note.
