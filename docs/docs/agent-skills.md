---
sidebar_position: 3
---

# Agent Skills

Agent Kernel ships with **Agent Skills**: structured guides that coding agents (GitHub Copilot, Claude Code, Codex, etc.) can follow to help you build, extend, and deploy AI agents. Skills use the [Agent Skills Open Standard](https://agentskills.io) (SKILL.md format) for cross-agent compatibility.

## What Are Agent Skills?

Agent Skills are machine-readable guides that coding agents discover and follow automatically. Instead of reading documentation yourself and translating it into code, you describe what you want in natural language and the coding agent reads the relevant skill to generate correct, idiomatic code for Agent Kernel.

Each skill is a `SKILL.md` file with:
- **YAML frontmatter**: name, description, metadata for discovery (~100 tokens)
- **Markdown body**: step-by-step instructions, code templates, checklists (under 5000 tokens)

## Installing Skills

The `ak` CLI (installed with `agentkernel`) can copy bundled skills into your project:

```bash
# List available skills
ak skill list

# List supported coding assistants and their skill directories
ak skill assistants

# Install all skills (default: GitHub Copilot → .agents/skills/)
ak skill install

# Install for a specific coding assistant
ak skill install --assistant claude    # → .claude/commands/
ak skill install --assistant cursor    # → .cursor/rules/
ak skill install --assistant windsurf  # → .windsurf/rules/
ak skill install --assistant codex     # → .codex/skills/
ak skill install --assistant aider     # → .aider/skills/

# Install a single skill
ak skill install ak-init --assistant claude

# Update previously installed skills to latest version
ak skill update
ak skill update --assistant claude
```

### Supported Assistants

| Assistant  | Directory          | Description                          |
|------------|--------------------|--------------------------------------|
| `copilot`  | `.agents/skills`   | GitHub Copilot (VS Code / JetBrains) |
| `claude`   | `.claude/commands`  | Claude Code (Anthropic)              |
| `cursor`   | `.cursor/rules`    | Cursor IDE                           |
| `windsurf` | `.windsurf/rules`  | Windsurf (Codeium)                   |
| `codex`    | `.codex/skills`    | Codex CLI (OpenAI)                   |
| `aider`    | `.aider/skills`    | Aider                                |

Once installed, skills are automatically discovered by the corresponding coding agent.

## Available User Skills

These skills are bundled with the `agentkernel` PyPI package and help you build agent projects:

### ak-init

Interactively scaffold a new Agent Kernel project. Covers all supported frameworks (OpenAI Agents SDK, CrewAI, LangGraph, Google ADK, Smolagents) and all deployment modes (CLI, REST API, AWS Lambda, Azure Functions, containerized).

**Example prompts:**
- *"Create a new agent project using CrewAI for AWS Lambda"*
- *"Scaffold a LangGraph project with REST API"*

### ak-build

Add tools, agents, and handoffs to an existing project. The workhorse skill for iterative development: it reads your project's framework, existing agents, and config, then generates context-aware code for new tools, agents, and routing.

**Example prompts:**
- *"Add a weather lookup tool to my agent"*
- *"Add a support agent and wire it into the triage handoffs"*
- *"Add a new tool that accesses session state"*

### ak-add-integration

Add messaging platform integrations to an existing project. Covers Slack, WhatsApp, Messenger, Instagram, Telegram, Teams, and Gmail with complete configuration and setup instructions.

**Example prompts:**
- *"Add Slack integration to my agent"*
- *"Set up WhatsApp and Telegram for my project"*

### ak-cloud-deploy

Deploy your agent to AWS, Azure, GCP, or any Kubernetes cluster. Generates complete Terraform configurations for six cloud deployment modes, plus Helm-chart deployments to on-prem/baremetal/EKS Kubernetes (the `ak-deployment/ak-k8s` chart: io-handler + agent-runner Deployments over NATS/Kafka/SQS, optional WebSocket gateway tier, KEDA queue-depth autoscaling). Terraform modes: AWS Serverless (Lambda), AWS Containerized (ECS Fargate), Azure Serverless (Functions), Azure Containerized (Container Apps), GCP Serverless (Cloud Run scale-to-zero), and GCP Containerized (Cloud Run always-on). AWS serverless templates also cover `rest_sync`, `rest_async`, `async` (WebSocket), queue/scalable mode, custom API Gateway authorizers, and external artifact sources (`lambda_package_s3` for S3 ZIP, `ecr_image_uri` for pre-built ECR images). AWS containerized supports `ecr_image_uri` for pre-built ECR images alongside local Docker builds, plus a scalable SQS queue mode (`queue_mode = true`) that splits the deployment into a REST/IO ECS service (`ECSIOHandler`) and a separate Agent Runner ECS service (`ECSAgentRunner`) with `sync`/`async` execution modes and DynamoDB-backed response storage.

**Example prompts:**
- *"Deploy my agent to AWS Lambda"*
- *"Set up Azure Container Apps deployment"*
- *"Deploy my agent to GCP Cloud Run"*
- *"Deploy my agent to our on-prem Kubernetes cluster"*

### ak-add-capabilities

Add advanced capabilities: guardrails (OpenAI Moderation, AWS Bedrock), tracing (Langfuse, OpenLLMetry, Logfire), session persistence (Redis, DynamoDB, Cosmos DB, Firestore), knowledge base tools (ChromaDB, Neo4j, Starburst, Open Knowledge Format bundles, and custom adapters), MCP server, A2A server, AG-UI server, custom hooks, multimodal support, conversation thread support (in-memory, Redis, Valkey, DynamoDB, Firestore, Cosmos DB), sandbox code execution, and scheduling (deferred/recurring chat execution, agent-facing scheduling tools).

**Example prompts:**
- *"Add OpenAI guardrails to my agent"*
- *"Set up Redis session persistence"*
- *"Enable Langfuse tracing"*

### ak-test

Set up testing and debug common issues. Covers test modes (score, llm, fallback), pluggable `AKEvaluator` backends (built-in DeepEval, or bring-your-own), CLI and API test patterns, and 8 common debugging scenarios with solutions.

**Example prompts:**
- *"Set up automated testing for my agent"*
- *"My agent session isn't persisting across requests"*

## Developer Skills: Accelerating Contributions with AI

Agent Kernel doesn't just expose its capabilities as skills for users; it also exposes its internals as skills for contributors. The `.agents/skills/` folder at the repository root contains sixteen developer skills that teach coding assistants how to work on the Agent Kernel codebase itself.

When a contributor opens the repository in a coding assistant (Copilot, Claude Code, Cursor, etc.), these skills are automatically discovered. The assistant immediately understands the architecture, adapter patterns, testing conventions, and code quality standards, eliminating the onboarding curve for new contributors.

| Skill | What It Teaches Your Coding Assistant |
|---|---|
| `ak-dev-architecture` | Core abstractions (`Session`, `Agent`, `Runner`, `Module`, `Runtime`, `AgentService`, `ChatService`), design principles, adapter pattern, execution flow, the unified queue execution pipeline (`agentkernel.pipeline`: `QueueMessage`/`QueueTransport`/`ConsumerLoop`, the `in_memory` transport, `AgentRunner`/`ResponseHandler`/`RequestHandler`/`IOHandler`, the `RESTAPI.run` delegation rule, and the relocation shims), and the AWS ECS containerized deployment classes (`ECSIOHandler`, `ECSOutputConsumer`, `ECSAgentRunner`, `ECSStreamAgentRunner`, `ECSSQSConsumer`, `RawQueueConsumer`, `ThreadRunner`), everything needed to understand the codebase |
| `ak-dev-new-framework-integration` | Step-by-step guide to add a new agent framework adapter (beyond OpenAI, CrewAI, LangGraph, Google ADK, Smolagents): subclass creation, dependency wiring, exports, tests |
| `ak-dev-new-messaging-integration` | How to add a new messaging platform integration (beyond Slack, WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail): handler class, webhook routes, message parsing, config |
| `ak-dev-new-knowledgebase-integration` | How to add a new knowledge base backend (beyond ChromaDB, Neo4j, Starburst, Open Knowledge Format): declare capabilities, implement the matching `KnowledgeBase` operations, reuse `DocumentStore` for document-shaped backends, wire dependencies, add contract tests/docs/examples |
| `ak-dev-new-guardrail-provider` | How to add a new content safety provider (beyond OpenAI, Bedrock, Walled AI): input/output guardrails, factory registration, configuration |
| `ak-dev-new-tracing-provider` | How to add a new observability backend (beyond Langfuse, OpenLLMetry, Logfire): `BaseTrace` interface, traced runners, factory wiring |
| `ak-dev-new-multimodal-storage` | How to add a new multimodal attachment storage backend (beyond in-memory, Redis, DynamoDB): storage interface, config wiring, tests, and docs |
| `ak-dev-new-sandbox-provider` | How to add a new sandbox code-execution backend (beyond `local_subprocess`, `docker`, `kubernetes`, `e2b`, `daytona`, `ec2_ssm`): implement the `Sandbox`/`SandboxProvider` ABCs, declare capabilities honestly, factory registration, config block, contract tests |
| `ak-dev-new-queue-transport` | How to add a new queue transport to the execution pipeline (beyond `in_memory`, SQS, Kafka, NATS JetStream): the queue-semantics contract, `QueueTransport`/`TransportConsumer` implementation, factory registration, config and extras, the `QueueTransportContract` suite (fake and live-broker), the transport example, and Helm chart wiring |
| `ak-dev-sync-skills-from-branch` | How to inspect branch commits plus uncommitted changes, then add/update/remove developer and user skills so the skill trees stay aligned with the implemented capability set |
| `ak-dev-sync-docs-from-branch` | How to inspect branch commits plus uncommitted changes, then update root docs, package docs, website docs, deployment READMEs, and example READMEs so documentation matches the implemented behavior |
| `ak-dev-sync-skills-and-docs-from-commit` | How to process a specific commit hash (typically merged to develop), update dev/user skills and documentation based on that commit delta, and support automation PR flows with loop prevention |
| `ak-dev-write-spec` | How to spec a planned change under `docs/specs/<issue-number>-<short-title>/` in three ordered stages: a concise point-form design spec (`design.md`) reviewed first, then a detailed implementation spec (`spec.md`), then a concise iteration-by-iteration plan (`plan.md`) the PR review checks the code against — plus an optional `research/` subfolder preserving the supporting investigation the design cites |
| `ak-dev-review-pr` | Given a PR number or URL, fetch it with the GitHub CLI, review the delta against the architecture/code-quality/testing skills, dedupe findings, and post a single batched review with inline comments |
| `ak-dev-testing-conventions` | Pytest patterns, async testing, mocking external services, pluggable `AKEvaluator` test backends, CI/CD test workflows |
| `ak-dev-code-quality` | Formatting with `black`/`isort`, commit conventions, PR checklist, review workflow |

### How Contributors Benefit

A first-time contributor doesn't need to spend hours reading source code to understand how Agent Kernel is structured. They simply ask their coding assistant:

- *"Add support for a new agent framework called X"* → The assistant reads `ak-dev-new-framework-integration` and generates the complete adapter module with correct subclasses, exports, and tests.
- *"Add a new tracing provider for Datadog"* → The assistant reads `ak-dev-new-tracing-provider` and implements the `BaseTrace` interface, creates traced runners, and wires the factory.
- *"Add Microsoft Teams integration"* → The assistant reads `ak-dev-new-messaging-integration` and scaffolds the handler, webhook routes, config, and example.
- *"Add a new sandbox provider for X"* → The assistant reads `ak-dev-new-sandbox-provider` and implements the `Sandbox`/`SandboxProvider` ABCs, declares capabilities honestly, and wires the factory, config, and contract tests.
- *"Add a RabbitMQ transport for queue mode"* → The assistant reads `ak-dev-new-queue-transport` and implements the `QueueTransport`/`TransportConsumer` ABCs against the queue-semantics contract, wires the factory, config, and extras, and runs the `QueueTransportContract` suite against a fake and a live broker.

The skills carry the same architectural knowledge the core team has: patterns, conventions, where things go, how components interact. Contributors ship features faster because their coding assistant already understands the codebase.

## Example Workflow

1. **Install skills** into your project:
   ```bash
   ak skill install
   ```

2. **Open your project** in VS Code (with Copilot), Claude Code, or Codex

3. **Ask in natural language**, for example:
   - *"Scaffold a new agent project using CrewAI for AWS Lambda"*
   - *"Add Slack and WhatsApp integrations"*
   - *"Deploy to Azure Container Apps"*
   - *"Add Langfuse tracing and Redis session store"*

4. The coding agent reads the relevant skill and **generates all the code**, configuration, and infrastructure files for you.

## Real-World Use Cases

The [`use-cases/`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases) directory in the repository contains complete agent projects built using this exact workflow. Each project starts from a `SPEC.md` describing the agent's purpose, and the coding assistant uses the Agent Kernel skills to generate all code, configuration, and deployment files.

**Example: Waste Sorting Assistant**

The [`waste-sorting-assistant`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases/waste-sorting-assistant) is a domain-specific agent that recommends waste disposal categories based on item material and local recycling rules. It demonstrates:
- OpenAI Agents SDK agent with custom tools
- Agent Kernel session memory for region-specific rules
- AWS Lambda deployment with DynamoDB-backed session persistence

See [`use-cases/README.md`](https://github.com/yaalalabs/agent-kernel/tree/develop/use-cases/README.md) for the full workflow to build your own agent from a spec file.

## Compatibility

Agent Skills work with any coding agent that supports the [Agent Skills Open Standard](https://agentskills.io), including:

- **GitHub Copilot** (VS Code, JetBrains)
- **Claude Code**
- **OpenAI Codex**
- **Cursor**
- **Windsurf**

Skills are discovered automatically when placed in `.agents/skills/` in your project root.
