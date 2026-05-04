---
slug: /knowledge-bases-self-evolving-agents
title: "Knowledge Bases: The Missing Layer That Lets AI Agents Self-Evolve"
authors: [yaala]
tags: [agent-kernel, knowledge-bases, chromadb, neo4j, starburst, rag, vector-store, graph-database, self-evolving-agents, enterprise-ai]
image: /img/card.png
---

# Knowledge Bases: The Missing Layer That Lets AI Agents Self-Evolve

Most AI agents have a fundamental flaw: **they forget everything.**

Every conversation starts from zero. The agent doesn't remember that it got a fact wrong last Tuesday. It doesn't remember the new product line you told it about. It doesn't remember that a customer is a high-value account who hates upsells. It doesn't even remember its own mistakes.

That's not an AI agent. That's a very expensive autocomplete that resets every session.

**Agent Kernel's Knowledge Base layer changes this completely.** And more importantly — it gives agents something they've never had before: the ability to *learn from their own operation* and get measurably smarter over time.

<!-- truncate -->

## What's Actually Wrong with Today's AI Agents

Let's be direct about the problem.

Current agent architectures give you session memory — what was said in this conversation — and that's about it. When the session ends, that memory is gone. The next user, the next session, the next agent instance starts fresh. Every piece of operational knowledge your agent accumulates evaporates when the conversation closes.

This creates a ceiling. Your agents plateau. They never improve from experience. They repeat the same mistakes. They rediscover the same domain knowledge on every call. And if you want them to know something new, you're back to prompt engineering, fine-tuning, or rebuilding the whole system.

There is a better architecture. And it's been sitting in front of us the whole time.

## Durable Knowledge: The Layer Below Sessions

Agent Kernel draws a sharp line between two kinds of memory:

**Session memory** is volatile and scoped to one conversation. When the session ends, it's gone. This is the right place for things like: what the user said three messages ago, the partial result of a multi-step tool call, or a temporary calculation.

**Knowledge bases** are durable and cross-session. They persist between conversations, across agent instances, across deployments. This is the right place for: domain facts, learned corrections, customer profiles, product catalogs, operational patterns, and anything the agent should *remember forever*.

When you combine both layers, something remarkable happens: **your agents accumulate intelligence over time.** Every interaction is an opportunity to write something back. Every mistake can be corrected and stored. Every successful pattern can be reinforced.

That's self-evolution. Not in a science-fiction sense. In a very practical, engineering sense.

## The Self-Evolving Agent Pattern

Here's the concrete pattern that unlocks self-improvement.

The agent has access to both read and write tools for the knowledge base. When it encounters something worth remembering, it writes it. When it starts a new session, it reads from the knowledge base before responding. Over time, the knowledge base grows richer and the agent's responses improve — without any human retraining.

Consider a customer-facing support agent:

1. **Day 1**: A customer asks about a product edge case. The agent searches the KB, finds nothing, researches it, and answers correctly. It then writes that edge case and the correct answer to the KB.
2. **Day 2**: A different customer asks the same question. The agent reads the KB, finds the answer immediately, responds in milliseconds. No LLM reasoning required for that step.
3. **Week 2**: A product manager updates the answer because the product changed. The agent reads the updated record. Every future session gets the new answer automatically.
4. **Month 3**: The KB now contains hundreds of edge cases, customer patterns, and domain corrections. The agent is dramatically more accurate than on Day 1 — not because of retraining, but because of accumulated knowledge.

This is the compounding effect that static agent architectures can never achieve.

## Three Backends, One API

Agent Kernel ships with production-grade support for three fundamentally different knowledge storage paradigms — all behind a single, consistent interface.

### ChromaDB — Semantic Memory for Text

ChromaDB is a vector database purpose-built for semantic similarity search. You write natural language text; ChromaDB embeds it and stores it as high-dimensional vectors. When an agent queries it, ChromaDB returns the most semantically relevant records — not keyword matches, but *meaning* matches.

This is the right backend for:
- Product documentation and FAQs
- Support knowledge that agents discover during operation
- Domain-specific terminology and explanations
- Any knowledge that requires natural language retrieval

