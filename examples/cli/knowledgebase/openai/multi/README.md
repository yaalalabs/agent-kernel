# Multi Knowledge Base Demo (Chroma + Neo4j + Starburst)

This is the most complete OpenAI knowledge-base example in this folder.

It combines four backends behind one router agent:

- `ChromaDB` for semantic text retrieval
- `Neo4jDB` for entities and relationships
- `StarburstDB-mongo` for Mongo data via Trino
- `StarburstDB_Sheets` for Sheets data via Trino

## What This Demo Teaches

1. How to define multiple KB backends with clear role descriptions.
2. How to publish schema guidance so the agent can self-route safely.
3. How to map placeholders to physical Starburst sources with `semantic_map`.
4. How to build KB tools once and bind them to one router agent.

> These have been implemneted in demo.py please refer that 

## Prerequisites

- Python 3.12 or 3.13
- `uv` installed
- `OPENAI_API_KEY`
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `STARBURST_USER`
- `STARBURST_PASSWORD`

Example:

```bash
export OPENAI_API_KEY="your-key-here"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="your-password"
export STARBURST_USER="your-starburst-user"
export STARBURST_PASSWORD="your-starburst-password"
```

## Setup

Run from this folder:

```bash
./build.sh
```

Use local source code from this repository (instead of the published package):

```bash
./build.sh local
```

## Placeholder Rule For Starburst Sources

Keep these placeholders exactly as-is in query templates:

- `<MONGO_SOURCE>`
- `<SHEETS_SOURCE>`

`semantic_map` resolves them to concrete source paths at runtime.

Starburst docs: https://docs.starburst.io/starburst-galaxy/

## Run The Demo

```bash
python demo.py
```

Suggested prompts:

- "Store this memory in Chroma: Alice likes matcha tea."
- "Create friendship between Alice and Bob in graph."
- "Query clients from Mongo source with active status."
- "Search Sheets knowledge for onboarding policy."

## What Happens In demo.py

1. All four backends are configured with explicit schema metadata.
2. `KnowledgeBuilder` merges them into one tool surface.
3. `OpenAIToolBuilder.bind(...)` attaches KB tools to the router agent.
4. The agent is registered with `OpenAIModule`.
5. CLI starts, and external backends are closed safely on exit.

## Run Tests

```bash
uv run pytest -s demo_test.py
```