---
name: ak-dev-architecture
description: >
  Agent Kernel architectural principles, core abstractions, and design patterns.
  Use this skill when you need to understand the codebase structure, how components
  interact, or before making changes to core functionality. Covers Session, Agent,
  Runner, Module, Runtime, AgentService, AKConfig, tools, hooks, multimodal, conversation
  threads, the adapter pattern, and the AWS ECS containerized deployment classes
  (ECSIOHandler, ECSOutputConsumer, ECSAgentRunner, ECSStreamAgentRunner, ECSSQSConsumer, QueueConsumer, ThreadRunner).
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Agent Kernel Architecture

## Design Principles

1. **Framework-agnostic core**: All core abstractions (`Session`, `Agent`, `Tool`, `Runner`, `Module`, `Runtime`) are framework-independent. Framework-specific logic lives exclusively in adapter modules under `ak-py/src/agentkernel/framework/`.
2. **Adapter pattern**: Each supported agent framework (OpenAI Agents SDK, CrewAI, LangGraph, Google ADK, Smolagents, and Pydantic AI) implements `Agent`, `Tool`, `Runner`, and `Module` subclasses that wrap native framework objects.
3. **Config-driven behavior**: All runtime behavior is governed by `AKConfig` (Pydantic-based), loaded from YAML/JSON files and environment variables (`AK_` prefix, `__` for nesting).
4. **Session lifecycle**: Sessions are async context managers providing concurrency-safe state management. Session stores are pluggable (in-memory, Redis, Valkey, DynamoDB, Cosmos DB, Firestore).
5. **Plugin architecture**: Tools, hooks, guardrails, tracing providers, session stores, knowledge base backends, sandbox providers, and messaging integrations are all pluggable via well-defined interfaces. Backend-selection factories (guardrail, trace, session/thread/multimodal stores, sandbox provider) share one shape via `core/util/factory.py` (`resolve_dotted`, `require_extra`, `AKConfigError`): built-ins resolved by `if/elif` + real imports, with a dotted-path "bring your own" branch on every surface.
6. **Minimal coupling**: Integrations (Slack, WhatsApp, etc.), deployment adapters (AWS Lambda, Azure Functions, Google Cloud Run), and API layers (REST, MCP, A2A) depend on the core but the core never depends on them.

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
- **`stream(agent, session, requests) -> AsyncGenerator[str, None]`**: Abstract async generator that yields token deltas for streaming execution (`execution.mode: stream`). Frameworks without native token streaming (CrewAI, smolagents) implement it by raising `NotImplementedError`
- Each framework implements its own Runner (e.g., `OpenAIRunner`, `LangGraphRunner`, `CrewAIRunner`, `GoogleADKRunner`, `SmolagentsRunner`, `PydanticAIRunner`)
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
- **`stream(agent, session, requests) -> AsyncGenerator[StreamChunk, None]`**: Streaming counterpart of `run()`, sharing the same pre-hook pipeline via `_prepare_requests()`:
  1. Runs pre-hooks; if halted, yields a `StreamChunk(error=..., done=True)` and returns
  2. Iterates `agent.runner.stream(agent, session, requests)`, passing each token delta through `PostHook.on_stream_chunk()` (a hook can drop a token by returning `None`)
  3. Yields a `StreamChunk(delta=...)` per token, then a final `StreamChunk(done=True, session_id=...)`
  4. Stores session and clears volatile cache in `finally`, same as `run()`
- **System hooks**: Automatically includes `InputGuardrailFactory` as system pre-hook, `OutputGuardrailFactory` as system post-hook
- **Context manager**: `with Runtime(sessions):` sets an isolated runtime as current

### AgentService (`ak-py/src/agentkernel/core/service.py`)

High-level utility encapsulating a conversation:

- Combines a `Runtime`, a selected `Agent`, and a `Session`
- **`select(name, session_id)`**: Selects an agent and loads/creates a session
- **`run(prompt) -> str`**: Wraps prompt in `AgentRequestText`, calls `runtime.run()`, returns text
- **`run_multi(requests) -> AgentReply`**: For multi-modal requests
- **`stream_multi(requests) -> AsyncGenerator[StreamChunk, None]`**: Calls `runtime.stream()`, yielding `StreamChunk` objects for token-level streaming
- Used by CLI, API handlers, and integration handlers

### AKConfig (`ak-py/src/agentkernel/core/config.py`)

Pydantic-based configuration:

