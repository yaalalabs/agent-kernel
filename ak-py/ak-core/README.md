# Agent Kernel Core Library

This package provides core agent wrapper functions for the Agent Kernel framework. It is designed to be used by agent logic developers to create and manage AI agents.

## Features

- Base Agent class for creating custom agents
- AgentFactory for creating different types of agents
- AgentTeam for managing collections of agents that collaborate

## Installation

### From Source

```bash
cd ak-py/core
uv pip install -e .
```

### As a Dependency

In your pyproject.toml:

```toml
dependencies = [
    "ak_common==0.1.0",
    "ak_core==0.1.0",
]
```

## Usage

### Creating and Using an Agent

```python
from ak_core.agent import Agent, AgentFactory

# Create an agent using the factory
agent = AgentFactory.create_agent("basic", "my_agent", {"key": "value"})

# Execute the agent
result = agent.execute("Hello, agent!")
print(result)
```

### Creating a Custom Agent

```python
from ak_core.agent import Agent
from typing import Any, Dict

class MyCustomAgent(Agent):
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        # Custom initialization
        
    def execute(self, input_data: Any) -> Any:
        # Custom execution logic
        self.logger.info(f"Executing custom agent {self.name}")
        return {
            "status": "success",
            "agent": self.name,
            "type": "custom",
            "input": input_data,
            "result": "Custom processing result"
        }
```

### Working with Agent Teams

```python
from ak_core.agent import Agent, AgentTeam

# Create some agents
agent1 = Agent("agent1", {"key": "value"})
agent2 = Agent("agent2", {"key": "value"})

# Create a team
team = AgentTeam("my_team")
team.add_agent(agent1)
team.add_agent(agent2)

# Execute all agents in the team
results = team.execute("Team input data")
print(results)
```

## Development

To set up the development environment:

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Format code
black .
isort .

# Type check
mypy .
```