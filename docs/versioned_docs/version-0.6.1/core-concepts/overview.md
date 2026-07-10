---
sidebar_position: 1
---

# Overview

Agent Kernel is built around six core abstractions that work together to provide a unified interface for AI agent development and execution.

## Architecture Overview

```mermaid
graph TB
    subgraph "Your Application"
        A[Agent Definition<br/>OpenAI/CrewAI/LangGraph/ADK]
    end
    
    subgraph "Agent Kernel Core"
        B[Agent<br/>Framework Wrapper]
        T[Tools<br/>Framework-Agnostic]
        C[Runner<br/>Execution Strategy]
        D[Session<br/>Conversation State]
        E[Module<br/>Agent Registry]
        F[Runtime<br/>Global Orchestrator]
    end
    
    subgraph "Execution Modes"
        G[CLI]
        H[REST API]
        I[AWS Lambda / Azure Functions]
        J[AWS ECS / Azure Container Apps]
        K[MCP Server]
        L[A2A Server]
    end
    
    A --> B
    T --> B
    B --> C
    C --> D
    E --> F
    B --> E
    F --> G
    F --> H
    F --> I
    F --> J
    F --> K
    F --> L
    
    style A fill:#4e85c5,stroke:#fff,stroke-width:2px,color:#fff
    style F fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style E fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
```

## The Six Core Abstractions

### 1. **Agent**

A wrapper around framework-specific agent implementations that provides a unified interface.

```python
from agentkernel.core import Agent

# Agent wraps your framework-specific agent
# Provides consistent interface across frameworks
```

**Key Features:**
- Framework-agnostic interface
- Consistent naming and identification
- Unified execution model

[Learn more about Agents →](./agent)

### 2. **Tools**

Bind plain Python functions as tools to any supported agent framework.

```python
from agentkernel.core import ToolContext

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    session = ToolContext.get().session
    return f"Weather in {city}: sunny"
```

**Key Features:**
- Write tools once, use with any framework
- Sync and async function support
- Access execution context via `ToolContext.get()`
- Framework-specific binding via `ToolBuilder.bind()`

[Learn more about Tools →](./tools)

### 3. **Runner**

Executes agent logic using framework-specific execution strategies.

```python
from agentkernel.core import Runner

# Runner encapsulates how agents are executed
# Each framework has its own Runner implementation
```

**Key Features:**
- Framework-specific execution
- Async/await support
- Error handling and retry logic
- Fault-tolerant execution patterns

[Learn more about Runners →](./runner)

### 4. **Session**

Manages conversation state across multiple agent interactions.

```python
from agentkernel.core import Session

# Session tracks conversation history
# Persists state between interactions
session = Session(id="user-123")
```

**Key Features:**
- Conversation history tracking
- State persistence (in-memory, Redis, or DynamoDB)
- Thread management
- Context preservation

[Learn more about Sessions →](./session)

### 5. **Module**

A container that registers agents with the Runtime.

```python
from agentkernel.crewai import CrewAIModule

# Module groups related agents together
CrewAIModule([agent1, agent2, agent3])
```

**Key Features:**
- Agent grouping and organization
- Automatic registration with Runtime
- Framework-specific initialization
- Lifecycle management

[Learn more about Modules →](./module)

### 6. **Runtime**

The global orchestrator that manages all agents and execution.

```python
from agentkernel.core import Runtime

# Runtime is the central registry
runtime = Runtime.get()
agent = runtime.get_agent("my-agent")
```

**Key Features:**
- Global agent registry
- Centralized configuration
- Execution coordination
- Service integration (API, MCP, A2A)
- Fault tolerance and health monitoring

[Learn more about Runtime →](./runtime)

## How They Work Together

### Basic Flow

```mermaid
sequenceDiagram
    participant U as User
    participant R as Runtime
    participant A as Agent
    participant Run as Runner
    participant S as Session
    participant F as Framework
    
    U->>R: Get agent "general"
    R->>A: Return Agent instance
    U->>Run: Execute with prompt
    Run->>S: Load session state
    S-->>Run: Current state
    Run->>F: Execute framework logic
    F-->>Run: Result
    Run->>S: Update session state
    Run-->>U: Return result
```

### Initialization Flow

```mermaid
graph LR
    A[Define Framework Agents] --> B[Create Module]
    B --> C[Module.__init__]
    C --> D[Create AK Agents]
    D --> E[Create Runners]
    E --> F[Register with Runtime]
    F --> G[Ready for Execution]
    
    style F fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

### Execution Flow

```mermaid
graph TD
    A[Request arrives] --> B{Runtime}
    B --> C[Lookup Agent]
    C --> D[Get/Create Session]
    D --> E{Runner}
    E --> F[Execute Framework Logic]
    F --> G[Update Session]
    G --> H[Return Result]
    
    style B fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style E fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