- **Auto-initialized** at import time via `AKConfig._set()`
- **Config sources** (priority order): environment variables (`AK_` prefix) → config file (YAML/JSON, default `config.yaml`) → defaults
- **Override path**: Set `AK_CONFIG_PATH_OVERRIDE` env var
- **Key sections**: `session`, `api`, `websocket_api`, `a2a`, `mcp`, `slack`, `whatsapp`, `messenger`, `instagram`, `telegram`, `gmail`, `multimodal`, `trace`, `guardrail`, `execution`, `logging`

## Request/Reply Model (`ak-py/src/agentkernel/core/model.py`)

- **Request types**: `AgentRequestText`, `AgentRequestFile`, `AgentRequestImage`, `AgentRequestAny`
- **Reply types**: 
  - `AgentReplyText`, 
  - `AgentReplyImage`
  - `AgentReplyAny`: `content: dict` — returned when the agent is configured for structured output (OpenAI `output_type`, LangGraph `response_format`, ADK `output_schema`, CrewAI module-level `output_pydantic`/`output_json`, Smolagents dict/Pydantic `final_answer`, Pydantic AI `output_type`); `str(reply)` returns the JSON-serialized content. Non-streaming only.
  - `StreamChunk`: `delta: str | None`, `done: bool`, `error: str | None`, `session_id: str | None` — yielded by `Runtime.stream()` / `AgentService.stream_multi()` for token-level streaming
- Type aliases: `AgentRequest = Union[...]`, `AgentReply = Union[...]`

## Tools (`ak-py/src/agentkernel/core/tool.py`)

- **`ToolContext`**: Execution context available inside tool functions via `ToolContext.get()`. Provides access to `runtime`, `agent`, `session`, `requests`.
- **`ToolBuilder`**: Base class for framework-specific tool builders. Each framework implements `bind(funcs)` to wrap plain Python functions into framework-native tool objects.
- Write plain Python functions → bind via the framework's ToolBuilder → tools work across frameworks

## Hooks (`ak-py/src/agentkernel/core/hooks.py`)

- **`PreHook`**: `on_run(session, agent, requests) -> list[AgentRequest] | AgentReply` — return modified requests to continue, or an `AgentReply` to halt execution
- **`PostHook`**: `on_run(session, requests, agent, agent_reply) -> AgentReply` — return modified or unmodified reply
- **`PostHook.on_stream_chunk(session, requests, agent, delta) -> str | None`**: Optional override called for each streaming token delta before it reaches the client. Default implementation passes the delta through unchanged; return `None` to drop the token
- Use cases: RAG injection, input/output guardrails, logging, disclaimers, prompt modification, multimodal preprocessing, streaming token filtering/redaction

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
| Redis | `RedisAttachmentStore` | `storage/redis.py` | Persistent, TTL, shared `RedisDriver` (lazy connect, retry, ping/reconnect) |
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

## Conversation Threads (`ak-py/src/agentkernel/core/thread/`)

Provides persistent, named conversation threads keyed by `session_id`, gated behind a `thread` config block and independent of session persistence (`session:`). When enabled, `user_id` becomes required on every chat request, a thread is auto-created on a session's first request, and history becomes readable over REST.

### Key Components

- **`ConversationThreadManager`** (`manager.py`): Service façade owning thread lifecycle (create/load/append/history) and, when multimodal is enabled, saving attachment bytes into the shared `AttachmentStore` before the agent runs. A single process-wide instance (`ConversationThreadManager.get()` / class-level singleton, guarded by an `RLock`) is shared by `ChatService` and `ThreadRESTRequestHandler` — `None` when thread support is disabled
- **`ThreadStore`** (`store/base.py`): Abstract base with backend persistence methods (create/get/append/list); pluggable per backend
- **`ThreadStoreBuilder`** (`store/__init__.py`): Factory that constructs the configured `ThreadStore` from `AKConfig`'s `thread.type`
- **`Thread` / `ThreadMessage` / `ThreadAttachment` / `ThreadPage` / `MessagePage`** (`model.py`): Pydantic models for thread metadata, individual messages, attachment references, and cursor-paginated listings
- **`ThreadNamingStrategy`** (`naming.py`): Overridable strategy that names auto-created threads — default implementation makes a single LiteLLM call (`thread.naming.model`, requires the `thread` extra) to derive a concise title from the first prompt, falling back to a truncated prompt prefix when `litellm`/an API key is unavailable. Explicit `thread_name` on a chat request always wins and locks the thread against further automatic naming
- **`Authoriser`** (`authoriser.py`): Pluggable base class (`authorise(token) -> Optional[user_id]`) that `ThreadRESTRequestHandler` calls to protect the read routes; routes are open when no `Authoriser` is configured
- **`ThreadRESTRequestHandler`** (`api/thread.py`): Mounts `GET /api/v1/threads` (list, filterable by `user_id`/`group_id`, cursor-paginated) and `GET /api/v1/threads/{session_id}` (thread + paginated message history); raises 404 when thread support is disabled and 403 when a resolved `user_id` doesn't own the requested thread

