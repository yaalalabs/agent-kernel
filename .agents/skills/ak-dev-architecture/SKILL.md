---
name: ak-dev-architecture
description: >
  Agent Kernel architectural principles, core abstractions, and design patterns.
  Use this skill when you need to understand the codebase structure, how components
  interact, or before making changes to core functionality. Covers Session, Agent,
  Runner, Module, Runtime, AgentService, AKConfig, tools, hooks, multimodal, the adapter pattern,
  and the AWS ECS containerized deployment classes (ECSIOHandler, ECSOutputConsumer,
  ECSAgentRunner, ECSSQSConsumer, ThreadRunner).
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Agent Kernel Architecture

## Design Principles

1. **Framework-agnostic core**: All core abstractions (`Session`, `Agent`, `Tool`, `Runner`, `Module`, `Runtime`) are framework-independent. Framework-specific logic lives exclusively in adapter modules under `ak-py/src/agentkernel/framework/`.
2. **Adapter pattern**: Each supported agent framework (OpenAI Agents SDK, CrewAI, LangGraph, Google ADK, and Smolagents) implements `Agent`, `Tool`, `Runner`, and `Module` subclasses that wrap native framework objects.
3. **Config-driven behavior**: All runtime behavior is governed by `AKConfig` (Pydantic-based), loaded from YAML/JSON files and environment variables (`AK_` prefix, `__` for nesting).
4. **Session lifecycle**: Sessions are async context managers providing concurrency-safe state management. Session stores are pluggable (in-memory, Redis, DynamoDB, Cosmos DB).
5. **Plugin architecture**: Tools, hooks, guardrails, tracing providers, session stores, and messaging integrations are all pluggable via well-defined interfaces.
6. **Minimal coupling**: Integrations (Slack, WhatsApp, etc.), deployment adapters (Lambda, Azure Functions), and API layers (REST, MCP, A2A) depend on the core but the core never depends on them.

## Core Abstractions

### Session (`ak-py/src/agentkernel/core/base.py`)

Tracks state across related interactions. Key properties:

- **`id`**: Unique session identifier
- **Framework-specific data**: Stored via `get(key)` / `set(key, value)` — each framework stores its own state under a unique key (e.g., `"openai"`, `"langgraph"`)
- **Volatile cache** (`v_cache`): Cleared after every `Runtime.run()` invocation — use for transient per-request data
- **Non-volatile cache** (`nv_cache`): Persisted across requests within the session — use for data that should survive multiple interactions
- **Async context manager**: `async with session:` acquires a lock and sets the session as the current context via `contextvars`
- **`Session.current()`**: Class method to retrieve the active session from any code running within the session context

### Agent (`ak-py/src/agentkernel/core/base.py`)

Wraps a framework-specific agent. Key properties:

- **`name`**: Derived from the native agent (e.g., OpenAI `agent.name`, CrewAI `agent.role`)
- **`runner`**: The `Runner` instance that executes this agent
- **`pre_hooks` / `post_hooks`**: Lists of `PreHook` / `PostHook` instances applied during execution
- **`get_description()`**: Abstract method — returns the agent's description/instructions
- **`get_a2a_card()`**: Abstract method — returns an A2A agent card for inter-agent communication

### Runner (`ak-py/src/agentkernel/core/base.py`)

Encapsulates framework-specific execution logic:

- **`run(agent, session, requests) -> AgentReply`**: Async method that executes the agent with the given requests within a session context
- Each framework implements its own Runner (e.g., `OpenAIRunner`, `LangGraphRunner`, `CrewAIRunner`, `GoogleADKRunner`)
- Runners handle: creating `ToolContext`, converting request models to framework-native formats, invoking the framework's execution API, converting responses back to `AgentReply`

### Module (`ak-py/src/agentkernel/core/module.py`)

Container that wraps framework agents and registers them with Runtime:

