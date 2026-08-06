---
sidebar_position: 1
---

# Architecture Overview

Understanding Agent Kernel's architecture helps you build robust, scalable AI agent systems.

## High-Level Architecture

Agent Kernel sits between your agent logic (written in any supported framework) and the surfaces that expose it to the world: CLI, REST/SSE, WebSocket, MCP, A2A, messaging platforms, and cloud deployment targets.

```mermaid
graph TB
    subgraph APP["Application Layer"]
        A[Your Agent Logic + Tools]
    end

    subgraph AK["Agent Kernel Core"]
        B[Module<br/>registration]
        C[Agent<br/>wrapper]
        D[Runner<br/>run / stream]
        F[Runtime<br/>orchestrator]
        E[Session<br/>state]
        HK[Hooks<br/>pre / post]
        SVC[AgentService / ChatService]
    end

    subgraph FW["Framework Adapters"]
        G[OpenAI Agents SDK]
        H[CrewAI]
        I[LangGraph]
        J[Google ADK]
        SA[Smolagents]
    end

    subgraph SYS["System Plugins"]
        GR[Guardrails<br/>OpenAI · Bedrock · Walled AI]
        MM[Multimodal<br/>attachments]
        TH[Conversation Threads]
        KB[Knowledge Bases<br/>Chroma · Neo4j · Starburst]
        TR[Tracing<br/>Langfuse · OpenLLMetry · Logfire]
    end

    subgraph STORE["State Stores"]
        K[In-Memory]
        L[Redis / Valkey]
        M[DynamoDB]
        N[Cosmos DB]
        FS[Firestore]
    end

    subgraph EXEC["Execution Surfaces"]
        O[CLI]
        P[REST API + SSE Streaming]
        WS[WebSocket<br/>AWS API Gateway]
        Q[MCP Server]
        R[A2A Server]
        MSG[Messaging<br/>Slack · WhatsApp · Teams · ...]
        DEP[Cloud Deployments<br/>Lambda · ECS · Functions · Cloud Run]
    end

    A --> B
    B --> C
    C --> D
    C --> F
    D --> E
    E --> F
    HK --> F
    F --> SVC

    C --- G
    C --- H
    C --- I
    C --- J
    C --- SA

    GR --> HK
    MM --> HK
    TH --> SVC
    F --> KB
    F --> TR

    E --> K
    E --> L
    E --> M
    E --> N
    E --> FS

    SVC --> O
    SVC --> P
    SVC --> WS
    SVC --> Q
    SVC --> R
    SVC --> MSG
    SVC --> DEP

    style A fill:#4e85c5,stroke:#fff,stroke-width:2px,color:#fff
    style F fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style SVC fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
    style KB fill:#7d5ba6,stroke:#fff,stroke-width:2px,color:#fff
    style GR fill:#7d5ba6,stroke:#fff,stroke-width:2px,color:#fff
    style MM fill:#7d5ba6,stroke:#fff,stroke-width:2px,color:#fff
    style TH fill:#7d5ba6,stroke:#fff,stroke-width:2px,color:#fff
    style TR fill:#7d5ba6,stroke:#fff,stroke-width:2px,color:#fff
```

**Layers at a glance:**

| Layer | Components | Responsibility |
|-------|-----------|----------------|
| Application | Your agents and tools | Domain logic, written with any supported framework |
| Core | `Module`, `Agent`, `Runner`, `Session`, `Runtime`, hooks, `AgentService`/`ChatService` | Framework-agnostic orchestration, state, and the run/stream pipeline |
| Framework adapters | OpenAI Agents SDK, CrewAI, LangGraph, Google ADK, Smolagents | Wrap native agents behind the core abstractions |
| System plugins | Guardrails, multimodal, conversation threads, knowledge bases, tracing | Cross-cutting features implemented as hooks, tools, and services |
| State stores | In-memory, Redis, Valkey, DynamoDB, Cosmos DB, Firestore | Pluggable persistence for sessions, threads, attachments, and responses |
| Execution surfaces | CLI, REST (JSON + SSE), WebSocket, MCP, A2A, messaging integrations, cloud deployments | How requests reach the runtime and how replies get back out |

## Key Design Principles

### 1. Framework Agnostic

All core abstractions (`Session`, `Agent`, `Runner`, `Module`, `Runtime`) are framework-independent. Framework-specific logic lives exclusively in adapter modules; the same hooks, tools, session stores, and deployment targets work with every supported framework, and agents from different frameworks can run side by side in one runtime.

### 2. Minimal Overhead

The kernel adds minimal latency and complexity; it's primarily orchestration and state management around your framework's native execution.

### 3. Config-Driven Behavior

All runtime behavior is governed by `AKConfig` (Pydantic-based), loaded from YAML/JSON files and environment variables (`AK_` prefix, `__` for nesting). The same application code switches between synchronous REST, SSE streaming, queue-backed async, and WebSocket delivery purely through configuration.

### 4. Production Ready

Built-in support for:
- Multi-cloud session persistence (AWS, Azure, GCP)
- Token-level streaming (SSE over REST, WebSocket on AWS serverless)
- Queue-based scalable execution (SQS-backed, on Lambda and ECS)
- Input/output guardrails and PII redaction
- Multi-agent coordination and multimodal attachments
- Observability and tracing (Langfuse, OpenLLMetry, Logfire)

### 5. Extensible