The agent doesn't need to know the exact words used when the knowledge was stored. It asks a question in plain language and gets the most relevant answer, even if the stored text uses different phrasing.

```python
from agentkernel.knowledgebase.chroma import ChromaManager

v_db = ChromaManager(name="ProductKB").add_schema({
    "description": "Product documentation and support knowledge. Use for product questions, feature explanations, and known issue resolutions.",
    "usage": "Pass a natural language query. Returns the most semantically relevant knowledge entries.",
    "write_format": {"text": "string (the knowledge to store)", "metadata": {"source": "string", "category": "string"}},
})
```

### Neo4j — Relational Memory for Connected Knowledge

Neo4j is a graph database. Instead of storing isolated facts, it stores *relationships* between entities. This unlocks a category of agent reasoning that flat databases simply cannot support: traversal, inference, and multi-hop relationship queries.

Think about what this means for an agent:
- A customer support agent can reason about which customers use which products, and which products have which known issues.
- An enterprise agent can navigate org charts, escalation paths, and approval workflows.
- A research agent can traverse citation graphs, author relationships, and topic hierarchies.

This is the right backend for:
- Customer relationship graphs
- Organizational structures and reporting lines
- Concept maps and knowledge ontologies
- Dependency trees (products, services, systems)
- Any domain where "how is X connected to Y?" matters

```python
from agentkernel.knowledgebase.neo4j import Neo4jManager

g_db = Neo4jManager(name="CustomerGraph").add_schema({
    "description": "Customer and product relationship graph. Use for account-level context, product usage patterns, and escalation chains.",
    "usage": "Write Cypher queries to read/write nodes and relationships.",
    "write_format": {"text": "Cypher CREATE or MERGE statement", "metadata": {"entity_type": "Customer|Product|Issue"}},
})
```

### Starburst Galaxy — Analytical Memory for Structured Data

Starburst Galaxy is a distributed SQL query engine built on Trino. It can query across multiple data sources simultaneously — PostgreSQL, MongoDB, Google Sheets, S3, and dozens of others — using standard SQL. From the agent's perspective, it's a single, unified analytical layer over all your structured data.

This is read-only by design: Starburst is for *reading* structured operational data that already exists in your systems, not for agent-generated writes. It's the right backend for:
- Live business metrics and dashboards
- Customer transaction history
- Inventory and pricing data
- Any structured data that agents need to read but shouldn't write

With Starburst, your agent can answer questions like "What are the top 10 customers by revenue this quarter?" or "Which SKUs are below reorder threshold right now?" — directly from your live data systems, with no ETL pipeline in between.

```python
from agentkernel.knowledgebase.starburst import StarburstManager

s_db = StarburstManager(name="SalesData").add_schema({
    "description": "Live sales and inventory data via Starburst Galaxy. READ-ONLY. Use for revenue queries, inventory lookups, and customer transaction history.",
    "usage": "Pass SQL SELECT statements. Use <SALES_SOURCE> as the table placeholder.",
    "query_template": "SELECT ... FROM <SALES_SOURCE> WHERE ...",
})
```

## Semantic Map: Keeping Agents Portable

One of the most powerful details in Agent Kernel's KB design is `semantic_map` — and it's easy to miss if you don't look for it.

The problem it solves: physical resource names in databases change. Table names change when you migrate. Collection names differ between dev and prod. Catalog paths in Starburst differ between environments. If your agent hardcodes those physical names in its queries, you're constantly updating prompts whenever the environment changes.

`semantic_map` fixes this by letting agents reason over stable, logical tokens — `<CUSTOMER_SOURCE>`, `<INVENTORY_TABLE>`, `<VECTOR_STORE>` — while `KnowledgeBuilder` resolves them to the correct physical target at runtime.

```python
semantic_map = {
    "<CUSTOMER_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'SHEET_ID_PROD'))",  # Prod
    "<INVENTORY_TABLE>": "warehouse.inventory.current_stock",
}
# In staging, swap out the values — agent prompts stay identical
```

Your agent stays portable. Your prompts stay unchanged. Environment-specific details live in deployment config, not in the model's context.

## KnowledgeBuilder: The Composition Layer

`KnowledgeBuilder` is the glue that composes backends into a unified tool surface for the agent. You register one or more backends, optionally provide a `semantic_map`, call `.build()`, and get back a list of plain Python callables:

