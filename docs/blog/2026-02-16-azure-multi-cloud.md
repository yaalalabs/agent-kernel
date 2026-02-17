---
slug: /azure-multi-cloud-support
title: "Agent Kernel Goes Multi-Cloud: Azure Support is Here"
authors: [yaala]
tags: [agent-kernel, azure, multi-cloud, aws, container-apps, azure-functions, cosmos-db, cloud-agnostic]
image: /img/card.png
---

# Agent Kernel Goes Multi-Cloud: Azure Support is Here

**Your AI investment should never be hostage to a single cloud provider.**

**Write once. Deploy anywhere. That's not a slogan, it's now reality.**

Today, we're announcing full Azure support for Agent Kernel. Your AI agents can now run on Azure Container Apps, Azure Functions, and leverage Cosmos DB for persistent memory, all with zero changes to your agent code. The same agent that runs on AWS Lambda today can run on Azure Functions tomorrow. This is multi-cloud done right.

<!-- truncate -->

## Why Multi-Cloud Matters

The cloud landscape has fundamentally changed how enterprises think about infrastructure:

- **More than 90% of enterprises** will operate in multi-cloud environments by 2027 (Source: [Gartner](https://www.gartner.com/en/newsroom/press-releases/2024-11-19-gartner-forecasts-worldwide-public-cloud-end-user-spending-to-total-723-billion-dollars-in-2025))
- **Vendor lock-in** is the top concern for cloud decision-makers
- **Regulatory requirements** often mandate geographic or provider diversity
- **Cost optimization** demands the flexibility to leverage competitive pricing

Yet most AI agent frameworks force you to choose. Build for AWS, rebuild for Azure. Agent Kernel eliminates this false choice.

## Cloud-Agnostic by Design

Agent Kernel wasn't retrofitted for multi-cloud, it was **architected for it from day one**.

![Agent Kernel Multi-Cloud Architecture](/img/blog/azure-intro.png)

The separation is clean:
- **Your agent logic** stays unchanged across clouds
- **Agent Kernel runtime** handles the abstraction
- **Cloud-specific adapters** manage infrastructure differences

## What's Available on Azure

### Serverless: Azure Functions
Perfect for variable workloads and cost-sensitive deployments:
- Automatic scaling from zero to thousands of concurrent executions
- Pay only for what you use
- Native integration with Azure API Management

### Containerized: Azure Container Apps
Ideal for consistent, low-latency workloads:
- Managed Kubernetes without the Kubernetes complexity
- Built-in scaling and load balancing
- Reduced cold start latency compared to serverless

### Memory: Cosmos DB Integration
Enterprise-grade session persistence:
- Global distribution with multi-region writes
- Guaranteed single-digit millisecond latency
- Automatic and instant scalability

### Full Enterprise Feature Parity

Azure deployments get the complete Agent Kernel feature set:

- **Observability**: Full tracing, metrics, and audit logs across all agent operations
- **Guardrails**: Content safety and PII protection with OpenAI Guardrails support
- **Comprehensive Test Framework**: CLI-based testing and automated scenario validation
- **MCP & A2A Support**: Multi-context processing and agent-to-agent communication

No compromises. No feature gaps. The same production-grade capabilities on every cloud.

## Getting Started

Deploying to Azure is as simple as deploying to AWS:

```bash
# Clone an Azure example
git clone https://github.com/yaalalabs/agent-kernel
cd examples/azure-containerized/openai-cosmos/deploy

# Configure and deploy
terraform init
terraform apply
```

Your agents. Your framework. Your choice of cloud.

## The Road Ahead: Google Cloud Platform

Multi-cloud isn't complete with two providers. **GCP support is our next milestone.**

We're bringing Agent Kernel to Google Cloud with:
- **Cloud Run** for containerized workloads
- **Cloud Functions** for serverless execution  
- **Firestore** and **Cloud Spanner** for persistent memory

The goal remains unchanged: write your agent once, deploy it everywhere.

---

## Join the Multi-Cloud Movement

Agent Kernel is open source and community-driven. Whether you're running on AWS today and evaluating Azure, or building greenfield with multi-cloud requirements, we've got you covered.

- 📖 [Azure Deployment Guide](https://kernel.yaala.ai/docs/deployment/overview)
- 💻 [GitHub Repository](https://github.com/yaalalabs/agent-kernel)
- 💬 [Discord Community](https://discord.gg/snrPzb46uu)

**The future of AI agents is multi-cloud. The future is now.**
