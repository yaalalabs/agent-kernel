# Knowledge Base Router – OpenAI Agents Demo

This example demonstrates how to build a **knowledge base router agent** using Agent Kernel and the **OpenAI Agents SDK**.

The agent can:
- Store and retrieve **semantic text** in a **ChromaDB** vector store.
- Store and query **entities/relationships** in **Neo4j** (optional, via environment variables).
- Automatically choose the right backend for each read/write based on backend schemas and descriptions.

The router is implemented in `demo.py` and exposed via the Agent Kernel CLI.

## Prerequisites

- Python 3.12–3.13
- `OPENAI_API_KEY` set in your environment

Optional:
- Neo4j credentials if you want to use the graph backend:
  - `NEO4J_URI` (default: `bolt://localhost:7687`)
  - `NEO4J_USERNAME` (default: `neo4j`)
  - `NEO4J_PASSWORD` (default: `password`)

## Install

From this directory:

```bash
./build.sh
```

For local development (installs local `agentkernel`):

```bash
./build.sh local
```

## Run

```bash
python demo.py
```

After startup, use the CLI to select `KB_Router_Agent` and chat.

## What the router does

The agent is bound to the knowledge base tools produced by `KnowledgeBuilder`:

- `get_schemas()` – inspects all registered backends and their payload shapes.
- `get_all_kb_descriptions()` – short backend descriptions for routing decisions.
- `read_kb(backend, query, limit)` – reads relevant records from a chosen backend.
- `write_kb(backend, text, query, params_json, ...)` – writes facts/records into a chosen backend.

The agent instructions require it to:
1. Call `get_schemas()` early.
2. Pick a backend explicitly (vector vs graph).
3. Use `read_kb()` for reads and `write_kb()` for writes.
4. Fall back to its own model knowledge when the KB has nothing relevant.

## Data persistence

This demo persists Chroma data under `./Scratches/` so it remains available across runs.

## Tests

If you add tests for this example, run:

```bash
uv run pytest -s
```