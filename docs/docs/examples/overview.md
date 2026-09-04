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
- **`agui/`** - AG-UI protocol example: an OpenAI Agents SDK agent driven by a React/Vite frontend
  over a streamed AG-UI event surface, with shared state and client-context tools
- **`slack/`** - Slack integration example
- **`whatsapp/`** - WhatsApp integration example
- **`instagram/`** - Instagram integration example
- **`telegram/`** - Telegram integration example
- **`schedule-openai/`** - Deferred and recurring chats: a chat request carrying a `schedule` block is registered instead of run (HTTP 202), with the in-process `local` provider, an `in_memory` task store, the `/api/v1/schedules` management routes, and an agent that can schedule work itself

### 📁 CLI Examples (`/examples/cli`)

Command-line interface examples for local development and testing:

- **`adk/`** - Google ADK (Agent Development Kit) agents with CLI interaction
- **`crewai/`** - CrewAI framework integration examples
- **`guardrail/`** - Content safety and compliance validation examples
  - `openai/` - OpenAI Guardrails integration with LangGraph agents
- **`langgraph/`** - LangGraph framework integration examples
- **`logfire/`** - Pydantic Logfire tracing over the OpenAI Agents SDK example
- **`multi/`** - Multi-agent examples combining different frameworks
- **`openai/`** - OpenAI Agent SDK integration examples
- **`openai-dynamic/`** - OpenAI Agent SDK agents registered dynamically at runtime
- **`openai_structured/`** - OpenAI Agent SDK agent returning structured (Pydantic) output
- **`pydanticai/`** - Pydantic AI framework integration examples
- **`smolagents/`** - HuggingFace smolagents `CodeAgent` integration examples
- **`knowledgebase/openai/`** - OpenAI Agents knowledge base demos split into `chromadb/`, `neo4j/`, `starburst/`, `okf/` (Open Knowledge Format markdown bundle), and `multi/`

Per-run framework context/state demos — a grocery assistant that carries a cart across turns through the reserved `framework_context` session key, one per framework, using each framework's native context mechanism (see the [Session](../core-concepts/session.md) guide):

- **`openai_context/`** - OpenAI Agents SDK, via `RunContextWrapper.context`
- **`langgraph_context/`** - LangGraph, via a declared state channel on a custom graph
- **`adk_context/`** - Google ADK, via `ToolContext.state`
- **`pydanticai_context/`** - Pydantic AI, via `RunContext.deps`

### 📁 Sandbox Examples (`/examples/sandbox`)

Sandbox capability examples (execute code/commands in an isolated, permission-bounded environment). See the [Sandbox](../advanced/sandbox.md) guide:

- **`basic/`** - Enable the sandbox, run code, persist a workspace across turns, manage named sessions
- **`profiles/`** - Multiple named workload profiles (provider + scope routing: a docker-backed workspace and a local throwaway sandbox)
- **`policy/`** - Policy/permissions on the docker provider: an enforced envelope (network deny, resource limits) and the fail-closed `strict` model for what docker cannot enforce (egress allowlist)
- **`docker/`** - The docker provider: container-isolated execution, package installs, and enforced network policy (requires a Docker daemon)
- **`daytona/`** - The daytona provider: cloud container sandboxes with enforced network and resource policy and native idle auto-stop (requires a Daytona API key)
- **`e2b/`** - The e2b provider: Firecracker micro-VM sandboxes with a stateful Jupyter kernel (variables persist across executions) and enforced network policy (requires an E2B API key)
- **`identity/`** - Sandbox code running under the authenticated end user's identity, end-to-end over REST (custom pre-hook, principal resolver, and bring-your-own provider)
- **`ec2-ssm/`** - The ec2_ssm provider (mode-3 attach): execute code on an existing EC2 instance over SSM (manual; requires a real instance and AWS credentials)
- **`broker-kafka/`** - The queue broker flavor over Kafka: a two-process split where the worker runs read-only kubectl pods in a kind cluster via the kubernetes provider, with RBAC as the security boundary (requires Docker, kind, kubectl)
- **`broker-nats/`** - The queue broker fully in-cluster: pipeline plus sandbox worker deployed by the ak-k8s Helm chart over NATS, with sandbox pods in a hardened namespace (requires a micro-cluster and Helm)

