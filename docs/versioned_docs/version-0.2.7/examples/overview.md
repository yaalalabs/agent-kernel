---
sidebar_position: 1
---

# Examples Overview

The Agent Kernel repository includes a comprehensive set of examples demonstrating different deployment patterns, frameworks, and integrations. All examples are located in the [examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples) directory and are organized by deployment method and use case.

## Directory Structure

The examples are organized into the following main categories:

### 📁 API Examples (`/examples/api`)

Examples demonstrating Agent Kernel's API capabilities and integrations:

- **`a2a/`** - Agent-to-Agent (A2A) compatibility examples
  - `multi/` - Multi-agent runtime with CrewAI and OpenAI agents exposed as A2A compatible
- **`mcp/`** - Model Context Protocol (MCP) integration examples
  - `multi/` - Multi-agent runtime with agents exposed as MCP tools
- **`slack/`** - Slack integration example
- **`whatsapp/`** - WhatsApp integration example

### 📁 CLI Examples (`/examples/cli`)

Command-line interface examples for local development and testing:

- **`adk/`** - Google ADK (Agent Development Kit) agents with CLI interaction
- **`crewai/`** - CrewAI framework integration examples
- **`langgraph/`** - LangGraph framework integration examples
- **`multi/`** - Multi-agent examples combining different frameworks
- **`openai/`** - OpenAI Agent SDK integration examples

### 📁 Containerized Examples (`/examples/containerized`)

Docker-based deployment examples:

- **`openai/`** - OpenAI agents running in Docker containers with REST API access

### 📁 AWS Containerized Examples (`/examples/aws-containerized`)

AWS ECS/Fargate deployment examples:

- **`adk/`** - Google ADK agents deployed on AWS container services
- **`crewai/`** - CrewAI agents deployed on AWS container services

### 📁 AWS Serverless Examples (`/examples/aws-serverless`)

AWS Lambda serverless deployment examples:

- **`adk/`** - Google ADK agents running on AWS Lambda
- **`crewai/`** - CrewAI agents running on AWS Lambda  
- **`langgraph/`** - LangGraph agents running on AWS Lambda
- **`openai/`** - OpenAI agents running on AWS Lambda

## Supported Frameworks

Agent Kernel supports multiple AI agent frameworks:

| Framework | Description | Examples Available |
|-----------|-------------|-------------------|
| **Google ADK** | Google's Agent Development Kit | CLI, AWS Containerized, AWS Serverless |
| **CrewAI** | Multi-agent orchestration framework | CLI, AWS Containerized, AWS Serverless, API |
| **LangGraph** | Graph-based agent framework | CLI, AWS Serverless |
| **OpenAI Agent SDK** | OpenAI's official agent framework | CLI, Containerized, AWS Serverless, API |

## Deployment Patterns

### Local Development
- **CLI Examples**: Perfect for local development, testing, and prototyping
- Run agents directly from command line with immediate feedback

### API Integration
- **A2A Compatibility**: Enable agent-to-agent communication
- **MCP Integration**: Expose agents as Model Context Protocol tools
- **REST API**: Standard HTTP API for agent interaction

### Container Deployment
- **Docker**: Containerized agents with REST API endpoints
- **AWS ECS/Fargate**: Scalable container deployment on AWS

### Serverless Deployment
- **AWS Lambda**: Event-driven, serverless agent execution
- Cost-effective for sporadic workloads
- Automatic scaling based on demand

## Getting Started

Each example includes:
- **README.md**: Detailed setup and usage instructions
- **build.sh**: Dependency installation script
- **Demo files**: Working example implementations
- **Tests**: Validation and testing capabilities

### Quick Start Steps

1. **Choose your deployment pattern** (CLI, Containerized, or Serverless)
2. **Select your preferred framework** (ADK, CrewAI, LangGraph, or OpenAI)
3. **Navigate to the example directory**
4. **Follow the README instructions** for setup and execution

### Common Setup Pattern

Most examples follow this pattern:
```bash
# Install dependencies
./build.sh

# For local development
./build.sh local

# Run the example
python demo.py  # or server.py for API examples
```

## Integration Features

### A2A (Agent-to-Agent) Compatibility
Enable agent-to-agent communication by setting `a2a.enabled = True` in your configuration.

### MCP (Model Context Protocol) Support
Expose agents as MCP tools by setting:
```python
mcp.enabled = True
mcp.expose_agents = True
```

### Multi-Agent Runtimes
Several examples demonstrate running multiple agent frameworks within a single Agent Kernel runtime, showcasing the platform's flexibility and interoperability.

## Prerequisites

Depending on the example you choose, you may need:
- Python 3.12+ with UV package manager
- Docker (for containerized examples)
- AWS CLI and credentials (for AWS examples)
- Terraform (for AWS infrastructure deployment)
- Valid API keys for the respective AI services (OpenAI, etc.)

## Next Steps

- Browse the specific framework examples that match your use case
- Start with CLI examples for local development
- Progress to containerized or serverless deployments for production
- Explore multi-agent examples for complex orchestration scenarios

For detailed implementation guides, refer to the individual README files in each example directory.