- **`load(agents)`**: Takes a list of native framework agents, wraps each via `_wrap()`, registers with `Runtime.current()`
- **`_wrap(agent, agents) -> Agent`**: Abstract method — framework adapters implement this to create their `Agent` subclass
- **`pre_hook(agent, hooks)` / `post_hook(agent, hooks)`**: Attach hooks to a specific agent
- **`unload()`**: Deregisters all agents from the Runtime
- Constructed with native framework agents: e.g., `OpenAIModule([triage_agent, math_agent])`

### Runtime (`ak-py/src/agentkernel/core/runtime.py`)

Global orchestrator and agent registry:

- **Singleton**: `Runtime.current()` returns the global `GlobalRuntime` instance (or the active context-managed runtime)
- **Agent registry**: `register(agent)`, `deregister(agent)`, `agents()` (returns `dict[str, Agent]`)
- **Session store**: `sessions()` returns the configured `SessionStore`
- **`run(agent, session, requests) -> AgentReply`**: The central execution method:
  1. Acquires session lock (`async with session`)
  2. Runs pre-hooks (agent hooks + system hooks like input guardrails)
  3. Calls `agent.runner.run(agent, session, requests)`
  4. Runs post-hooks (system hooks + agent hooks)
  5. Stores session via `SessionStore.store()`
  6. Clears volatile cache in `finally` block
- **System hooks**: Automatically includes `InputGuardrailFactory` as system pre-hook, `OutputGuardrailFactory` as system post-hook
- **Context manager**: `with Runtime(sessions):` sets an isolated runtime as current

### AgentService (`ak-py/src/agentkernel/core/service.py`)

High-level utility encapsulating a conversation:

- Combines a `Runtime`, a selected `Agent`, and a `Session`
- **`select(name, session_id)`**: Selects an agent and loads/creates a session
- **`run(prompt) -> str`**: Wraps prompt in `AgentRequestText`, calls `runtime.run()`, returns text
- **`run_multi(requests) -> AgentReply`**: For multi-modal requests
- Used by CLI, API handlers, and integration handlers

### AKConfig (`ak-py/src/agentkernel/core/config.py`)

Pydantic-based configuration:

- **Auto-initialized** at import time via `AKConfig._set()`
- **Config sources** (priority order): environment variables (`AK_` prefix) → config file (YAML/JSON, default `config.yaml`) → defaults
- **Override path**: Set `AK_CONFIG_PATH_OVERRIDE` env var
- **Key sections**: `session`, `api`, `a2a`, `mcp`, `slack`, `whatsapp`, `messenger`, `instagram`, `telegram`, `gmail`, `multimodal`, `trace`, `test`, `guardrail`

## Request/Reply Model (`ak-py/src/agentkernel/core/model.py`)

- **Request types**: `AgentRequestText`, `AgentRequestFile`, `AgentRequestImage`, `AgentRequestAny`
- **Reply types**: `AgentReplyText`, `AgentReplyImage`
- Type aliases: `AgentRequest = Union[...]`, `AgentReply = Union[...]`

## Tools (`ak-py/src/agentkernel/core/tool.py`)

- **`ToolContext`**: Execution context available inside tool functions via `ToolContext.get()`. Provides access to `runtime`, `agent`, `session`, `requests`.
- **`ToolBuilder`**: Base class for framework-specific tool builders. Each framework implements `bind(funcs)` to wrap plain Python functions into framework-native tool objects.
- Write plain Python functions → bind via the framework's ToolBuilder → tools work across frameworks

## Hooks (`ak-py/src/agentkernel/core/hooks.py`)

- **`PreHook`**: `on_run(session, agent, requests) -> list[AgentRequest] | AgentReply` — return modified requests to continue, or an `AgentReply` to halt execution
- **`PostHook`**: `on_run(session, requests, agent, agent_reply) -> AgentReply` — return modified or unmodified reply
- Use cases: RAG injection, input/output guardrails, logging, disclaimers, prompt modification, multimodal preprocessing

## Multimodal (`ak-py/src/agentkernel/core/multimodal/`)

Provides image and file attachment support via a pluggable storage and PreHook architecture. When enabled, attachments are automatically processed, described via a vision LLM, and stored outside the session to prevent memory bloat.

### Key Components