- `get_schemas()` — returns each backend's schema so the agent can decide where to route
- `read_kb(backend, query, limit)` — query a specific backend
- `write_kb(backend, text, ...)` — write to a backend
- `get_all_kb_descriptions()` — short summary of all registered backends for routing context

These callables are framework-agnostic. A framework adapter then binds them into the actual agent runtime.

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager

kb = KnowledgeBuilder(
    backends=[v_db, g_db, s_db],
    semantic_map=semantic_map,
)
kb_tools = kb.build()
```

Then wire into any supported framework:

```python
# OpenAI Agents SDK
from agentkernel.openai import OpenAIToolBuilder
from agents import Agent

kb_agent = Agent(
    name="KnowledgeAgent",
    instructions="...",
    tools=OpenAIToolBuilder.bind(kb_tools),
)
```

The same `kb_tools` works identically with LangGraph, CrewAI, and Google ADK. One knowledge layer, all frameworks.

## Why This Changes the Game

Here's the honest assessment of what this unlocks that wasn't possible before.

**Agents that improve without retraining.** Every write to the KB is a micro-improvement. Scale that across thousands of sessions and you have an agent that is genuinely smarter at month three than it was on day one — without a single fine-tuning run.

**Knowledge that survives agent restarts, redeploys, and framework switches.** The knowledge base is outside the agent. Swap from LangGraph to CrewAI? Your KB comes with you. Redeploy to a new environment? Your KB is still there.

**Multi-agent knowledge sharing.** Multiple agents — a support agent, a billing agent, a triage agent — can all read from and write to the same KB. Knowledge discovered by one agent is immediately available to all others. This is the foundation of a genuinely collaborative multi-agent system.

**Specialised query capabilities per domain.** Use ChromaDB for fuzzy natural language retrieval. Use Neo4j for relationship traversal. Use Starburst for SQL analytics. Route each query to the backend that's architecturally correct for the question type. No more forcing all your data through a single retrieval strategy that's wrong for most of it.

**Custom backends for any storage system.** Not locked in to the three built-in backends. Implement the `KnowledgeBase` adapter for your existing Pinecone instance, your Elasticsearch cluster, your internal knowledge API — and it plugs into the same KB tools infrastructure with zero changes to your agent code.

## The Recommended Pattern: KB Router Agent

For multi-backend setups, Agent Kernel recommends dedicating one agent to knowledge routing. This agent's only job is to decide which KB to query, execute the read or write, and return results to the calling agent.

Why this matters: routing decisions benefit from inspecting schemas first. A specialised routing agent can call `get_schemas()`, understand what each backend contains, and make an accurate routing decision before executing. Mixing this responsibility into a task-focused agent leads to routing errors and hallucinated backends.

```python
kb_router = Agent(
    name="KB_Router_Agent",
    instructions="""
    You manage access to multiple knowledge backends.

    Start every request by calling get_schemas() to inspect available backends.
    Then call get_all_kb_descriptions() for routing context.

    Routing rules:
    - Natural language / semantic questions → ChromaDB backend
    - Relationship or entity traversal → Neo4j backend (Cypher only)
    - Structured data / analytics / SQL → Starburst backend (READ-ONLY, no write_kb)

    When writing knowledge:
    - Use write_kb with the correct backend name
    - Never call write_kb for Starburst backends
    - Always include descriptive metadata in the write payload

    When the query contains a placeholder like <CUSTOMER_SOURCE>, keep it unchanged
    in your query string — the semantic_map will resolve it at runtime.
    """,
    tools=OpenAIToolBuilder.bind(kb_tools),
)
```

## Technical Reference

### The `KnowledgeBase` Abstract Interface

All backends — built-in and custom — implement the same contract:

| Member | Type | Description |
|---|---|---|
| `backend_name` | `@property str` | Unique identifier used in tool calls and schemas |
| `connect(**kwargs)` | `abstractmethod` | Establish backend connection |
| `write(records, **kwargs)` | `abstractmethod` | Persist `[{"text": str, "metadata": dict}]` records |
| `read(query, limit, **kwargs)` | `abstractmethod` | Return top-N relevant records for query |
| `get_description()` | `abstractmethod` | Human-readable description for agent routing |
| `add_schema(config)` | Inherited | Merge config dict into backend schema |
| `schema()` | Inherited | Returns `{"backend": name, ...schema_config}` |
| `format_results(rows)` | Optional override | Format records for agent response |
| `close()` | Optional override | Release connections / flush buffers |

### Writing a Custom Adapter

```python
from agentkernel.knowledgebase.base import KnowledgeBase, Record
from typing import Any, Iterable, List, Mapping


