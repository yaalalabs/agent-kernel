---
sidebar_position: 2
title: What's new
description: The latest capabilities added to Open Agent Kernel (OAK), newest first.
---

# What's new

The latest capabilities added to Open Agent Kernel (OAK), newest first. Each entry links to its guide.
For every user-visible change by release, including breaking changes and how to migrate, see the
[changelog](https://github.com/yaalalabs/agent-kernel/blob/develop/CHANGELOG.md).

- **Authorization**: An `authorization` block grants users, groups, roles and messaging senders a level on agents. A caller then runs only the agents it is granted and is listed only the ones it may see, on REST, A2A, MCP and AG-UI alike, and an agent hidden from it answers like one that does not exist. A tool policy sets which tools each level is offered, and every framework adapter answers a call to a denied tool with the reason instead of running it, on voice calls too. The OpenAI Agents SDK, Pydantic AI, Claude Agent SDK and Microsoft Agent Framework adapters also hide the tool from the model. [Learn more →](./advanced/identity-and-access.md#authorization)
- **Agent Registry**: Every agent carries one descriptor (name, version, description, owner, tags, skills and tools), and the agent catalog (`GET /api/v1/agents`), A2A cards, MCP agent tools and the AG-UI listing are all built from it. Describe an agent with `Module.describe` or `registry.agents.<id>`, choose the surfaces it is served on, and share the registry across processes with Redis, Valkey or DynamoDB. [Learn more →](./core-concepts/configuration.md#agent-registry)
- **Identity and Access**: One configured identity provider (Auth0, Keycloak or Okta over OIDC, Amazon Cognito, Microsoft Entra ID, Firebase, a static map, or your own) authenticates every surface, and tools, hooks, threads and scheduled tasks see the same `Principal`. [Learn more →](./advanced/identity-and-access.md)
- **Queue mode on GCP**: Cloud Run deployments now run the queue pipeline by default: an edge service and a push-driven agent-runner service connected by Google Cloud Pub/Sub, both scaling to zero, with Memorystore for replies. [Learn more →](./deployment/gcp-serverless.md#queue-mode)
- **Claude Agent SDK**: Run agents built on Anthropic's Claude Code harness (built-in file, shell and web tools, subagents, hooks) in OAK, with conversations that continue on any replica. [Learn more →](./frameworks/claude-agent-sdk.md)
- **Fetch spans back for evaluation**: Read agent, LLM and tool spans back from Langfuse, Logfire, OpenLLMetry or CloudWatch with one provider-neutral `Trace.fetch_spans()` or `Trace.fetch_traces()` filter, including each model call's tokens and cost, to grade production traffic. [Learn more →](./advanced/traceability.md#fetching-spans-back)
- **A2UI**: Turn two config keys on and an agent's JSON reply reaches the client as an [A2UI](https://a2ui.org/) document: `result` carries the object and `media_type` names the format, over REST, MCP and AG-UI alike. [Learn more →](./advanced/a2ui.md)
- **Realtime multi-agent handoffs**: A voice call moves between agents with the OpenAI Agents SDK's handoffs or Google ADK's transfers, and in LiveKit every agent appears as its own participant, with only the active one unmuted. [Learn more →](./integrations/livekit.md#multi-agent-handoffs)
- **Human in the Loop**: Let a run pause for a person's approval or answer, and resume from their decision minutes or hours later, on any replica. Works on OpenAI, LangGraph, Pydantic AI, Google ADK and Microsoft Agent Framework, over REST, streaming, AG-UI, and from a Slack or Telegram message with buttons on it. [Learn more →](./advanced/human-in-the-loop.md)
- **LiveKit Voice Integration**: Connect OpenAI Agents SDK and Google ADK agents to LiveKit WebRTC rooms through the realtime execution pipeline. [Learn more →](./integrations/livekit.md)
- **Microsoft Agent Framework**: Run agents built with Microsoft Agent Framework (the successor to AutoGen and Semantic Kernel) through `MAFModule`, with token streaming, sessions, portable tools, structured output, and framework context round-trips. [Learn more →](./frameworks/microsoft-agents.md)
- **Per-agent native run options**: Pass each framework's own run arguments (OpenAI `RunHooks`, `RunConfig` and `max_turns`, LangGraph `config`, ADK `plugins`, Pydantic AI `usage_limits`, CrewAI `step_callback`, smolagents `max_steps`, Microsoft Agent Framework `options`) through `Module.run_options`, statically or computed per run by a factory, with the keys OAK owns kept safe. [Learn more →](./core-concepts/runner.md#native-run-options)
- **On-Prem Kubernetes**: Official Helm chart that runs the queue pipeline on any cluster (bare metal, EKS, or a laptop k3d), with NATS, Kafka, or SQS as the broker, KEDA autoscaling, a sandbox worker tier, and air-gapped installs. [Learn more →](/docs/deployment/onprem-kubernetes)
- **Scheduling**: Defer chat execution to a later moment or a recurring cadence (`at`/`cron`), with a management REST API and agent-facing scheduling tools. [Learn more →](./advanced/scheduling.md)
- **Sandbox**: Let agents execute code and shell commands in an isolated, permission-bounded environment, with pluggable providers, workload profiles, per-user identity, and per-profile language and package-install permissions. [Learn more →](/docs/advanced/sandbox)
