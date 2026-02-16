---
sidebar_position: 1
slug: /
---

# Introduction to Agent Kernel

Welcome to **Agent Kernel** - a versatile, framework-agnostic runtime for building and deploying AI agents.

:::tip What's New
☁️ **Multi-Cloud Azure Support** - Agent Kernel now supports Microsoft Azure! Deploy to Azure Functions (serverless) or Azure Container Apps (containerized) with the same ease as AWS. Full Terraform modules, Cosmos DB session storage, and enterprise-ready deployment patterns. [Learn more →](/docs/deployment/overview)
:::

## What is Agent Kernel?

Agent Kernel is a **lightweight, multi-cloud AI agent runtime** and adapter layer for building and running AI agents across multiple frameworks and cloud providers. It provides the low level scaffolding to build, test and deploy your agents, your MCP tools and A2A quickly in many deployment configurations on **AWS and Azure**. The unified execution environment provides the session and memory management seamlessly.

**Supported Python Versions:** 3.12 - 3.13.x 
**Supported Cloud Platforms:** AWS, Azure 

Migrate your existing agents to Agent Kernel and instantly utilize pre-built execution and testing capabilities. It eliminates the complexity of framework development allowing AI engineers to focus on Agent development and provides a consistent development experience regardless of the underlying AI agent framework.

It's not
- a substitute for popular Agent frameworks and SDKs like LangGraph and OpenAI 
- another heavy abstraction that you have to learn

It's a lightweight, simple, intuitive framework to make your life easy.

```mermaid
---
config:
  layout: dagre
---
flowchart LR
    B["Unified Runtime"] --> A["Unified Execution"]
    C["OpenAI Agents"] --> B
    D["CrewAI"] --> B
    E["LangGraph"] --> B
    F["Google ADK"] --> B
    G["Test Framework"]
    B --> G
    style A fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style B fill:#2e4555,stroke:#fff,stroke-width:2px,color:#fff
    style G fill:#005073,stroke:#fff,stroke-width:2px,color:#fff
```

## Why Agent Kernel?

### Effortless Migration

Build agents using any AI agentic framework and migrate them to Agent Kernel to benefit from its execution framework capabilities. No need to build a platform code from scratch to run your agents. You can focus on domain-specific Agent development and Agent Kernel takes care of testing, deployment and execution.

### Ready-to-Use Execution

Agent Kernel provides pre-built execution capabilities:
- **CLI Testing Environment** for local development
- **REST API Server** for web integration
- **Built-in popular integrations** for pluggable integrations and ability to build custom integrations quickly
  - Slack
  - WhatsApp
  - Messenger
  - Telegram
  - Instagram
  - Gmail
- **Multi-Cloud Serverless Deployment** for scalable production
  - AWS Lambda
  - Azure Functions
- **Multi-Cloud Containerized Deployment** for consistent loads
  - AWS ECS/Fargate
  - Azure Container Apps
- **MCP Server** for Model Context Protocol tool publishing
- **A2A Server** for Agent-to-Agent communication

### Multi-Cloud Architecture

Deploy the same agent code to **AWS or Azure** without modification. Agent Kernel provides:
- Cloud-agnostic agent development
- Provider-specific optimizations
- Consistent APIs across clouds
- No vendor lock-in

### Pluggable Architecture

Easily extend Agent Kernel with custom framework adapters, memory back-ends, and deployment profiles.

### Enterprise-Ready Features

- **Session Management**: Built-in conversational state tracking across multiple backends
- **Memory Management**: Pluggable memory with smart caching
  - In-memory (development)
  - Redis (AWS & Azure)
  - DynamoDB (AWS serverless)
  - Cosmos DB (Azure serverless)
  - **Volatile Cache**: Request-scoped temporary storage for RAG context, file content, and intermediate data
  - **Non-Volatile Cache**: Session-persistent storage for user preferences, metadata, and configurations
  
  [Learn more about session management →](/docs/core-concepts/session) | [Advanced memory features →](/docs/architecture/memory-management)
- **Execution Hooks**: Powerful pre and post-execution hooks for ultimate control
  - **Pre-execution hooks**: Guard rails, RAG context injection, input validation, authentication
  - **Post-execution hooks**: Response moderation, disclaimers, output filtering, analytics
  - **Hook chaining**: Compose multiple hooks in sequence for complex behaviors
  - **Early termination**: Pre-hooks can halt execution and return custom responses
- **Fault Tolerance**: Production-grade resilience
  - Multi-AZ deployments for high availability
  - Automatic failure recovery and retry mechanisms
  - Health monitoring and auto-scaling (auto-scaling will be made available soon)
  - Persistent state across failures
- **Traceability**: Track and audit all agent operations
  - LangFuse
  - OpenLLMetry
- **Multi-Agent Collaboration**: Leverage multi-agent hierarchies of supported agentic frameworks
- **Agent Testing Capability**: Built in Agent test framework so that you can write automated tests easily
- **Governance**: Guard rails and human in the middle capabilities are coming soon

## Key Features

### Unified API

```python
from agentkernel.core import Agent, Runner, Session, Module, Runtime
```

All framework adapters expose the same core abstractions:
- **Agent**: Framework-specific agent wrapped by Agent Kernel
- **Runner**: Framework-specific execution strategy
- **Session**: Shared conversational state
- **Module**: Container for registering agents
- **Runtime**: Global orchestrator