class PineconeBackend(KnowledgeBase):

    @property
    def backend_name(self) -> str:
        return "PineconeKB"

    def connect(self, **kwargs) -> None:
        import pinecone
        pinecone.init(api_key=kwargs["api_key"], environment=kwargs["env"])
        self._index = pinecone.Index(kwargs["index_name"])

    def write(self, records: Iterable[Record], **kwargs) -> None:
        vectors = []
        for r in records:
            embedding = embed(r["text"])  # your embedding function
            vectors.append((r["metadata"]["id"], embedding, {"text": r["text"]}))
        self._index.upsert(vectors=vectors)

    def read(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        embedding = embed(query)
        results = self._index.query(vector=embedding, top_k=limit, include_metadata=True)
        return [{"text": m["metadata"]["text"], "metadata": m["metadata"]} for m in results["matches"]]

    def get_description(self) -> str:
        return "Pinecone vector store for high-scale semantic search over product embeddings."
```

Register it exactly like the built-ins:

```python
pinecone_kb = PineconeBackend().add_schema({
    "description": "Product embedding store — high-scale semantic similarity search.",
    "usage": "Pass a natural language query. Returns semantically nearest product entries.",
})

kb = KnowledgeBuilder([pinecone_kb, g_db], semantic_map=semantic_map)
```

### Full Wiring Example (OpenAI Agents SDK)

```python
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager
from agentkernel.openai import OpenAIToolBuilder
from agents import Agent, Runner

# 1. Configure backends
v_db = ChromaManager(name="DocsKB").add_schema({...})
g_db = Neo4jManager(name="RelGraph").add_schema({...})
s_db = StarburstManager(name="Analytics").add_schema({...})

# 2. Define semantic map
semantic_map = {
    "<CUSTOMER_TABLE>": "catalog.crm.customers",
    "<ORDERS_TABLE>":   "catalog.sales.orders",
}

# 3. Build KB tools
kb = KnowledgeBuilder([v_db, g_db, s_db], semantic_map=semantic_map)
kb_tools = kb.build()

# 4. Connect backends
v_db.connect(host="localhost", port=8000, collection="docs")
g_db.connect(uri="bolt://localhost:7687", user="neo4j", password="...")
s_db.connect(host="galaxy.starburst.io", port=443, token="...", catalog="kb_sheets")

# 5. Create the router agent
router = Agent(
    name="KnowledgeRouter",
    instructions="Route queries to the correct knowledge backend. "
                 "Check schemas first. Starburst is read-only.",
    tools=OpenAIToolBuilder.bind(kb_tools),
)

# 6. Run
result = await Runner.run(router, "What are our top 5 customers by revenue this month?")
print(result.final_output)
```

### Importing from `agentkernel.knowledgebase`

```python
from agentkernel.knowledgebase.base          import KnowledgeBase, Record
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.chroma        import ChromaManager
from agentkernel.knowledgebase.neo4j         import Neo4jManager
from agentkernel.knowledgebase.starburst     import StarburstManager
```

---

Knowledge bases are the layer that transforms AI agents from stateless request handlers into systems that genuinely accumulate expertise. The built-in ChromaDB, Neo4j, and Starburst backends cover the three fundamental storage paradigms. The custom adapter API means you're never locked out of your existing infrastructure.

The compounding effect is real. The first agent that writes back to the KB makes the next session better. Over time, your agents stop being expensive autocomplete and start being genuine institutional knowledge systems.

That's the shift. Build it today.

**[→ Knowledge Bases Documentation](/docs/next/architecture/knowledge-bases)**  
**[→ Example: OpenAI KB Router](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/knowledgebase/openai)**