```

## Design Principles

### Framework Agnostic

Agent Kernel provides a consistent API regardless of the Agent framework you use. In fact you can have mix frameworks for different Agents and all can run together in the same deployment. If you decide to switch the Agent framework, the kernel provides a similar interface and hence the porting can be really quick.

### Minimal Overhead

Agent Kernel adds minimal overhead to framework execution. It's a thin adapter layer, not a heavy abstraction.

### Pluggable Architecture

All components are designed to be extended or replaced:
- Custom Runners for new frameworks
- Pluggable Session storage backends
- Custom execution modes

### Production Ready

Built-in features for production deployment:
- Session persistence
- Error handling
- Logging and traceability
- Multiple deployment modes
- Fault tolerance and high availability

[Learn more about Fault Tolerance →](./fault-tolerance)

## Configuration

Agent Kernel can be configured via environment variables or a configuration object:

```python
from agentkernel.core import AKConfig

# Access configuration
config = AKConfig.get()

# Configuration is loaded from environment variables
# or defaults to sensible values
```

Common configuration options:

| Variable | Description | Default |
|----------|-------------|---------|
| `AK_LOG_LEVEL` | Logging level | `INFO` |
| `AK_SESSION__TYPE` | Session storage backend | `in_memory` |
| `AK_SESSION__REDIS__URL` | Redis connection URL | `redis://localhost:6379` |
| `AK_SESSION__DYNAMODB__TABLE_NAME` | DynamoDB table name | - |

[Learn more about Configuration →](./configuration)

## Example: Putting It All Together

Here's a complete example showing how all components work together:

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

# 1. Define framework-specific agents
general_agent = CrewAgent(
    role="general",
    goal="Answer general questions",
    backstory="You are a helpful assistant",
    verbose=False,
)

math_agent = CrewAgent(
    role="math",
    goal="Solve math problems",
    backstory="You are a math expert",
    verbose=False,
)

# 2. Create a Module to wrap them
CrewAIModule([general_agent, math_agent])

# 3. Module automatically registers agents with Runtime
# Behind the scenes:
# - CrewAIModule creates Agent instances
# - Each Agent gets a Runner
# - All agents registered with Runtime.get()

# 4. Execute using CLI (or API, Lambda, etc.)
if __name__ == "__main__":
    CLI.main()
    
# The CLI uses Runtime to:
# - Discover available agents
# - Create/retrieve sessions
# - Execute agent logic via Runners
```

## Knowledge Bases

Sessions and caches help with short- to medium-term conversational context, but many applications also need durable, cross-session knowledge that persists across conversations and agents. Examples include product manuals, user or customer profiles, organizational policies, or domain knowledge graphs.

Agent Kernel's **Knowledge Base** support provides a unified way to connect multiple storage backends (vector stores and graph databases) and expose them to agents as callable tools. This lets agents query and update knowledge with the same interface, regardless of which backend system stores the data.

### Core Components

**`KnowledgeBase` Interface**

A backend-agnostic interface that every knowledge backend must implement (ChromaDB, Neo4j, Starburst/Trino, etc.). This ensures agents can read and write across different storage systems using the same API.

```python
from agentkernel.knowledgebase import KnowledgeBase

# Every backend implements:
# - schema(): metadata about what the backend contains
# - read(query, limit): retrieve data
# - write(records, **kwargs): persist data
# - format_results(): present results to agents
```

**`KnowledgeBuilder`**

Composes multiple backends and generates callable tools that agents can use. It creates three main functions:
- `get_schemas()`: returns metadata for all connected backends (agent uses this to decide which backend to query)
- `read_kb(backend, query)`: retrieve information from a specific backend
- `write_kb(backend, text, query)`: persist information to a specific backend

Critically, `KnowledgeBuilder` also handles **semantic placeholders** via `semantic_map`. This reduces agent hallucinations and errors by letting agents use stable logical names instead of remembering exact catalog/schema/table names or long physical identifiers:

```python
knowledgeBuilder = KnowledgeBuilder(
    [mongo_backend, sheets_backend],
    semantic_map={
        "<MONGO_SOURCE>": "mongodb.prod.customers",  # Agent uses <MONGO_SOURCE>
        "<SHEETS_SOURCE>": "sheets.prod.policies",   # Agent uses <SHEETS_SOURCE>
    },
)
```

The agent generates queries like `SELECT * FROM <MONGO_SOURCE> WHERE status = 'active'` and the semantic map resolves placeholders at runtime. If you deploy to a different environment, you simply provide a different map—the agent's query logic never changes.

**KB Router Pattern**

In practice, an agent often needs to decide *which* backend to query for a given task. The **KB Router** pattern uses a coordinator agent that:
1. Calls `get_schemas()` once to inspect all available backends and their purposes
2. For each user request, decides which backend(s) to query
3. Routes reads/writes to the appropriate backend via `read_kb` / `write_kb`

This keeps agents focused on domain logic while the router handles backend selection.

When you have multiple knowledge bases, you can provide explicit instructions to your agent about routing decisions. The agent then uses these instructions plus the schema information to intelligently decide:
- **Which KB to read from** – e.g., "For customer data, query the MongoDB backend. For company policies, query the Sheets backend."
- **Which KB to write to** – e.g., "Store graph relationships in Neo4j using explicit Cypher. Store unstructured notes in ChromaDB."

```python
router_agent = CrewAgent(
    role="knowledge_coordinator",
    goal="Route queries to the right knowledge backend",
    instructions="""
    You have access to multiple knowledge bases:
    - VectorDB: Use for semantic search of unstructured facts, documents, and notes
    - GraphDB: Use for structured relationships, entities, and their connections
    - MongoDB: Use for customer records, transactions, and business data
    
    When the user asks a question:
    1. Call get_schemas() to see all available backends
    2. Decide which backend(s) best answer the question
    3. Call read_kb() to query the chosen backend
    4. When storing new knowledge:
       - New relationships or entities → write to GraphDB
       - Unstructured notes or documents → write to VectorDB
       - Business transactions → write to MongoDB
    """,
    tools=[],  # Knowledge base tools auto-registered
)
```

The agent now has the intelligence to:
- Understand *what* each backend stores (from `get_schemas()`)
- Follow *where* to write based on instruction rules
- Route both reads and writes to minimize hallucinations and ensure data goes to the right place

### Example Flow

```python
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder

