---
sidebar_position: 5
---

# Knowledge Bases

Agent Kernel provides a **backend‑agnostic knowledge base interface** that lets agents read and write long‑term knowledge across multiple storage systems (vector stores and graph databases) using a consistent API.

This builds on top of core session and memory concepts:
- **Session + caches** → short‑ and medium‑term conversation state.
- **Knowledge bases** → durable, cross‑session knowledge.

## Core Abstractions

### `KnowledgeBase`

`KnowledgeBase` is an abstract interface implemented by concrete backends:

- `ChromaManager` – ChromaDB vector store for semantic text recall.
- `Neo4jManager` – Neo4j graph database for entities and relationships.
- `StarburstManager` – Starburst Galaxy (read-only SQL via Trino) for querying structured data in MongoDB, Google Sheets, PostgreSQL, and other Trino-connected sources.

For Starburst operational details, see Starburst Galaxy documentation:
- https://docs.starburst.io/starburst-galaxy/

Each backend implements:

- `backend_name: str` – unique identifier (used by tools and schemas).
- `add_schema(schema_config: dict)` – register backend‑specific schema/usage metadata.
- `schema() -> Mapping[str, Any>` – returns a JSON‑serializable schema describing capabilities and payload shapes.
- `connect(**kwargs) -> None` – establish any underlying client connections.
- `write(records: Iterable[Record], **kwargs) -> None` – persist records (`{"text": ..., "metadata": ...}`).
- `read(query: str, limit: int = N, **kwargs) -> list[Record]` – retrieve relevant records.
- `format_results(rows: list[Record]) -> str` – helper for formatting results for the agent.
- `get_description() -> str` – human‑readable description for routing decisions.

All backends live under `agentkernel.knowledgebase`:

```python
from agentkernel.knowledgebase.base import KnowledgeBase
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager
```

## KnowledgeBuilder and Tools

`KnowledgeBuilder` composes one or more `KnowledgeBase` instances and exposes a **small set of tools** that can be bound to any supported agent framework:

- `get_schemas()` – returns JSON with each backend’s schema/metadata.
- `read_kb(backend: str, query: str, limit: int = 3)` – query a specific backend.
- `write_kb(backend: str, text: str, ..., query: str, params_json: str, ...)` – write to a backend (write semantics are backend-specific).
- `get_all_kb_descriptions()` – short descriptions of each registered backend.

Important: `StarburstManager` is read-only. Use `read_kb` for Starburst backends and do not route `write_kb` calls to Starburst.

`KnowledgeBuilder` also supports a `semantic_map` parameter that resolves logical placeholders in agent-generated queries into backend-specific resource names at runtime. This is the key abstraction that keeps agents simple: they reason over stable, human-friendly tokens such as `<SHEETS_SOURCE>` or `<MONGO_SOURCE>` instead of memorizing changing catalog names, schema names, table names, or long physical paths.

In practice, the agent writes a query against the logical placeholder, and `KnowledgeBuilder` performs the translation immediately before the backend executes it. That means the agent can stay portable across environments while each deployment maps the same logical token to its own concrete target.

Example:

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager

v_db = ChromaManager(name="ChromaDB").add_schema({...})
g_db = Neo4jManager(name="Neo4jDB").add_schema({...})

kb_tools = KnowledgeBuilder([v_db, g_db]).build()
```

`kb_tools` is the output of `KnowledgeBuilder.build()`: a list of plain Python callables such as `get_schemas`, `read_kb`, and `write_kb`. Those callables are not yet agent tools on their own. The framework-specific adapter binds them into the agent runtime. In the OpenAI examples, that happens in one step with `tools=OpenAIToolBuilder.bind(knowledgeBuilder.build())`.



### `semantic_map`

1. What is `semantic_map`:
  - **Definition**: A mapping of stable, human-friendly placeholder tokens (keys) to concrete backend resource identifiers (values) used by `KnowledgeBuilder` at runtime.
  - **Form**: a plain Python dict where keys are tokens like `<SHEETS_SOURCE>` and values are backend-specific resource strings (SQL table references, DB paths, Trino/Starburst CALL syntax, etc.).

2. Purpose:
  - Decouples agent prompts from changing physical resource names so agent prompts remain portable across deployments.
  - Lets agents generate queries using logical tokens while the runtime binds those tokens to the correct backend targets.
  - Reduces agent hallucinations by centralizing backend-specific details in the deployment configuration.

3. Examples:
  - Vector store (Chroma): no physical table name needed — map to the backend name when helpful: `"<VECTOR_STORE>": "ChromaDB"`.
  - Graph (Neo4j): map to a named graph or connection string: `"<GRAPH>": "neo4j.default.graph"`.
  - Starburst/Trino (Sheets/Mongo): map logical placeholders to SQL FROM targets: `"<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID'))"` or `"<MONGO_SOURCE>": "catalog.schema.table"`.

4. How to write a `semantic_map` (best practices):
  - Keep placeholders short and descriptive (e.g., `<SHEETS_SOURCE>`, `<MONGO_SOURCE>`).
  - Use one mapping per logical resource; avoid aliasing the same physical target under many keys.
  - Document expected query syntax in the backend `schema()` so agents can build correct queries (see demo examples for required templates).
  - Never expose credentials in `semantic_map` values; keep `semantic_map` purely as resource identifiers.
  - Make environment-specific overrides (CI, staging, prod) by supplying a different `semantic_map` at deployment time.

  #### KnowledgeBuilder example (semantic_map)

  The short example below shows the minimal steps to register backends, provide a `semantic_map`, build KB tools, and how the token replacement works at runtime. All explanatory notes are in comments.

  ```python
  # 1) Import the pieces
  from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
  from agentkernel.knowledgebase.chroma import ChromaManager
  from agentkernel.knowledgebase.neo4j import Neo4jManager

  # 2) Define (lightweight) backends and their schemas
  #    In real code you would supply full schema dictionaries as in the demos.
  v_db = ChromaManager(name="ChromaDB").add_schema({"description": "Vector store"})
  g_db = Neo4jManager(name="Neo4jDB").add_schema({"description": "Graph DB"})

  # 3) Define the semantic_map - agent prompts use the LEFT side tokens
  #    and the runtime replaces them with the RIGHT side physical targets.
  semantic_map = {
    "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID'))",  # Trino/Starburst wrapper
    "<MONGO_SOURCE>": "catalog.schema.clients",  # Example catalog.schema.table path
  }

  # 4) Create the KnowledgeBuilder with backends + semantic_map
  kb = KnowledgeBuilder([v_db, g_db], semantic_map=semantic_map)

  # 5) Build the KB tools (framework adapters bind these into agents)
  #    The exact return shape can be a list of callables; here we store as a variable.
  kb_tools = kb.build()

  # 6) Agent constructs a query using the logical placeholder token
  query = "SELECT client_name, status FROM <MONGO_SOURCE> WHERE status = 'active' LIMIT 5"

  # 7) At runtime, before the backend executes the SQL, KnowledgeBuilder
  #    replaces `<MONGO_SOURCE>` with `catalog.schema.clients` from `semantic_map`.
  #    Then `read_kb()` sends the resolved SQL to the correct Starburst backend.
  #    (In practice the agent calls the `read_kb` callable from `kb_tools`.)
  resolved_query = query.replace("<MONGO_SOURCE>", semantic_map["<MONGO_SOURCE>"])
  # read_results = read_kb("StarburstDB-mongo", resolved_query)

  # NOTE: Keep placeholders consistent in prompts and document required
  #       query templates in each backend's `schema()` to avoid runtime errors.
  ```


Example of wiring the KB tools into an agent:

```python
from agents import Agent
from agentkernel.openai import OpenAIToolBuilder

