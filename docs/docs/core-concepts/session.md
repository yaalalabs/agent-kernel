---
sidebar_position: 4
---

# Session

The **Session** is the core component that manages conversation state across multiple agent interactions, providing memory and context persistence. Sessions enable multi-turn conversations by tracking history and maintaining state between agent invocations.

## Overview

```mermaid
graph TB
    subgraph "Application Layer"
        A[CLI/API/Lambda Requests]
    end
    
    subgraph "Session Manager"
        B[Session Cache<br/>LRU Cache]
        C[Session Factory]
    end
    
    subgraph "Storage Backends"
        D[In-Memory<br/>Development]
        E[Redis / Valkey<br/>All clouds]
        F[DynamoDB<br/>AWS]
        G[Cosmos DB<br/>Azure]
        H[Firestore<br/>GCP]
    end
    
    A --> B
    B --> C
    C --> D
    C --> E
    C --> F
    C --> G
    C --> H
    
    style B fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style C fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
```

## What is a Session?

A Session:
- **Tracks** conversation history across interactions
- **Persists** state between agent invocations
- **Manages** thread context for multi-turn conversations
- **Supports** multiple storage backends with **multi-cloud support**:
  - In-memory (development)
  - Redis (AWS, Azure & GCP production)
  - Valkey (AWS production; open-source Redis fork)
  - DynamoDB (AWS serverless)
  - Cosmos DB (Azure serverless)
  - Firestore (GCP)
- **Stores** framework-specific state separately per agent
- **Enables** session-scoped caching and memory management

## Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created: First Interaction
    Created --> Active: Subsequent Interactions
    Active --> Active: More Interactions
    Active --> Expired: TTL Timeout
    Active --> Closed: Explicit Clear
    Expired --> [*]
    Closed --> [*]
    
    note right of Active
        Session data persisted
        on each interaction
    end note
```

## Creating and Managing Sessions

### Automatic Session Management (CLI)

In CLI mode, sessions are automatically created and managed:

```python
from agentkernel.cli import CLI

# CLI automatically creates unique session per user
# Session ID is generated automatically
CLI.main()
```

The CLI creates a unique session ID for each interactive session, maintaining context throughout the conversation.

### API-Controlled Sessions

In API mode, you control session IDs to manage user conversations:

```bash
POST /api/v1/chat
{
  "agent": "assistant",
  "prompt": "Hello!",
  "session_id": "user-123-conversation-1"
}
```

**Best Practice**: Use descriptive session IDs that identify users and conversations:

```python
# Good - descriptive and unique
session_id = f"user-{user_id}-thread-{thread_id}"
session_id = f"{platform}-{user_id}-{timestamp}"

# Less useful - not descriptive
session_id = "session1"
```

### Programmatic Session Creation (Advanced)

For advanced use cases, create sessions programmatically:

```python
from agentkernel.core import Session

# Create a new session with custom ID
session = Session(id="custom-session-id")

# Use with runner
result = await runner.run(agent, session, prompt)
```

## Storage Backends

Agent Kernel supports multiple storage backends for session persistence, each optimized for different deployment scenarios.

### In-Memory Storage (Default)

Fast, ephemeral storage suitable for development and testing:

```bash
export AK_SESSION__TYPE=in_memory
```

**Characteristics:**
- ✅ Fastest performance (no I/O)
- ✅ No setup required
- ✅ Perfect for development and testing
- ❌ Sessions lost on restart
- ❌ Single-process only
- ❌ Not suitable for production

**Use When:**
- Local development
- Testing
- Non-critical data
- Single-instance deployments

### Redis Storage (AWS, Azure & GCP) {#redis-storage}

Persistent, high-performance storage for production deployments on AWS (ElastiCache), Azure (Azure Cache for Redis), and GCP (Memorystore):

```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
export AK_SESSION__REDIS__PASSWORD=your-password
export AK_SESSION__REDIS__TTL=604800  # 7 days in seconds
export AK_SESSION__REDIS__PREFIX=ak:sessions:
```

**Characteristics:**
- ✅ Persistent across restarts
- ✅ High performance (sub-millisecond latency)
- ✅ Supports distributed/multi-process deployments
- ✅ Configurable TTL for automatic cleanup
- ✅ Redis Cluster for high availability
- ✅ **Multi-cloud support**: AWS ElastiCache, Azure Cache for Redis & GCP Memorystore
- ✅ Ideal for containerized deployments (ECS/Fargate, Azure Container Apps)

**Use When:**
- Production containerized deployments (AWS, Azure, or GCP)
- Multi-instance applications
- High-throughput requirements
- Need for sub-millisecond session access

**High Availability Configuration:**
```bash
# Redis Cluster endpoint (AWS ElastiCache or Azure Cache for Redis)
export AK_SESSION__REDIS__URL=redis://cluster-endpoint:6379

