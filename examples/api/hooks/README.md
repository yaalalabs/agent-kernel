# OpenAI Hooks Demo

This example demonstrates the use of **pre-execution hooks** and **post-execution hooks** in Agent Kernel with OpenAI agents. It showcases four important hook patterns:

1. **Guard Rail Hook** (Pre-hook) - Input validation and content filtering
2. **RAG Hook** (Pre-hook) - Retrieval-Augmented Generation (context injection)
3. **Disclaimer Hook** (Post-hook) - Adding disclaimers to agent responses
4. **History Trim Hook** (Post-hook) - Capping the framework-native session history via `Session.get_framework_session()`

## Features

### Guard Rail Hook (Pre-hook)
The guardrail hook validates user input before execution:
- Blocks inappropriate content (harmful keywords)
- Prevents excessively long inputs
- Returns polite rejection messages when triggered

### RAG Hook (Pre-hook)
The RAG hook simulates retrieval-augmented generation:
- Searches a knowledge base for relevant context
- Injects context into the prompt before execution
- Enriches agent responses with additional information

### Disclaimer Hook (Post-hook)
The disclaimer hook adds compliance messages to agent responses:
- Appends a disclaimer to all agent replies
- Reminds users that responses are AI-generated
- Encourages verification for critical decisions

### History Trim Hook (Post-hook)
The history trim hook bounds the OpenAI Agents SDK's own raw conversation history (not the AK
`Session` cache) as a session grows: once it exceeds `THRESHOLD` items, the oldest `TRIM_COUNT`
items are dropped after every turn:
- Calls `session.get_framework_session()` to reach the framework-native session object directly
- Trims it via its own `get_items()` / `clear_session()` / `add_items()` methods
- Needs no `session.set(...)` call afterward — see [Key Concepts](#framework-session-access) below

### Hook Chaining
The example demonstrates **hook chaining** where multiple hooks are executed in sequence:

**Pre-execution hooks (in order):**
1. **RAG Hook** runs first to enrich the prompt with context
2. **Guard Rail Hook** runs second to validate the enriched prompt

**Post-execution hooks:**
3. **Disclaimer Hook** runs first to add a disclaimer to the reply
4. **History Trim Hook** runs after to cap the framework-native session history

This order ensures that:
- Context is added to all safe queries
- Inappropriate content is blocked even after context injection
- All successful responses include a disclaimer
- The underlying OpenAI session history never grows unbounded

## How It Works

### Pre-Execution Hooks
```python
from agentkernel import AuxiliaryCache

# Create module
module = OpenAIModule([qa_assistant_agent])

# Register pre-execution hooks in order: RAG first, then GuardRail
module.pre_hook(qa_assistant_agent, [RAGHook(), GuardRailHook()])
```

### Post-Execution Hooks
```python
# Register post-execution hooks: add a disclaimer, then trim the framework session history
module.post_hook(qa_assistant_agent, [DisclaimerHook(), HistoryTrimHook()])
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
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "What is Agent Kernel?"
  }'
```

Expected: Response includes context from the knowledge base about Agent Kernel, plus a disclaimer at the end.

#### Test Guard Rail Blocking
```bash
curl -X POST http://localhost:8000/api/v1/chat \
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
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "What is the capital of France?"
  }'
```

Expected: Normal response (Paris) with a disclaimer appended.

### Run Automated Tests

```bash
source .venv/bin/activate
pytest app_test.py -v
```

The test suite validates:
- ✓ Guardrail blocks inappropriate requests
- ✓ Guardrail allows safe requests
- ✓ RAG hook injects relevant context
- ✓ RAG hook works with hooks topic
- ✓ Hooks chain correctly (RAG → GuardRail)
- ✓ Guardrail blocks excessively long inputs
- ✓ Works without RAG context when topic not in knowledge base
- ✓ Disclaimer hook adds disclaimer to all responses
- ✓ Disclaimer hook not applied when guardrail blocks request
- ✓ Full hook chain works correctly (RAG → GuardRail → Agent → Disclaimer)
- ✓ Disclaimer hook preserves agent response content

## File Structure

```
hooks/
├── app.py           # Main application with agent and hook registration
├── hooks.py         # GuardRailHook, RAGHook, DisclaimerHook, and HistoryTrimHook implementations
├── app_test.py      # Automated end-to-end test suite (drives the real OpenAI Agents SDK over HTTP)
├── hooks_test.py     # Network-free unit test for HistoryTrimHook / get_framework_session()
├── demonstration.py # Demonstration script
├── pyproject.toml   # Project dependencies
├── build.sh         # Build script
└── README.md        # This file
```

## Key Concepts

### Pre-Execution Hooks
Hooks that run **before** the agent executes:
- Modify the prompt
- Inject additional context (RAG)
- Validate input (guardrails)
- Can halt execution and return early

### Post-Execution Hooks
Hooks that run **after** the agent generates a response:
- Modify the agent's reply
- Add disclaimers or additional information
- Apply content moderation to outputs
- Cannot halt execution (always return modified response)

### Hook Interfaces

#### Pre-hook Interface
```python
from agentkernel import PreHook

class MyPreHook(PreHook):
    async def on_run(
      self, session: Session, agent: Agent, requests: list[AgentRequest])->list[AgentRequest]|AgentReply:
        return requests # modify as required or send AgentReply to stop execution
    
    def name(self):
        return "MyPreHook"
```

#### Post-hook Interface
```python
from agentkernel import PostHook

class MyPostHook(PostHook):
    async def on_run(
        self, session: Session, requests: list[AgentRequest], agent: Agent, agent_reply: AgentReply
    ) -> AgentReply:
      return agent_reply # modify as required

    def name(self):
      return "MyPostHook"
```

**Note:** Hook methods are async, allowing you to perform asynchronous operations like database queries, API calls, or vector searches.

### Framework Session Access

`Session.get_framework_session()` returns the framework-native session object for whichever
agent is currently executing (it reads `Agent.current().runner.name`, e.g. `"openai"`, and looks
that key up in the session). This is a **live reference**, not a copy: `Session.get()`/`set()`
just read and write a plain `dict` of object references (`ak-py/src/agentkernel/core/base.py`), so
mutating the returned object through its own methods (as `HistoryTrimHook` does with
`clear_session()`/`add_items()`) updates what's stored immediately — no `session.set(...)`
call is needed afterward.

It can only be called while an agent is executing (inside a hook or a tool) — calling it with no
agent running raises `RuntimeError`, since there'd be no framework key to resolve.

### Hook Execution Order
Hooks execute in the order registered:
```python
runtime.register_pre_hooks("agent_name", [Hook1(), Hook2(), Hook3()])
runtime.register_post_hooks("agent_name", [PostHook1(), PostHook2()])
```

Order: `Hook1 → Hook2 → Hook3 → Agent Execution → PostHook1 → PostHook2`

Each hook receives the prompt/response modified by the previous hook.

## Learn More

- [Agent Kernel Documentation](https://docs.agent-kernel.io)
- [Core Concepts: Hooks](https://docs.agent-kernel.io/core-concepts/hooks)
- [OpenAI Integration](https://docs.agent-kernel.io/frameworks/openai)