### 📁 Containerized Examples (`/examples/containerized`)

Docker-based deployment examples:

- **`openai/`** - OpenAI agents running in Docker containers with REST API access

### 📁 AWS Containerized Examples (`/examples/aws-containerized`)

AWS ECS/Fargate deployment examples:

- **`adk/`** - Google ADK agents deployed on AWS container services
- **`crewai/`** - CrewAI agents deployed on AWS container services
- **`openai-dynamodb-scalable/`** - OpenAI agents on AWS ECS with SQS queue mode for scalable, asynchronous request processing and DynamoDB response storage
- **`openai-websocket/`** - OpenAI agents on AWS ECS over a WebSocket API in direct (non-queue) mode: one service authenticates `$connect`, runs the agent inline, and pushes the reply back over the same connection
- **`openai-websocket-scalable/`** - OpenAI agents on AWS ECS over a WebSocket API in queue mode: the REST/IO service enqueues chat frames and pushes responses, while a separately-scalable Agent Runner service processes them from SQS
- **`openai-stream/`** - OpenAI agents on AWS ECS over a WebSocket API in direct (non-queue), STREAM execution mode: the reply is delivered token-by-token as `STREAM_CHUNK` messages instead of one final `CHAT_RESPONSE`
- **`openai-stream-queue-mode/`** - OpenAI agents on AWS ECS over a WebSocket API in queue-based STREAM execution mode: the Agent Runner streams token-by-token chunks onto the Output Queue so it can scale independently of ingress
- **`openai-schedule/`** - Deferred and recurring chats on AWS ECS: EventBridge Scheduler owns the timers and delivers each occurrence into the Input Queue, with a DynamoDB schedule store and the `/api/v1/schedules` management routes on the REST service

### 📁 AWS Serverless Examples (`/examples/aws-serverless`)

AWS Lambda serverless deployment examples:

- **`adk/`** - Google ADK agents running on AWS Lambda
- **`crewai/`** - CrewAI agents running on AWS Lambda
- **`langgraph/`** - LangGraph agents running on AWS Lambda
- **`openai/`** - OpenAI agents running on AWS Lambda
- **`websocket-openai/`** - OpenAI agents with WebSocket API for real-time bidirectional communication
- **`streaming-openai/`** - OpenAI agents with WebSocket event streaming (`execution.mode: stream`)
- **`schedule-openai/`** - Deferred and recurring chats on AWS Lambda: EventBridge Scheduler delivers each occurrence into the Input Queue for the agent-runner Lambda, backed by a DynamoDB schedule store

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
| **Pydantic AI** | Type-safe agent framework from the Pydantic team | CLI, API |
| **smolagents** | HuggingFace's code-first agent framework | CLI |

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

## Use Cases: Skills-Driven End-to-End Agents

The [`use-cases/`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases) directory contains complete agent projects built end-to-end using Agent Kernel skills and a coding assistant. Each use case starts from a `SPEC.md` describing the agent's purpose and requirements, then uses the `ak-init`, `ak-build`, `ak-add-capabilities`, `ak-cloud-deploy`, and `ak-test` skills to generate all project files.

### Available Use Cases

- **`waste-sorting-assistant/`**: A waste sorting advisor agent that recommends disposal categories (recycle, compost, landfill, hazardous waste) based on item material and the user's local recycling rules. Includes OpenAI Agents SDK integration, session memory for region-specific rules, and AWS Lambda deployment with DynamoDB-backed session persistence.

### How to Use the Use Cases

See [`use-cases/README.md`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases/README.md) for the full workflow, from installing Agent Kernel skills to asking a coding assistant to generate a complete project from a `SPEC.md`.

Unlike the `examples/` directory (which demonstrates specific deployment patterns and integrations), the `use-cases/` directory shows complete domain-specific agents that were built by a coding agent using the Agent Kernel skills pack.

## Next Steps

- Browse the specific framework examples that match your use case
- Start with CLI examples for local development
- Progress to containerized or serverless deployments for production
- Explore multi-agent examples for complex orchestration scenarios
- See [`use-cases/`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases) for complete agents built with Agent Kernel skills

For detailed implementation guides, refer to the individual README files in each example directory.