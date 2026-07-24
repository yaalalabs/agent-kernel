---
sidebar_position: 6
---

# Smolagents

Integrate Hugging Face Smolagents with Agent Kernel.

## Installation

```bash
pip install agentkernel[smolagents]
```

## Basic Usage

```python
from smolagents import LiteLLMModel, ToolCallingAgent
from agentkernel.cli import CLI
from agentkernel.smolagents import SmolagentsModule

model = LiteLLMModel(model_id="openai/gpt-4o")

agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="assistant",
    description="You are a helpful AI assistant.",
)

SmolagentsModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent Setup

```python
from smolagents import LiteLLMModel, ToolCallingAgent
from agentkernel.smolagents import SmolagentsModule

model = LiteLLMModel(model_id="openai/gpt-4o")

general_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="general",
    description="General assistant for broad user questions.",
)

math_agent = ToolCallingAgent(
    tools=[],
    model=model,
    name="math",
    description="Specialist agent for math questions.",
)

SmolagentsModule([general_agent, math_agent])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...
```

If you use another LiteLLM provider, set its credentials instead.

## Tool Binding

Use `SmolagentsToolBuilder` to bind plain Python functions as tools to your Smolagents agents:

```python
from smolagents import LiteLLMModel, ToolCallingAgent
from agentkernel.smolagents import SmolagentsModule, SmolagentsToolBuilder

def get_weather(city: str) -> str:
    """Returns the weather for a given city."""
    return f"Weather in {city}: sunny, 25C"

model = LiteLLMModel(model_id="openai/gpt-4o")

agent = ToolCallingAgent(
    tools=SmolagentsToolBuilder.bind([get_weather]),
    model=model,
    name="weather",
    description="Use the get_weather tool for weather questions.",
)

SmolagentsModule([agent])
```

See [Tools](../core-concepts/tools) for the full guide on writing and binding tools.

## Structured Output

SmolAgents has no first-class schema parameter; the agent returns whatever value is passed to `final_answer`. Agent Kernel detects the value's type: a dict or Pydantic instance is returned as an `AgentReplyAny` whose `content` is the result as a dict; anything else is stringified into an `AgentReplyText` as before:

```python
from smolagents import CodeAgent
from agentkernel.smolagents import SmolagentsModule

agent = CodeAgent(
    tools=[],
    model=model,
    name="classifier",
    description="Classify the input and return a dict: {\"verdict\": ..., \"confidence\": ...}",
)

SmolagentsModule([agent])
```

Pydantic results are converted via `model_dump()`, and `str(reply)` returns the JSON-serialized content, so text-based consumers work unchanged. See [Reply Types](../core-concepts/runner#structured-replies) for how structured replies are surfaced, and [Execution Hooks](../integrations/hooks#structured-replies-in-hooks) for how hooks receive them.

:::info Streaming limitation
Structured output applies to non-streaming execution only. (SmolAgents does not support streaming in Agent Kernel.)
:::

## Per-run context/state

Smolagents **round-trips a filtered subset** of the reserved [`framework_context`](../core-concepts/session.md#framework-context--per-run-state) session key. It is injected as `agent.run(..., additional_args=...)`; on write-back the runner reads `agent.state` but keeps **only the keys you pre-seeded** (framework-internal entries have no clean prefix to filter on). Consequence: a tool that mutates a **pre-seeded** key round-trips, but a tool that adds a **brand-new** key has it silently dropped — pre-seed every key you intend to write.

## Features

- ✅ ToolCalling and CodeAgent support
- ✅ Managed agent delegation
- ✅ Session management via Agent Kernel runtime
- ✅ Framework-agnostic tool binding
- ✅ Structured output (dict / Pydantic `final_answer` → `AgentReplyAny`)

## Example

See [examples/cli/smolagents](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/smolagents) for complete examples.
