---
sidebar_position: 3
---

# Runner

The **Runner** encapsulates framework-specific execution strategies, providing a consistent interface for running agents across different frameworks. You can skip this section if you are not planning to contribute to Agent Kernel.

## Overview

```mermaid
graph TB
    A[User Request] --> B{Agent}
    B --> C[Runner]
    C --> D{Framework}
    D --> E[OpenAI Runner]
    D --> F[CrewAI Runner]
    D --> G[LangGraph Runner]
    D --> H[Google ADK Runner]
    D --> I[Smolagents Runner]

    E --> J["run() / stream()"]
    F --> J
    G --> J
    H --> J
    I --> J

    style C fill:#25c2a0,stroke:#fff,stroke-width:2px,color:#fff
```

## What is a Runner?

A Runner:
- **Executes** framework-specific agent logic (`run()`)
- **Streams** AK stream events (text/reasoning deltas, tool calls) for frameworks that support it (`stream()`)
- **Converts** Agent Kernel request models to framework-native input, and framework output back to `AgentReply` models
- **Manages** framework session state within the Agent Kernel `Session`
- **Creates** the `ToolContext` so tools can access the runtime, agent, session, and requests

## Runner Interface

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from agentkernel.core import Session
from agentkernel.core.event import StreamEvent
from agentkernel.core.model import AgentReply, AgentRequest

class Runner(ABC):
    @abstractmethod
    async def run(self, agent: "Agent", session: Session, requests: list[AgentRequest]) -> AgentReply:
        """Execute the agent with the given requests within the session context."""

    @property
    def supports_streaming(self) -> bool:
        """Whether this runner streams; adapters without streaming support override to False."""
        return True

    @abstractmethod
    async def stream(self, agent: "Agent", session: Session, requests: list[AgentRequest]) -> AsyncGenerator[StreamEvent, None]:
        """Yield AK stream events for streaming execution (execution.mode: stream)."""
```

- `run()` takes a **list of typed requests** (`AgentRequestText`, `AgentRequestImage`, `AgentRequestFile`, `AgentRequestAny`), not a raw prompt string, and returns an `AgentReply`.
- `stream()` is an async generator of `StreamEvent` members (`core/event.py`: `MessageStart`/`TextDelta`/`MessageEnd`, `ReasoningStart`/`ReasoningDelta`/`ReasoningEnd`, `ToolCallStart`/`ToolCallArgs`/`ToolCallEnd`/`ToolCallResult`, `StepStart`/`StepEnd`) — never a bare `str`. `Runtime.stream()` wraps each event in a `StreamChunk` (`delta` is populated only for `TextDelta`) and passes it through post-hook filtering before it reaches the client. See `docs/specs/523-ag-ui-support/spec.md` for the full event-mapping rules.

## Framework Runners

| Runner | Framework | AK `Runner.stream()` |
|--------|-----------|----------------------|
| `OpenAIRunner` | OpenAI Agents SDK | ✅ (`Runner.run_streamed`) |
| `LangGraphRunner` | LangGraph | ✅ (`astream_events`) |
| `GoogleADKRunner` | Google ADK | ✅ (SSE streaming mode) |
| `PydanticAIRunner` | Pydantic AI | ✅ (`run_stream_events`) |
| `CrewAIRunner` | CrewAI | ❌ raises `NotImplementedError` |
| `SmolagentsRunner` | Smolagents | ❌ raises `NotImplementedError` |

Each runner follows the same shape internally:

```python
class OpenAIRunner(Runner):
    async def run(self, agent, session, requests):
        # 1. Restore framework-specific session state from the AK session
        # 2. Convert AgentRequest models to framework-native input
        # 3. Create ToolContext, execute the framework's run API
        # 4. Save updated framework state back into the session
        # 5. Convert the result to AgentReplyText / AgentReplyImage / AgentReplyAny
