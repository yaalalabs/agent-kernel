# Local Session Memory Demo

This example shows how a normal Agent Kernel API app uses the **session store** as
conversation memory, and how switching `session.type` changes whether that memory survives a
restart.

It is the runnable companion to
[Choosing a Memory Backend](https://kernel.yaala.ai/docs/core-concepts/memory-backends).

## What This Demo Teaches

1. Conversation memory is configured entirely through `config.yaml` (`session.type`).
2. The default `in_memory` backend forgets the conversation when the process stops.
3. Switching to Redis (or Valkey) keeps the same conversation across a restart.
4. A network-free test can verify the configured store without calling an LLM.

## Prerequisites

- Python 3.12 or newer
- `uv` installed
- `OPENAI_API_KEY` exported in your shell for the API demo

```bash
export OPENAI_API_KEY="your-key-here"
```

## Setup

Run from this folder:

```bash
./build.sh
```

Use local Agent Kernel source code instead of the published package:

```bash
./build.sh local
```

The dependencies include the `redis` and `valkey` extras, so you can switch backends without
reinstalling anything.

## Run: in-memory (default)

Start the API server:

```bash
uv run demo.py
```

Tell the agent a fact, using a fixed `session_id`:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent": "memory_assistant", "session_id": "local-demo", "prompt": "Remember that my favourite tea is green tea."}'
```

Stop the server with `Ctrl+C`, start it again, and ask a follow-up with the **same**
`session_id`:

```bash
uv run demo.py
```

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent": "memory_assistant", "session_id": "local-demo", "prompt": "What is my favourite tea?"}'
```

With `in_memory`, the agent has forgotten the earlier turn — that is expected.

## Run: Redis (survives restart)

1. Start Redis:

   ```bash
   docker run --rm -p 6379:6379 redis:7
   ```

2. In `config.yaml`, replace the `in_memory` block with the commented Redis block.

3. Repeat the two requests above. Stop and restart the server between them, and the agent now
   remembers the earlier turn because the session lives in Redis.

Valkey works the same way: uncomment the Valkey block and point it at a Valkey server.

## Run Tests

```bash
uv run pytest -s
```

`demo_test.py` is network-free. It builds the store from this folder's `config.yaml` and proves
that a session round-trips through it, plus that a fresh `in_memory` store starts empty.

## File Structure

```
local-session/
├── demo.py          # OpenAI agent served over the REST API
├── config.yaml      # Session backend: in_memory by default, Redis/Valkey commented out
├── demo_test.py     # Network-free session-store test
├── build.sh         # Build script
├── pyproject.toml   # Project dependencies
└── README.md        # This file
```

## Learn More

- [Choosing a Memory Backend](https://kernel.yaala.ai/docs/core-concepts/memory-backends)
- [Session Management](https://kernel.yaala.ai/docs/core-concepts/session)
- [Memory Management](https://kernel.yaala.ai/docs/architecture/memory-management)
- [Deployment examples](../redis/README.md) for Redis, Valkey, DynamoDB, and Cosmos DB on real cloud infrastructure
