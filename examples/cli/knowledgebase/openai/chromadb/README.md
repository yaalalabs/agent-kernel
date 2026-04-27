# ChromaDB Knowledge Base Demo

This example shows how to add a **single knowledge base** using ChromaDB.

## What This Demo Teaches

1. How to define a ChromaDB backend with a clear schema.
2. How to build KB tools from `KnowledgeBuilder`.
3. How to bind KB tools into an OpenAI Agent.
4. How to run the agent from the Agent Kernel CLI.

> These have been implemneted in demo.py please refer that 

## Prerequisites

- Python 3.12 or 3.13
- `uv` installed
- `OPENAI_API_KEY` exported in your shell

Example:

```bash
export OPENAI_API_KEY="your-key-here"
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

When the CLI starts, ask questions such as:

- "Store this fact: John prefers tea over coffee."
- "What do you know about John's preferences?"

## What Happens In demo.py

1. A Chroma backend is configured with schema metadata.
2. `KnowledgeBuilder` creates `get_schemas`, `read_kb`, and `write_kb` tools.
3. `OpenAIToolBuilder.bind(...)` attaches those tools to the router agent.
4. The agent is registered in `OpenAIModule`.
5. `CLI.main()` starts the interactive chat loop.

## Run Tests

```bash
uv run pytest -s demo_test.py
```