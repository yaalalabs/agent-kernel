---
sidebar_position: 2
---

# OpenAI Agents SDK

Integrate OpenAI's official Agents SDK with Agent Kernel.

## Installation

```bash
pip install agentkernel[openai]
```

## Basic Usage

```python
from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent System

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule

# Define agents with handoff capabilities
general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide general assistance.",
)

math_agent = OpenAIAgent(
    name="math",
    handoff_description="Specialist for math problems",
    instructions="You solve math problems.",
)

OpenAIModule([general_agent, math_agent])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_MODEL=gpt-4  # Optional, override default
```

## Tool Binding

Use `OpenAIToolBuilder` to bind plain Python functions as tools to your OpenAI agents:

```python
from agents import Agent as OpenAIAgent
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = OpenAIAgent(
    name="weather",
    instructions="You provide weather information.",
    tools=OpenAIToolBuilder.bind([get_weather]),
)

OpenAIModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

Configure structured output with the OpenAI Agents SDK's `output_type` parameter. Agent Kernel detects the structured result and returns an `AgentReplyAny` whose `content` is the result as a dict; no re-parsing of text needed:

```python
from agents import Agent as OpenAIAgent
from pydantic import BaseModel
from agentkernel.openai import OpenAIModule

class CalendarEvent(BaseModel):
    name: str
    date: str

agent = OpenAIAgent(
    name="extractor",
    instructions="Extract the calendar event from the text.",
    output_type=CalendarEvent,
)

OpenAIModule([agent])
```

Pydantic results are converted via `model_dump()`, and `str(reply)` returns the JSON-serialized content, so text-based consumers (chat integrations, logging) work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. Streamed runs emit typed [`StreamEvent`](../core-concepts/runner#streaming-execution)s — `TextDelta` for assistant prose, plus `ReasoningStart`/`ReasoningDelta`/`ReasoningEnd` and `ToolCallStart`/`ToolCallArgs`/`ToolCallEnd`/`ToolCallResult` — not just plain text deltas.
:::

## Per-run context/state

OpenAI has **full round-trip** fidelity for the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key. It is injected as the OpenAI Agents SDK run **context** (`Runner.run(..., context=...)`), which tools read and mutate in place via `RunContextWrapper.context`; the mutated object is written back to the session after a successful run, so every key — including ones a tool adds mid-run — survives to the next turn.

## Features

- ✅ Function calling
- ✅ Multi-agent handoff
- ✅ Streaming responses
- ✅ Structured output (`output_type` → `AgentReplyAny`)
- ✅ Session management
- ✅ Framework-agnostic tool binding

## Example

See [examples/cli/openai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai) for complete examples.

For structured output, see [examples/cli/openai_structured](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_structured) and [examples/api/openai_structured](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/api/openai_structured) (REST API + post-execution hook).

For per-run context/state carried across turns, see [examples/cli/openai_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai_context) (a cart kept in `framework_context`, seeded by a pre-hook and round-tripped by the runner).
