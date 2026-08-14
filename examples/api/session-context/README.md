# OpenAI Session Context Demo

This example demonstrates `Session.get_framework_session()` with OpenAI agents: reaching the
framework adapter's own session object directly from a post-execution hook, in order to bound its
growth over the life of a conversation.

For general pre/post hook patterns (guardrails, RAG, disclaimers), see
[`examples/api/hooks`](../hooks/README.md).

## Features

### History Trim Hook (Post-hook)
The history trim hook bounds the OpenAI Agents SDK's own raw conversation history (not the AK
`Session` cache) as a session grows: once it exceeds `THRESHOLD` items, it is trimmed back down to
the most recent `THRESHOLD` items after every turn:
- Calls `session.get_framework_session()` to reach the framework-native session object directly
- Trims it via its own `get_items()` / `clear_session()` / `add_items()` methods
- Needs no `session.set(...)` call afterward — see [Framework Session Access](#framework-session-access) below

## How It Works

```python
from agentkernel.openai import OpenAIModule

module = OpenAIModule([qa_assistant_agent])

# Register a post-execution hook that caps the framework session history
module.post_hook(qa_assistant_agent, [HistoryTrimHook()])
```

```python
from agentkernel import PostHook

class HistoryTrimHook(PostHook):
    THRESHOLD = 3

    async def on_run(self, session, requests, agent, agent_reply):
        openai_session = session.get_framework_session()
        if openai_session is None:
            return agent_reply

        items = await openai_session.get_items()
        if len(items) > self.THRESHOLD:
            capped = items[-self.THRESHOLD:]  # keep only the most recent THRESHOLD items
            await openai_session.clear_session()
            await openai_session.add_items(capped)

        return agent_reply

    def name(self):
        return "HistoryTrimHook"
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

### Test History Trimming
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "qa_assistant",
    "session_id": "test-123",
    "prompt": "What is the capital of France?"
  }'
```

Send enough turns on the same `session_id` to push the OpenAI-native item count past
`HistoryTrimHook.THRESHOLD`, then inspect the session store to confirm the history was trimmed.

### Run Automated Tests

```bash
source .venv/bin/activate
pytest hooks_test.py -v
```

`hooks_test.py` is a network-free unit test: it fabricates the OpenAI framework session directly
and proves that `Session.get_framework_session()` hands back a *live* reference that
`HistoryTrimHook` mutates in place.

## File Structure

```
session-context/
├── app.py           # Main application with agent and hook registration
├── hooks.py         # HistoryTrimHook implementation
├── hooks_test.py    # Network-free unit test for HistoryTrimHook / get_framework_session()
├── pyproject.toml   # Project dependencies
├── build.sh         # Build script
└── README.md        # This file
```

## Key Concepts

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

## Learn More

- [Agent Kernel Documentation](https://docs.agent-kernel.io)
- [Core Concepts: Session](https://docs.agent-kernel.io/core-concepts/session)
- [Core Concepts: Hooks](https://docs.agent-kernel.io/core-concepts/hooks)
- [OpenAI Integration](https://docs.agent-kernel.io/frameworks/openai)
