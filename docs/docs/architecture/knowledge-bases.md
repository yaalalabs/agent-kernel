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
- `write_kb(backend: str, text: str, ..., query: str, params_json: str, ...)` – write to a backend (supports both simple text facts and backend‑specific queries like Cypher).
- `get_all_kb_descriptions()` – short descriptions of each registered backend.

`KnowledgeBuilder` also supports a `semantic_map` parameter to resolve logical placeholders in agent queries. This is useful for Starburst-style query templates such as `<SHEETS_SOURCE>` and `<MONGO_SOURCE>`.

Example:

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager

v_db = ChromaManager(name="ChromaDB").add_schema({...})
g_db = Neo4jManager(name="Neo4jDB").add_schema({...})

kb_tools = KnowledgeBuilder([v_db, g_db]).build()
```

`kb_tools` is a list of plain Python callables that you bind using the framework‑specific `ToolBuilder` (for example, `OpenAIToolBuilder.bind(kb_tools)`).

Example with semantic placeholders:

```python
kb_tools = KnowledgeBuilder(
  [v_db, g_db],
  semantic_map={
    "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => '...'))",
    "<MONGO_SOURCE>": "kb_mongo.my_company_kb.clients",
  },
).build()
```

## KB Router Pattern

The recommended pattern is to build a **“knowledge base router” agent**:

1. **Inject tools**: Bind the knowledge base tools into your agent via the appropriate module/adapter.
2. **Describe backends**: Provide clear descriptions and schema metadata for each backend (what it stores, how to query it, and when to use it).
3. **Routing instructions**: In the agent’s instructions, require it to:
   - Call `get_schemas()` (and/or `get_all_kb_descriptions()`) at the start.
   - Choose a backend based on the question and backend descriptions.
  - Follow backend query templates exactly (including placeholder tokens where present).
   - Use `read_kb` for queries and `write_kb` for storing new facts.
   - Fall back to its own model knowledge when no relevant KB data exists.

This pattern works the same across all supported agent frameworks (OpenAI Agents, LangGraph, CrewAI, Google ADK) because the tools are framework‑agnostic.

## Example: OpenAI KB Router

The repository includes OpenAI Agents SDK examples split by backend type:

- **Location**: `examples/cli/knowledgebase/openai`
- **Demos**:
  - `chromadb/` - semantic text only.
  - `neo4j/` - graph facts and Cypher queries.
  - `starburst/` - SQL backends via Starburst/Trino.
  - `multi/` - combined router demo with all backends.
- **Agent**: `KB_Router_Agent`, created with clear routing rules, bound knowledge base tools from `KnowledgeBuilder`, and instructions to always inspect schemas before choosing a backend.

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

