# Starburst Knowledge Base Demo

This example uses **two Starburst/Trino read-only backends** in one router agent:

- MongoDB source via Starburst
- Google Sheets source via Starburst

## What This Demo Teaches

1. How to define SQL-style schemas and query templates for Starburst backends.
2. How to use semantic placeholders (`<MONGO_SOURCE>`, `<SHEETS_SOURCE>`).
3. How `semantic_map` resolves placeholders to real physical sources.
4. How to bind and run KB tools from an OpenAI agent.

> These have been implemneted in demo.py please refer that 

## Prerequisites

- Python 3.12 or 3.13
- `uv` installed
- `OPENAI_API_KEY`
- `STARBURST_USER`
- `STARBURST_PASSWORD`

Example:

```bash
export OPENAI_API_KEY="your-key-here"
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

## Important Placeholder Rule

Keep placeholder tokens in query templates exactly as written:

- `<MONGO_SOURCE>`
- `<SHEETS_SOURCE>`

Do not manually replace them in agent instructions. `KnowledgeBuilder.semantic_map` resolves them at runtime.

## Run The Demo

```bash
python demo.py
```

Try prompts such as:

- "Show clients from Mongo with status active."
- "Find policy notes in the sheets source about security."

## What Happens In demo.py

1. Two Starburst backends are configured with schema and constraints.
2. A `semantic_map` maps logical placeholders to physical source paths.
3. `KnowledgeBuilder` creates KB tools.
4. Tools are bound to an OpenAI router agent.
5. CLI runs and both Starburst backends are closed on exit.

## Starburst Reference

- https://docs.starburst.io/starburst-galaxy/

## Run Tests

```bash
uv run pytest -s demo_test.py
```