kb_router_agent = Agent(
  name="KB_Router_Agent",
  instructions="""
  You have access to multiple knowledge bases.
  Use get_schemas() to inspect them first, then decide which backend to read from or write to.
  Use read_kb for retrieval and write_kb for persistence.
  Starburst is read-only: never call write_kb for Starburst backends.
  When a placeholder such as <MONGO_SOURCE> appears in a query, keep it unchanged in the prompt;
  the semantic_map will resolve it to the correct backend target at runtime.
  """,
  tools=OpenAIToolBuilder.bind(kb_tools),
)
```

Note: `kb_tools` used above is the result of calling `build()` on a `KnowledgeBuilder` instance (for example, `kb_tools = KnowledgeBuilder([...], semantic_map={...}).build()` or `kb_tools = kb.build()`); ensure you have created that variable before binding it into the agent to avoid confusion.


## KB Router Pattern

The recommended pattern is to build a **“knowledge base router” agent**:

1. **Inject tools**: Bind the knowledge base tools into the agent via the appropriate framework adapter.
2. **Describe backends**: Provide clear backend descriptions and schemas so the agent can tell what belongs in each store.
3. **Route explicitly**: In the instructions, tell the agent how to choose between KBs, when to read, and when to write, including backend constraints (for example, Starburst is read-only).
4. **Keep placeholders logical**: Let the agent use tokens like `<SHEETS_SOURCE>` or `<MONGO_SOURCE>` while `semantic_map` handles the physical translation.
5. **Prefer a router agent for multi-KB setups**: One agent can inspect schemas and route requests, which reduces hallucination and keeps backend selection deterministic.

This pattern works the same across all supported agent frameworks (OpenAI Agents, LangGraph, CrewAI, Google ADK) because the tools are framework‑agnostic.

## Example: OpenAI KB Router

The repository includes OpenAI Agents SDK examples split by backend type:

- **Location**: `examples/cli/knowledgebase/openai`
- **Demos**:
  - `chromadb/` - semantic text only.
  - `neo4j/` - graph reads/writes using Cypher queries.
  - `starburst/` - SQL backends via Starburst/Trino.
  - `multi/` - combined router demo with all backends.
- **Agent**: `KB_Router_Agent`, created with clear routing rules, bound knowledge base tools from `KnowledgeBuilder`, and instructions to inspect schemas before choosing a backend, then route each query to the correct KB.

See the per-backend READMEs for step-by-step usage and routing behavior:
- `examples/cli/knowledgebase/openai/chromadb/README.md`
- `examples/cli/knowledgebase/openai/neo4j/README.md`
- `examples/cli/knowledgebase/openai/starburst/README.md`
- `examples/cli/knowledgebase/openai/multi/README.md`

## When to Use Knowledge Bases vs. Memory

Use **session memory and caches** when:
- Data is tied to a single conversation or short‑lived workflow.
- Content should influence the current LLM context only.
- You don’t need durable, cross‑session storage.

Use **knowledge bases** when:
- You need durable, reusable knowledge (docs, profiles, domain data).
- You want multiple agents or sessions to share the same information.
- You need specialized query capabilities (semantic search, graph queries).

You can also **combine** them:
- Fetch from a knowledge base, then cache results in the session’s volatile cache for fast reuse during a single request.

