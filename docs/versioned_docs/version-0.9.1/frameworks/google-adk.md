---
sidebar_position: 5
---

# Google ADK

Integrate Google's Agent Development Kit with Agent Kernel.

## Installation

```bash
pip install agentkernel[adk]
```

## Basic Usage

```python
from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import GoogleADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

GoogleADKModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent System

```python
from adk import Agent as ADKAgent
from agentkernel.adk import GoogleADKModule

general_agent = ADKAgent(
    name="general",
    model="gemini-2.0-flash-exp",
    instructions="You handle general queries",
)

specialist_agent = ADKAgent(
    name="specialist",
    model="gemini-2.0-flash-exp",
    instructions="You handle specialized queries",
)

GoogleADKModule([general_agent, specialist_agent])
```

## Configuration

```bash
export GOOGLE_API_KEY=...
export GEMINI_MODEL=gemini-2.0-flash-exp  # Optional
```

## Tool Binding

Use `GoogleADKToolBuilder` to bind plain Python functions as tools to your Google ADK agents:

```python
from google.adk.agents import Agent as ADKAgent
from agentkernel.adk import GoogleADKModule, GoogleADKToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25°C"

agent = ADKAgent(
    name="weather",
    model="gemini-2.0-flash-exp",
    description="You provide weather information upon request",
    instruction="Use the get_weather tool for weather-related questions.",
    tools=GoogleADKToolBuilder.bind([get_weather]),
)

GoogleADKModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

Configure structured output with ADK's `output_schema` parameter on `LlmAgent`. ADK returns the final response as a JSON string conforming to the schema; Agent Kernel validates and parses it, returning an `AgentReplyAny` whose `content` is the result as a dict:

```python
from google.adk.agents import LlmAgent
from pydantic import BaseModel
from agentkernel.adk import GoogleADKModule

class CapitalOutput(BaseModel):
    country: str
    capital: str

agent = LlmAgent(
    name="capitals",
    model="gemini-2.0-flash",
    instruction="Answer with the country and its capital.",
    output_schema=CapitalOutput,
)

GoogleADKModule([agent])
```

If the model's reply does not validate against the schema, the runner logs a warning and falls back to a plain `AgentReplyText` with the raw text. `str(reply)` on an `AgentReplyAny` returns the JSON-serialized content, so text-based consumers work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. Streamed runs emit typed [`StreamEvent`](../core-concepts/runner#streaming-execution)s — `TextDelta` for assistant prose, plus `ReasoningStart`/`ReasoningDelta`/`ReasoningEnd` and `ToolCallStart`/`ToolCallArgs`/`ToolCallEnd`/`ToolCallResult` — not just plain text deltas.
:::

## Per-run context/state

Google ADK **round-trips all caller keys** of the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key **except AK-internal ones**. It is merged into the ADK session `state` on input (the internal `ak_tool_context` key is written last, so a caller key of that name cannot displace it); on write-back the accumulated state is read back with `ak_tool_context` and ADK's `app:`/`user:`/`temp:`-prefixed keys stripped — the first two are app- and user-scoped values ADK merges in on read, the third is invocation-scoped, and none are per-session caller state. Because the rest of the state is returned whole, keys a tool **adds** during the run survive to the next turn. ADK's native state is in-memory only, so this write-back is what gives the context cross-turn durability.

Two consequences of reading the state back wholesale:

- **The state is accumulate-only.** ADK keeps every key written to a session for that session's lifetime, so removing a key from `framework_context` does not remove it from ADK — it reappears on the next write-back. To clear a value on ADK, overwrite it (e.g. set it to `None` or `[]`) rather than deleting the key.
- **Agent-written state round-trips too.** A value an agent writes itself — most commonly `LlmAgent(output_key="...")`, which stores the agent's response in the state — is indistinguishable from a key a tool wrote, so it also lands in `framework_context`. Expect the stored context on ADK to hold more than what your tools put there.

## Features

- ✅ Gemini models
- ✅ Google Cloud integration
- ✅ Function calling
- ✅ Multi-agent coordination
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`output_schema` → `AgentReplyAny`)

## Example

See [examples/cli/adk](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk) for complete examples.

For per-run context/state carried across turns, see [examples/cli/adk_context](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk_context) (a cart kept in `framework_context`, written through `tool_context.state`, with a tool-added key demonstrating ADK's full read-back).
