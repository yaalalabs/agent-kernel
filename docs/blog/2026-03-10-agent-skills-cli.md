---
slug: /agent-skills-cli
title: "Agent Skills: Agent Kernel Builds Enterprise Agents for You"
authors: [yaala]
tags: [agent-kernel, skills, cli, copilot, claude, cursor, windsurf, developer-experience]
image: /img/card.png
---

# Agent Skills: Agent Kernel Builds Enterprise Agents for You

What if you never had to read a single page of Agent Kernel documentation?

What if you didn't need to know which agentic framework to use, how to wire handoffs, how to configure session persistence, or how to write Terraform for a cloud deployment?

What if you just told your coding assistant what you wanted — and Agent Kernel handled the rest?

**That's exactly what Agent Skills deliver.**

<!-- truncate -->

## Agent Kernel Exposes Its Entire Capability Set as Skills

This is the idea that changes everything: **Agent Kernel doesn't ask you to learn it. It teaches your coding assistant instead.**

Every feature Agent Kernel supports — every framework, every deployment target, every integration, every capability — is packaged as a skill that your coding assistant can read and act on. The skills contain the same knowledge the Agent Kernel team has: the right patterns, the right config keys, the right import paths, the right framework-specific gotchas, the right Terraform modules. All of it.

When you install Agent Kernel skills, you're not installing a tutorial. You're giving your coding assistant **the complete expertise to develop and deploy enterprise AI agents on your behalf.** You describe what you want in plain English. Your assistant — armed with Agent Kernel's own skills — writes the code, wires the config, and gets it right.

No documentation to read. No experience required. No trial and error.

## You Don't Need to Be a Developer

Traditional agent frameworks assume you're an experienced developer. You need to understand framework APIs, deployment infrastructure, config formats, dependency management. The learning curve is steep and the documentation is long.

Agent Kernel takes a radically different approach. By publishing its capabilities as skills, Agent Kernel puts its expertise directly into the hands of your coding assistant. The assistant becomes the developer. You become the director.

Want an enterprise agent that handles customer support across Slack and WhatsApp, with guardrails, session persistence, and tracing — deployed to AWS? Here's your workflow:

> *"Create a new agent project using OpenAI with REST API"*
>
> *"Add a triage agent, a support agent, and a billing agent with handoffs"*
>
> *"Add Slack and WhatsApp integration"*
>
> *"Add Redis session persistence, Bedrock guardrails, and Langfuse tracing"*
>
> *"Deploy to AWS Lambda with DynamoDB sessions"*
>
> *"Set up automated testing with judge mode"*

Six prompts. No documentation. No framework expertise. A production-grade enterprise agent — scaffolded, built, integrated, hardened, deployed, and tested.

Each prompt activates a different Agent Kernel skill. Each skill tells your coding assistant exactly what to do — not in vague terms, but with precise instructions covering every framework Agent Kernel supports: OpenAI Agents SDK, CrewAI, LangGraph, and Google ADK.

## Everything Agent Kernel Can Do, Packaged as Six Skills

Agent Kernel publishes six skills that span the entire agent development lifecycle. Together, they cover **every feature Agent Kernel supports**:

### ak-init — Scaffold a Complete Project

Your assistant creates a production-ready project structure: `pyproject.toml` with the right extras, agent file, tool file, config, build script, and tests. It knows the correct setup for all four frameworks and both deployment modes (containerized and serverless).

> *"Create a new agent project using CrewAI with REST API"*

### ak-build — Add Tools, Agents, and Handoffs

The skill you'll use the most. Your assistant reads your existing project — identifies the framework, lists existing agents and tools, checks the entry point — then generates code that fits seamlessly into what's already there. It knows the handoff wiring for every framework: `handoffs=` for OpenAI, `create_supervisor()` for LangGraph, `sub_agents=` for ADK, crew composition for CrewAI.

> *"Add a weather lookup tool and a support agent with handoffs to billing"*

### ak-add-capabilities — Guardrails, Tracing, Sessions, MCP, A2A, and More

Your assistant adds enterprise capabilities with the correct config, code, and dependencies. This single skill covers guardrails (OpenAI, Bedrock, Walled AI), tracing (Langfuse, OpenLLMetry), session persistence (Redis, DynamoDB, Cosmos DB), MCP server exposure, A2A protocol, lifecycle hooks, and multimodal support.

