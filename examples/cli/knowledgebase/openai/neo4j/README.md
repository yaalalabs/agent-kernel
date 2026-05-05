# Neo4j Knowledge Base Demo

This example shows how to use **Neo4j as a graph knowledge base** with an OpenAI router agent.

## What This Demo Teaches

1. How to configure a Neo4j backend and expose query rules to the agent.
2. How to keep Cypher generation safe and predictable through schema guidance.
3. How to build and bind KB tools (`get_schemas`, `read_kb`, `write_kb`).
4. How to run the demo through the Agent Kernel CLI.

> These have been implemneted in demo.py please refer that 

## Prerequisites

- Python 3.12 or 3.13
- `uv` installed
- `OPENAI_API_KEY`
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`

Example:

```bash
export OPENAI_API_KEY="your-key-here"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="your-password"
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

## Run The Demo

```bash
python demo.py
```

Try prompts such as:

- "Add friendship between Alice and Bob."
- "Are Alice and Bob friends?"

## What Happens In demo.py

1. A Neo4j backend is configured with strict Cypher guidance.
2. `KnowledgeBuilder` creates callable KB tools.
3. `OpenAIToolBuilder.bind(...)` converts them into OpenAI Agent tools.
4. The router agent is registered in `OpenAIModule`.
5. CLI runs and the Neo4j connection is closed on exit.

## Run Tests

```bash
uv run pytest -s demo_test.py
```