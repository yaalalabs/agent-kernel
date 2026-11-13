---
sidebar_position: 2
---

# Installation

Get started with Agent Kernel in just a few minutes.

## Prerequisites

Before installing Agent Kernel, ensure you have:

- **Python 3.12 - 3.13.x** installed on your system
  - ⚠️ Python 3.14 and later support to be available soon
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** package manager

## Basic Installation

Create a uv project (skip this if you already have one), then add Agent Kernel to it:

```bash
uv init --python 3.12 my-agent
cd my-agent
uv add agentkernel
```

This installs the core Agent Kernel library with minimal dependencies, records it in `pyproject.toml`, and creates
the project's `.venv` for you.

## Framework-Specific Installation

Agent Kernel supports multiple AI agent frameworks. Install the extras for the framework(s) you plan to use:

### OpenAI Agents

```bash
uv add "agentkernel[openai]"
```

### CrewAI

```bash
uv add "agentkernel[crewai]"
```

### LangGraph

```bash
uv add "agentkernel[langgraph]"
```

### Google ADK

```bash
uv add "agentkernel[adk]"
```

### Smolagents

```bash
uv add "agentkernel[smolagents]"
```

### Pydantic AI

```bash
uv add "agentkernel[pydanticai]"
```

`agentkernel[pydanticai]` installs the provider-agnostic `pydantic-ai-slim` core only. Also install
the provider you intend to use, e.g. `uv add "pydantic-ai-slim[openai]"`.

### Microsoft Agent Framework

```bash
uv add "agentkernel[maf]"
```

`agentkernel[maf]` installs the provider-agnostic `agent-framework-core` only. Also install the MAF package
for the model provider you intend to use, e.g. `uv add agent-framework-openai` (or `agent-framework-anthropic`).

### Claude Agent SDK

```bash
uv add "agentkernel[claude]"
```

The `claude-agent-sdk` wheel bundles the Claude Code CLI it drives (no Node.js needed). It runs Claude models only,
authenticated with `ANTHROPIC_API_KEY` or a cloud provider (Bedrock, Vertex, Foundry). See
[Claude Agent SDK](./frameworks/claude-agent-sdk.md).

### Multiple Frameworks

You can install support for multiple frameworks at once:

```bash
uv add "agentkernel[openai,crewai,langgraph]"
```

## Additional Components

### REST API Server

For running agents with REST API endpoints:

```bash
uv add "agentkernel[api]"
```

### Multi-Cloud Deployment

For deploying to AWS (Lambda, ECS/Fargate):

```bash
uv add "agentkernel[aws]"
```

For deploying to Azure (Functions, Container Apps):

```bash
uv add "agentkernel[azure]"
```

For deploying to GCP (Cloud Run, includes Firestore session support):

```bash
uv add "agentkernel[gcp]"
```

For multiple clouds:

```bash
uv add "agentkernel[aws,azure,gcp]"
```

### Session / State Stores

```bash
uv add "agentkernel[redis]"    # Redis session/response/attachment stores
uv add "agentkernel[valkey]"   # Valkey session/response stores (Redis fork)
```

### Optional Features

```bash
uv add "agentkernel[multimodal]"  # Image/file attachment support
uv add "agentkernel[thread]"      # Conversation threads (LLM auto-naming)
uv add "agentkernel[mcp]"         # MCP server
uv add "agentkernel[a2a]"         # Agent-to-Agent server
uv add "agentkernel[langfuse]"    # Langfuse tracing
uv add "agentkernel[openllmetry]" # OpenLLMetry tracing
uv add "agentkernel[logfire]"     # Pydantic Logfire tracing
uv add "agentkernel[cloudwatch]"  # AWS CloudWatch (X-Ray) tracing
uv add "agentkernel[auth]"        # JWT auth helpers
```

Messaging integrations each have their own extra: `slack`, `whatsapp`, `messenger`, `instagram`, `telegram`, `teams`, `gmail`. Knowledge base backends: `chromadb`, `neo4j`, `trino`. Open Knowledge Format bundles need no extra - `pyyaml` is a core dependency - unless the bundle is served from S3, which uses the `aws` extra.

### CLI Testing

For interactive command-line testing:

```bash
uv add "agentkernel[cli]"
```

### All Features

Install everything (all frameworks and cloud providers):

```bash
uv add "agentkernel[openai,crewai,langgraph,adk,smolagents,pydanticai,maf,claude,api,aws,azure,gcp,cli]"
```

## Virtual Environment Setup

`uv add` creates and manages the project's `.venv` automatically. Run commands inside it with `uv run`, or
activate it:

```bash
# Run without activating
uv run python my_agent.py

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### Using an existing environment

To install into an environment you already manage (a plain venv or a conda environment) instead of a uv
project, activate it and use uv's pip interface:

```bash
# venv
python -m venv .venv
source .venv/bin/activate
uv pip install "agentkernel[openai,api]"

# conda
conda create -n .venv python=3.12
conda activate .venv
uv pip install "agentkernel[openai,api]"
```

## Verify Installation

After installation, verify that Agent Kernel is installed correctly:

```bash
# In a uv project
uv run python -c "import agentkernel; print(agentkernel.__version__)"

# In an existing environment you activated (venv or conda)
python -c "import agentkernel; print(agentkernel.__version__)"
```

You should see the version number printed (e.g., `0.1.2`).

## Development Installation

If you want to contribute to Agent Kernel or modify the source code:

```bash
# Clone the repository
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/ak-py

# Install in development mode
./build.sh

# Go to any example and run
./build.sh local
```

## Configuration

Agent Kernel can be configured using environment variables or a configuration file. See the [Configuration Guide](./core-concepts/configuration) for details.

### Basic Environment Variables

```bash
# Set log level
export AK_LOGGING__AK__LEVEL=INFO

# Set session storage - Redis
export AK_SESSION__TYPE=redis
export AK_SESSION__REDIS__URL=redis://localhost:6379

# Set session storage - DynamoDB (for AWS deployments)
export AK_SESSION__TYPE=dynamodb
export AK_SESSION__DYNAMODB__TABLE_NAME=agent-kernel-sessions
```

## Troubleshooting

### Python Version Issues

Agent Kernel requires Python 3.12+. Check your Python version:

```bash
uv run python --version
```

If the project picked up an unsupported version, first set `requires-python = ">=3.12,<3.14"` in its
`pyproject.toml` (uv rejects a pin outside that range), then pin Python 3.12 (uv downloads it if needed) and
re-sync:

```bash
uv python pin 3.12
uv sync
```

### Dependency Conflicts

If you encounter dependency conflicts, recreate the project's virtual environment:

```bash
rm -rf .venv
uv sync
```

### Import Errors

If you get import errors after installation, ensure you've installed the appropriate extras:

```bash
# If using OpenAI Agents
uv add "agentkernel[openai]"

# If using CrewAI
uv add "agentkernel[crewai]"
```

## Next Steps

Now that you have Agent Kernel installed, proceed to the [Quick Start Guide](./quick-start) to build your first agent!

## Version Information

- **Python Requirements**: 3.12+
- **License**: Apache-2.0

## Support

If you encounter installation issues:

1. Check the [GitHub Issues](https://github.com/yaalalabs/agent-kernel/issues)
2. Search for existing solutions
3. Open a new issue with your error details

---

**Ready to build?** Continue to the [Quick Start Guide](./quick-start) →