# Enable SSL/TLS
export AK_SESSION__REDIS__URL=rediss://secure-endpoint:6380
```

### Valkey Storage (AWS) {#valkey-storage}

[Valkey](https://valkey.io/) is the open-source, Linux Foundation-governed fork of Redis. It is
wire-compatible with Redis and available on AWS ElastiCache as a native engine at a lower price
point than the Redis OSS engine. Agent Kernel treats it as a first-class backend with its own
client library (`valkey-py`) and configuration block:

```bash
export AK_SESSION__TYPE=valkey
export AK_SESSION__VALKEY__URL=valkey://localhost:6379
export AK_SESSION__VALKEY__TTL=604800  # 7 days in seconds
export AK_SESSION__VALKEY__PREFIX=ak:sessions:
```

Install the optional dependency with `agentkernel[valkey]`.

**Characteristics:**
- ✅ Persistent across restarts
- ✅ High performance (sub-millisecond latency)
- ✅ Supports distributed/multi-process deployments
- ✅ Configurable TTL for automatic cleanup
- ✅ Open-source license (avoids Redis licensing concerns)
- ✅ AWS ElastiCache for Valkey (lower cost than the Redis OSS engine)
- ✅ Ideal for containerized (ECS/Fargate) and serverless (Lambda) deployments

**Use When:**
- You are standardizing on Valkey rather than Redis
- Production AWS deployments (containerized or serverless)
- Multi-instance applications needing sub-millisecond session access

**High Availability / SSL Configuration:**
```bash
# ElastiCache for Valkey endpoint
export AK_SESSION__VALKEY__URL=valkey://cluster-endpoint:6379

# Enable SSL/TLS
export AK_SESSION__VALKEY__URL=valkeys://secure-endpoint:6380
```

`valkey-py` also accepts the `redis://` / `rediss://` URL schemes, so an ElastiCache endpoint
works with either form; Agent Kernel standardizes on `valkey://` / `valkeys://`.

### DynamoDB Storage

Serverless, fully-managed storage for AWS deployments:

```bash
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
export AK_SESSION__DYNAMODB__TTL=604800  # 7 days (0 to disable)
```

**Characteristics:**
- ✅ Serverless, fully managed by AWS
- ✅ Auto-scaling capacity
- ✅ Multi-AZ replication by default
- ✅ 99.999% availability SLA
- ✅ No infrastructure management
- ✅ Pay-per-use pricing
- ✅ Ideal for Lambda deployments
- ⚠️ Higher latency than Redis (~10-20ms)

**Use When:**
- AWS serverless deployments (Lambda)
- Auto-scaling requirements
- AWS-native infrastructure
- Minimal operational overhead preferred

**Requirements:**
- DynamoDB table with partition key `session_id` (String)
- DynamoDB table with sort key `key` (String)
- Optional: TTL attribute `expiry_time` enabled
- Appropriate IAM permissions

**Note**: Agent Kernel's Terraform modules automatically create the required DynamoDB table with proper configuration.

### Cosmos DB Storage {#cosmosdb-storage}

Serverless, fully-managed storage for Azure deployments:

```bash
export AK_SESSION__TYPE=cosmosdb
export AK_SESSION__COSMOSDB__TABLE_NAME=sessions
export AK_SESSION__COSMOSDB__TABLE_ENDPOINT=https://your-account.documents.azure.com:443/
export AK_SESSION__COSMOSDB__CONNECTION_STRING=AccountEndpoint=https://...;AccountKey=...
export AK_SESSION__COSMOSDB__TTL=604800  # 7 days (0 to disable)
```

