---
sidebar_position: 7
---

# Pydantic AI

Integrate [Pydantic AI](https://ai.pydantic.dev) with Agent Kernel. Pydantic AI is built by the
Pydantic team and gives Agent Kernel native, first-class support for many model providers
(OpenAI, Anthropic, Google, Bedrock, Groq, Mistral, Cohere, xAI, Ollama, …) plus `FallbackModel`
for automatic provider failover.

## Installation

```bash
pip install agentkernel[pydanticai]
```

`agentkernel[pydanticai]` installs the **provider-agnostic** `pydantic-ai-slim` core — it ships no
model provider. Install the provider you intend to use:

```bash
pip install "pydantic-ai-slim[openai]"       # or [anthropic], [google], [bedrock], [groq], ...
```

Switching providers is then a one-line change to the model string — that provider freedom is the
main reason to reach for this adapter.

## Basic Usage

```python
from pydantic_ai import Agent
from agentkernel.cli import CLI
from agentkernel.pydanticai import PydanticAIModule

agent = Agent(
    model="openai:gpt-4o-mini",
    name="assistant",
    description="A helpful assistant.",
    instructions="You are a helpful assistant.",
)

PydanticAIModule([agent])

if __name__ == "__main__":
    CLI.main()
```

:::warning name= and description= are both required in practice
- **`name=` is mandatory.** Pydantic AI infers an agent's name lazily from the call frame on first
  run, but Agent Kernel registers agents by name *immediately* at load time — before any run. A
  Pydantic AI agent without an explicit `name=` therefore reaches registration with `name is None`,
  and `PydanticAIModule` raises a `ValueError`. Always pass `name=`.
- **`description=` should be set.** Unlike the OpenAI adapter (where `instructions` is effectively
  mandatory and doubles as the description), Pydantic AI's `description` is an optional, separate
  field — and it is what Agent Kernel reports as the agent's description and A2A card summary. When
  `description=` is unset, Agent Kernel falls back to the agent's static `instructions=` on a
  best-effort basis (Pydantic AI has no public getter for instructions, so this reads a private
  attribute and degrades to an empty string if that attribute changes in a future release). Setting
  `description=` explicitly is the reliable path; an agent with neither yields an empty description,
  not an error.
:::

## Multi-Agent System

Pydantic AI has no built-in `handoffs=` primitive. Route between agents with
**delegation-via-tool**: give a triage agent a tool that runs the specialist agent and returns its
output.

```python
from pydantic_ai import Agent
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder

MODEL = "openai:gpt-4o-mini"

math_agent = Agent(model=MODEL, name="math", description="Specialist for math problems",
                   instructions="You solve math problems.")
general_agent = Agent(model=MODEL, name="general", description="Agent for general questions",
                      instructions="You provide general assistance.")


async def ask_math(question: str) -> str:
    """Delegate a math question to the math specialist."""
    return str((await math_agent.run(question)).output)


async def ask_general(question: str) -> str:
    """Delegate a general question to the general agent."""
    return str((await general_agent.run(question)).output)


triage_agent = Agent(
    model=MODEL,
    name="triage",
    description="Routes each question to the right specialist",
    instructions="Call ask_math for math questions and ask_general for everything else. "
    "Return the specialist's answer directly.",
    tools=PydanticAIToolBuilder.bind([ask_math, ask_general]),
)

PydanticAIModule([triage_agent, math_agent, general_agent])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...        # or the key for whichever provider your model string names
```

Pydantic AI resolves the provider **eagerly, at `Agent(...)` construction** — so the relevant
provider key must be set in the environment when your module is imported, not just when a run
happens. (This differs from the OpenAI Agents SDK, which defers the credential check to run time.)

## Tool Binding

Use `PydanticAIToolBuilder` to bind plain Python functions as tools:

```python
from pydantic_ai import Agent
from agentkernel.pydanticai import PydanticAIModule, PydanticAIToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = Agent(
    model="openai:gpt-4o-mini",
    name="weather",
    description="Provides weather information.",
    instructions="You provide weather information.",
    tools=PydanticAIToolBuilder.bind([get_weather]),
)

PydanticAIModule([agent])
```

Tools bound this way reach execution context (session, agent, requests) through `ToolContext.get()` —
the same portable mechanism as every other adapter, so a tool function bound here also works unchanged
on any other framework. Agent Kernel does not require `deps_type`/`RunContext` for its own tools;
`deps` carries the per-run [framework context](#per-run-contextstate) instead, which your **native**
Pydantic AI tools can read. See [Tools](../core-concepts/tools) for the full guide.

## Structured Output

Configure structured output with Pydantic AI's `output_type` parameter. Agent Kernel detects the
structured result and returns an `AgentReplyAny` whose `content` is the result as a dict; no
re-parsing of text needed:

```python
from pydantic_ai import Agent
from pydantic import BaseModel
from agentkernel.pydanticai import PydanticAIModule

class CalendarEvent(BaseModel):
    name: str
    date: str

agent = Agent(
    model="openai:gpt-4o-mini",
    name="extractor",
    description="Extracts calendar events from text.",
    output_type=CalendarEvent,
)

PydanticAIModule([agent])
```

Pydantic results are converted via `model_dump()`, and `str(reply)` returns the JSON-serialized
content, so text-based consumers (chat integrations, logging) work unchanged. See
[Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced,
and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Structured output and streaming now agree
This used to be a limitation: the older `run_stream()` treated the **first `output_type` match** as the
final output, so combining `output_type` with streaming truncated differently from the non-streaming
path. The adapter now drives `run_stream_events()`, which wraps Pydantic AI's own `run()` — so a
streamed run and a synchronous one produce the same structured output. Plain-text streaming is
unaffected; it emits `TextDelta` events as usual.
:::

## Per-run context/state

Pydantic AI has **full round-trip** fidelity for the reserved
[`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key. It is
injected as the run's **`deps`** (`agent.run(..., deps=...)` and `agent.run_stream(..., deps=...)`),
which native tools, instruction functions and output validators read and mutate in place via
`RunContext.deps`; the mutated object is written back to the session after a successful run, so every
key — including ones a tool adds mid-run — survives to the next turn.

```python
from pydantic_ai import Agent, RunContext

agent = Agent(model="openai:gpt-4o-mini", name="shop", deps_type=dict)

@agent.tool
def add_to_cart(ctx: RunContext[dict], item: str) -> str:
    """Native Pydantic AI tool: reads and writes the per-run context via ctx.deps."""
    ctx.deps.setdefault("cart", []).append(item)
    return f"Added {item}"
```

Two caveats:

- **`deps` is not validated at runtime.** Pydantic AI deliberately does not type-check `deps` against
  `deps_type`, so an agent declaring `deps_type=MyDeps` receives the context **dict** without error. A
  tool doing `ctx.deps.some_field` fails at tool-call time — as it already did against the previous
  `deps=None` default. Annotate `deps_type=dict` (as above) when you use the framework context.
- **`agent.override(deps=...)` wins.** Pydantic AI resolves an active override ahead of the `deps=`
  argument, so inside an override block the framework context never reaches your tools and the
  write-back stores the unmutated copy.

Agent Kernel owns the `deps` slot: it exposes no way for application code to pass its own `deps`, so
this injection cannot displace a caller-supplied value.

## Features

- ✅ Function calling
- ✅ Multi-agent delegation (delegation-via-tool; no `handoffs=` primitive)
- ✅ Per-run context/state (`framework_context` → `deps`, full round-trip)
- ✅ Streaming responses (native token streaming)
- ✅ Structured output (`output_type` → `AgentReplyAny`)
- ✅ Session management (message history persisted per session)
- ✅ Framework-agnostic tool binding
- ✅ Native multi-provider support (`FallbackModel` for failover)

## Example

See [examples/cli/pydanticai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/pydanticai)
for a complete triage/math/weather delegation-via-tool example.

For per-run context/state carried across turns, see
[examples/cli/pydanticai_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/pydanticai_context)
— a cart kept in the framework context, mutated by native `RunContext` tools alongside an Agent Kernel
tool that uses `ToolContext`, so the two tool styles are shown side by side.
