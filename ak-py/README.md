# Agent Kernel

[![PyPI version](https://badge.fury.io/py/agentkernel.svg)](https://badge.fury.io/py/agentkernel)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Agent Kernel is a lightweight runtime and adapter layer for building and running AI agents across multiple frameworks with a unified API. Write your agent logic once and run it under different frameworks via thin adapters.

## Features

- **Unified API**: Common abstractions (Agent, Runner, Session, Module, Runtime) across frameworks
- **Multi-Framework Support**: OpenAI Agents SDK, CrewAI, LangGraph, Google ADK
- **Session Management**: Built-in session abstraction for conversational state
- **Flexible Deployment**: Interactive CLI for local development and testing, AWS Lambda handler for serverless deployment, AWS ECS Fargate deployment
- **Pluggable Architecture**: Easy to extend with custom framework adapters
- **MCP Server**: Built-in Model Context Protocol server for exposing agents as MCP tools and exposing any custom tool
- **A2A Server**: Built-in Agent-to-Agent communication server for exposing agents with a simple configuration change
- **REST API**: Built-in REST API server for agent interaction
- **Test Automation**: Built-in test suite for testing agents

## Installation

```bash
pip install agentkernel
```

**Requirements:**
- Python 3.12+

## Quick Start

### Basic Concepts

- **Agent**: Framework-specific agent wrapped by an Agent Kernel adapter
- **Runner**: Framework-specific execution strategy
- **Session**: Shared state across conversation turns
- **Module**: Container that registers agents with the Runtime
- **Runtime**: Global registry and orchestrator for agents

### CrewAI Example

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

general_agent = CrewAgent(
    role="general",
    goal="Agent for general questions",
    backstory="You provide assistance with general queries. Give direct and short answers",
    verbose=False,
)

math_agent = CrewAgent(
    role="math",
    goal="Specialist agent for math questions",
    backstory="You provide help with math problems. Explain your reasoning at each step and include examples. \
        If prompted for anything else you refuse to answer.",
    verbose=False,
)

# Register agents with Agent Kernel
module = CrewAIModule([general_agent, math_agent])

if __name__ == "__main__":
    CLI.main()
```

### LangGraph Example

```python
from langgraph.graph import StateGraph
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

# Build and compile your graph
sg = StateGraph(...)
compiled = sg.compile()
compiled.name = "assistant"

module = LangGraphModule([compiled])

if __name__ == "__main__":
    CLI.main()
```

### OpenAI Agents SDK Example

```python
from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

general_agent = OpenAIAgent(
    name="general",
    handoff_description="Agent for general questions",
    instructions="You provide assistance with general queries. Give short and direct answers.",
)

module = OpenAIModule([general_agent])

if __name__ == "__main__":
    CLI.main()
```

### Google ADK Example

```python
from google.adk.agents import Agent
from agentkernel.cli import CLI
from agentkernel.adk import GoogleADKModule
from google.adk.models.lite_llm import LiteLlm

# Create Google ADK agents
math_agent = Agent(
    name="math",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    description="Specialist agent for math questions",
    instruction="""
    You provide help with math problems.
    Explain your reasoning at each step and include examples.
    If prompted for anything else you refuse to answer.
    """,
)

module = GoogleADKModule([math_agent])

if __name__ == "__main__":
    CLI.main()
```

## Interactive CLI

Agent Kernel includes an interactive CLI for local development and testing.

**Available Commands:**
- `!h`, `!help` — Show help
- `!ld`, `!load <module_name>` — Load a Python module containing agents
- `!ls`, `!list` — List registered agents
- `!s`, `!select <agent_name>` — Select an agent
- `!n`, `!new` — Start a new session
- `!q`, `!quit` — Exit

**Usage:**

```bash
python demo.py
```

Then interact with your agents:

```text
(assistant) >> !load my_agents
(assistant) >> !select researcher
(researcher) >> What is the latest news on AI?
```

## AWS Lambda Deployment

Deploy your agents as serverless functions using the built-in Lambda handler.

```python
from openai import OpenAI
from agents import Agent as OpenAIAgent
from agentkernel.aws import Lambda
from agentkernel.openai import OpenAIModule

client = OpenAI()
assistant = OpenAIAgent(name="assistant")

module = OpenAIModule([assistant])
handler = Lambda.handler
```

**Request Format:**

```json
{
  "prompt": "Hello agent",
  "agent": "assistant"
}
```

**Response Format:**

```json
{
  "result": "Agent response here"
}
```

**Status Codes:**
- `200` — Success
- `400` — No agent available
- `500` — Unexpected error

## Configuration

Agent Kernel can be configured via environment variables, `.env` files, or YAML/JSON configuration files.

### Configuration Precedence

Values are loaded in the following order (highest precedence first):
1. Environment variables (including variables from `.env` file)
2. Configuration file (YAML or JSON)
3. Built-in defaults

### Configuration File

By default, Agent Kernel looks for `./config.yaml` in the current working directory.

**Override the config file path:**

```bash
export AK_CONFIG_PATH_OVERRIDE=config.json
# or
export AK_CONFIG_PATH_OVERRIDE=conf/agent-kernel.yaml
```

Supported formats: `.yaml`, `.yml`, `.json`

### Configuration Options

#### Debug Mode

- **Field**: `debug`
- **Type**: boolean
- **Default**: `false`
- **Description**: Enable debug mode across the library
- **Environment Variable**: `AK_DEBUG`

#### Session Store

Configure where agent sessions are stored.

- **Field**: `session.type`
- **Type**: string
- **Options**: `in_memory`, `redis`
- **Default**: `in_memory`
- **Environment Variable**: `AK_SESSION_TYPE`

##### Redis Configuration

Required when `session.type=redis`:

- **URL**
  - **Field**: `session.redis.url`
  - **Default**: `redis://localhost:6379`
  - **Description**: Redis connection URL. Use `rediss://` for SSL
  - **Environment Variable**: `AK_SESSION_REDIS_URL`

- **TTL (Time to Live)**
  - **Field**: `session.redis.ttl`
  - **Default**: `604800` (7 days)
  - **Description**: Session TTL in seconds
  - **Environment Variable**: `AK_SESSION_REDIS_TTL`

- **Key Prefix**
  - **Field**: `session.redis.prefix`
  - **Default**: `ak:sessions:`
  - **Description**: Key prefix for session storage
  - **Environment Variable**: `AK_SESSION_REDIS_PREFIX`

#### API Configuration

Configure the REST API server (if using the API module).

- **Host**
  - **Field**: `api.host`
  - **Default**: `0.0.0.0`
  - **Environment Variable**: `AK_API_HOST`

- **Port**
  - **Field**: `api.port`
  - **Default**: `8000`
  - **Environment Variable**: `AK_API_PORT`

- **Enabled Routes**
  - **Field**: `api.enabled_routes.agents`
  - **Default**: `true`
  - **Description**: Enable agent interaction routes
  - **Environment Variable**: `AK_API_ENABLED_ROUTES_AGENTS`

#### A2A (Agent-to-Agent) Configuration

- **Enabled**
  - **Field**: `a2a.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_A2A_ENABLED`

- **Agents**
  - **Field**: `a2a.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to enable A2A (use `["*"]` for all)
  - **Environment Variable**: `AK_A2A_AGENTS` (comma-separated)

- **URL**
  - **Field**: `a2a.url`
  - **Default**: `http://localhost:8000/a2a`
  - **Environment Variable**: `AK_A2A_URL`

- **Task Store Type**
  - **Field**: `a2a.task_store_type`
  - **Options**: `in_memory`, `redis`
  - **Default**: `in_memory`
  - **Environment Variable**: `AK_A2A_TASK_STORE_TYPE`

#### MCP (Model Context Protocol) Configuration

- **Enabled**
  - **Field**: `mcp.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_MCP_ENABLED`

- **Expose Agents**
  - **Field**: `mcp.expose_agents`
  - **Default**: `false`
  - **Description**: Expose agents as MCP tools
  - **Environment Variable**: `AK_MCP_EXPOSE_AGENTS`

- **Agents**
  - **Field**: `mcp.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to expose as MCP tools
  - **Environment Variable**: `AK_MCP_AGENTS` (comma-separated)

- **URL**
  - **Field**: `mcp.url`
  - **Default**: `http://localhost:8000/mcp`
  - **Environment Variable**: `AK_MCP_URL`

### Configuration Examples

#### Environment Variables

Use the `AK_` prefix and underscores for nested fields:

```bash
export AK_DEBUG=true
export AK_SESSION_TYPE=redis
export AK_SESSION_REDIS_URL=redis://localhost:6379
export AK_SESSION_REDIS_TTL=604800
export AK_SESSION_REDIS_PREFIX=ak:sessions:
export AK_API_HOST=0.0.0.0
export AK_API_PORT=8000
export AK_A2A_ENABLED=true
export AK_MCP_ENABLED=false
```

#### .env File

Create a `.env` file in your working directory:

```env
AK_DEBUG=false
AK_SESSION_TYPE=redis
AK_SESSION_REDIS_URL=rediss://my-redis:6379
AK_SESSION_REDIS_TTL=1209600
AK_SESSION_REDIS_PREFIX=ak:prod:sessions:
AK_API_HOST=0.0.0.0
AK_API_PORT=8080
AK_A2A_ENABLED=true
AK_A2A_URL=http://localhost:8080/a2a
```

#### config.yaml

```yaml
debug: false
session:
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 604800
    prefix: "ak:sessions:"
api:
  host: 0.0.0.0
  port: 8000
  enabled_routes:
    agents: true
a2a:
  enabled: true
  agents: ["*"]
  url: http://localhost:8000/a2a
  task_store_type: in_memory
mcp:
  enabled: false
  expose_agents: false
  agents: ["*"]
  url: http://localhost:8000/mcp
```

#### config.json

```json
{
  "debug": false,
  "session": {
    "type": "redis",
    "redis": {
      "url": "redis://localhost:6379",
      "ttl": 604800,
      "prefix": "ak:sessions:"
    }
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "enabled_routes": {
      "agents": true
    }
  },
  "a2a": {
    "enabled": true,
    "agents": ["*"],
    "url": "http://localhost:8000/a2a",
    "task_store_type": "in_memory"
  },
  "mcp": {
    "enabled": false,
    "expose_agents": false,
    "agents": ["*"],
    "url": "http://localhost:8000/mcp"
  }
}
```

### Configuration Notes

- Empty environment variables are ignored
- Unknown fields in files or environment variables are ignored
- Environment variables override configuration file values
- Configuration file values override built-in defaults
- Nested fields use underscore (`_`) delimiter in environment variables

## Extensibility

### Custom Framework Adapters

To add support for a new framework:

1. Implement a `Runner` class for your framework
2. Create an `Agent` wrapper class
3. Create a `Module` class that registers agents with the Runtime

Example structure:

```python
from agentkernel.core import Agent, Runner, Module

class MyFrameworkRunner(Runner):
    def run(self, agent, prompt, session):
        # Implement framework-specific execution
        pass

class MyFrameworkAgent(Agent):
    def __init__(self, native_agent):
        self.native_agent = native_agent
        self.runner = MyFrameworkRunner()

class MyFrameworkModule(Module):
    def __init__(self, agents):
        super().__init__()
        for agent in agents:
            wrapped = MyFrameworkAgent(agent)
            self.register(wrapped)
```

### Session Management

Sessions maintain state across agent interactions. Framework adapters manage their own session storage within the Session object using namespaced keys:

- `"crewai"` — CrewAI session data
- `"langgraph"` — LangGraph session data
- `"openai"` — OpenAI Agents SDK session data
- `"adk"` — Google ADK session data

Access the session in your runner:

```python
def run(self, agent, prompt, session):
    # Get framework-specific data
    my_data = session.get("my_framework", {})
    
    # Process and update data
    my_data["last_prompt"] = prompt
    
    # Update session
    session.set("my_framework", my_data)
```

## Development

**Requirements:**
- Python 3.12+
- uv 0.8.0+ (recommended) or pip

**Setup:**

```bash
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/ak-py
uv sync  # or: pip install -e ".[dev]"
```

**Run Tests:**

```bash
uv run pytest
# or: pytest
```

**Code Quality:**

The project uses:
- `black` — Code formatting
- `isort` — Import sorting
- `mypy` — Type checking

## License

MIT License - see LICENSE file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
- **Documentation**: [Full Documentation](https://github.com/yaalalabs/agent-kernel)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
