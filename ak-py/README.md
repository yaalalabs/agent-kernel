# Agent Kernel

[![PyPI version](https://badge.fury.io/py/agentkernel.svg)](https://badge.fury.io/py/agentkernel)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Agent Kernel is a lightweight runtime and adapter layer for building and running AI agents across multiple frameworks and running within a unified execution environment. Migrate your existing agents to Agent Kernel and instantly utilize pre-built execution and testing capabilities.

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
CrewAIModule([general_agent, math_agent])

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

LangGraphModule([compiled])

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

OpenAIModule([general_agent])

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

GoogleADKModule([math_agent])

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

OpenAIModule([assistant])
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
- **Environment Variable**: `AK_SESSION__TYPE`

##### Redis Configuration

Required when `session.type=redis`:

- **URL**
  - **Field**: `session.redis.url`
  - **Default**: `redis://localhost:6379`
  - **Description**: Redis connection URL. Use `rediss://` for SSL
  - **Environment Variable**: `AK_SESSION__REDIS__URL`

- **TTL (Time to Live)**
  - **Field**: `session.redis.ttl`
  - **Default**: `604800` (7 days)
  - **Description**: Session TTL in seconds
  - **Environment Variable**: `AK_SESSION__REDIS__TTL`

- **Key Prefix**
  - **Field**: `session.redis.prefix`
  - **Default**: `ak:sessions:`
  - **Description**: Key prefix for session storage
  - **Environment Variable**: `AK_SESSION__REDIS__PREFIX`

#### API Configuration

Configure the REST API server (if using the API module).

- **Host**
  - **Field**: `api.host`
  - **Default**: `0.0.0.0`
  - **Environment Variable**: `AK_API__HOST`

- **Port**
  - **Field**: `api.port`
  - **Default**: `8000`
  - **Environment Variable**: `AK_API__PORT`

- **Custom Router Prefix**
  - **Field**: `api.custom_router_prefix`
  - **Default**: `/custom`
  - **Environment Variable**: `AK_API__CUSTOM_ROUTER_PREFIX`

- **Enabled Routes**
  - **Field**: `api.enabled_routes.agents`
  - **Default**: `true`
  - **Description**: Enable agent interaction routes
  - **Environment Variable**: `AK_API__ENABLED_ROUTES__AGENTS`

#### A2A (Agent-to-Agent) Configuration

- **Enabled**
  - **Field**: `a2a.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_A2A__ENABLED`

- **Agents**
  - **Field**: `a2a.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to enable A2A (use `["*"]` for all)
  - **Environment Variable**: `AK_A2A__AGENTS` (comma-separated)

- **URL**
  - **Field**: `a2a.url`
  - **Default**: `http://localhost:8000/a2a`
  - **Environment Variable**: `AK_A2A__URL`

- **Task Store Type**
  - **Field**: `a2a.task_store_type`
  - **Options**: `in_memory`, `redis`
  - **Default**: `in_memory`
  - **Environment Variable**: `AK_A2A__TASK_STORE_TYPE`

#### MCP (Model Context Protocol) Configuration

- **Enabled**
  - **Field**: `mcp.enabled`
  - **Default**: `false`
  - **Environment Variable**: `AK_MCP__ENABLED`

- **Expose Agents**
  - **Field**: `mcp.expose_agents`
  - **Default**: `false`
  - **Description**: Expose agents as MCP tools
  - **Environment Variable**: `AK_MCP__EXPOSE_AGENTS`

- **Agents**
  - **Field**: `mcp.agents`
  - **Default**: `["*"]`
  - **Description**: List of agent names to expose as MCP tools
  - **Environment Variable**: `AK_MCP__AGENTS` (comma-separated)

- **URL**
  - **Field**: `mcp.url`
  - **Default**: `http://localhost:8000/mcp`
  - **Environment Variable**: `AK_MCP__URL`

#### Trace (Observability) Configuration

Configure tracing and observability for monitoring agent execution.

- **Enabled**
  - **Field**: `trace.enabled`
  - **Default**: `false`
  - **Description**: Enable tracing/observability
  - **Environment Variable**: `AK_TRACE__ENABLED`

- **Type**
  - **Field**: `trace.type`
  - **Options**: `langfuse`, `openllmetry`
  - **Default**: `langfuse`
  - **Description**: Type of tracing provider to use
  - **Environment Variable**: `AK_TRACE__TYPE`

**Langfuse Setup:**

To use Langfuse for tracing, install the langfuse extra:

```bash
pip install agentkernel[langfuse]
```

Configure Langfuse credentials via environment variables:

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com  # or your self-hosted instance
```

Enable tracing in your configuration:

```yaml
trace:
  enabled: true
  type: langfuse
```

**OpenLLMetry (Traceloop) Setup:**

To use OpenLLMetry for tracing, install the openllmetry extra:

```bash
pip install agentkernel[openllmetry]
```

Configure Traceloop credentials via environment variables:

```bash
export TRACELOOP_API_KEY=your-api-key
export TRACELOOP_BASE_URL=https://api.traceloop.com  # Optional: for self-hosted
```

Enable tracing in your configuration:

```yaml
trace:
  enabled: true
  type: openllmetry
```

#### Test Configuration

Configure test comparison modes for automated testing.

- **Mode**
  - **Field**: `test.mode`
  - **Options**: `fuzzy`, `judge`, `fallback`
  - **Default**: `fallback`
  - **Description**: Test comparison mode
  - **Environment Variable**: `AK_TEST__MODE`

- **Judge Model**
  - **Field**: `test.judge.model`
  - **Default**: `gpt-4o-mini`
  - **Description**: LLM model for judge evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__MODEL`

- **Judge Provider**
  - **Field**: `test.judge.provider`
  - **Default**: `openai`
  - **Description**: LLM provider for judge evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__PROVIDER`

- **Judge Embedding Model**
  - **Field**: `test.judge.embedding_model`
  - **Default**: `text-embedding-3-small`
  - **Description**: Embedding model for similarity evaluation
  - **Environment Variable**: `AK_TEST__JUDGE__EMBEDDING_MODEL`

**Test Modes:**
- `fuzzy`: Uses fuzzy string matching (RapidFuzz)
- `judge`: Uses LLM-based evaluation (Ragas) for semantic similarity
- `fallback`: Tries fuzzy first, falls back to judge if fuzzy fails

```yaml
test:
  mode: fallback
  judge:
    model: gpt-4o-mini
    provider: openai
    embedding_model: text-embedding-3-small
```

#### Guardrails Configuration

Configure input and output guardrails to validate agent requests and responses for safety and compliance.

- **Input Guardrails**
  - **Enabled**
    - **Field**: `guardrail.input.enabled`
    - **Default**: `false`
    - **Description**: Enable input validation guardrails
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__ENABLED`

  - **Type**
    - **Field**: `guardrail.input.type`
    - **Default**: `openai`
    - **Options**: `openai`, `bedrock`
    - **Description**: Guardrail provider type
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__TYPE`

  - **Config Path**
    - **Field**: `guardrail.input.config_path`
    - **Default**: `None`
    - **Description**: Path to guardrail configuration JSON file (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__CONFIG_PATH`

  - **Model**
    - **Field**: `guardrail.input.model`
    - **Default**: `gpt-4o-mini`
    - **Description**: LLM model to use for guardrail validation (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__MODEL`

  - **ID**
    - **Field**: `guardrail.input.id`
    - **Default**: `None`
    - **Description**: AWS Bedrock guardrail ID (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__ID`

  - **Version**
    - **Field**: `guardrail.input.version`
    - **Default**: `DRAFT`
    - **Description**: AWS Bedrock guardrail version (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__INPUT__VERSION`

- **Output Guardrails**
  - **Enabled**
    - **Field**: `guardrail.output.enabled`
    - **Default**: `false`
    - **Description**: Enable output validation guardrails
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__ENABLED`

  - **Type**
    - **Field**: `guardrail.output.type`
    - **Default**: `openai`
    - **Options**: `openai`, `bedrock`
    - **Description**: Guardrail provider type
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__TYPE`

  - **Config Path**
    - **Field**: `guardrail.output.config_path`
    - **Default**: `None`
    - **Description**: Path to guardrail configuration JSON file (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__CONFIG_PATH`

  - **Model**
    - **Field**: `guardrail.output.model`
    - **Default**: `gpt-4o-mini`
    - **Description**: LLM model to use for guardrail validation (OpenAI only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__MODEL`

  - **ID**
    - **Field**: `guardrail.output.id`
    - **Default**: `None`
    - **Description**: AWS Bedrock guardrail ID (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__ID`

  - **Version**
    - **Field**: `guardrail.output.version`
    - **Default**: `DRAFT`
    - **Description**: AWS Bedrock guardrail version (Bedrock only)
    - **Environment Variable**: `AK_GUARDRAIL__OUTPUT__VERSION`

**Guardrail Setup:**

To use OpenAI guardrails, install the openai-guardrails package:

```bash
pip install agentkernel[openai]
```

To use AWS Bedrock guardrails, install the AWS package:

```bash
pip install agentkernel[aws]
```

Create guardrail configuration:

**For OpenAI:** Create configuration files following the [OpenAI Guardrails format](https://guardrails.openai.com/).

**For Bedrock:** Create a guardrail in AWS Bedrock and note the guardrail ID and version.

Configure guardrails in your configuration:

**OpenAI Example:**
```yaml
guardrail:
  input:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_input.json
  output:
    enabled: true
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_output.json
```

**Bedrock Example:**
```yaml
guardrail:
  input:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"  # or "DRAFT"
  output:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"
```

#### Messaging Platform Integrations

Configure integrations with messaging platforms.

##### Slack

- **Agent**
  - **Field**: `slack.agent`
  - **Default**: `""`
  - **Description**: Default agent for Slack interactions
  - **Environment Variable**: `AK_SLACK__AGENT`

- **Agent Acknowledgement**
  - **Field**: `slack.agent_acknowledgement`
  - **Default**: `""`
  - **Description**: Acknowledgement message when Slack message is received
  - **Environment Variable**: `AK_SLACK__AGENT_ACKNOWLEDGEMENT`

##### WhatsApp

- **Agent**
  - **Field**: `whatsapp.agent`
  - **Default**: `""`
  - **Description**: Default agent for WhatsApp interactions
  - **Environment Variable**: `AK_WHATSAPP__AGENT`

- **Verify Token**, **Access Token**, **App Secret**, **Phone Number ID**, **API Version**
  - **Environment Variables**: `AK_WHATSAPP__VERIFY_TOKEN`, `AK_WHATSAPP__ACCESS_TOKEN`, `AK_WHATSAPP__APP_SECRET`, `AK_WHATSAPP__PHONE_NUMBER_ID`, `AK_WHATSAPP__API_VERSION`

##### Facebook Messenger

- **Agent**
  - **Field**: `messenger.agent`
  - **Default**: `""`
  - **Description**: Default agent for Facebook Messenger interactions
  - **Environment Variable**: `AK_MESSENGER__AGENT`

- **Verify Token**, **Access Token**, **App Secret**, **API Version**
  - **Environment Variables**: `AK_MESSENGER__VERIFY_TOKEN`, `AK_MESSENGER__ACCESS_TOKEN`, `AK_MESSENGER__APP_SECRET`, `AK_MESSENGER__API_VERSION`

##### Instagram

- **Agent**
  - **Field**: `instagram.agent`
  - **Default**: `""`
  - **Description**: Default agent for Instagram interactions
  - **Environment Variable**: `AK_INSTAGRAM__AGENT`

- **Instagram Account ID**, **Verify Token**, **Access Token**, **App Secret**, **API Version**
  - **Environment Variables**: `AK_INSTAGRAM__INSTAGRAM_ACCOUNT_ID`, `AK_INSTAGRAM__VERIFY_TOKEN`, `AK_INSTAGRAM__ACCESS_TOKEN`, `AK_INSTAGRAM__APP_SECRET`, `AK_INSTAGRAM__API_VERSION`

##### Telegram

- **Agent**
  - **Field**: `telegram.agent`
  - **Default**: `""`
  - **Description**: Default agent for Telegram interactions
  - **Environment Variable**: `AK_TELEGRAM__AGENT`

- **Bot Token**, **Webhook Secret**, **API Version**
  - **Environment Variables**: `AK_TELEGRAM__BOT_TOKEN`, `AK_TELEGRAM__WEBHOOK_SECRET`, `AK_TELEGRAM__API_VERSION`

##### Gmail

- **Agent**
  - **Field**: `gmail.agent`
  - **Default**: `"general"`
  - **Description**: Default agent for Gmail interactions
  - **Environment Variable**: `AK_GMAIL__AGENT`

- **Client ID**, **Client Secret**, **Token File**, **Poll Interval**, **Label Filter**
  - **Environment Variables**: `AK_GMAIL__CLIENT_ID`, `AK_GMAIL__CLIENT_SECRET`, `AK_GMAIL__TOKEN_FILE`, `AK_GMAIL__POLL_INTERVAL`, `AK_GMAIL__LABEL_FILTER`

### Configuration Examples

#### Environment Variables

Use the `AK_` prefix and underscores for nested fields:

```bash
export AK_DEBUG=true
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379
export AK_SESSION__REDIS__TTL=604800
export AK_SESSION__REDIS__PREFIX=ak:sessions:
export AK_API__HOST=0.0.0.0
export AK_API__PORT=8000
export AK_A2A__ENABLED=true
export AK_MCP__ENABLED=false
export AK_TRACE__ENABLED=true
export AK_TRACE__TYPE=langfuse  # or openllmetry
# For Langfuse:
# export LANGFUSE_PUBLIC_KEY=pk-lf-...
# export LANGFUSE_SECRET_KEY=sk-lf-...
# export LANGFUSE_HOST=https://cloud.langfuse.com
# For OpenLLMetry:
# export TRACELOOP_API_KEY=your-api-key
export AK_TEST__MODE=fallback  # Options: fuzzy, judge, fallback
export AK_TEST__JUDGE__MODEL=gpt-4o-mini
export AK_TEST__JUDGE__PROVIDER=openai
export AK_TEST__JUDGE__EMBEDDING_MODEL=text-embedding-3-small
# Guardrails configuration
export AK_GUARDRAIL__INPUT__ENABLED=false
export AK_GUARDRAIL__INPUT__TYPE=openai
export AK_GUARDRAIL__INPUT__MODEL=gpt-4o-mini
export AK_GUARDRAIL__INPUT__CONFIG_PATH=/path/to/guardrails_input.json
export AK_GUARDRAIL__OUTPUT__ENABLED=false
export AK_GUARDRAIL__OUTPUT__TYPE=openai
export AK_GUARDRAIL__OUTPUT__MODEL=gpt-4o-mini
export AK_GUARDRAIL__OUTPUT__CONFIG_PATH=/path/to/guardrails_output.json
# Messaging platforms (optional)
export AK_SLACK__AGENT=my-agent
export AK_WHATSAPP__AGENT=my-agent
export AK_MESSENGER__AGENT=my-agent
export AK_INSTAGRAM__AGENT=my-agent
export AK_TELEGRAM__AGENT=my-agent
export AK_GMAIL__AGENT=my-agent
export AK_GMAIL__CLIENT_ID=your-google-client-id
export AK_GMAIL__CLIENT_SECRET=your-google-client-secret
```

#### .env File

Create a `.env` file in your working directory:

```env
AK_DEBUG=false
AK_SESSION__TYPE=redis
AK_SESSION__REDIS__URL=rediss://my-redis:6379
AK_SESSION__REDIS__TTL=1209600
AK_SESSION__REDIS__PREFIX=ak:prod:sessions:
AK_API__HOST=0.0.0.0
AK_API__PORT=8080
AK_A2A__ENABLED=true
AK_A2A__URL=http://localhost:8080/a2a
AK_TRACE__ENABLED=true
AK_TRACE__TYPE=langfuse  # or openllmetry
# Langfuse credentials (if using langfuse):
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://cloud.langfuse.com
# OpenLLMetry credentials (if using openllmetry):
# TRACELOOP_API_KEY=your-api-key
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
trace:
  enabled: true
  type: langfuse
test:
  mode: fallback
  judge:
    model: gpt-4o-mini
    provider: openai
    embedding_model: text-embedding-3-small
guardrail:
  input:
    enabled: false
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_input.json
  output:
    enabled: false
    type: openai
    model: gpt-4o-mini
    config_path: /path/to/guardrails_output.json
slack:
  agent: my-agent
  agent_acknowledgement: "Processing your request..."
whatsapp:
  agent: my-agent
  agent_acknowledgement: "Processing..."
messenger:
  agent: my-agent
instagram:
  agent: my-agent
telegram:
  agent: my-agent
gmail:
  agent: my-agent
  poll_interval: 30
  label_filter: "INBOX"
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
  },
  "trace": {
    "enabled": true,
    "type": "langfuse"
  },
  "test": {
    "mode": "fallback",
    "judge": {
      "model": "gpt-4o-mini",
      "provider": "openai",
      "embedding_model": "text-embedding-3-small"
    }
  },
  "guardrail": {
    "input": {
      "enabled": false,
      "type": "openai",
      "model": "gpt-4o-mini",
      "config_path": "/path/to/guardrails_input.json"
    },
    "output": {
      "enabled": false,
      "type": "openai",
      "model": "gpt-4o-mini",
      "config_path": "/path/to/guardrails_output.json"
    }
  },
  "slack": {
    "agent": "my-agent",
    "agent_acknowledgement": "Processing your request..."
  },
  "whatsapp": {
    "agent": "my-agent",
    "agent_acknowledgement": "Processing..."
  },
  "messenger": {
    "agent": "my-agent"
  },
  "instagram": {
    "agent": "my-agent"
  },
  "telegram": {
    "agent": "my-agent"
  },
  "gmail": {
    "agent": "my-agent",
    "poll_interval": 30,
    "label_filter": "INBOX"
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
