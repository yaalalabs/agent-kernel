# Agent Kernel Python Distribution

This directory contains Agent Kernel's code. This follows a [uv](https://docs.astral.sh/uv/) based monorepo structure.

## Monorepo Structure

The monorepo consists of three main components:

1. **common** - Common library used by other components
   - Provides utility functions and shared functionality
   - Located in `ak-py/common/`

2. **core** - Agent core wrapper functions
   - Exposes functionality for agent logic developers
   - Depends on the common library
   - Located in `ak-py/core/`

3. **logic** - Agent logic implementation
   - Contains agent logic code written using common and core
   - Depends on both common and core libraries
   - Located in `ak-py/logic/`

## Development Setup

### Requirements

- Python 3.12 or higher
- uv package manager

To set up the development environment:

```bash
# Install uv if you don't have it already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create and activate a virtual environment (uses Python 3.12 by default)
uv venv

# Install all components in development mode
cd ak-py
uv pip install -e common/ -e core/ -e logic/
```

## Usage

### Using the Common Library

```python
from ak_common.utils import Logger

logger = Logger("MyApp")
logger.info("Hello from the common library!")
```

### Using the Core Library

```python
from ak_core.agent import Agent, AgentFactory

# Create an agent
agent = AgentFactory.create_agent("basic", "my_agent", {"key": "value"})

# Execute the agent
result = agent.execute("Hello, agent!")
print(result)
```

### Using the Logic Library

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

## Building and Distribution

To build the packages for distribution:

```bash
# Build the common package
cd ak-py/common
uv pip build

# Build the core package
cd ../core
uv pip build

# Build the logic package
cd ../logic
uv pip build
```

The built packages will be available in the `dist/` directory of each component.
