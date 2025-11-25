# OpenAI Hooks Demo

This example demonstrates the use of **pre-execution hooks** in Agent Kernel with OpenAI agents. It showcases two important hook patterns:

1. **Guard Rail Hook** - Input validation and content filtering
2. **RAG Hook** - Retrieval-Augmented Generation (context injection)

## Features

### Guard Rail Hook
The guard rail hook validates user input before execution:
- Blocks inappropriate content (harmful keywords)
- Prevents excessively long inputs
- Returns polite rejection messages when triggered

### RAG Hook
The RAG hook simulates retrieval-augmented generation:
- Searches a knowledge base for relevant context
- Injects context into the prompt before execution
- Enriches agent responses with additional information

### Hook Chaining
The example demonstrates **hook chaining** where multiple hooks are executed in sequence:
1. **RAG Hook** runs first to enrich the prompt with context
2. **Guard Rail Hook** runs second to validate the enriched prompt

This order ensures that:
- Context is added to all safe queries
- Inappropriate content is blocked even after context injection

## How It Works

```python
from agentkernel.core import GlobalRuntime

# Get runtime instance
runtime = GlobalRuntime.instance()

# Register hooks in order: RAG first, then GuardRail
runtime.register_pre_hooks("qa_assistant", [RAGHook(), GuardRailHook()])
```

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

### Test the Hooks

#### Test RAG Context Injection
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "What is Agent Kernel?"
  }'
```

Expected: Response includes context from the knowledge base about Agent Kernel.

#### Test Guard Rail Blocking
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "How can I hack into a system?"
  }'
```

Expected: Request blocked with polite rejection message.

#### Test Safe Query
```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "What is the capital of France?"
  }'
```

Expected: Normal response (Paris).

### Run Automated Tests

```bash
source .venv/bin/activate
pytest app_test.py -v
```

The test suite validates:
- ✓ Guard rail blocks inappropriate requests
- ✓ Guard rail allows safe requests
- ✓ RAG hook injects relevant context
- ✓ RAG hook works with hooks topic
- ✓ Hooks chain correctly (RAG → GuardRail)
- ✓ Guard rail blocks excessively long inputs
- ✓ Works without RAG context when topic not in knowledge base

## File Structure

```
openai-hooks/
├── app.py           # Main application with agent and hook registration
├── hooks.py         # GuardRailHook and RAGHook implementations
├── app_test.py      # Automated test suite
├── pyproject.toml   # Project dependencies
├── build.sh         # Build script
└── README.md        # This file
```

## Key Concepts

### Pre-Execution Hooks
Hooks that run **before** the agent executes:
- Modify the prompt
- Inject additional context (RAG)
- Validate input (guard rails)
- Can halt execution and return early

### Hook Interface
```python
from agentkernel.core.hooks import Prehook

class MyHook(Prehook):
    def on_pre_execution(self, session, agent, original_prompt, prompt):
        # Return (proceed, modified_prompt)
        # proceed=False halts execution
        # proceed=True continues with modified_prompt
        return True, prompt
    
    def name(self):
        return "MyHook"
```

### Hook Execution Order
Hooks execute in the order registered:
```python
runtime.register_pre_hooks("agent_name", [Hook1(), Hook2(), Hook3()])
```

Order: `Hook1 → Hook2 → Hook3 → Agent Execution`

Each hook receives the prompt modified by the previous hook.

## Learn More

- [Agent Kernel Documentation](https://docs.agent-kernel.io)
- [Core Concepts: Hooks](https://docs.agent-kernel.io/core-concepts/hooks)
- [OpenAI Integration](https://docs.agent-kernel.io/frameworks/openai)