- **`MultimodalPreHook`** (`hooks.py`): System `PreHook` that intercepts `AgentRequestImage` / `AgentRequestFile` entries, calls a vision LLM (via LiteLLM) for a brief description, saves binary data to a storage backend, removes raw binaries from the request list, and injects attachment metadata (IDs + descriptions) into the last `AgentRequestText`
- **`MultimodalPreHookFactory`** (`factory.py`): Returns `MultimodalPreHook` when `config.multimodal.enabled` is `True`, otherwise a `NoOpPreHook`
- **`AnalyzeAttachmentsTool`** (`tools.py`): A `SystemTool` auto-registered on all agents when multimodal is enabled. Lets the agent retrieve and analyze stored attachments (images and PDFs) on demand via the `analyze_attachments(attachment_ids, prompt)` function
- **`AttachmentStorageManager`** (`storage/storage_manager.py`): High-level API that delegates to the configured `AttachmentStore` backend. Generates UUIDs for attachment IDs and serializes `AttachmentData` dicts
- **`AttachmentStore`** (`storage/base.py`): Abstract base with `save()`, `get()`, `delete()` methods
- **`AttachmentData`** (`storage/base.py`): Dataclass: `id`, `type`, `data` (base64), `name`, `mime_type`, `description`, `timestamp`

### Storage Backends

| Backend | Class | Module | Key traits |
|---------|-------|--------|------------|
| In-memory | `InMemoryAttachmentStore` | `storage/in_memory.py` | `ClassVar` dict, ephemeral, zero setup |
| Redis | `RedisAttachmentStore` | `storage/redis.py` | Persistent, TTL, connection pooling |
| DynamoDB | `DynamoDBAttachmentStore` | `storage/dynamodb.py` | Serverless/AWS, TTL via `expiry_time` |
| Session cache | `SessionNonVolatileCacheAttachmentStore` | `storage/session_cache.py` | Legacy, stores in `nv_cache` (not recommended) |

### Execution Flow

```
User sends {text + image/file}
  → MultimodalPreHook.on_run()
    → _describe_attachment_briefly()        # Vision LLM via LiteLLM
    → AttachmentStorageManager.save_attachment()  # store binary
    → Remove AgentRequestImage/AgentRequestFile from requests
    → Inject "[Attached Images/Files:]\n- <id>: <description>" into last AgentRequestText
  → Agent sees text with attachment metadata only (no binary)
  → Agent calls analyze_attachments(ids, prompt) when detailed analysis is needed
    → AttachmentStorageManager.get_attachment_data()
    → LiteLLM vision call with binary + user prompt
    → Returns analysis text (clean for conversation history)
```

### Configuration (`_MultimodalConfig` in `config.py`)

```yaml
multimodal:
  enabled: true
  storage_type: in_memory        # in_memory | redis | dynamodb | session_cache
  max_attachments: 20
  description_max_length: 200
  description_model: gpt-4o      # LiteLLM model for brief descriptions (PreHook)
  analysis_model: gpt-4o         # LiteLLM model for detailed analysis (tool)
  redis:
    url: "redis://localhost:6379"
    ttl: 604800
    prefix: "ak:attachments:"
  dynamodb:
    table_name: "ak-attachments"
    ttl: 604800
```

## Directory Structure

