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
Structured output applies to non-streaming execution only. Streamed runs emit token-by-token text deltas.
:::

## Features

- ✅ Gemini models
- ✅ Google Cloud integration
- ✅ Function calling
- ✅ Multi-agent coordination
- ✅ Framework-agnostic tool binding
- ✅ Structured output (`output_schema` → `AgentReplyAny`)

## Example

See [examples/cli/adk](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/adk) for complete examples.
