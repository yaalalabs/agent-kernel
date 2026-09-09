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

## Features

- ✅ Function calling
- ✅ Multi-agent handoff
- ✅ Streaming responses
- ✅ Session management
- ✅ Framework-agnostic tool binding

## Example

See [examples/cli/openai](https://github.com/yaalalabs/agent-kernel/tree/develop/examples/cli/openai) for complete examples.