```
ak-py/src/agentkernel/
├── core/                    # Framework-agnostic abstractions
│   ├── base.py              # Session, Agent, Runner
│   ├── module.py            # Module
│   ├── runtime.py           # Runtime, GlobalRuntime
│   ├── service.py           # AgentService
│   ├── config.py            # AKConfig
│   ├── model.py             # Request/Reply models
│   ├── tool.py              # ToolContext, ToolBuilder
│   ├── hooks.py             # PreHook, PostHook
│   ├── builder.py           # SessionStoreBuilder, A2ACardBuilder
│   └── session/             # Session store implementations
│       ├── base.py           # SessionStore, SessionCache
│       ├── in_memory.py
│       ├── redis.py
│       ├── dynamodb.py
│       └── cosmosdb.py
├── framework/               # Framework adapters
│   ├── openai/              # OpenAI Agents SDK adapter
│   ├── crewai/              # CrewAI adapter
│   ├── langgraph/           # LangGraph adapter
│   └── adk/                 # Google ADK adapter
├── api/                     # API layers
│   ├── handler.py           # REST API handler
│   ├── http.py              # RESTAPI class
│   ├── a2a/                 # Agent-to-Agent server
│   └── mcp/                 # MCP server
├── deployment/              # Cloud deployment adapters
│   ├── aws/
│   │   ├── serverless/      # Lambda handlers: Lambda, ResponseHandler, ServerlessAgentRunner, etc.
│   │   ├── containerized/   # ECS Fargate handlers
│   │   │   ├── core/
│   │   │   │   ├── sqs_consumer.py      # ECSSQSConsumer — ABC: SQS poll loop
│   │   │   │   └── thread_runner.py     # ThreadRunner — run N callables as peer threads
│   │   │   ├── akagentrunner.py         # ECSAgentRunner — polls Input Queue, runs agent
│   │   │   ├── akoutputconsumer.py      # ECSOutputConsumer — polls Output Queue, writes to DB/WS
│   │   │   ├── ecs_io_handler.py        # ECSIOHandler — entrypoint: wires both threads
│   │   │   └── ecs_queue_handler.py     # ECSQueueRequestHandler — FastAPI routes
│   │   └── core/            # Shared: SQSHandler, WebSocketHandler, ResponseStore
│   └── azure/               # Azure Functions handler
├── integration/             # Messaging integrations
│   ├── slack/
│   ├── whatsapp/
│   ├── messenger/
│   ├── instagram/
│   ├── telegram/
│   └── gmail/
├── guardrail/               # Guardrail providers
│   ├── guardrail.py         # Factory + base
│   ├── openai.py            # OpenAI guardrails
│   ├── bedrock.py           # AWS Bedrock guardrails
│   └── walledai.py          # Walled AI guardrails (safety + PII redaction)
├── trace/                   # Observability
│   ├── base.py              # BaseTrace
│   ├── trace.py             # Trace factory
│   ├── langfuse/            # Langfuse adapter
│   └── openllmetry/         # OpenLLMetry adapter
├── cli/                     # CLI interface
│   └── cli.py               # Interactive CLI
├── auth/                    # Authentication
├── test/                    # Test automation
└── core/multimodal/         # Multimodal support
    ├── factory.py            # MultimodalPreHookFactory (NoOp when disabled)
    ├── hooks.py              # MultimodalPreHook (describe + save + inject)
    ├── tools.py              # AnalyzeAttachmentsTool (SystemTool)
    └── storage/              # Pluggable attachment stores
        ├── base.py            # AttachmentStore ABC, AttachmentData
        ├── storage_manager.py # AttachmentStorageManager (high-level API)
        ├── in_memory.py       # InMemoryAttachmentStore
        ├── redis.py           # RedisAttachmentStore
        ├── dynamodb.py        # DynamoDBAttachmentStore
        └── session_cache.py   # SessionNonVolatileCacheAttachmentStore (legacy)
```

## AWS ECS Containerized Deployment

The containerized deployment runs on ECS Fargate and uses a two-container architecture for scalable queue-based processing.

### Class Hierarchy

| Class | File | Role |
|---|---|---|
| `ECSSQSConsumer` | `containerized/core/sqs_consumer.py` | Abstract base: SQS long-poll loop, retry/DLQ logic |
| `ThreadRunner` | `containerized/core/thread_runner.py` | Runs N callables as peer threads via `ThreadPoolExecutor` |
| `ECSOutputConsumer` | `containerized/akoutputconsumer.py` | Extends `ECSSQSConsumer` — polls Output Queue, writes to DynamoDB or broadcasts via WebSocket |
| `ECSAgentRunner` | `containerized/akagentrunner.py` | Extends `ECSSQSConsumer` — polls Input Queue, runs the agent, sends to Output Queue |
| `ECSIOHandler` | `containerized/ecs_io_handler.py` | Entrypoint for the IO container: wires REST API + output consumer as peer threads |
| `ECSQueueRequestHandler` | `containerized/ecs_queue_handler.py` | FastAPI routes: `POST /api/v1/chat` enqueues; `GET /api/v1/chat/{id}` polls |