Pluggable via well-defined interfaces:
- New framework adapters (`Agent`/`Runner`/`Module`/`ToolBuilder` subclasses)
- Custom session, thread, and attachment storage backends
- Custom guardrail and tracing providers
- Pre/post execution hooks
- Knowledge base backends

## The Run Pipeline

`Runtime.run()` is the heart of every execution surface. It wraps the framework call with session locking, hooks, and persistence:

```mermaid
sequenceDiagram
    participant U as Caller (CLI / REST / Queue / WS)
    participant SVC as AgentService
    participant R as Runtime
    participant PH as PreHooks
    participant Run as Runner
    participant F as Framework
    participant PoH as PostHooks
    participant Store as SessionStore

    U->>SVC: run(prompt) / run_multi(requests)
    SVC->>R: run(agent, session, requests)
    R->>R: acquire session lock
    R->>PH: agent pre-hooks, then system pre-hooks<br/>(guardrails, multimodal, RAG, ...)
    alt a pre-hook halts
        PH-->>R: AgentReply
        R-->>SVC: halted reply (agent never runs)
    else continue
        PH-->>R: (possibly modified) requests
        R->>Run: runner.run(agent, session, requests)
        Run->>F: native framework execution
        F-->>Run: result
        Run-->>R: AgentReply
        R->>PoH: system post-hooks, then agent post-hooks<br/>(output guardrails, disclaimers, ...)
        PoH-->>R: final AgentReply
    end
    R->>Store: store(session)
    R->>R: clear volatile cache
    R-->>SVC: AgentReply
    SVC-->>U: response
```

Key properties:

- **Session locking**: `async with session` serializes concurrent requests for the same session and sets the session as the current context (`Session.current()` works anywhere inside the run).
- **Pre-hooks** can rewrite the request list or halt execution by returning an `AgentReply` (this is how input guardrails block a request before the LLM sees it).
- **Post-hooks** can transform the reply (output guardrails, disclaimers, redaction).
- **Persistence and cleanup** always run: the session is stored and the volatile cache cleared even if the run raises.

## The Streaming Pipeline

`Runtime.stream()` is the streaming counterpart, sharing the same pre-hook pipeline but yielding `StreamChunk` objects as tokens arrive:

```mermaid
sequenceDiagram
    participant U as Client
    participant R as Runtime
    participant PH as PreHooks
    participant Run as Runner.stream()
    participant PoH as PostHook.on_stream_chunk()

    U->>R: stream(agent, session, requests)
    R->>PH: pre-hook pipeline (same as run)
    alt halted by pre-hook
        R-->>U: StreamChunk(error=..., done=true)
    else streaming
        loop each token delta
            Run-->>R: delta (str)
            R->>PoH: on_stream_chunk(delta)
            alt hook returns None
                Note over R: token dropped
            else
                R-->>U: StreamChunk(delta=...)
            end
        end
        R->>R: store session, clear volatile cache
        R-->>U: StreamChunk(done=true, session_id=...)
    end
```

- Each `StreamChunk` carries `delta`, `done`, `error`, and `session_id` fields.
- Post-hooks can filter or redact individual tokens via `on_stream_chunk()`; returning `None` drops the token.
- Delivery depends on the surface: the REST API serves chunks as **Server-Sent Events** (`text/event-stream`); AWS serverless and AWS ECS containerized WebSocket modes push each chunk as a separate `STREAM_CHUNK` WebSocket message (optionally through SQS queues).
- OpenAI Agents SDK, LangGraph, and Google ADK stream natively; CrewAI and Smolagents do not support token streaming (their runners raise `NotImplementedError` in stream mode).

See [Execution Flow](./execution-flow) for the full request lifecycle including the queue-based and WebSocket paths.

## Scalable Execution Topologies

Beyond the in-process pipeline above, Agent Kernel ships deployment adapters that decouple request ingestion from agent execution using SQS queues. The same `execution` config block drives both:

```mermaid
graph LR
    CL[Client] --> RH[Request Handler<br/>Lambda / IO container]
    RH --> IQ[/Input Queue SQS FIFO/]
    IQ --> AR[Agent Runner<br/>Lambda / ECS service]
    AR --> OQ[/Output Queue SQS FIFO/]
    OQ --> RSH[Response Handler<br/>Lambda / output-consumer thread]
    RSH --> RS[(Response Store<br/>DynamoDB / Redis / Valkey)]
    RSH -. WebSocket push .-> CL
    RS -. poll .-> RH

    style RH fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style AR fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style RSH fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

- On **AWS Lambda**, the three roles are three Lambda functions wired by SQS event source mappings; see [AWS Serverless](../deployment/aws-serverless).
- On **AWS ECS Fargate**, the request handler and response handler run as threads inside one IO container, and the agent runner is a separate auto-scaling ECS service with a pool of consumer threads; see [AWS Containerized](../deployment/aws-containerized) and the [Queue Mode Guide](../advanced/queue-mode-guide).
- The client receives the reply either by **polling** the response store (`rest_sync` waits server-side, `rest_async` polls with a `request_id`) or by **WebSocket push** (`async` for full responses, `stream` for token-level chunks) on both AWS serverless and AWS ECS containerized.

## Next Steps

- [Execution Flow](./execution-flow): request lifecycle across all execution modes
- [Session Management](/docs/core-concepts/session): detailed session configuration
- [Memory Management](./memory-management): advanced memory features
- [Knowledge Bases](../advanced/knowledge-bases.md): knowledge backends and KB routing
- [Deployment Overview](../deployment/overview): choosing a deployment mode
