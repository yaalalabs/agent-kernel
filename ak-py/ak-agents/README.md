# Agent Kernel Logic Library

This package provides agent logic implementations for the Agent Kernel framework. It builds on the core and common components to create specialized agents and orchestration mechanisms.

## Features

- Specialized agent implementations (AssistantAgent, ResearchAgent)
- AgentOrchestrator for coordinating multiple agents in complex workflows
- Ready-to-use agent logic for common AI tasks

## Installation

### From Source

```bash
cd ak-py/logic
uv pip install -e .
```

### As a Dependency

In your pyproject.toml:

```toml
dependencies = [
    "ak_common==0.1.0",
    "ak_core==0.1.0",
    "ak_logic==0.1.0",
]
```

## Usage

### Using Specialized Agents

```python
from ak_logic.implementation import AssistantAgent, ResearchAgent

# Create an assistant agent
assistant = AssistantAgent("my_assistant", {"key": "value"})
assistant_result = assistant.execute("How can you help me?")
print(assistant_result)

# Create a research agent
researcher = ResearchAgent("my_researcher", {"key": "value"})
research_result = researcher.execute("Find information about AI agents")
print(research_result)
```

### Using the Agent Orchestrator

```python
from ak_logic.implementation import AssistantAgent, ResearchAgent, AgentOrchestrator

# Create an orchestrator
orchestrator = AgentOrchestrator("my_orchestrator")

# Add agents to the orchestrator
assistant = AssistantAgent("assistant", {"key": "value"})
researcher = ResearchAgent("researcher", {"key": "value"})
orchestrator.add_agent(assistant)
orchestrator.add_agent(researcher)

# Execute a workflow
result = orchestrator.execute_workflow("Find information about AI agents")
print(result)
```

### Creating a Custom Workflow

```python
from ak_logic.implementation import AssistantAgent, ResearchAgent, AgentOrchestrator
from typing import Any, Dict

# Create specialized agents
assistant = AssistantAgent("assistant", {"key": "value"})
researcher = ResearchAgent("researcher", {"key": "value"})

# Create an orchestrator
orchestrator = AgentOrchestrator("custom_workflow")
orchestrator.add_agent(researcher)
orchestrator.add_agent(assistant)

# Define a custom workflow function
def custom_workflow(query: str) -> Dict[str, Any]:
    # First, get research results
    research_results = researcher.execute(query)
    
    # Then, have the assistant process the research results
    assistant_input = {
        "query": query,
        "research": research_results
    }
    assistant_results = assistant.execute(assistant_input)
    
    # Return the combined results
    return {
        "query": query,
        "research": research_results,
        "assistant": assistant_results,
        "summary": "Workflow completed successfully"
    }

# Execute the custom workflow
result = custom_workflow("What are the latest advancements in AI?")
print(result)
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