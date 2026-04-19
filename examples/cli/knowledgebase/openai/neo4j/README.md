# Neo4j Demo

This OpenAI Agents SDK demo routes all knowledge lookups to a single Neo4j backend.

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

## Run

From this directory:

```bash
python demo.py
```

## Tests

```bash
uv run pytest -s demo_test.py
```