> *"Add Redis session persistence and Langfuse tracing"*

### ak-add-integration — Connect Messaging Platforms

Your assistant generates the handler class, environment variables, config block, and webhook setup for Slack, WhatsApp, Messenger, Instagram, Telegram, or Gmail — correctly, the first time.

> *"Add Slack and WhatsApp integration"*

### ak-cloud-deploy — Deploy to AWS or Azure

Your assistant generates complete Terraform configurations for AWS Lambda, AWS ECS/Fargate, Azure Functions, or Azure Container Apps. Includes IAM roles, networking, environment variables, and container registry setup.

> *"Deploy my agent to AWS Lambda"*

### ak-test — Test and Debug

Your assistant configures test modes (fuzzy, judge, fallback), generates test patterns, and knows how to diagnose the most common issues — from tool binding errors to session conflicts.

> *"Set up automated testing for my agent"*

## Skills Know Every Framework

Each skill isn't a generic template — it contains **framework-specific knowledge for all four agentic frameworks** Agent Kernel supports. When your assistant reads a skill, it learns the differences that trip up even experienced developers:

| Pattern | OpenAI | LangGraph | CrewAI | Google ADK |
|---------|--------|-----------|--------|------------|
| Agent identity | `name=` | `name=` in `create_react_agent()` | `role=` (not `name=`) | `name=` |
| Model wrapping | Direct string | Direct string | Direct string | `LiteLlm()` wrapper |
| Handoff wiring | `handoffs=` | `create_supervisor()` | Module composition | `sub_agents=` |

Your assistant doesn't guess which pattern to use. The skill tells it. The code is correct on the first try.

## A Guided Journey, Not Isolated Commands

The six skills form a natural progression. Each skill ends with a "What to do next" section that points your assistant to the logical next step:

**`ak-init`** → **`ak-build`** ↻ → **`ak-add-capabilities`** / **`ak-add-integration`** → **`ak-cloud-deploy`** → **`ak-test`**

Your assistant doesn't just answer your current question — it knows where you are in the development journey and guides you forward. Start with scaffolding, iterate on tools and agents, layer in enterprise capabilities, connect messaging platforms, deploy to cloud, and validate with tests.

You never have to figure out "what comes next." The skills already know.

## Works With Every Major Coding Assistant

Agent Skills work with GitHub Copilot, Claude Code, Cursor, Windsurf, Codex, and Aider. The `ak` CLI installs skills into the right directory for each assistant:

```bash
pip install agentkernel

# Install skills (defaults to GitHub Copilot)
ak skill install

# Or pick your assistant
ak skill install --assistant claude     # → .claude/skills/
ak skill install --assistant cursor     # → .cursor/skills/
ak skill install --assistant windsurf   # → .windsurf/skills/
ak skill install --assistant codex      # → .codex/skills/
ak skill install --assistant aider      # → .aider/skills/
```

Browse and explore:

```bash
ak skill list                  # See all 6 skills
ak skill info ak-build         # Full description of a skill
ak skill assistants            # See supported assistants
```

## Built on an Open Standard

Agent Skills follow the [SKILL.md open standard](https://agentskills.io) — plain Markdown files with YAML frontmatter that coding assistants automatically discover. Each skill is lean (under 5000 tokens) so your assistant reads it fully, and precise enough to produce correct code without trial and error.

Every skill also ships with an `evals/evals.json` — structured test scenarios that validate the assistant's output. These evals are the contract: if the assistant passes them, the generated code is correct Agent Kernel code.

## Three Commands. No Docs. Enterprise Agents.

```bash
# 1. Install
pip install agentkernel

# 2. Give your assistant Agent Kernel's expertise
ak skill install

# 3. Tell it what to build
# "Create a multi-agent system with triage, support, and billing"
# "Add Slack integration and Redis sessions"
# "Deploy to AWS Lambda and set up testing"
```

You don't read the documentation. You don't learn the framework. You don't study the deployment patterns. **Agent Kernel's skills already know all of it — and they teach your coding assistant so it can build enterprise agents for you.**

---

*Agent Skills follow the [SKILL.md open standard](https://agentskills.io). Agent Kernel is open-source under the Apache 2.0 license. [Get started →](/docs)*