### Store Backends

| Backend | Class | Module | Key traits |
|---------|-------|--------|------------|
| In-memory | `InMemoryThreadStore` | `store/in_memory.py` | `ClassVar` dict, ephemeral, zero setup |
| Redis | `RedisThreadStore` | `store/redis.py` | Persistent, TTL, index-key expiry/refresh for listings |
| DynamoDB | `DynamoDBThreadStore` | `store/dynamodb.py` | Serverless/AWS, partition key `session_id` + sort key `sk`, optional TTL |
| Firestore | `FirestoreThreadStore` | `store/firestore.py` | Serverless/GCP, one document per `session_id` |
| Cosmos DB | `CosmosDBThreadStore` | `store/cosmosdb.py` | Azure Table API, partitioned by `session_id`, no TTL support |

### Configuration (`_ThreadConfig` in `config.py`)

```yaml
thread:
  type: memory       # memory | redis | dynamodb | firestore | cosmosdb
  naming:
    model: gpt-4o-mini
    max_length: 80
  redis:
    url: "redis://localhost:6379"
    ttl: 2592000
    prefix: "ak:thread:"
  dynamodb:
    table_name: "ak-agent-threads"
    ttl: 0
```

Attachments in thread mode additionally require `multimodal.enabled: true` with a shared attachment store (`in_memory`, `redis`, or `dynamodb` — `session_cache` is rejected, since threads need durable, cross-request-scoped attachment storage that a session-local cache can't provide).

## Knowledge Bases (`ak-py/src/agentkernel/knowledgebase/`)

Pluggable storage backends agents can read from and write to as tools:

- **`KnowledgeBase`** (`base.py`): ABC — backends implement `connect()`, `write()`, `read()`, `backend_name`, `get_description()`; `schema()`, `add_schema()`, `format_results()`, `close()` are provided by the base
- **`KnowledgeBuilder`** (`knowledgebuilder.py`): Wraps one or more `KnowledgeBase` instances and `build()`s plain-function tools (`get_schemas`, `read_kb`, `write_kb`, `get_all_kb_descriptions`) for binding via a framework's `ToolBuilder`
- **Backends**: `ChromaManager` (vector, `chroma.py`), `Neo4jManager` (graph, `neo4j.py`), `StarburstManager` (read-only SQL via Trino, `starburst.py`) — each behind an optional dependency extra (`chromadb`, `neo4j`, `trino`)

## Sandbox (`ak-py/src/agentkernel/sandbox/`)

Config-driven, pluggable code execution: agents run code, shell commands, and file operations in
an isolated, permission-bounded environment. Enabled via a `sandbox` block in `config.yaml`;
inert when disabled. To add a provider, use the `ak-dev-new-sandbox-provider` skill.

- **`SandboxProvider` / `Sandbox`** (`base.py`): the public ABCs a backend implements. `Sandbox`
  has two abstract methods, `execute_code` (`language="python"`) and `close`;
  `execute_command`/`upload_file`/`download_file`/`install_packages` are optional and raise
  `SandboxCapabilityError` unless the provider declares them. `SandboxProvider` implements
  `create`/`destroy` (and `attach` when `capabilities.attach` is declared) and declares a
  `capabilities` class attribute.
- **`SandboxCapabilities`** (`model.py`): the honest per-provider declaration (isolation tier,
  shell, languages, files, package_install, stateful, attach, principal_user, policy_*). The
  manager/worker consult it before routing; the worker enforces principal and policy **fail-closed**
  against it (unenforceable + `strict` → `SandboxPolicyError`).
- **`SandboxManager`** (`manager.py`): process-wide singleton (like `ConversationThreadManager`).
  Resolves the workload **profile** → provider, owns sandbox **sessions** (nv_cache registry,
  namespace-isolated per AK session; `per_call`/`per_session`/`per_runtime` scopes), and records
  promoted tasks. `SandboxManager.get()` returns `None` when disabled.
- **`SandboxProviderFactory` / `SandboxBrokerFactory`** (`factory.py`): the #541 house pattern —
  built-in short names are `if/elif` real-import branches listed in `_BUILTIN_PROVIDER_NAMES`; a
  dotted-path `type` resolves via `resolve_dotted` (bring-your-own). Providers: `local_subprocess`
  (no isolation), `docker` (container). Broker flavors: `thread` (default, dedicated loop thread),
  `embedded` (inline/synchronous); `BrokerWorkerCore` is the shared engine.
- **Agent surface**: `tools.py` provides eight system tools (attached via `SystemToolFactory` when
  enabled, optionally scoped to `sandbox.agents`); `hooks.py`'s `SandboxPreHook` ingests
  task-completion events (the third system pre-hook). `principal.py` maps session/agent to a
  `SandboxPrincipal` (`principal_resolver` config for user identity). `testing.py` ships
  `FakeSandboxProvider` and the reusable `SandboxProviderContract`.

## Shared Database Drivers (`ak-py/src/agentkernel/core/util/driver/`)

The Session, Multimodal attachment, Response Store, and Thread backends share one set of
connection drivers: `RedisDriver`, `ValkeyDriver` (both subclassing `_RedisLikeDriver`),
`DynamoDBDriver`, `CosmosDBDriver`, and `FirestoreDriver`. Three rules govern the package:

1. **Drivers never read `AKConfig`** — all connection parameters are explicit constructor
   arguments; config reading and validation stay in the stores and factories
2. **Drivers own the connection lifecycle** (lazy connect, 3-retry/2s back-off, Redis/Valkey
   ping health-check with reconnect, `socket_connect_timeout=5`, TTL plumbing) plus a generic
   command surface; key schemas, serialization, and data layouts stay in the store classes
3. **Drivers expose their native handle** (`client` / `table` / `table_client` / `collection`)
   for consumers whose data operations exceed the generic surface (e.g. the DynamoDB/Cosmos/
   Firestore thread stores)

`driver/__init__.py` has no eager imports — `redis`, `valkey`, `azure`, and `gcp` extras stay
optional; consumers import the concrete module (`from agentkernel.core.util.driver.redis import
RedisDriver`). Connect/reconnect is serialized by a per-instance `threading.Lock`, so drivers
are safe to share across threads (e.g. response stores under `ECSOutputConsumer`).

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
│   ├── chat_service.py      # ChatService, RequestBuilder, AgentHandler, ResponseBuilder
│   ├── logger.py            # Logging setup
│   ├── util/                # Shared utilities
│   │   ├── factory.py       # resolve_dotted/require_extra/AKConfigError for pluggable-backend factories
│   │   └── driver/          # Shared DB connection drivers (Redis, Valkey, DynamoDB, Cosmos DB, Firestore)
│   └── session/             # Session store implementations
│       ├── base.py           # SessionStore, SessionCache
│       ├── serde.py          # Session (de)serialization helpers
│       ├── in_memory.py
│       ├── redis.py
│       ├── valkey.py          # ValkeySessionStore (requires the `valkey` extra)
│       ├── dynamodb.py
│       ├── cosmosdb.py
│       └── firestore.py
├── framework/               # Framework adapters
│   ├── openai/              # OpenAI Agents SDK adapter
│   ├── crewai/              # CrewAI adapter
│   ├── langgraph/           # LangGraph adapter
│   ├── adk/                 # Google ADK adapter
│   ├── smolagents/          # Smolagents adapter
│   └── pydanticai/          # Pydantic AI adapter
├── api/                     # API layers
│   ├── handler.py           # REST API handler
│   ├── http.py              # RESTAPI class
│   ├── a2a/                 # Agent-to-Agent server
│   └── mcp/                 # MCP server
├── deployment/              # Cloud deployment adapters
│   ├── common/              # Shared across Lambda + ECS
│   │   ├── thread_runner.py     # ThreadRunner — run N callables as peer threads
│   │   ├── queue_consumer.py    # QueueConsumer — ABC shared by ECSSQSConsumer + LambdaSQSConsumer
│   │   ├── response_store.py    # ResponseStore
│   │   ├── rest_handler.py      # RestHandler — queue-aware AgentRESTRequestHandler subclass (enqueue_and_wait/poll_response), shared by ECS's ECSQueueRequestHandler
│   │   └── websocket_service.py # WebSocketConnectionStoreABC + WebSocketHandlerABC — shared WS connection-store contract and MessageType/broadcast lifecycle, used by both serverless and containerized AWS handlers
│   ├── aws/
│   │   ├── serverless/      # Lambda handlers: Lambda, ResponseHandler, ServerlessAgentRunner, etc.
│   │   │   └── core/router/ws_lambda.py  # LambdaWSHandler (renamed from BaseWSHandler) — subclasses AWSWebSocketHandler, adds Lambda-event parsing only
│   │   ├── containerized/   # ECS Fargate handlers
│   │   │   ├── core/
│   │   │   │   ├── sqs_consumer.py      # ECSSQSConsumer — extends QueueConsumer: SQS poll loop
│   │   │   │   └── api/
│   │   │   │       ├── rest_api.py      # ECSQueueRequestHandler (extends RestHandler), AWSRestAPI (extends RESTAPI)
│   │   │   │       └── websocket_api.py # ECSWebSocketHandlerBase, ECSWebSocketSystemRequestHandler, ECSWebSocketRequestHandler, AWSWebsocketAPI (extends RESTAPI)
│   │   │   ├── akagentrunner.py         # ECSAgentRunner — polls Input Queue, runs agent
│   │   │   ├── akoutputconsumer.py      # ECSOutputConsumer — polls Output Queue, writes to DB/WS
│   │   │   └── ecs_io_handler.py        # ECSIOHandler — entrypoint: wires both threads
│   │   └── core/            # Shared AWS-only: SQSHandler, ResponseStore, websocket_service.py (WebSocketConnectionStore — DynamoDB, AWSWebSocketHandler — API Gateway Management API push, extends WebSocketHandlerABC)
│   └── azure/               # Azure Functions handler
├── integration/             # Messaging integrations
│   ├── slack/
│   ├── whatsapp/
│   ├── messenger/
│   ├── instagram/
│   ├── telegram/
│   ├── teams/
│   └── gmail/
├── knowledgebase/           # Knowledge base backends
│   ├── base.py              # KnowledgeBase ABC
│   ├── knowledgebuilder.py  # KnowledgeBuilder (exposes KB tools to agents)
│   ├── chroma.py            # ChromaDB (vector)
│   ├── neo4j.py             # Neo4j (graph)
│   └── starburst.py         # Starburst/Trino (read-only SQL)
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
├── sandbox/                 # Sandbox capability (execute code/commands in an isolated env)
│   ├── base.py              # Sandbox, SandboxProvider ABCs
│   ├── model.py             # SandboxCapabilities, SandboxResult, SandboxSession, policy/principal
│   ├── errors.py            # SandboxError hierarchy
│   ├── manager.py           # SandboxManager (profile routing, sessions, fail-closed enforcement)
│   ├── factory.py           # SandboxProviderFactory + SandboxBrokerFactory
│   ├── principal.py         # PrincipalResolver, AgentPrincipalResolver
│   ├── tools.py             # The eight agent-facing system tools
│   ├── hooks.py             # SandboxPreHook (task-completion ingestion)
│   ├── testing.py           # FakeSandboxProvider + SandboxProviderContract (BYO test suite)
│   ├── providers/           # local_subprocess, docker (+ planned: e2b, daytona, kubernetes, ...)
│   └── broker/              # embedded, thread flavors + BrokerWorkerCore (+ planned: sqs)
├── cli/                     # CLI interface
│   └── cli.py               # Interactive CLI
├── auth/                    # Authentication
├── skills/                  # Bundled end-user skills (ak-init, ak-build, ak-test, ...)
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
| `QueueConsumer` | `deployment/common/queue_consumer.py` | Abstract base shared by `ECSSQSConsumer` and `LambdaSQSConsumer`: declares `poll`, `process_message`, `on_permanent_failure`, `delete_message` |
| `ECSSQSConsumer` | `containerized/core/sqs_consumer.py` | Extends `QueueConsumer`: SQS long-poll loop, retry/DLQ logic |
| `ThreadRunner` | `deployment/common/thread_runner.py` | Runs N callables as peer threads (one `threading.Thread` per `Task`, gated by a `Semaphore`) |
| `ECSOutputConsumer` | `containerized/akoutputconsumer.py` | Extends `ECSSQSConsumer` — polls Output Queue, writes to DynamoDB or broadcasts via WebSocket |
| `ECSAgentRunner` | `containerized/akagentrunner.py` | Extends `ECSSQSConsumer` — polls Input Queue, runs the agent, sends to Output Queue. The public name resolves to `ECSStreamAgentRunner` when `execution.mode == stream` (a mode-based export swap in `containerized/__init__.py`, mirroring the serverless `ServerlessAgentRunner`/`ServerlessStreamAgentRunner` swap in `serverless/__init__.py`) |
| `ECSStreamAgentRunner` | `containerized/akagentrunner.py` | Extends `ECSSQSConsumer` — STREAM-mode sibling of `ECSAgentRunner`: fans out each streamed chunk as its own Output Queue message instead of sending one full response |
| `ECSIOHandler` | `containerized/ecs_io_handler.py` | Entrypoint for the IO container: wires REST/WebSocket API + output consumer as peer threads |
| `RestHandler` | `deployment/common/rest_handler.py` | Queue-aware `AgentRESTRequestHandler` subclass shared by Lambda and ECS: `enqueue_and_wait` (`POST /api/v1/chat`, `REST_SYNC` waits on the response store / `REST_ASYNC` returns a `request_id`) and `poll_response` (`GET /api/v1/chat`, `request_id` in a JSON body via `BaseRequest` — not a query string — same model the serverless Lambda poll path parses; `request_id` alone is the lookup key) |
| `ECSQueueRequestHandler` | `containerized/core/api/rest_api.py` | Thin `RestHandler` subclass wiring SQS (`QueueHandler`) + `ResponseDBHandler`; routes inherited from `RestHandler.get_router()` |
| `AWSRestAPI` | `containerized/core/api/rest_api.py` | Extends `RESTAPI`; defaults to `ECSQueueRequestHandler` (eager `_default_handlers`, safe to construct without config) |
| `ECSWebSocketHandlerBase` | `containerized/core/api/websocket_api.py` | Abstract shared base for the two WS handlers: connection store, push-endpoint construction, response envelope, `x-ws-*` headers |
| `ECSWebSocketSystemRequestHandler` | `containerized/core/api/websocket_api.py` | Framework-managed protocol routes `$connect`/`$disconnect`/`$default`; owns the `AuthValidator` (only `$connect` authenticates). Not an extension point |
| `ECSWebSocketRequestHandler` | `containerized/core/api/websocket_api.py` | Application routes: built-in chat route + custom routes. Framework-managed (not a subclassing extension point) and **not publicly exported** — `AWSWebsocketAPI` constructs it; custom routes are added via `AWSWebsocketAPI.register(route)` and passed in as `custom_routes`. Needs **no** `AuthValidator` (user resolved from the connection store) |
| `AWSWebsocketAPI` | `containerized/core/api/websocket_api.py` | Extends `RESTAPI`; `run()` (no params) **always builds** exactly two handlers — the system handler (built lazily from the validator registered via `set_auth_handler`) plus one `ECSWebSocketRequestHandler` carrying every route registered via the `register(route)` decorator. Lazy build keeps importing the module safe when WebSocket mode isn't configured |

### Shared WebSocket Transport (Serverless + Containerized)

Containerized (ECS) and serverless (Lambda) WebSocket modes share the same AWS transport class,
not just a similar shape:

- `WebSocketHandlerABC` / `WebSocketConnectionStoreABC` (`deployment/common/websocket_service.py`)
  declare the cloud-agnostic contract: `MessageType` enum (`CHAT_RESPONSE`, `CHAT_QUEUED`,
  `SYSTEM_RESPONSE`, `STREAM_CHUNK`), `on_connect`/`on_disconnect`/`on_default`, `broadcast()`.
- `AWSWebSocketHandler` (`deployment/aws/core/websocket_service.py`, renamed from `WebSocketHandler`)
  implements the AWS-specific half: DynamoDB-backed `WebSocketConnectionStore`, a cached
  `apigatewaymanagementapi` client, `construct_endpoint_url`, and `send()`/`PostToConnection`
  (pruning stale connections on `GoneException`).
- **Containerized** `ECSWebSocketHandlerBase` and **serverless** `LambdaWSHandler`
  (`aws/serverless/core/router/ws_lambda.py`, renamed from `BaseWSHandler`) both build on
  `AWSWebSocketHandler` — the serverless side adds only Lambda-event parsing on top. This is a
  pure reuse refactor: serverless WebSocket runtime behavior is unchanged.

`api/handler.py`'s `AgentRESTRequestHandler` was refactored to expose path constants
(`AGENTS_PATH`, `CHAT_PATH`, `CHAT_MULTIPART_PATH`) and named methods (`list_agents`, `run`,
`run_multipart`) instead of inline route closures, and `RESTAPI.get_default_handlers()`
(`api/http.py`) is a new overridable classmethod `run()` calls when no handlers are passed —
this is what lets `RestHandler`/`AWSWebsocketAPI` reuse the base routes/paths instead of
redefining them.

### Two-Container Layout

```
Container 1 — ECSIOHandler
  Thread 1 (ThreadRunner):  AWSRestAPI.run(handlers=[ECSQueueRequestHandler()])
                            (or AWSWebsocketAPI.set_auth_handler(validator).run() in
                            ASYNC/STREAM mode — system + custom-route handlers built automatically)
                            — FastAPI/uvicorn, handles POST /chat and GET /chat?request_id=...
  Thread 2 (ThreadRunner):  ECSOutputConsumer.run()
                            — polls Output Queue, writes to DynamoDB / broadcasts via WebSocket

Container 2 — ECSAgentRunner
  N threads (ThreadRunner):  ECSSQSConsumer._consumer_loop, one per
                             execution.queues.input.no_of_consumers (default 5)
                             — each polls Input Queue, runs agent, sends result to Output Queue
```

### ECSSQSConsumer Contract

- **`get_queue_url(cls) → str`** *(abstract)*: return the SQS queue URL to poll.
- **`process_message(cls, record)`** *(abstract, from `QueueConsumer`)*: handle one message; called on every successful receive.
- **`on_permanent_failure(cls, record)`** *(abstract, from `QueueConsumer`)*: called when `ApproximateReceiveCount > max_receive_count`; **must catch its own exceptions** — if it raises, the message is not deleted and loops back.
- **`delete_message(cls, msg: dict)`** *(public)*: subclasses may call this directly when manual deletion is needed.
- **`run(cls)`**: blocking poll loop — the container entry-point.

### ThreadRunner Contract

`ThreadRunner.run(tasks: list[ThreadRunner.Task], max_workers=None) -> dict[Task, Any]` starts one
`threading.Thread` per `Task` (daemon, so a never-ending task can't block interpreter shutdown),
gated by a `Semaphore(max_workers or len(tasks))`, and drains completions off a shared queue until
every task in that call has reported in. It returns a dict keyed by the exact `Task` instance,
populated only for tasks that completed without raising.

Each `ThreadRunner.Task` has:
- `stop_task_on_failure` (default `True`) — log and ignore vs. log only, on that task's own exception.
- `stop_all_on_failure` (default `False`) — also bring down the whole `run()` call on that task's failure. Requires `stop_task_on_failure=True`.
- `graceful` (default `False`) — only meaningful with `stop_all_on_failure=True`. Requires it, or raises `ValueError`.
- `awaited_on_shutdown` (default `True`) — whether `run()`'s drain loop waits for this task to report a completion before proceeding. Set `False` for a task that can never observe `shutdown_event` and has no other way to be told to stop (e.g. a blocking call like `uvicorn.run()`) — otherwise a `graceful=True` failure elsewhere in the same `run()` call hangs forever waiting for it. Every thread's completion still lands on the shared queue regardless of this flag; `run()` just doesn't count that task toward "everyone's reported in."

On a task raising with `stop_all_on_failure=True`:
- `graceful=False` → logs the exception, `logging.shutdown()` + `os._exit(1)` **immediately**, without waiting on other tasks.
- `graceful=True` → logs the exception, sets a **class-level singleton** `ThreadRunner.shutdown_event` (a `threading.Event`), and keeps draining the *other tasks started by this same `run()` call*. Cooperating tasks (e.g. `ECSSQSConsumer._consumer_loop`) check `ThreadRunner.shutdown_event.is_set()` in their loop condition and return once set. Only after every task from this call has reported completion does it check `shutdown_event` and call `os._exit(1)` — so it never waits on tasks it didn't itself start (e.g. the IO container's `rest-api` thread, which doesn't check the event at all and is simply killed when `os._exit(1)` fires).

#### How to Use ThreadRunner

`ThreadRunner` is internal-only — not part of the public API, never imported by user application
code. Reach for it when adding a new internal component that needs several peer threads with
uniform failure handling (as opposed to a raw `threading.Thread`, which gives you none of the
crash/result/shutdown plumbing below for free).

```python
from agentkernel.deployment.common import ThreadRunner

def poll_forever():
    while not ThreadRunner.shutdown_event.is_set():
        ...  # do one unit of work per iteration, so the shutdown check is actually reached

def compute(item):
    return item * 2  # a task's return value shows up in the results dict, keyed by its Task

results = ThreadRunner.run(
    tasks=[
        ThreadRunner.Task(
            execution_function=poll_forever,
            thread_name="poller",
            stop_all_on_failure=True,
            graceful=True,  # opt in only if this task's execution_function actually checks
                             # shutdown_event in its loop — otherwise "graceful" drain never ends
        ),
        ThreadRunner.Task(execution_function=compute, thread_name="compute-1", item=5),
    ],
)
```

Guidance:
- A task with a `while` loop that should participate in a graceful shutdown **must** check
  `ThreadRunner.shutdown_event.is_set()` (or `.wait(timeout)` for a sleep/backoff) once per
  iteration before setting `graceful=True` on it — `graceful=True` on a task that never checks the
  event just makes that `run()` call hang forever waiting for it to return, *unless* that task is
  also marked `awaited_on_shutdown=False` (see below).
- `stop_all_on_failure=True` always requires `stop_task_on_failure=True` (the default), and
  `graceful=True` always requires `stop_all_on_failure=True` — both raise `ValueError` in
  `Task.__post_init__` if violated.
- Only set `graceful=True` on tasks in a `run()` call where every *other* task in that same call is
  either similarly cooperative, or marked `awaited_on_shutdown=False` — e.g. `ECSIOHandler`
  deliberately marks its `rest-api` task (`uvicorn.run()`, which never checks `shutdown_event` and
  can only be stopped by an OS signal) as `awaited_on_shutdown=False`, so the drain loop doesn't
  wait on it and it's simply cut off whenever `os._exit(1)` eventually fires.
- `ThreadRunner.shutdown_event` is a **process-wide singleton**, not scoped to one `run()` call —
  once any call sets it, every other `run()` call in the process sees it set too, and will
  `os._exit(1)` once its own tasks finish draining. This is deliberate (a fatal failure anywhere
  should bring the whole process down), but it also means **tests must reset it between cases**
  (`ThreadRunner.shutdown_event.clear()`), or a graceful-path test will leave every later test in
  the same run silently triggering a real `os._exit(1)`. See the `autouse` fixture in
  `ak-py/tests/test_thread_runner.py`.
- No hard timeout on graceful drain: if a task in the *same batch* as the failure is
  `awaited_on_shutdown=True` (the default) but never checks `shutdown_event` and never naturally
  returns, that `run()` call's drain loop — and therefore its `os._exit(1)` — never fires. Mark such
  a task `awaited_on_shutdown=False` to opt it out of the drain instead.

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
    ECSAgentRunner,           # Container 2 entry-point
    ECSIOHandler,             # Container 1 entry-point
    ECSOutputConsumer,        # Subclass ECSSQSConsumer for custom output processing
    AWSRestAPI,               # RESTAPI subclass defaulting to ECSQueueRequestHandler
    AWSWebsocketAPI,          # RESTAPI subclass; builds system + custom-route handlers; register(route) decorator
    ECSWebSocketSystemRequestHandler, # Framework $connect/$disconnect/$default handler (injected automatically)
)
from agentkernel.deployment.aws.containerized.core import ECSSQSConsumer
from agentkernel.deployment.common import ThreadRunner
```

## Execution Flow

```
User Input
    → AgentService.run(prompt)
        → AgentRequestText(prompt=prompt)
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

### Streaming Execution Flow

```
User Input
    → AgentService.stream_multi(requests)
        → Runtime.stream(agent, session, requests)
            → async with session:                    # acquire lock, set context
            → PreHooks (agent hooks, then system)    # halt → yield StreamChunk(error, done=True)
            → agent.runner.stream(agent, session, requests)  # async generator of token deltas
                → for each delta: PostHook.on_stream_chunk() # can drop or modify token
                → yield StreamChunk(delta=...)
            → session_store.store(session)           # persist state
            → yield StreamChunk(done=True, session_id=...)
            → clear volatile cache                   # cleanup
    → REST: SSE (`text/event-stream`) when execution.mode=stream
    → AWS Lambda serverless: each StreamChunk sent as a separate SQS/WebSocket `STREAM_CHUNK` message
    → AWS ECS containerized: queue mode — `ECSStreamAgentRunner` fans out one SQS output message per
      chunk, `ECSOutputConsumer` broadcasts each as `STREAM_CHUNK`; direct mode — `ECSWebSocketRequestHandler`
      broadcasts chunks inline via `ChatService.process_stream_chat_async`
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
