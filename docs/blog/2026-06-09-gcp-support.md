---
slug: /gcp-support
title: "Agent Kernel Now Runs on GCP - AWS, Azure, GCP, On-Prem. One Platform."
authors: [yaala]
tags: [agent-kernel, gcp, google-cloud, multi-cloud, cloud-agnostic, cloud-run, terraform, enterprise-ai]
image: /img/blog/gcp-announcement-banner.png
---

# Agent Kernel Now Runs on GCP

![Agent Kernel GCP Support](/img/blog/gcp-announcement-banner.png)

**AWS. Azure. GCP. On-Prem. One platform. No rewrites. No lock-in.**

Agent Kernel now ships full Google Cloud Platform support, completing the trifecta of major public clouds. Your agents now deploy identically across every environment, same observability pipeline, same compliance primitives, zero code changes.

<!-- truncate -->

## What's Included

Built on **Cloud Run**, with two modes controlled by a single parameter:

- **Serverless** - scale-to-zero serverless. No idle cost.
- **Containerized** - always-on with zero cold starts.

Both are fully provisioned by Terraform: Artifact Registry, API Gateway + JWT auth, Firestore for session state, Memorystore for shared cache, and VPC isolation.

## The Runtime That Takes Agents to Production

Getting an AI agent running is the easy part. Getting it running reliably in production, with proper auth, compliance guardrails, observability, and scalable infrastructure, is where the real work begins.

Agent Kernel is the runtime that handles all of it. You bring the agent logic; Agent Kernel brings everything required to make it production-grade: framework support (OpenAI Agents SDK, LangGraph, CrewAI, Google ADK etc.), cloud infrastructure via Terraform, built-in PII detection and audit traces, and full tracing on every LLM call and tool invocation through LangFuse and OpenLLMetry or bring-your-own.

The result is that shipping an agent to production feels like shipping any other service. No bespoke infrastructure work, no compliance bolt-ons, no cloud-specific rewrites. Just deploy.

Agent Kernel is the only agent operating system that offers true cloud-agnostic deployment across all three major public clouds and on-premises infrastructure. That's not a coincidence of timing; it's a direct outcome of Agent Kernel's adaptor architecture. Every cloud provider, every AI framework, every LLM, and every tool integration is wired in through a clean adaptor layer. Adding a new cloud is a new adaptor, not a rewrite. This is what future-proofs AI companies: as the landscape shifts, new models emerge, and infrastructure requirements evolve, Agent Kernel extends without breaking what already runs in production.

## The Full Picture

| | AWS | Azure | GCP | On-Prem |
|---|---|---|---|---|
| Serverless | Lambda | Functions | Cloud Run | - |
| Containerized | ECS Fargate | Container Apps | Cloud Run | Docker / K8s |
| Session Store | DynamoDB | Cosmos DB | Firestore | Redis |
| IaC | Terraform | Terraform | Terraform | Terraform |

Same agent code. Every cloud. That's the point.

## Get Started

```hcl
module "agent_kernel_gcp" {
  source  = "yaalalabs/ak-serverless/google"
  version = "0.5.1"

}
```

:::info Ready to deploy?
See the [GCP Serverless](/docs/deployment/gcp-serverless) or [GCP Containerized](/docs/deployment/gcp-containerized) deployment guides.
:::