### Two-Container Layout

```
Container 1 — ECSIOHandler
  Thread 1 (ThreadRunner):  RESTAPI.run(handlers=[ECSQueueRequestHandler()])
                            — FastAPI/uvicorn, handles POST /chat and GET /chat/{id}
  Thread 2 (ThreadRunner):  ECSOutputConsumer.run()
                            — polls Output Queue, writes to DynamoDB / broadcasts via WebSocket

Container 2 — ECSAgentRunner
  Main thread:              ECSSQSConsumer.run()
                            — polls Input Queue, runs agent, sends result to Output Queue
```

### ECSSQSConsumer Contract

- **`_get_queue_url(cls) → str`** *(abstract)*: return the SQS queue URL to poll.
- **`process_message(cls, record)`** *(abstract)*: handle one message; called on every successful receive.
- **`on_permanent_failure(cls, record)`** *(abstract)*: called when `ApproximateReceiveCount > max_receive_count`; **must catch its own exceptions** — if it raises, the message is not deleted and loops back.
- **`delete_message(cls, client, msg)`** *(public)*: subclasses may call this directly when manual deletion is needed.
- **`run(cls)`**: blocking poll loop — the container entry-point.

### ThreadRunner Contract

`ThreadRunner.run(*targets, thread_names=..., exit_on_failure=True)` submits all callables to a `ThreadPoolExecutor` and waits for `FIRST_COMPLETED`:

- Thread **raises** → logs exception; if `exit_on_failure=True`, calls `os._exit(1)` inside the `with` block so the container restarts cleanly via ECS (the `_exit` is placed before `executor.shutdown(wait=True)` to avoid blocking on the other infinite-loop thread).
- Thread **returns normally** (no exception) → logs unexpected exit; `os._exit` is **not** called.

### Entry Point Pattern

```python
# Container 1 — app_rest_service.py
from agentkernel.deployment.aws.containerized import ECSIOHandler

runner = ECSIOHandler.run

if __name__ == "__main__":
    runner()

# Container 2 — app_agent_runner.py
from agentkernel.deployment.aws import ECSAgentRunner
from agentkernel.openai import OpenAIModule

OpenAIModule([...])

if __name__ == "__main__":
    ECSAgentRunner.run()
```

### Public Exports

```python
# agentkernel.deployment.aws
from agentkernel.deployment.aws import (
    ECSAgentRunner,      # Container 2 entry-point
    ECSIOHandler,        # Container 1 entry-point
    ECSOutputConsumer,   # Subclass ECSSQSConsumer for custom output processing
)
from agentkernel.deployment.aws.containerized.core import ECSSQSConsumer, ThreadRunner
```

## Execution Flow

```
User Input
    → AgentService.run(prompt)
        → AgentRequestText(text=prompt)
        → Runtime.run(agent, session, requests)
            → async with session:                    # acquire lock, set context
            → PreHooks (agent hooks, then system)    # guardrails, multimodal, RAG, etc.
            → agent.runner.run(agent, session, requests)  # framework execution
            → PostHooks (system, then agent hooks)   # output guardrails
            → session_store.store(session)           # persist state
            → clear volatile cache                   # cleanup
        → AgentReply
    → response text
```

### Multimodal Execution Flow

When multimodal is enabled and the request contains images/files:

```
User Input (text + image/file)
    → Runtime.run(agent, session, requests)
        → MultimodalPreHook.on_run()
            → Describe attachments via vision LLM (LiteLLM)
            → Save binary data to storage backend
            → Replace requests: drop images/files, inject metadata into text
        → agent.runner.run(agent, session, modified_requests)
            → Agent sees text with attachment IDs + descriptions
            → Agent may call analyze_attachments(ids, prompt) for details
                → Retrieves binary from storage, calls LLM, returns analysis text
        → PostHooks
    → AgentReply (no binary data in conversation history)
```