**Characteristics:**
- ✅ Serverless, fully managed by Azure
- ✅ Auto-scaling capacity
- ✅ Multi-region replication support
- ✅ 99.999% availability SLA
- ✅ No infrastructure management
- ✅ Pay-per-use pricing
- ✅ Ideal for Azure Functions deployments
- ⚠️ Higher latency than Redis (~10-20ms)

**Use When:**
- Azure serverless deployments (Azure Functions)
- Auto-scaling requirements
- Azure-native infrastructure
- Minimal operational overhead preferred

**Requirements:**
- Cosmos DB table with partition key `/session_id`
- Optional: TTL configured on the table
- Appropriate Azure permissions (connection string or managed identity)

**Note**: Agent Kernel's Terraform modules automatically create the required Cosmos DB resources with proper configuration.

### Firestore Storage (GCP) {#firestore-storage}

Serverless, fully-managed storage for GCP deployments:

```bash
export AK_SESSION__TYPE=firestore
export AK_SESSION__FIRESTORE__COLLECTION_NAME=ak_sessions  # default: ak_sessions
export AK_SESSION__FIRESTORE__PROJECT_ID=my-project        # optional, inferred from ADC if omitted
export AK_SESSION__FIRESTORE__DATABASE_ID="(default)"      # optional
export AK_SESSION__FIRESTORE__TTL=604800                   # 7 days (0 to disable)
```

**Characteristics:**
- ✅ Serverless, fully managed by Google Cloud
- ✅ Auto-scaling capacity, multi-region replication
- ✅ No infrastructure management, pay-per-use pricing
- ✅ Ideal for Cloud Run deployments
- ⚠️ Higher latency than Redis/Memorystore

**How it works:** one Firestore document per `session_id`, with one field per session key. The store writes an `expiry_time` timestamp field on each document; enable a **Firestore TTL policy** on the collection pointing at `expiry_time` for automatic document expiry.

**Use When:**
- GCP Cloud Run deployments (serverless or always-on)
- GCP-native infrastructure with minimal operational overhead

**Note**: The GCP Terraform modules create the Firestore database and inject the `AK_SESSION__*` environment variables automatically when `create_firestore_db = true`. Requires the `agentkernel[gcp]` extra.

### Session Caching (Redis, Valkey, DynamoDB & Cosmos DB)

Redis, Valkey, DynamoDB, and Cosmos DB backends all support optional in-memory session caching for improved performance:

```bash
# Enable in-memory session caching with LRU eviction
export AK_SESSION__CACHE__SIZE=256
```

**How It Works:**
- Sessions are cached in memory using LRU (Least Recently Used) eviction
- Subsequent accesses to cached sessions avoid backend I/O
- Session data is still persisted to backend after each interaction
- Cache is process-local (not shared across instances)

**Performance Benefits:**
- Eliminates backend round-trips for cached sessions
- Reduces latency for frequent session access
- Lowers backend costs (DynamoDB RCU/WCU)

**Important Limitation:**
When session caching is enabled, session data is **not reloaded from storage** while in cache. This means:
- ⚠️ All requests for the same session should route to the same runtime instance
- ⚠️ Not suitable for round-robin load balancing without sticky sessions
- ✅ Works well with consistent hashing or session-affinity load balancing

**Recommendation**: Enable session caching when using sticky sessions or single-instance deployments. Disable for true stateless, multi-instance deployments.

## How Sessions Work

### Session Data Storage

Sessions store framework-specific conversation state separately for each agent:

```python
# Framework adapters automatically manage session data
# You don't need to manually set these - shown for illustration

# OpenAI Swarm stores thread information
session.set("openai_assistant_session", openai_thread_obj)

# LangGraph stores graph state
session.set("langgraph_state", graph_checkpoint)

# CrewAI stores crew context
session.set("crewai_context", crew_state)

# Access session data (advanced usage)
openai_session = session.get("openai_assistant_session")
```

**Key Points:**
- Each framework adapter manages its own session data
- Session keys are framework-specific
- Multiple agents can share the same session
- Session data is automatically persisted to the configured backend

### Accessing the current framework session {#framework-session-access}

