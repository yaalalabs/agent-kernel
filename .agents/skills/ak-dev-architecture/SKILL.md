---
name: ak-dev-architecture
description: >
  Agent Kernel architectural principles, core abstractions, and design patterns.
  Use this skill when you need to understand the codebase structure, how components
  interact, or before making changes to core functionality. Covers Session, Agent,
  Runner, Module, Runtime, AgentService, AKConfig, tools, hooks, and the adapter pattern.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Agent Kernel Architecture

## Design Principles

1. **Framework-agnostic core**: All core abstractions (`Session`, `Agent`, `Tool`, `Runner`, `Module`, `Runtime`) are framework-independent. Framework-specific logic lives exclusively in adapter modules under `ak-py/src/agentkernel/framework/`.
2. **Adapter pattern**: Each supported agent framework (OpenAI Agents SDK, CrewAI, LangGraph, Google ADK) implements `Agent`, `Tool`, `Runner`, and `Module` subclasses that wrap native framework objects.
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
- Use cases: RAG injection, input/output guardrails, logging, disclaimers, prompt modification

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
│   ├── aws/                 # Lambda handler
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
```

## Execution Flow

```
User Input
    → AgentService.run(prompt)
        → AgentRequestText(text=prompt)
        → Runtime.run(agent, session, requests)
            → async with session:                    # acquire lock, set context
            → PreHooks (agent hooks, then system)    # guardrails, RAG, etc.
            → agent.runner.run(agent, session, requests)  # framework execution
            → PostHooks (system, then agent hooks)   # output guardrails
            → session_store.store(session)           # persist state
            → clear volatile cache                   # cleanup
        → AgentReply
    → response text
```
