---
sidebar_position: 1
slug: /
---

# Introduction to Agent Kernel

Welcome to **Agent Kernel** - a versatile, framework-agnostic runtime for building and deploying AI agents.

## What is Agent Kernel?

Agent Kernel (AK) is a lightweight runtime and adapter layer that enables developers to build AI agents once and run them across multiple frameworks within a unified execution environment. It eliminates the complexity of framework lock-in and provides a consistent development experience regardless of the underlying AI agent framework.

```mermaid
graph LR
    A[Your Agent Logic] --> B[Agent Kernel]
    B --> C[OpenAI Agents]
    B --> D[CrewAI]
    B --> E[LangGraph]
    B --> F[Google ADK]
    
    style B fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
```

## Why Agent Kernel?

### 🔄 Framework Flexibility

Build agents using Agent Kernel's standardized API and switch between underlying frameworks effortlessly. No need to rewrite your agent logic when you want to try a different framework.

### 🚀 Ready-to-Use Execution

Agent Kernel provides pre-built execution capabilities:
- **CLI Testing Environment** for local development
- **REST API Server** for web integration
- **AWS Serverless Deployment** for scalable production
- **AWS Containerized Deployment** for consistent loads
- **MCP Server** for Model Context Protocol integration
- **A2A Server** for Agent-to-Agent communication

### 🧩 Pluggable Architecture

Easily extend Agent Kernel with custom framework adapters, memory backends, and deployment profiles.

### 📊 Enterprise-Ready Features

- **Session Management**: Built-in conversational state tracking
- **Memory Management**: Pluggable short-term (Redis, in-memory) and long-term (DynamoDB, MongoDB) storage
- **Role-Based Access Control**: Control agent and tool access
- **Traceability**: Track and audit all agent operations
- **Multi-Agent Collaboration**: Build agent hierarchies and teams

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

### Multi-Framework Support

Agent Kernel currently supports:

- ✅ **OpenAI Agents SDK** - Official OpenAI agents framework
- ✅ **CrewAI** - Role-based multi-agent framework
- ✅ **LangGraph** - Graph-based agent orchestration
- ✅ **Google ADK** - Google's Agent Development Kit

### Flexible Deployment

```mermaid
graph TD
    A[Agent Logic] --> B{Deployment Mode}
    B -->|Local| C[CLI Testing]
    B -->|API| D[REST API Server]
    B -->|Cloud| E[AWS Serverless]
    B -->|Cloud| F[AWS Containers]
    B -->|Integration| G[MCP Server]
    B -->|Integration| H[A2A Server]
    
    style A fill:#2e8555,stroke:#fff,stroke-width:2px,color:#fff
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
module = CrewAIModule([agent])

# Run with built-in CLI
if __name__ == "__main__":
    CLI.main()
```

Now you can:
- Test locally with the CLI
- Deploy to AWS Lambda with one command
- Expose as a REST API
- Integrate with MCP or A2A protocols

All without changing your agent code!

## Who Should Use Agent Kernel?

Agent Kernel is ideal for:

- **AI Engineers** who want framework flexibility without vendor lock-in
- **Teams** building production AI agent systems
- **Developers** who need to migrate between frameworks
- **Organizations** requiring enterprise-grade agent deployment
- **Researchers** exploring different agent frameworks

## Next Steps

Ready to get started? Here's what to do next:

1. [**Install Agent Kernel**](./installation) - Get up and running in minutes
2. [**Quick Start Guide**](./quick-start) - Build your first agent
3. [**Core Concepts**](./core-concepts/overview) - Understand the architecture
4. [**Framework Integration**](./frameworks/overview) - Choose your framework
5. [**Deployment Guide**](./deployment/overview) - Deploy to production

## Community & Support

- **GitHub**: [yaalalabs/agent-kernel](https://github.com/yaalalabs/agent-kernel)
- **PyPI**: [agentkernel](https://pypi.org/project/agentkernel/)
- **Issues**: [Report bugs or request features](https://github.com/yaalalabs/agent-kernel/issues)

## License

Agent Kernel is released under the MIT License. See the [LICENSE](https://github.com/yaalalabs/agent-kernel/blob/main/LICENSE) file for details.

---

**Built with ❤️ by Yaala Labs**
