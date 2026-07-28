---
sidebar_position: 5
---

# Sandbox Internals

How the [sandbox capability](../advanced/sandbox.md) works under the hood: the components involved, the class contracts, and the runtime flows. This page is for contributors and for anyone plugging in a custom provider, broker, or principal resolver. For enabling and configuring the sandbox, see the [Sandbox guide](../advanced/sandbox.md).

## Component view

The capability is split into three layers with one wire contract between them. Everything the agent sees lives in the agent process (tools, `SandboxManager`, registries). The **broker** is a transport seam: in-process flavors call the worker engine directly, while remote flavors ship the same `SandboxBrokerRequest` over a queue. The worker engine is the only component that touches providers.

```mermaid
flowchart TB
    subgraph AGENT["Agent process"]
        LLM["Agent turn (LLM)"]
        TOOLS["System tools<br/>run_code · run_command · read/write_sandbox_file<br/>check_sandbox_task · list/new/destroy_sandbox_session"]
        HOOK["SandboxPreHook<br/>task-completion ingestion"]
        MGR["SandboxManager (singleton façade)"]
        RES["PrincipalResolver<br/>default: AgentPrincipalResolver"]
        REG[("Session registries<br/>AK-session nv_cache + per_runtime memory")]
    end

    subgraph BROKER["Broker transport (sandbox.broker.flavor)"]
        EMB["EmbeddedBroker<br/>inline, always synchronous"]
        THR["ThreadBroker (default)<br/>daemon thread + private event loop"]
        SQS["Remote flavor, e.g. sqs (planned)<br/>queue to a remote worker"]
    end

    subgraph WORKER["Execution engine"]
        CORE["BrokerWorkerCore<br/>fail-closed principal + policy checks<br/>attach-or-create with self-heal<br/>per-session lock · timeout"]
        PF["SandboxProviderFactory<br/>one provider per profile+type, cached"]
    end

    subgraph PROV["Providers (profile.type)"]
        LSP["local_subprocess<br/>isolation: none"]
        DKR["docker<br/>isolation: container"]
        BYO["Bring-your-own<br/>dotted path to SandboxProvider"]
    end

    LLM --> TOOLS --> MGR
    HOOK --> MGR
    MGR --> RES
    MGR <--> REG
    MGR -- "SandboxBrokerRequest" --> EMB
    MGR -- "SandboxBrokerRequest" --> THR
    MGR -. "SandboxBrokerRequest over queue" .-> SQS
    EMB --> CORE
    THR --> CORE
    SQS -.-> CORE
    CORE --> PF
    PF --> LSP
    PF --> DKR
    PF --> BYO
```

A `SandboxBrokerRequest` is **self-sufficient**: it carries the resolved principal, the policy, and the full sandbox-session handle (including the provider reconnect id), so a remote worker needs nothing else to execute it.

## The execution contract

Only four methods are mandatory across all backends: `execute_code` (with `language="python"`), `close`, `create`, and `destroy`. Every richer operation is optional and raises `SandboxCapabilityError` unless the provider both declares it in `capabilities` and overrides it. Declaring only what the backend truly enforces is the core security rule ("capability honesty").

```mermaid
classDiagram
    direction LR
    class Sandbox {
        <<abstract>>
        +str id
        +execute_code(code, language, timeout)* SandboxResult
        +execute_command(command, timeout) SandboxResult
        +upload_file(path, content) None
        +download_file(path) bytes
        +install_packages(packages) SandboxResult
        +close()* None
    }
    class SandboxProvider {
        <<abstract>>
        +capabilities SandboxCapabilities$
        -_config BaseModel
        +create(principal, policy)* Sandbox
        +attach(sandbox_id, principal, policy) Sandbox
        +destroy(sandbox_id)* None
    }
    class SandboxCapabilities {
        +isolation IsolationTier
        +shell bool
        +languages list
        +files bool
        +package_install bool
        +stateful bool
        +attach bool
        +principal_user bool
        +policy_network bool
        +policy_filesystem bool
        +policy_resources bool
    }
    class IsolationTier {
        <<enumeration>>
        NONE
        OS_POLICY
        CONTAINER
        SYSCALL_FILTER
        MICRO_VM
        WASM
    }
    class LocalSubprocessSandbox
    class DockerSandbox
    class LocalSubprocessSandboxProvider
    class DockerSandboxProvider
    class SandboxProviderFactory {
        -_cache dict$
        +get(profile_name)$ SandboxProvider
        -_build(profile_name, profile)$ SandboxProvider
    }

    Sandbox <|-- LocalSubprocessSandbox
    Sandbox <|-- DockerSandbox
    SandboxProvider <|-- LocalSubprocessSandboxProvider
    SandboxProvider <|-- DockerSandboxProvider
    SandboxProvider --> SandboxCapabilities : declares honestly
    SandboxCapabilities --> IsolationTier
    SandboxProvider ..> Sandbox : create / attach
    SandboxProviderFactory ..> SandboxProvider : builds, caches per profile+type
```

