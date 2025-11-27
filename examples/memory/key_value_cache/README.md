# Key-Value Cache Demo

This example demonstrates the use of **volatile cache** and **non-volatile cache** in Agent Kernel to share data between hooks and agent tools.

## Cache Types

### Volatile Cache
Session-scoped cache that stores data only for the current request execution:
- Data is cleared after the request completes
- Use for temporary context within a single execution
- Accessed via: `session.get_volatile_cache() or GlobalRuntime.instance().get_volatile_cache()`

### Non-Volatile Cache
Persistent cache that stores data throughout the session lifecycle:
- Data persists across multiple requests
- Use for extracted information from user inputs (e.g., file attachments, user preferences)
- Accessed via: `session.get_non_volatile_cache() or GlobalRuntime.instance().get_non_volatile_cache()`

**Usage is identical for both cache types** - the only difference is data lifetime.

## Typical Use Case

Instead of adding extracted information to the prompt, store it in the cache:
- Extract data from file attachments in a pre-hook
- Store extracted content in cache (volatile or non-volatile)
- Tools retrieve from cache instead of receiving data in prompts
- Keeps prompts clean and reduces token usage

## Example

This demo shows a RAG pattern where:
1. **RAGHook** (pre-execution hook) retrieves context from a knowledge base and stores it in volatile cache
2. **query_private_knowledge_base** tool retrieves the cached context to answer questions

**Two agents demonstrate cache behavior:**
- **Senior Assistant**: Has RAG hook enabled, can answer questions about AcmeXXLabs and SoftYYLabs
- **Junior Assistant**: No RAG hook, cannot access cached context

**Pre-execution Hook** (`hooks.py`):
```python
cache = session.get_volatile_cache()
cache.set("rag_context", relevant_contexts)
```

**Agent Tool** (`app.py`):
```python
cache = GlobalRuntime.instance().get_volatile_cache()
rag_context = cache.get("rag_context")
```

## Running the Example

### Build
```bash
./build.sh
```

### Run the API Server
```bash
uv run app.py
```

### Test with curl
```bash
# Senior assistant (with RAG context in cache)
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent": "senior_assistant", "session_id": "test-123", "prompt": "What is AcmeXXLabs?"}'

# Junior assistant (no cached context)
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"agent": "junior_assistant", "session_id": "test-456", "prompt": "What is AcmeXXLabs?"}'
```

### Run Tests
```bash
uv run pytest
```