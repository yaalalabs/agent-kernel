---
sidebar_position: 1
---

# Examples Overview

The Agent Kernel repository includes a comprehensive set of examples demonstrating different **multi-cloud deployment patterns**, frameworks, and integrations for **AWS, Azure, and GCP**. All examples are located in the [examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples) directory and are organized by deployment method and use case.

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
- **`instagram/`** - Instagram integration example
- **`telegram/`** - Telegram integration example

### 📁 CLI Examples (`/examples/cli`)

Command-line interface examples for local development and testing:

- **`adk/`** - Google ADK (Agent Development Kit) agents with CLI interaction
- **`a2a/`** - Agent-to-Agent (A2A) communication examples
- **`crewai/`** - CrewAI framework integration examples
- **`guardrail/`** - Content safety and compliance validation examples
  - `openai/` - OpenAI Guardrails integration with LangGraph agents
- **`langgraph/`** - LangGraph framework integration examples
- **`multi/`** - Multi-agent examples combining different frameworks
- **`openai/`** - OpenAI Agent SDK integration examples
- **`knowledgebase/openai/`** - OpenAI Agents knowledge base demos split into `chromadb/`, `neo4j/`, `starburst/`, and `multi/`

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
- **`websocket-openai/`** - OpenAI agents with WebSocket API for real-time bidirectional communication

### 📁 Azure Containerized Examples (`/examples/azure-containerized`)

Azure Container Apps deployment examples:

- **`adk/`** - Google ADK agents deployed on Azure Container Apps
- **`crewai/`** - CrewAI agents deployed on Azure Container Apps

### 📁 Azure Serverless Examples (`/examples/azure-serverless`)

Azure Functions serverless deployment examples:

- **`adk/`** - Google ADK agents running on Azure Functions
- **`crewai/`** - CrewAI agents running on Azure Functions
- **`langgraph/`** - LangGraph agents running on Azure Functions
- **`openai/`** - OpenAI agents running on Azure Functions

### 📁 GCP Serverless Examples (`/examples/gcp-serverless`)

GCP Cloud Run serverless deployment examples (scale-to-zero):

- **`openai/`** - OpenAI agents on Cloud Run with Redis sessions
- **`openai-auth/`** - OpenAI agents with JWT authentication via API Gateway
- **`openai-firestore/`** - OpenAI agents with Firestore session storage

### 📁 GCP Containerized Examples (`/examples/gcp-containerized`)

GCP Cloud Run containerized deployment examples (always-on):

- **`openai/`** - OpenAI agents on Cloud Run with Redis sessions
- **`openai-auth/`** - OpenAI agents with JWT authentication via API Gateway

## Supported Frameworks

Agent Kernel supports multiple AI agent frameworks:

| Framework | Description | Examples Available |
|-----------|-------------|-------------------|
| **Google ADK** | Google's Agent Development Kit | CLI, AWS Containerized, AWS Serverless, Azure Containerized, Azure Serverless |
| **CrewAI** | Multi-agent orchestration framework | CLI, AWS Containerized, AWS Serverless, Azure Containerized, Azure Serverless, API |
| **LangGraph** | Graph-based agent framework | CLI, AWS Serverless, Azure Serverless |
| **OpenAI Agent SDK** | OpenAI's official agent framework | CLI, Containerized, AWS Serverless, AWS Containerized, Azure Serverless, Azure Containerized, GCP Serverless, GCP Containerized, API |

## Deployment Patterns

### Local Development
- **CLI Examples**: Perfect for local development, testing, and prototyping
- Run agents directly from command line with immediate feedback

### API Integration
- **A2A Compatibility**: Enable agent-to-agent communication
- **MCP Integration**: Expose agents as Model Context Protocol tools
- **REST API**: Standard HTTP API for agent interaction

### Container Deployment (Multi-Cloud)
- **Docker**: Containerized agents with REST API endpoints
- **AWS ECS/Fargate**: Scalable container deployment on AWS
- **Azure Container Apps**: Scalable container deployment on Azure
- **GCP Cloud Run (Containerized)**: Always-on container deployment on GCP

### Serverless Deployment (Multi-Cloud)
- **AWS Lambda**: Event-driven, serverless agent execution on AWS
- **Azure Functions**: Event-driven, serverless agent execution on Azure
- **GCP Cloud Run (Serverless)**: Scale-to-zero agent execution on GCP
- Cost-effective for sporadic workloads
- Automatic scaling based on demand across all cloud platforms

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
- **AWS CLI and credentials** (for AWS examples)
- **Azure CLI and credentials** (for Azure examples)
- **GCP CLI (`gcloud`) and credentials** (for GCP examples)
- **Terraform** (for multi-cloud infrastructure deployment)
- Valid API keys for the respective AI services (OpenAI, etc.)

## Use Cases — Skills-Driven End-to-End Agents

The [`use-cases/`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases) directory contains complete agent projects built end-to-end using Agent Kernel skills and a coding assistant. Each use case starts from a `SPEC.md` describing the agent's purpose and requirements, then uses the `ak-init`, `ak-build`, `ak-add-capabilities`, `ak-cloud-deploy`, and `ak-test` skills to generate all project files.

### Available Use Cases

- **`waste-sorting-assistant/`** — A waste sorting advisor agent that recommends disposal categories (recycle, compost, landfill, hazardous waste) based on item material and the user's local recycling rules. Includes OpenAI Agents SDK integration, session memory for region-specific rules, and AWS Lambda deployment with DynamoDB-backed session persistence.

### How to Use the Use Cases

See [`use-cases/README.md`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases/README.md) for the full workflow — from installing Agent Kernel skills to asking a coding assistant to generate a complete project from a `SPEC.md`.

Unlike the `examples/` directory (which demonstrates specific deployment patterns and integrations), the `use-cases/` directory shows complete domain-specific agents that were built by a coding agent using the Agent Kernel skills pack.

## Next Steps

- Browse the specific framework examples that match your use case
- Start with CLI examples for local development
- Progress to containerized or serverless deployments for production
- Explore multi-agent examples for complex orchestration scenarios
- See [`use-cases/`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases) for complete agents built with Agent Kernel skills

For detailed implementation guides, refer to the individual README files in each example directory.