**Result discipline:** a failing *program* (non-zero exit, exception in user code) comes back as a `SandboxResult` with `exit_code != 0`. Exceptions are reserved for failures of the sandbox *machinery* (see [Error hierarchy](#error-hierarchy)).

## The control plane

`SandboxManager` is a process-wide singleton (mirroring `ConversationThreadManager`). `SandboxManager.get()` returning `None` is the feature-disabled check every tool performs. Both in-process brokers delegate to the same `BrokerWorkerCore`; the difference is only where it runs and whether a bounded wait can promote the execution to a background task.

```mermaid
classDiagram
    direction TB
    class SandboxManager {
        -_broker SandboxBroker
        -_resolver PrincipalResolver
        -_runtime_registry dict$
        +get()$ SandboxManager
        +execute(code, command, language, profile, sandbox_session_id, wait)
        +upload(path, content, profile, sandbox_session_id)
        +download(path, profile, sandbox_session_id) bytes
        +task_status(task_id) SandboxTask
        +ingest_completion(completion) SandboxTask
        +new_session(profile, name) SandboxSession
        +destroy_session(sandbox_session_id)
        +list_sessions() list
    }
    class SandboxBroker {
        <<abstract>>
        +submit(request, wait)* SandboxResult or SandboxTask
        +result(task_id)* SandboxCompletion
        +discard(task_id)
        +close()
    }
    class EmbeddedBroker {
        -_worker BrokerWorkerCore
        -_completions BoundedCompletionStore
    }
    class ThreadBroker {
        -_worker BrokerWorkerCore
        -_completions BoundedCompletionStore
        -_thread Thread
        -_queue Queue
    }
    class BrokerWorkerCore {
        -_locks dict per sandbox_session_id
        +run(request) result and session
        +process(request) SandboxCompletion
        -_check_principal(provider, request)
        -_enforce_policy(provider, request)
        -_acquire(provider, request) sandbox and recreated
        -_execute(sandbox, request) SandboxResult
    }
    class BoundedCompletionStore {
        +set(task_id, completion)
        +get(task_id) SandboxCompletion
        +discard(task_id)
    }
    class PrincipalResolver {
        <<abstract>>
        +resolve(session, agent)* SandboxPrincipal
    }
    class AgentPrincipalResolver
    class SandboxPreHook {
        +on_run(session, agent, requests)
    }
    class SandboxBrokerFactory {
        +get()$ SandboxBroker
    }

    SandboxBroker <|-- EmbeddedBroker
    SandboxBroker <|-- ThreadBroker
    PrincipalResolver <|-- AgentPrincipalResolver
    SandboxManager --> SandboxBroker : submit / result / discard
    SandboxManager --> PrincipalResolver : resolve identity
    SandboxBrokerFactory ..> SandboxBroker : builds from broker.flavor
    EmbeddedBroker --> BrokerWorkerCore : inline
    ThreadBroker --> BrokerWorkerCore : on broker thread
    EmbeddedBroker --> BoundedCompletionStore
    ThreadBroker --> BoundedCompletionStore
    SandboxPreHook --> SandboxManager : ingest_completion
    BrokerWorkerCore ..> SandboxProviderFactory : resolve provider
```

Two enforcement gates run inside `BrokerWorkerCore.run()` before any provider call, both fail-closed:

- **Principal:** a profile demanding `identity.mode: user` requires a provider declaring `principal_user` *and* a resolver that actually produced a user principal; otherwise the request is rejected.
- **Policy:** every non-default policy dimension (network, filesystem, cpu/memory) is checked against the provider's declared `policy_*` capabilities; unenforceable under `strict: true` raises `SandboxPolicyError`. See [Policy and permissions](../advanced/sandbox.md#policy-and-permissions) for the user-facing semantics.

## Data and wire models

All models are Pydantic. The left column is what travels between manager and worker; the right column is what the capability stores and returns. `SandboxSession` is the cross-turn handle: a stable `sandbox_session_id` minted by the manager, plus the provider-scoped `sandbox_id` used to reconnect.

```mermaid
classDiagram
    direction LR
    class SandboxBrokerRequest {
        +task_id str
        +operation execute_code, execute_command, install_packages, upload_file, download_file, destroy
        +payload dict
        +profile str
        +principal SandboxPrincipal
        +policy SandboxPolicy
        +sandbox_session SandboxSession
        +ak_session_id str
        +agent str
        +wait_deadline float
    }
    class SandboxCompletion {
        +task_id str
        +status succeeded, failed, timed_out
        +result SandboxResult
        +result_ref dict when offloaded
        +error str
        +sandbox_session SandboxSession
    }
    class SandboxPrincipal {
        +mode agent or user
        +subject str
        +credentials dict
        +groups list
    }
    class SandboxPolicy {
        +network_egress allow, deny, allowlist
        +network_allow list
        +fs_allow_read list
        +fs_allow_write list
        +cpu float
        +memory_mb int
        +timeout float
        +strict bool
    }
    class SandboxSession {
        +sandbox_session_id str
        +name str
        +profile str
        +provider_type str
        +sandbox_id str reconnect handle
        +created_at float
        +last_used_at float
        +status active or closed
    }
    class SandboxTask {
        +task_id str
        +sandbox_session_id str
        +profile str
        +status pending, succeeded, failed, timed_out
        +submitted_at float
        +consumed bool
        +notice str
    }
    class SandboxResult {
        +stdout str
        +stderr str
        +exit_code int
        +output_files list
        +sandbox_session_id str
        +notice str
        +provider_data dict
    }
    class SandboxFile {
        +path str
        +content bytes
        +mime_type str
    }

    SandboxBrokerRequest *-- SandboxPrincipal
    SandboxBrokerRequest *-- SandboxPolicy
    SandboxBrokerRequest *-- SandboxSession
    SandboxCompletion *-- SandboxResult
    SandboxCompletion *-- SandboxSession
    SandboxResult o-- SandboxFile
    SandboxTask ..> SandboxSession : addresses by id
```

## Synchronous execution flow

The common path with the default `thread` broker: the manager resolves everything agent-side, the worker enforces everything execution-side, and the result is stamped with the `sandbox_session_id` the agent reuses on the next call.

```mermaid
sequenceDiagram
    autonumber
    participant LLM as Agent turn
    participant Tool as run_code tool
    participant Mgr as SandboxManager
    participant Brk as ThreadBroker
    participant Core as BrokerWorkerCore
    participant Fac as ProviderFactory
    participant Prov as DockerSandboxProvider
    participant Sbx as DockerSandbox

    LLM->>Tool: run_code(code, sandbox_session_id?)
    Tool->>Mgr: execute(code, wait = broker.wait_timeout)
    Mgr->>Mgr: resolve profile, session (scope, idle check), principal, policy
    Mgr->>Brk: submit(SandboxBrokerRequest, wait)
    Note over Brk: enqueue to broker thread, bridge future back
    Brk->>Core: run(request)
    Core->>Fac: get(profile)
    Fac-->>Core: cached provider
    Core->>Core: check principal, enforce policy (fail closed)
    Note over Core: lock per sandbox_session_id
    alt session has sandbox_id
        Core->>Prov: attach(sandbox_id, principal, policy)
    else no backend yet
        Core->>Prov: create(principal, policy)
    end
    Prov-->>Core: Sandbox handle
    Core->>Sbx: execute_code(code) under asyncio.wait_for(policy.timeout)
    Sbx-->>Core: SandboxResult(stdout, stderr, exit_code)
    Core-->>Brk: result + updated session
    Brk-->>Mgr: SandboxResult
    Mgr->>Mgr: persist session handle to registry
    Mgr-->>Tool: SandboxResult
    Tool-->>LLM: JSON stdout, stderr, exit_code, sandbox_session_id
```

## Promotion and task polling

When `wait_timeout` expires before the execution finishes, `ThreadBroker.submit` returns a pending `SandboxTask` while the run continues on the broker thread. The agent polls with `check_sandbox_task`; the manager persists the completed run's session handle so later calls attach to the promoted run's sandbox instead of orphaning it.

```mermaid
sequenceDiagram
    autonumber
    participant LLM as Agent turn
    participant Mgr as SandboxManager
    participant Brk as ThreadBroker
    participant Core as BrokerWorkerCore

    LLM->>Mgr: execute(long-running code, wait = N)
    Mgr->>Brk: submit(request, wait = N)
    Brk->>Core: run(request) on broker thread
    Note over Brk: wait expires before completion
    Brk-->>Mgr: SandboxTask(status = pending)
    Mgr->>Mgr: record task in session registry
    Mgr-->>LLM: JSON task_id, status pending
    Core-->>Brk: completion stored in BoundedCompletionStore

    Note over LLM: a later turn
    LLM->>Mgr: check_sandbox_task(task_id)
    Mgr->>Mgr: registry lookup, still pending
    Mgr->>Brk: result(task_id)
    Brk-->>Mgr: SandboxCompletion
    Mgr->>Mgr: mark task terminal, refresh session handle
    Mgr->>Brk: discard(task_id)
    Mgr-->>LLM: JSON status succeeded / failed / timed_out
```

Remote flavors can also *push* the completion back: the event re-enters as an `AgentRequestAny(name="sandbox_task_completion")` and `SandboxPreHook` consumes it under the session lock before the agent's turn.

```mermaid
sequenceDiagram
    autonumber
    participant W as Remote worker
    participant Chat as ChatService
    participant Hook as SandboxPreHook
    participant Mgr as SandboxManager
    participant LLM as Agent turn

    W-->>Chat: completion event as request sandbox_task_completion
    Chat->>Hook: on_run(requests) under session lock
    Hook->>Mgr: ingest_completion(completion)
    alt fresh completion
        Mgr-->>Hook: updated SandboxTask, consumed = true
        Hook->>LLM: strip event, inject bounded result summary into text request
    else duplicate, unknown, or malformed
        Mgr-->>Hook: None
        Hook-->>Chat: halting AgentReplyText, turn ends as a no-op
    end
```

This is the at-least-once dedup: the `consumed` flag on `SandboxTask` guarantees a re-delivered completion never triggers a second agent turn.

## Session lifecycle

A session handle outlives any single backend sandbox. Idle expiry and a vanished backend (`SandboxGoneError` on attach) both recreate under the *same* `sandbox_session_id`, and both attach a `notice` to the next result: recreation is never silent. The scopes themselves (`per_session`, `per_call`, `per_runtime`) are described in the [Sandbox guide](../advanced/sandbox.md#scopes).

```mermaid
stateDiagram-v2
    [*] --> Registered: new_sandbox_session() or first use of default profile session
    Registered --> Live: first operation, provider.create() sets sandbox_id
    Live --> Live: attach + execute (serialized per session)
    Live --> Live: attach raises SandboxGoneError, self-heal recreate + notice
    Live --> Reset: idle_timeout exceeded on touch, backend destroyed + notice
    Reset --> Live: next operation recreates under the same session id
    Live --> Closed: destroy_sandbox_session() or per_call teardown in finally
    Registered --> Closed: destroy before first use
    Closed --> [*]
```

## Error hierarchy

Every machinery failure derives from `SandboxError`. `SandboxGoneError` doubles as a protocol signal: raised by `attach`, it tells the worker to self-heal by recreating the backend under the same session id. Tools never raise into the framework: any of these is caught at the tool layer and returned to the agent as an `{"error": ...}` JSON string.

```mermaid
classDiagram
    direction TB
    class SandboxError { base of all machinery failures }
    class SandboxConfigError { unknown profile, type, flavor, missing block }
    class SandboxCapabilityError { operation the provider never declared }
    class SandboxPolicyError { unenforceable under strict, identity fail-closed }
    class SandboxTimeoutError { effective execution timeout exceeded }
    class SandboxProvisionError { create or attach failed }
    class SandboxGoneError { attach target vanished, self-heal signal }
    class SandboxSessionNotFoundError { unknown sandbox_session_id }
    class SandboxBrokerError { transport or delivery failure }

    SandboxError <|-- SandboxConfigError
    SandboxError <|-- SandboxCapabilityError
    SandboxError <|-- SandboxPolicyError
    SandboxError <|-- SandboxTimeoutError
    SandboxError <|-- SandboxProvisionError
    SandboxProvisionError <|-- SandboxGoneError
    SandboxError <|-- SandboxSessionNotFoundError
    SandboxError <|-- SandboxBrokerError
```

## Where each piece lives

All paths are under `ak-py/src/agentkernel/`.

| File | Contents |
|---|---|
| `sandbox/base.py` | `Sandbox` and `SandboxProvider` ABCs, the public bring-your-own surface |
| `sandbox/model.py` | `SandboxCapabilities`, `SandboxResult`, `SandboxSession`, `SandboxTask`, `SandboxPrincipal`, `SandboxPolicy`, `IsolationTier` |
| `sandbox/manager.py` | `SandboxManager` singleton façade, session and task registries, scope handling |
| `sandbox/tools.py` | The eight system tools plus the system-prompt guidance injected via the first tool's description |
| `sandbox/hooks.py` | `SandboxPreHook` for push-based task-completion ingestion with dedup |
| `sandbox/principal.py` | `PrincipalResolver` ABC and the default `AgentPrincipalResolver` |
| `sandbox/factory.py` | `SandboxProviderFactory` and `SandboxBrokerFactory`, lazy imports and dotted-path escape hatches |
| `sandbox/errors.py` | The `SandboxError` hierarchy |
| `sandbox/broker/base.py` | `SandboxBroker` ABC, `SandboxBrokerRequest`, `SandboxCompletion`, `BoundedCompletionStore` |
| `sandbox/broker/worker.py` | `BrokerWorkerCore`, the flavor-independent execution engine |
| `sandbox/broker/embedded.py`, `thread.py` | The two in-process broker flavors |
| `sandbox/providers/` | `local_subprocess.py` and `docker.py` reference providers |
| `sandbox/testing.py` | Public `SandboxProviderContract` test suite for new providers |
