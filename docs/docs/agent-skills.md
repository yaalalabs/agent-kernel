---
sidebar_position: 3
---

# Agent Skills

Agent Kernel ships with **Agent Skills** — structured guides that coding agents (GitHub Copilot, Claude Code, Codex, etc.) can follow to help you build, extend, and deploy AI agents. Skills use the [Agent Skills Open Standard](https://agentskills.io) (SKILL.md format) for cross-agent compatibility.

## What Are Agent Skills?

Agent Skills are machine-readable guides that coding agents discover and follow automatically. Instead of reading documentation yourself and translating it into code, you describe what you want in natural language and the coding agent reads the relevant skill to generate correct, idiomatic code for Agent Kernel.

Each skill is a `SKILL.md` file with:
- **YAML frontmatter** — name, description, metadata for discovery (~100 tokens)
- **Markdown body** — step-by-step instructions, code templates, checklists (<5000 tokens)

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

Interactively scaffold a new Agent Kernel project. Covers all four supported frameworks (OpenAI Agents SDK, CrewAI, LangGraph, Google ADK) and all deployment modes (CLI, REST API, AWS Lambda, Azure Functions, containerized).

**Example prompts:**
- *"Create a new agent project using CrewAI for AWS Lambda"*
- *"Scaffold a LangGraph project with REST API"*

### ak-build

Add tools, agents, and handoffs to an existing project. The workhorse skill for iterative development — reads your project's framework, existing agents, and config, then generates context-aware code for new tools, agents, and routing.

**Example prompts:**
- *"Add a weather lookup tool to my agent"*
- *"Add a support agent and wire it into the triage handoffs"*
- *"Add a new tool that accesses session state"*

### ak-add-integration

Add messaging platform integrations to an existing project. Covers Slack, WhatsApp, Messenger, Instagram, Telegram, and Gmail with complete configuration and setup instructions.

**Example prompts:**
- *"Add Slack integration to my agent"*
- *"Set up WhatsApp and Telegram for my project"*

### ak-cloud-deploy

Deploy your agent to AWS or Azure. Generates complete Terraform configurations for four deployment modes: AWS Serverless (Lambda), AWS Containerized (ECS Fargate), Azure Serverless (Functions), and Azure Containerized (Container Apps).

**Example prompts:**
- *"Deploy my agent to AWS Lambda"*
- *"Set up Azure Container Apps deployment"*

### ak-add-capabilities

Add advanced capabilities: guardrails (OpenAI Moderation, AWS Bedrock), tracing (Langfuse, OpenLLMetry), session persistence (Redis, DynamoDB, Cosmos DB), MCP server, A2A server, custom hooks, and multimodal support.

**Example prompts:**
- *"Add OpenAI guardrails to my agent"*
- *"Set up Redis session persistence"*
- *"Enable Langfuse tracing"*

### ak-test

Set up testing and debug common issues. Covers test modes (fuzzy, judge, fallback), CLI and API test patterns, and 8 common debugging scenarios with solutions.

**Example prompts:**
- *"Set up automated testing for my agent"*
- *"My agent session isn't persisting across requests"*

## Developer Skills

These skills live in `.agents/skills/` at the repository root and help contributors to Agent Kernel:

| Skill | Description |
|---|---|
| `ak-dev-architecture` | Core abstractions, design principles, directory structure, execution flow |
| `ak-dev-new-framework-integration` | Step-by-step guide to add a new agent framework adapter |
| `ak-dev-new-messaging-integration` | Guide to add a new messaging platform integration |
| `ak-dev-new-guardrail-provider` | Guide to add a new guardrail provider |
| `ak-dev-new-tracing-provider` | Guide to add a new observability/tracing provider |
| `ak-dev-testing-conventions` | Testing patterns, async testing, mocking, CI/CD |
| `ak-dev-code-quality` | Formatting standards, commit conventions, PR workflow |

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

## Compatibility

Agent Skills work with any coding agent that supports the [Agent Skills Open Standard](https://agentskills.io), including:

- **GitHub Copilot** (VS Code, JetBrains)
- **Claude Code**
- **OpenAI Codex**
- **Cursor**
- **Windsurf**

Skills are discovered automatically when placed in `.agents/skills/` in your project root.
