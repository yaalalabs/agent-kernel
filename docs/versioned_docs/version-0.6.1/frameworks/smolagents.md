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

## Features

- ✅ ToolCalling and CodeAgent support
- ✅ Managed agent delegation
- ✅ Session management via Agent Kernel runtime
- ✅ Framework-agnostic tool binding

## Example

See [examples/cli/smolagents](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/smolagents) for complete examples.