```

## Reply Types

Every runner returns an `AgentReply` from `run()`. The union covers three reply models:

| Type | Produced when | Payload |
|------|---------------|---------|
| `AgentReplyText` | The agent produces plain text (default) | `text: str` |
| `AgentReplyImage` | The agent produces text plus an image | `text: str`, `image_data: str` |
| `AgentReplyAny` | The agent is configured for structured output | `content: dict` |

All reply types carry the `prompt` that was sent to the agent.

### Structured replies: `AgentReplyAny` {#structured-replies}

When an agent is configured to produce structured output (see the per-framework
"Structured Output" sections under [Frameworks](../frameworks/overview)), the runner
detects it and returns an `AgentReplyAny` instead of coercing the result to a string:

```python
from agentkernel.core.model import AgentReplyAny

reply = await runner.run(agent, session, requests)
if isinstance(reply, AgentReplyAny):
    data = reply.content          # dict, no re-parsing needed
```

- `content` holds the structured result as a JSON-compatible dict. Pydantic model
  results are converted with `model_dump(mode="json")`.
- `str(reply)` returns the JSON-serialized content, so any consumer that renders
  replies as text (chat integrations, logging, tracing) works unchanged.
- Plain-text agents are unaffected and continue to return `AgentReplyText`.

:::info Streaming and structured output
Structured output applies to **non-streaming** execution only — `run()` returns `AgentReplyAny`
directly. Streamed runs emit `StreamEvent`s (text/reasoning/tool-call deltas) rather than a parsed
reply; a streaming client reconstructs the final structured result from the tool-call events for
frameworks (like Pydantic AI) that stream the structured answer as a tool call. This is unrelated to
per-framework truncation behavior — see each framework's page for streaming fidelity notes.
:::

## Streaming Execution

When `execution.mode: stream` is configured, the pipeline calls `Runner.stream()` instead of `run()`:

```python
async for event in runner.stream(agent, session, requests):
    print(event)   # a StreamEvent, e.g. TextDelta, ToolCallStart, MessageEnd
```

In practice you rarely call this directly; use `AgentService.stream_multi()` or the REST API, which wrap each event in `StreamChunk` objects (`delta`, `event`, `done`, `error`, `session_id`) and run every event through the post-hook `on_stream_event()` chain:

```python
async for chunk in service.stream_multi(requests):
    if chunk.error:
        ...
    elif chunk.delta:
        print(chunk.delta, end="")   # populated only for TextDelta events
```

`delta` is populated only when `chunk.event` is a `TextDelta`, so a plain-text consumer can keep
concatenating `delta` unchanged; a consumer that wants tool calls, reasoning, or message/step
boundaries reads the full `event`. Frameworks without native token streaming (CrewAI, Smolagents)
declare `supports_streaming = False` and raise `NotImplementedError` from `stream()`; use the default
synchronous mode (or `rest_sync` on AWS) with those frameworks.

## Execution Flow

```mermaid
sequenceDiagram
    participant RT as Runtime
    participant R as Runner
    participant S as Session
    participant F as Framework

    RT->>R: run(agent, session, requests)
    R->>S: get framework state (session.get)
    S-->>R: current state
    R->>R: convert requests to native input,<br/>create ToolContext
    R->>F: framework execution (LLM calls, tools, handoffs)
    F-->>R: native result
    R->>S: update framework state (session.set)
    R-->>RT: AgentReply
```

Note that hooks, session locking, and persistence are handled by `Runtime.run()` *around* the runner; the runner itself only deals with framework execution and state conversion. See [Execution Flow](../architecture/execution-flow) for the full pipeline.

## Using Runners

Runners are typically accessed through agents, and invoked via the Runtime (which applies hooks and persistence):

```python
from agentkernel.core import Runtime
from agentkernel.core.model import AgentRequestText

runtime = Runtime.current()
agent = runtime.agents().get("assistant")
session = runtime.sessions().get("user-123") or runtime.sessions().new("user-123")

# Preferred: run through the Runtime so hooks and persistence apply
reply = await runtime.run(agent, session, [AgentRequestText(prompt="Hello")])
```

For most applications, the higher-level [`AgentService`](../architecture/execution-flow#2-request-building-and-agent-resolution) is more convenient than touching runners at all.

## Session Integration

Runners work closely with Sessions to maintain state. Each framework stores its own state under its own key:

```python
async def run(self, agent, session, requests):
    # Get framework-specific state from the AK session
    framework_state = session.get("openai")   # e.g. "openai", "langgraph", ...

    if not framework_state:
        framework_state = self._create_state()

    result = await self._execute(agent, framework_state, requests)

    session.set("openai", framework_state)    # persisted by Runtime after the run
    return result
