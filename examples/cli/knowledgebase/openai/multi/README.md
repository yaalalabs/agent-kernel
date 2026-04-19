# Multi Knowledge Base Demo

This OpenAI Agents SDK demo combines ChromaDB, Neo4j, and Starburst/Trino backends behind one router agent.

## Setup

From this directory:

```bash
./build.sh
```

For local development against this repository source (instead of the published PyPI package):

```bash
./build.sh local
```

## Prerequisites

- Python 3.12-3.13
- `OPENAI_API_KEY` set in your environment
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `STARBURST_USER`
- `STARBURST_PASSWORD`

## Placeholder-Based Query Routing (Starburst)

The Starburst backends use semantic placeholders in schema query templates:

- `<MONGO_SOURCE>`
- `<SHEETS_SOURCE>`

`KnowledgeBuilder.semantic_map` resolves these placeholders at runtime. Query templates should keep placeholder tokens intact and follow schema examples exactly.

Starburst Galaxy docs: https://docs.starburst.io/starburst-galaxy/

## Run

From this directory:

```bash
python demo.py
```

## Tests

```bash
uv run pytest -s demo_test.py
```