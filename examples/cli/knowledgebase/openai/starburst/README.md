# Starburst Demo

This OpenAI Agents SDK demo routes knowledge lookups to the Starburst/Trino SQL backends.

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
- `STARBURST_USER`
- `STARBURST_PASSWORD`

## Placeholder-Based Query Routing

This demo intentionally uses semantic placeholders in schema query templates:

- `<MONGO_SOURCE>`
- `<SHEETS_SOURCE>`

`KnowledgeBuilder.semantic_map` resolves these placeholders to physical Starburst sources at runtime. Keep these placeholder tokens in query templates and do not replace them manually in agent instructions.

## Starburst Reference

- Starburst Galaxy docs: https://docs.starburst.io/starburst-galaxy/

## Run

From this directory:

```bash
python demo.py
```

## Tests

```bash
uv run pytest -s demo_test.py
```