```

From inside a hook or a tool (i.e. while the agent is executing), read the currently-running
agent's framework state without naming its runner key explicitly via
[`session.get_framework_session()`](./session.md#framework-session-access).

### Per-run framework context {#per-run-framework-context}

In addition to their own internal state, runners honour one reserved session value, the
**framework context** — a framework-agnostic, per-run context/state dict carried across turns. Seed and
read it with `session.set_framework_context()` / `get_framework_context()` from a pre- or post-hook (see
[Session → Framework context / per-run state](./session.md#framework-context--per-run-state)). When a
context is set, a runner:

1. **Loads** a deep copy of the stored context before invoking the framework.
2. **Injects** it into the native framework call (mapped to each framework's own context/state
   mechanism).
3. **Writes back** the produced state — shallow-merged over the loaded copy (framework-touched
   top-level keys win, untouched caller keys are preserved) — but only after the native call
   **succeeds**, so a crashed or disconnected run leaves the previously stored context intact.

**How faithfully a caller dict round-trips is not uniform across frameworks:**

| Framework | Fidelity | Injected as | Written back |
|-----------|----------|-------------|--------------|
| OpenAI | **Full round-trip** | `Runner.run(..., context=ctx)` — tools mutate it in place | the same object, in full |
| Pydantic AI | **Full round-trip** | `agent.run(..., deps=ctx)` — native tools mutate it in place via `RunContext.deps` ([caveats](../frameworks/pydantic-ai.md#per-run-contextstate)) | the same object, in full |
| Google ADK | **Round-trips (filtered), accumulate-only** | merged into the ADK session `state` (AK-internal keys always win, so they cannot be displaced by a caller key) | the accumulated session state, minus AK-internal and `app:`/`user:`/`temp:`-prefixed keys — **tool-added keys survive**, and so does anything else written to the state ([caveats](../frameworks/google-adk.md#per-run-contextstate)) |
| Smolagents | **Round-trips (filtered)** | `agent.run(..., additional_args=ctx)` — which smolagents **also appends to the task prompt** ([caveat](../frameworks/smolagents.md#per-run-contextstate)) | `agent.state` **restricted to pre-seeded keys** — brand-new keys are dropped |
| LangGraph | **Declared channels only** | spread into the graph input alongside `messages` (written last, so a caller key cannot replace it) | only keys the graph's state schema declares as channels (prebuilt agents drop unknown keys) |
| CrewAI | **Unsupported** | not injected | none — a set context is **ignored**, with one warning logged per runner |

Because of this divergence, tool authors who want a context write to be portable across every
framework should **pre-seed every key they intend to write** before the run.

### Per-agent native run options {#native-run-options}

Each framework's run API takes options of its own: a turn cap, lifecycle hooks, a run config. Agent
Kernel does not abstract over them. Instead, an application declares them **per agent** through the
module, in the framework's own types, and the runner merges them into its native call:

```python
from agents import RunConfig

