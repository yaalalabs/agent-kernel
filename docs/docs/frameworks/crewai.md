---
sidebar_position: 3
---

# CrewAI

Integrate CrewAI's role-based agent framework with Agent Kernel.

## Installation

```bash
pip install agentkernel[crewai]
```

## Basic Usage

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
    role="assistant",
    goal="Help users with their questions",
    backstory="You are a helpful AI assistant",
    verbose=False,
)

module = CrewAIModule([agent])

if __name__ == "__main__":
    CLI.main()
```

## Multi-Agent Crew

```python
from crewai import Agent as CrewAgent, Task, Crew
from agentkernel.crewai import CrewAIModule

researcher = CrewAgent(
    role="researcher",
    goal="Research topics thoroughly",
    backstory="You are an expert researcher",
    verbose=False,
)

writer = CrewAgent(
    role="writer",
    goal="Write clear content",
    backstory="You are a skilled writer",
    verbose=False,
)

module = CrewAIModule([researcher, writer])
```

## Configuration

```bash
export OPENAI_API_KEY=sk-...  # CrewAI uses OpenAI by default
```

## Features

- ✅ Role-based agents
- ✅ Task delegation
- ✅ Sequential execution
- ✅ Hierarchical teams
- ✅ Custom tools

## Example

See [examples/cli/crewai](https://github.com/yaalalabs/agent-kernel/tree/main/examples/cli/crewai) for complete examples.
