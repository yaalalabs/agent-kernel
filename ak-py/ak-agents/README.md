# Agent Kernel Logic Library

This package provides agent logic implementations for the Agent Kernel framework. It builds on the core and common components to create specialized agents and orchestration mechanisms.

## Features

- Specialized agent implementations (AssistantAgent, ResearchAgent)
- AgentOrchestrator for coordinating multiple agents in complex workflows
- Ready-to-use agent logic for common AI tasks

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