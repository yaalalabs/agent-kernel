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
from agentkernel.adk import ADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent System

```python
from adk import Agent as ADKAgent
from agentkernel.adk import ADKModule

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

ADKModule([general_agent, specialist_agent])
```

## Configuration

```bash
export GOOGLE_API_KEY=...
export GEMINI_MODEL=gemini-2.0-flash-exp  # Optional
```

## Features

- ✅ Gemini models
- ✅ Google Cloud integration
- ✅ Function calling
- ✅ Multi-agent coordination
- ✅ Streaming

## Example

See [examples/cli/adk](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/adk) for complete examples.