OpenAIModule([agent]).run_options(
    agent,
    max_turns=25,
    hooks=ProgressHooks(),                                   # an SDK RunHooks subclass
    run_config=RunConfig(call_model_input_filter=trim),      # any RunConfig field
)
```

`Module.run_options(agent, **options)` is chained like `pre_hook` / `post_hook`; repeated calls merge,
the later call winning per key. The declared dict lives on `Agent.run_options`, is read on every run,
and is never persisted.

**The merge rule.** The runner copies the declared options and writes the keys it owns **last**, so a
declared option can never displace a value the adapter populates (the session, the framework
context, the input). The same keys are also rejected at declaration: each adapter names them in
`RESERVED_RUN_OPTIONS`, and `run_options` raises `ValueError` naming the key and the reason. Unknown
keys are not validated; they reach the SDK, whose own error surfaces on the first run.

Two adapters share an object with the caller rather than a key, and merge deeper:

- **LangGraph `config`** is deep-merged with the config the runner builds: dict-valued keys merge with
  the runner's entries winning (`configurable.thread_id` stays the session id), list-valued keys
  (`callbacks`, `tags`) concatenate with the runner's entries first (a tracing runner's handler is
  kept), everything else is the caller's.
- **ADK `run_config`** in stream mode is copied with `streaming_mode=SSE`, because the stream mapping
  depends on partial events; one warning is logged per runner when the caller's value differed.

| Framework | Options go to | Reserved keys | Turn limit | Progress hook |
|-----------|---------------|---------------|------------|---------------|
| OpenAI | `Runner.run` / `run_streamed` | `starting_agent`, `input`, `session`, `context` | `max_turns` | `hooks=RunHooks()` |
| LangGraph | `ainvoke` / `astream_events` | `input`, `version`, `stream_mode`, `output_keys`, `print_mode`, `config.configurable.thread_id` | `config["recursion_limit"]` | `config["callbacks"]` |
| Google ADK | the per-run `Runner(...)` constructor (`plugins`, `memory_service`, `artifact_service`, `credential_service`, `plugin_close_timeout`) and `run_async` (`run_config`) | `agent`, `app`, `app_name`, `node`, `session_service`, `auto_create_session`, `user_id`, `session_id`, `new_message`, `state_delta`, `invocation_id`, `yield_user_message` | `RunConfig(max_llm_calls=...)` | `plugins=[BasePlugin()]` |
| Pydantic AI | `agent.run` / `run_stream_events` | `user_prompt`, `message_history`, `deps` | `UsageLimits(request_limit=...)` | `event_stream_handler` (run mode; dropped with one warning in stream mode) |
| CrewAI | the per-run `Crew(...)` constructor (`verbose=False` is an overridable default) | `agents`, `tasks`, `memory` | `max_rpm` | `step_callback` / `task_callback` |
| Smolagents | `agent.run` | `task`, `reset`, `additional_args`, `stream`, `return_full_result` | `max_steps` | `step_callbacks` on the agent constructor (needs nothing from Agent Kernel) |

**Progress: two paths.** In `execution.mode: stream`, [`PostHook.on_stream_event`](../integrations/hooks.md#streaming-hooks-on_stream_event)
sees Agent Kernel's framework-agnostic `StreamEvent`s for whatever the adapter maps. Native hooks
through run options work in **any** mode, including `rest_sync`, and expose the framework's full
lifecycle (LLM start, agent start, handoffs). A native hook's callbacks run inside the Agent Kernel
run, so `Session.current()` and `Agent.current()` resolve in them; a hook instance declared once at
load time therefore needs no per-request plumbing. It is shared by every concurrent run of that
agent, so keep per-run state in the session (its volatile cache is cleared after each run), never on
the hook.

Run options compose with tracing: the Langfuse, Logfire and OpenLLMetry runners delegate to the base
runner, so a declared `hooks=` still reaches the SDK when `trace.enabled` is on. The
[custom-runner path](../advanced/traceability.md#how-to-add-your-own-platform) remains for behaviour
that is not a keyword argument of the native call.

See the per-framework demos: `examples/cli/openai-run-options`, `langgraph-run-options`,
`adk-run-options`, `pydanticai-run-options`, `crewai-run-options` and `smolagents-run-options`.

## Best Practices

### Async Execution

Always use `await` when calling runners:

```python
# Correct
reply = await runtime.run(agent, session, requests)

# Incorrect
reply = runtime.run(agent, session, requests)  # Returns coroutine
```

### Error Handling

Wrap execution in try-except:

```python
try:
    reply = await runtime.run(agent, session, requests)
except Exception as e:
    logger.error(f"Runner error: {e}")
    # Handle error appropriately
```

## Summary

- Runners execute framework-specific agent logic and expose both `run()` and `stream()`
- Each framework has its own Runner implementation
- OpenAI Agents SDK, LangGraph, Google ADK, and Pydantic AI support native token streaming (as AK `StreamEvent`s); CrewAI and Smolagents do not
- Runners convert typed requests/replies and manage framework session state
- Runners inject the reserved `framework_context` into the native call and write the produced state back on success (fidelity varies per framework)
- Always use async/await, and prefer `Runtime.run()`/`AgentService` over calling runners directly

## Next Steps

- [Session Management](./session)
- [Module Organization](./module)
- [Framework Integration](../frameworks/overview)
- [Execution Flow](../architecture/execution-flow)
