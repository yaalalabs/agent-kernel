````markdown
# Volatile Cache (Key-Value Cache) Demo

This example demonstrates the use of **volatile cache** (key-value cache) in Agent Kernel to share data between hooks and agent tools within the same execution session. It showcases how to use the session-scoped volatile cache for temporary data storage and retrieval.

## Overview

The example implements a simulated RAG (Retrieval-Augmented Generation) pattern where:
1. A **pre-execution hook** (RAGHook) retrieves relevant context from a knowledge base and stores it in the volatile cache
2. An **agent tool** (`query_private_knowledge_base`) retrieves the cached context and uses it to answer questions

This pattern is useful when you need to:
- Share data between hooks and tools within the same request
- Temporarily store context that doesn't need to persist across sessions
- Pass information from pre-processing steps to tool execution

## Key Features

### Volatile Cache (KeyValueCache)
The volatile cache provides session-scoped key-value storage:
- **Session-scoped**: Data is available only within the current execution
- **Temporary**: Data is cleared after the request completes
- **Fast**: In-memory storage for quick access
- **Simple**: Key-value interface for easy data sharing

### Two Agent Configurations
The example includes two agents to demonstrate cache usage:

1. **Senior Assistant** - Has RAG hook enabled
   - Pre-execution hook injects context into volatile cache
   - Can answer questions about AcmeXXLabs and SoftYYLabs

2. **Junior Assistant** - No RAG hook
   - No context injection
   - Cannot answer questions about private knowledge

### RAG Pattern with Volatile Cache

**Pre-execution Hook** (`hooks.py`):
```python
class RAGHook(Prehook):
    async def on_run(self, session, agent, original_prompt, prompt, additional_context):
        # Retrieve relevant context from knowledge base
        relevant_contexts = [...]
        
        # Store in volatile cache
        cache = session.get_volatile_cache()
        cache.set("rag_context", relevant_contexts)
        
        return True, prompt
```

**Agent Tool** (`app.py`):
```python
@function_tool
def query_private_knowledge_base(query: str) -> str:
    # Retrieve context from volatile cache
    cache = GlobalRuntime.instance().get_volatile_cache()
    rag_context = cache.get("rag_context")
    
    # Use context to answer query
    if rag_context:
        # Search for relevant information
        ...
```

## How It Works

### 1. Senior Assistant Flow (With RAG Hook)
```
User Query → RAG Hook → Volatile Cache (set) → Agent → Tool → Volatile Cache (get) → Response
```

1. User sends query: "What is AcmeXXLabs?"
2. RAGHook searches knowledge base for "AcmeXXLabs"
3. Hook stores context in volatile cache: `cache.set("rag_context", [...])`
4. Agent calls `query_private_knowledge_base` tool
5. Tool retrieves context from cache: `cache.get("rag_context")`
6. Tool uses cached context to answer the question
7. Agent returns enriched response

### 2. Junior Assistant Flow (Without RAG Hook)
```
User Query → Agent → Tool → Volatile Cache (empty) → "I don't know" Response
```

1. User sends query: "What is AcmeXXLabs?"
2. No hook runs (junior agent has no hooks)
3. Agent calls `query_private_knowledge_base` tool
4. Tool checks volatile cache but finds nothing
5. Tool returns: "No relevant information found"
6. Agent returns: "I don't know"

## Running the Example

### Setup
```bash
# Build the environment
./build.sh

# Or for local development
./build.sh local
```

### Run the API Server
```bash
source .venv/bin/activate
python app.py
```

The server will start on `http://localhost:8000`.

### Test the Volatile Cache

#### Test Senior Assistant (With RAG Context)
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "senior_assistant",
    "session_id": "test-123",
    "prompt": "What is AcmeXXLabs?"
  }'
```

Expected: Response mentions "cutting-edge green technology" and "San Francisco" (from cached context).

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "senior_assistant",
    "session_id": "test-456",
    "prompt": "What is SoftYYLabs?"
  }'
```

Expected: Response mentions "thorium", "research", and "Shandong, China" (from cached context).

#### Test Junior Assistant (Without RAG Context)
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "junior_assistant",
    "session_id": "test-789",
    "prompt": "What is AcmeXXLabs?"
  }'