# 1. Define backends
vector_store = ChromaManager(name="VectorDB", description="...")
graph_db = Neo4jManager(name="GraphDB", description="...")

# 2. Compose with semantic mapping
kb = KnowledgeBuilder(
    [vector_store, graph_db],
    semantic_map={"<GRAPH>": "neo4j.default.graph"},
)

# 3. Agent uses tools
kb.build()  # Creates get_schemas(), read_kb(), write_kb(), etc.

# 4. Agent can now:
# - Call get_schemas() to discover backends
# - Call read_kb("GraphDB", "MATCH (n) LIMIT 5") to query the graph
# - Call write_kb("VectorDB", text="new fact") to store knowledge
```

### Plugging Knowledge Base Into an Agent

Once you have a `KnowledgeBuilder`, connecting it to an agent is straightforward. Get the knowledge base tools and pass them to your agent framework:

```python
from crewai import Agent as CrewAgent
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.crewai import CrewAIToolBuilder

# 1. Create KnowledgeBuilder with your backends
kb = KnowledgeBuilder([mongo_backend, sheets_backend], semantic_map={...})

# 2. Extract the knowledge base tools
kb_tools = kb.build()  # Returns [get_schemas, read_kb, write_kb, get_all_kb_descriptions]

# 3. Create your agent with these tools automatically available
knowledge_agent = CrewAgent(
    role="knowledge_router",
    goal="Query and manage knowledge across vector stores and graphs",
    # Bind framework-agnostic KB callables into CrewAI-compatible tools
    # so the agent can invoke get_schemas/read_kb/write_kb at runtime.
    tools=crewAItoolbuilder.bind(kb_tools)
   
)
```

The knowledge base tools integrate seamlessly with Agent Kernel's `ToolBuilder` pattern, which means:
- **Framework-agnostic**: same KB tools work with OpenAI, CrewAI, LangGraph, etc.
- **No boilerplate**: Agent automatically gets `read_kb`, `write_kb`, and schema introspection
- **Pluggable**: swap backends without changing agent code
- **Type-aware**: agent knows the function signatures and can call them correctly

For a complete working example with multiple agents and interactive routing, see [`examples/cli/knowledgebase/openai/multi/demo.py`](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/knowledgebase/openai/multi).

## Next Steps

Dive deeper into each core concept:

- [**Agent**](./agent) - Learn about agent wrapping and identification
- [**Tools**](./tools) - Write framework-agnostic tools for your agents
- [**Runner**](./runner) - Understand execution strategies
- [**Session**](./session) - Master conversation state management
- [**Module**](./module) - Organize your agents effectively
- [**Runtime**](./runtime) - Control the global orchestrator
- [**Fault Tolerance**](./fault-tolerance) - Build resilient agent systems

Or explore specific use cases:

- [Framework Integration](../frameworks/overview) - Framework-specific details
- [Deployment](../deployment/overview) - Production deployment options
- [Session Management](./session) - Session configuration and lifecycle
- [Memory Management](../architecture/memory-management) - Advanced memory features and caching
- [Knowledge Bases](../architecture/knowledge-bases) -  knowledge backends and KB routing

---

**Questions?** Check out our [GitHub Discussions](https://github.com/yaalalabs/agent-kernel/discussions)!