### Execution Hooks

Powerful **pre-execution** and **post-execution** hooks give you surgical control over agent behavior:

- **Pre-hooks**: Intercept prompts before agents see them
  - 🛡️ Guard rails and content filtering
  - 🧠 RAG context injection from knowledge bases
  - 🔍 Input validation and authentication
  - 📊 Request logging and analytics
- **Post-hooks**: Transform responses after generation
  - ⚖️ Add disclaimers and compliance messages
  - 🔒 Output moderation and filtering
  - 📈 Response analytics and monitoring

**Works with any framework** - same hook code across OpenAI, CrewAI, LangGraph, and ADK.

[Learn more in our blog post →](/blog/hooks-and-smart-memory)

### Smart Memory Management

Two types of cache with identical APIs but different lifecycles:

- **Volatile Cache**: Request-scoped temporary storage
  - Perfect for RAG context, file content, intermediate calculations
  - Auto-clears after request completion
  - Keeps prompts clean and reduces token usage
- **Non-Volatile Cache**: Session-persistent storage
  - Store user preferences, metadata, configurations
  - Persists across multiple requests
  - Share data between hooks and tools

**Multiple backends with multi-cloud support** - swap between in-memory (local), Redis (AWS & Azure), DynamoDB (AWS), or Cosmos DB (Azure) with just environment variables.

[Read the advanced memory guide →](/docs/architecture/memory-management)

### Multi-Framework Support

Agent Kernel currently supports:

- **OpenAI Agents SDK** - Official OpenAI agents framework
- **CrewAI** - Role-based multi-agent framework
- **LangGraph** - Graph-based agent orchestration
- **Google ADK** - Google's Agent Development Kit

### Flexible Deployment

```mermaid
---
config:
  layout: dagre
  elk: true
---
flowchart LR
    A["Agent Logic"] --> B["Deployment Mode"]
    B -- Local --> C["CLI Testing"]
    B -- API --> D["REST API Server"] & G["MCP Server"] & H["A2A Server"]
    B -- AWS Cloud --> E["AWS Lambda"] & F["AWS ECS/Fargate"]
    B -- Azure Cloud --> K["Azure Functions"] & L["Azure Container Apps"]
    D -- Integration --> I["Slack"] & J["WhatsApp"] & M["Messenger"] & N["Instagram"] & O["Telegram"] & P["Gmail"]

    style A fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
    style E fill:#FF9900,stroke:#fff,stroke-width:2px,color:#fff
    style F fill:#FF9900,stroke:#fff,stroke-width:2px,color:#fff
    style K fill:#0078D4,stroke:#fff,stroke-width:2px,color:#fff
    style L fill:#0078D4,stroke:#fff,stroke-width:2px,color:#fff
    style I fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style J fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style M fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style N fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
    style O fill:#1ebbd7,stroke:#fff,stroke-width:2px,color:#fff
```

## Quick Example

Here's a simple agent built with Agent Kernel using CrewAI:

```python
from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

# Define your agent
agent = CrewAgent(
    role="assistant",
    goal="Help users with their questions",
    backstory="You are a helpful AI assistant",
    verbose=False,
)

# Register with Agent Kernel
CrewAIModule([agent])

# Run with built-in CLI
if __name__ == "__main__":
    CLI.main()
```

You can:
- Test locally with the CLI
- Deploy to **AWS Lambda** or **Azure Functions** with one line-change (multi-cloud!)
- Deploy to **AWS ECS/Fargate** or **Azure Container Apps** for containerized workloads
- Expose as a REST API
- Integrate with MCP or A2A protocols

All without changing your agent code!

## Who Should Use Agent Kernel?

Agent Kernel is ideal for:

- **AI Engineers** who want framework flexibility without vendor lock-in
- **Teams** building production AI agent systems across multiple clouds
- **Developers** who need to migrate between frameworks or cloud providers
- **Organizations** requiring enterprise-grade agent deployment with multi-cloud strategy
- **Researchers** exploring different agent frameworks

## Next Steps

Ready to get started? Here's what to do next:

1. [**Install Agent Kernel**](/docs/installation) - Get up and running in minutes
2. [**Quick Start Guide**](/docs/quick-start) - Build your first agent
3. [**Core Concepts**](/docs/core-concepts/overview) - Understand the architecture
4. [**Execution Hooks**](/docs/integrations/hooks) - Add guard rails, RAG, and response control
5. [**Session Management**](/docs/core-concepts/session) - Session configuration and storage
6. [**Memory Management**](/docs/architecture/memory-management) - Advanced caching and persistence
7. [**Framework Integration**](/docs/frameworks/overview) - Choose your framework
8. [**Deployment Guide**](/docs/deployment/overview) - Deploy to production

## Community & Support

- **GitHub**: [yaalalabs/agent-kernel](https://github.com/yaalalabs/agent-kernel)
- **PyPI**: [agentkernel](https://pypi.org/project/agentkernel/)
- **Issues**: [Report bugs or request features](https://github.com/yaalalabs/agent-kernel/issues)
- **Discord**: [Community chat](https://discord.gg/snrPzb46uu)

## License

Agent Kernel is released under the MIT License. See the [LICENSE](https://github.com/yaalalabs/agent-kernel/blob/develop/LICENSE) file for details.

---

**Built with ❤️ by [Yaala Labs](https://www.yaalalabs.com/)**