```

Expected: Response indicates "I don't know" or "no relevant information" (no cached context available).

### Run Automated Tests

```bash
source .venv/bin/activate
pytest app_test.py -v
```

The test suite validates:
- ✓ Junior agent cannot answer without cached context
- ✓ Senior agent successfully uses cached context
- ✓ Cache is properly scoped to each session
- ✓ Different queries retrieve different cached contexts

## File Structure

```
key_value_cache/
├── app.py           # Main application with agents and cache usage
├── hooks.py         # RAGHook implementation with cache injection
├── app_test.py      # Automated test suite
├── pyproject.toml   # Project dependencies
├── build.sh         # Build script
└── README.md        # This file
```

## Key Concepts

### Volatile Cache vs. Persistent Memory

| Feature | Volatile Cache | Persistent Memory (Redis/DynamoDB) |
|---------|---------------|-----------------------------------|
| **Scope** | Single request/execution | Multiple sessions |
| **Lifetime** | Request duration | Configurable TTL or permanent |
| **Use Case** | Hook-to-tool communication | Chat history, user preferences |
| **Performance** | Very fast (in-memory) | Fast (network call) |
| **Storage** | Simple key-value pairs | Structured conversation data |

### When to Use Volatile Cache

Use volatile cache when you need to:
- ✅ Share data between hooks and tools in the same execution
- ✅ Store temporary context that doesn't need to persist
- ✅ Pass metadata or configuration within a request
- ✅ Implement RAG patterns with dynamic context injection
- ✅ Cache computation results within a single request

Do **not** use volatile cache for:
- ❌ Storing conversation history across requests
- ❌ Persisting user preferences or state
- ❌ Sharing data between different sessions
- ❌ Long-term data storage

### Volatile Cache API

#### Storing Data
```python
from agentkernel import KeyValueCache

# In a hook (session available)
cache: KeyValueCache = session.get_volatile_cache()
cache.set("my_key", {"some": "data"})

# In a tool (use GlobalRuntime)
from agentkernel import GlobalRuntime
cache: KeyValueCache = GlobalRuntime.instance().get_volatile_cache()
cache.set("my_key", {"some": "data"})
```

#### Retrieving Data
```python
# Get data (returns None if key doesn't exist)
data = cache.get("my_key")

# Get data with default value
data = cache.get("my_key", default=[])
```

#### Checking Existence
```python
if cache.exists("my_key"):
    data = cache.get("my_key")
```

#### Removing Data
```python
cache.delete("my_key")
```

## Knowledge Base

The example includes a simulated knowledge base with the following entries:

- **AcmeXXLabs**: "AcmeXXLabs is cutting-edge green technology solution provider. Its headquarters is in San Francisco"
- **SoftYYLabs**: "SoftYYLabs is a leading Thorium based research agency. Its headquarters is in Shandong, China"

These are stored in `RAGHook.KNOWLEDGE_BASE` and injected into the volatile cache when matching topics are detected in the prompt.

## Advanced Usage

### Storing Multiple Data Types
```python
# Store strings
cache.set("user_intent", "information_seeking")

# Store lists
cache.set("retrieved_docs", [doc1, doc2, doc3])

# Store dictionaries
cache.set("metadata", {"source": "rag", "confidence": 0.95})

# Store custom objects (must be serializable)
cache.set("config", MyConfig())
```

### Namespacing Keys
```python
# Use prefixes to organize cache keys
cache.set("rag:context", context_data)
cache.set("rag:metadata", metadata)
cache.set("user:preferences", preferences)
```

### Cache Patterns

#### Pattern 1: Pre-Hook Data Injection
```python
class DataInjectionHook(Prehook):
    async def on_run(self, session, agent, original_prompt, prompt, additional_context):
        cache = session.get_volatile_cache()
        cache.set("enriched_data", await fetch_data(prompt))
        return True, prompt
```

#### Pattern 2: Tool Data Consumption
```python
@function_tool
def my_tool(query: str) -> str:
    cache = GlobalRuntime.instance().get_volatile_cache()
    data = cache.get("enriched_data", default={})
    return process(query, data)
```

#### Pattern 3: Cross-Tool Communication
```python
@function_tool
def analyzer(text: str) -> str:
    cache = GlobalRuntime.instance().get_volatile_cache()
    analysis = perform_analysis(text)
    cache.set("analysis_result", analysis)
    return "Analysis complete"

@function_tool
def reporter() -> str:
    cache = GlobalRuntime.instance().get_volatile_cache()
    analysis = cache.get("analysis_result")
    return generate_report(analysis)
```

## Learn More

- [Agent Kernel Documentation](https://docs.agent-kernel.io)
- [Core Concepts: Memory](https://docs.agent-kernel.io/core-concepts/memory)
- [Core Concepts: Hooks](https://docs.agent-kernel.io/core-concepts/hooks)
- [OpenAI Integration](https://docs.agent-kernel.io/frameworks/openai)

````