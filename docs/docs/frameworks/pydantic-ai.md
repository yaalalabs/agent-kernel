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

Tools reach execution context (session, agent, requests) through `ToolContext.get()` — the same
portable mechanism as every other adapter. Agent Kernel does **not** use Pydantic AI's
`deps_type`/`RunContext` dependency injection, so a tool function bound here also works unchanged on
any other framework. See [Tools](../core-concepts/tools) for the full guide.

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

:::info Streaming limitation
Structured output applies to non-streaming execution only. In Agent Kernel's streaming mode a
Pydantic AI run stops at the **first `output_type` match** and ends the run, so combining
`output_type` with streaming truncates differently than the non-streaming path. Plain text
streaming (the common case) is unaffected — it emits token-by-token deltas as usual.
:::

## Features

- ✅ Function calling
- ✅ Multi-agent delegation (delegation-via-tool; no `handoffs=` primitive)
- ✅ Streaming responses (native token streaming)
- ✅ Structured output (`output_type` → `AgentReplyAny`)
- ✅ Session management (message history persisted per session)
- ✅ Framework-agnostic tool binding
- ✅ Native multi-provider support (`FallbackModel` for failover)

## Example

See [examples/cli/pydanticai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/pydanticai)
for a complete triage/math/weather delegation-via-tool example.