`get_framework_session()` is a convenience accessor for the pattern above — it resolves the
framework-specific key for you, using [`Agent.current()`](./agent.md#currently-executing-agent) to
find out which agent (and therefore which framework) is running:

```python
# Equivalent to session.get(agent.runner.name) for whichever agent is currently executing
openai_session = session.get_framework_session()
```

- Returns the **same live object** the framework adapter stores its native session state under —
  `Session.get()`/`set()` just read and write a plain `dict` of object references, so mutating the
  returned object through its own methods updates what's stored immediately; no `session.set(...)`
  call is needed afterward.
- Returns `None` if nothing has been stored yet for the current agent's framework.
- Can only be called while an agent is executing (from inside a hook or a tool) — calling it with
  no agent running (`Agent.current()` is `None`) raises `RuntimeError`, since there'd be no
  framework key to resolve.

See [`examples/api/hooks`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/hooks)
for a complete example (`HistoryTrimHook`) that uses it from a post-hook to cap the OpenAI Agents
SDK's native conversation history as a session grows.

### Framework context / per-run state

Beyond the framework-internal keys above, the session exposes **one reserved key** that lets your
application carry a **framework-agnostic context/state object** across turns of a conversation:
`framework_context`. When set, the active framework's runner injects this object into the underlying
framework call, and writes the (possibly mutated) object back after a **successful** run — so tools can
read and update shared state that survives to the next turn.

Reach it through three dedicated `Session` methods — you never need to name the reserved key, the same
way `get_volatile_cache()` fronts its own key:

```python
# Read the stored context (the live dict), or None when none is set. Never creates the key.
ctx = session.get_framework_context()

# Seed or replace it (any picklable dict). Raises TypeError if the value is not a dict.
if ctx is None:
    ctx = session.set_framework_context({"user_id": "42", "cart": []})

# Remove it, so nothing is injected on the next turn.
session.clear_framework_context()
```

These accessors are for **pre-hooks and post-hooks** — the two places Agent Kernel hands your code the
session around a run (see
[Hooks → Per-run framework context](../integrations/hooks.md#per-run-framework-context)). A pre-hook
seeds or edits the context *before* the runner loads it, so the edit is part of what gets injected this
turn; a post-hook reads it *after* write-back, so it sees the completed run's mutations, and its own
edits are still persisted (post-hooks run before the session is stored).

```python
class SeedContext(PreHook):
    async def on_run(self, session, agent, requests):
        if session.get_framework_context() is None:
            session.set_framework_context({"cart": []})
        return requests
```

Inside a tool, read and write the context through the **framework's native handle** instead — that is
what the runner injected it into:

```python
from agents import RunContextWrapper   # OpenAI Agents SDK

def add_to_cart(wrapper: RunContextWrapper[dict], item: str) -> str:
    """Read and mutate the per-run context through the framework's own handle."""
    wrapper.context.setdefault("cart", []).append(item)
    return f"Added {item}"
```

:::warning Tools use the native handle, not the session accessors
The runner injects a **deep copy** of the stored dict into the framework and, on a successful run,
replaces the stored context wholesale with what the framework produced. A tool that reaches back through
`ToolContext.get().session` is therefore reading and writing a *different* object than the run is
carrying: its write is silently discarded on OpenAI, Pydantic AI, Google ADK, LangGraph and smolagents
(it survives only on CrewAI, which never writes back), and it would break the atomic-per-turn guarantee,
since the write would persist even when the run fails.

Each framework's native handle:

- **OpenAI** — mutate `wrapper.context` from a tool taking `RunContextWrapper`
  ([example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_context))
- **Pydantic AI** — mutate `ctx.deps` from a native tool taking `RunContext`
  ([example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/pydanticai_context))
- **LangGraph** — return an update for a declared state channel
  ([example](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/langgraph_context))
- **Google ADK** — write to `tool_context.state`
- **Smolagents** — write to a **pre-seeded** key in `agent.state`
- **CrewAI** — no injection and so no native handle; use
  [`get_non_volatile_cache()`](#session-data-storage) for tool-visible per-run state instead (see
  [CrewAI](../frameworks/crewai.md))
:::

**Rules and constraints:**
- **Optional and non-breaking.** If no context is set (`get_framework_context()` returns `None`),
  nothing is injected and behaviour is unchanged. A caller-set empty dict `{}` is treated as "present
  but empty" — it is injected and round-tripped, so tools can populate it. This is why
  `get_framework_context()` never auto-creates the context.
- **Must be a picklable `dict`.** `set_framework_context()` rejects a non-`dict` with a `TypeError` at
  your call site. Sessions are persisted with `pickle`, so a non-picklable value likewise raises a
  `TypeError` naming the offending key/type rather than an opaque store-level failure. In a
  non-streamed run these surface as an error reply; at the end of a **streamed** run — where the
  response has already reached the client — a write-back failure is logged and skipped instead, so
  the stored context stays intact and the rest of the session is still persisted.
- **Write-back is atomic per turn.** The updated context is stored only after the run completes
  successfully. On a framework error — or a client disconnect mid-stream — the previously stored
  context is left intact (partial state is discarded, not saved).
- **Round-trip fidelity differs per framework.** See the fidelity table in the
  [Runner](./runner.md#per-run-framework-context) documentation — notably, CrewAI does not support it
  (it warns and ignores a set context), and smolagents / prebuilt LangGraph agents round-trip only
  a subset of keys.

### Multi-Agent Sessions

Sessions can track multiple agents within the same conversation:

```python
# Same session, different agents
session = Session(id="user-123")

# Agent 1 execution
result1 = await agent1.runner.run(agent1, session, "First question")
# Stores: session.set("agent1_framework_session", ...)

# Agent 2 execution (same session)
result2 = await agent2.runner.run(agent2, session, "Second question")
# Stores: session.set("agent2_framework_session", ...)

# Both agents share the same session container
# But maintain separate framework-specific state
```

This enables complex multi-agent workflows where different agents can collaborate within a single user conversation.

### Thread Management

Sessions support multi-threaded conversations per user:

```python
# Each conversation thread gets a unique session
user_id = "user-123"
thread_id = "thread-456"
session_id = f"{user_id}-{thread_id}"

session = Session(id=session_id)

# Conversation history maintained per thread
# Different threads remain isolated
```

**Use Cases:**
- Multiple simultaneous conversations per user
- Topic-based conversation organization
- Isolated testing environments

### Execution Hooks and Sessions

[Execution hooks](/docs/integrations/hooks) have full access to session state:

```python
from agentkernel import PreHook

class RAGHook(PreHook):
    async def on_run(self, session, agent, requests):
        # Access session data
        user_prefs = session.get("user_preferences")
        
        # Use volatile cache for temporary data
        v_cache = session.get_volatile_cache()
        rag_context = v_cache.get("rag_context")
        
        # Modify requests based on session state
        return modified_requests
    
    def name(self):
        return "RAGHook"
```

Hooks can:
- Read and modify session state
- Access both volatile and non-volatile caches
- Store intermediate data for the request lifecycle

[Learn more about execution hooks →](/docs/integrations/hooks)

## Configuration Reference

Configure session behavior via environment variables or configuration files.

### Environment Variables

```bash
# ============================================
# Storage Type Selection (Multi-Cloud)
# ============================================
export AK_SESSION__TYPE=redis  # Options: 'in_memory', 'redis', 'dynamodb' (AWS), 'cosmosdb' (Azure)

# ============================================
# Redis Configuration (AWS, Azure & GCP)
# ============================================
export AK_SESSION__REDIS__URL=redis://localhost:6379
export AK_SESSION__REDIS__PASSWORD=your-password
export AK_SESSION__REDIS__TTL=604800  # 7 days in seconds
export AK_SESSION__REDIS__PREFIX=ak:sessions:

# ============================================
# DynamoDB Configuration (AWS)
# ============================================
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
export AK_SESSION__DYNAMODB__TTL=604800  # 7 days (0 to disable)

# ============================================
# Cosmos DB Configuration (Azure)
# ============================================
export AK_SESSION__COSMOSDB__TABLE_NAME=sessions
export AK_SESSION__COSMOSDB__TABLE_ENDPOINT=https://your-account.documents.azure.com:443/
export AK_SESSION__COSMOSDB__CONNECTION_STRING=AccountEndpoint=https://...;AccountKey=...
export AK_SESSION__COSMOSDB__TTL=604800  # 7 days (0 to disable)

# ============================================
# Session Caching (Redis, DynamoDB & Cosmos DB)
# ============================================
export AK_SESSION__CACHE__SIZE=256  # Number of sessions to cache (0 to disable)
```

### Configuration File (config.yaml)

```yaml
session:
  type: redis  # or 'in_memory' or 'dynamodb'
  
  redis:
    url: redis://localhost:6379
    password: your-password
    ttl: 604800  # 7 days in seconds
    prefix: "ak:sessions:"
  
  dynamodb:
    table_name: agent-kernel-sessions
    ttl: 604800  # 7 days in seconds (0 to disable)
  
  cosmosdb:
    table_name: sessions
    table_endpoint: https://your-account.documents.azure.com:443/
    connection_string: AccountEndpoint=https://...;AccountKey=...
    ttl: 604800  # 7 days in seconds (0 to disable)
  
  cache:
    size: 256  # Enable caching (0 to disable)
```

### Deployment-Specific Recommendations (Multi-Cloud)

**Local Development:**
```bash
export AK_SESSION__TYPE=in_memory
```

**Containerized Production:**

*AWS (ECS/Fargate):*
```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://elasticache-endpoint:6379
export AK_SESSION__CACHE__SIZE=256  # Enable with sticky sessions
```

*Azure (Container Apps):*
```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://azure-redis-endpoint:6379
export AK_SESSION__CACHE__SIZE=256  # Enable with sticky sessions
```

*GCP (Cloud Run always-on):*
```bash
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://memorystore-endpoint:6379
export AK_SESSION__CACHE__SIZE=256  # Enable with sticky sessions
```

**Serverless Deployments:**

*AWS Lambda:*
```bash
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
export AK_SESSION__DYNAMODB__TTL=604800
# Caching not recommended for Lambda (stateless invocations)
```

*Azure Functions:*
```bash
export AK_SESSION__TYPE=cosmosdb
export AK_SESSION__COSMOSDB__TABLE_NAME=sessions
export AK_SESSION__COSMOSDB__TABLE_ENDPOINT=https://your-account.documents.azure.com:443/
export AK_SESSION__COSMOSDB__CONNECTION_STRING=AccountEndpoint=https://...;AccountKey=...
export AK_SESSION__COSMOSDB__TTL=604800
# Caching not recommended for Azure Functions (stateless invocations)
```

*GCP Cloud Run (scale-to-zero):*
```bash
export AK_SESSION__TYPE=firestore
export AK_SESSION__FIRESTORE__COLLECTION_NAME=ak_sessions
export AK_SESSION__FIRESTORE__TTL=604800
# Caching not recommended for scale-to-zero deployments
```

[See deployment guides for detailed configuration →](/docs/deployment/overview)

## Best Practices

### Use Descriptive Session IDs

Create meaningful, unique session identifiers:

```python
# ✅ Good - descriptive and unique
session_id = f"user-{user_id}-conversation-{conv_id}"
session_id = f"{platform}-{user_id}-{timestamp}"
session_id = f"test-{test_name}-{run_id}"

# ❌ Less useful - not descriptive
session_id = "session1"
session_id = "abc123"
```

### Configure Appropriate TTL

Set Time-To-Live based on your use case:

```python
# Short-lived sessions (interactive chat)
export AK_SESSION__REDIS__TTL=3600  # 1 hour

# Medium-lived sessions (customer support)
export AK_SESSION__REDIS__TTL=86400  # 24 hours

# Long-lived sessions (ongoing projects)
export AK_SESSION__REDIS__TTL=604800  # 7 days
```

**Note**: TTL is automatically refreshed on each interaction.

### Let Framework Adapters Handle Context

Don't manually manage conversation history - framework adapters handle this automatically:

```python
# ✅ Correct - let the runner handle context
result = await runner.run(agent, session, new_prompt)
# Runner automatically includes previous context from session

# ❌ Don't do this - manual context management
history = session.get("manual_history") or []
history.append(new_prompt)
session.set("manual_history", history)
```

### Session Cleanup

Sessions automatically expire based on TTL configuration. For manual cleanup:

```python
# Clear session data while preserving session ID
session.clear()

# For complete removal (advanced usage)
from agentkernel.core import Runtime
runtime = Runtime.current()
runtime.session_manager.delete_session(session_id)
```

### Production Recommendations

**For High Availability:**
- Use Redis Cluster or DynamoDB
- Enable multi-AZ deployment
- Configure appropriate TTL for automatic cleanup
- Monitor session storage size

**For Performance:**
- Enable session caching with sticky sessions
- Use Redis for low-latency requirements
- Use DynamoDB for serverless simplicity

**For Cost Optimization:**
- Set appropriate TTL to avoid stale session accumulation
- Use DynamoDB on-demand pricing for variable workloads
- Monitor and adjust cache size based on actual usage

## Advanced Usage

### Custom Session Data

Store application-specific metadata alongside framework state:

```python
# Store custom data
session.set("user_preferences", {"language": "en", "theme": "dark"})
session.set("conversation_topic", "mathematics")
session.set("user_context", {"role": "student", "level": "advanced"})

# Retrieve later
prefs = session.get("user_preferences")
topic = session.get("conversation_topic")
```

**Use Cases:**
- User preferences and settings
- Conversation metadata
- Application-specific state
- Custom analytics data

### Session Inspection and Debugging

Debug session contents during development:

```python
# Iterate all session data
for key, value in session.get_all():
    print(f"{key}: {value}")

# Check if key exists
prefs = session.get("user_preferences")
if prefs is not None:
    ...
```

### Session Clearing

Remove all session data while preserving the session ID:

```python
# Clear all data from session
session.clear()

# Session ID remains the same
# Next interaction starts fresh context
```

**When to Use:**
- User requests to start over
- Switching conversation topics
- Resetting agent state
- Testing and development

### Direct Session Manager Access (Advanced)

For advanced scenarios, access the session manager directly:

```python
from agentkernel.core import Runtime

runtime = Runtime.current()
session_manager = runtime.session_manager

# Get or create session
session = session_manager.get_or_create_session("custom-id")

# Delete session completely
session_manager.delete_session("custom-id")

# Check session existence
exists = session_manager.has_session("custom-id")
```

**Caution**: Direct session manager manipulation bypasses normal session lifecycle. Use only when necessary.

## Summary

Sessions are the foundation of conversational AI in Agent Kernel:

- **Automatic Management**: Sessions are created and managed automatically in CLI and API modes
- **Multi-Backend Support**: Choose between in-memory (dev), Redis (production), or DynamoDB (serverless)
- **Framework Agnostic**: Works seamlessly with OpenAI, CrewAI, LangGraph, ADK
- **State Persistence**: Conversation history and context maintained across interactions
- **Flexible Storage**: TTL-based expiration, caching, and high-availability options
- **Production Ready**: Designed for distributed, fault-tolerant deployments

**Quick Reference:**

| Feature | In-Memory | Redis | DynamoDB |
|---------|-----------|-------|----------|
| **Persistence** | ❌ Lost on restart | ✅ Persistent | ✅ Persistent |
| **Multi-Process** | ❌ Single process | ✅ Distributed | ✅ Distributed |
| **Performance** | ⚡ Fastest | ⚡ Sub-millisecond | 🔄 ~10-20ms |
| **Setup** | ✅ None required | 🔧 Redis server | 🔧 AWS account |
| **Best For** | Development | Containerized prod | Serverless |
| **Caching** | N/A | ✅ Optional | ✅ Optional |

## Related Documentation

- **[Memory Management](/docs/architecture/memory-management)** - Advanced caching and auxiliary memory features
- **[Execution Hooks](/docs/integrations/hooks)** - Access and modify session state in hooks
- **[Configuration](/docs/core-concepts/configuration)** - Complete configuration reference
- **[Fault Tolerance](/docs/core-concepts/fault-tolerance)** - Session resilience and recovery
- **[AWS Serverless Deployment](/docs/deployment/aws-serverless)** - DynamoDB session configuration
- **[AWS Containerized Deployment](/docs/deployment/aws-containerized)** - Redis session configuration

## Next Steps

- [Module Organization](./module)
- [Runtime Orchestration](./runtime)
- [Memory Management](../architecture/memory-management)
- [Deployment Configuration](./configuration)
