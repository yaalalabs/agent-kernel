# Agent Skills for Agent Kernel

This spec describes the design and implementation plan for Agent Skills — structured, machine-readable guides that coding agents (GitHub Copilot, Claude Code, Codex, etc.) can follow to help developers build, extend, and deploy AI agents with Agent Kernel.

## Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Developer skills in `.agents/skills/` |
| Phase 2 | ✅ Complete | User skills bundled in `agentkernel` PyPI package |
| Phase 3 | ✅ Complete | `ak` CLI with `skill list/install/update` subcommands |
| Phase 4 | ⏳ Deferred | Copilot Agent Plugin & Claude marketplace plugin |
| Phase 5 | ✅ Complete | Documentation updates |

## Overview

### Problem

AI agent developers need to perform many tasks when building with Agent Kernel: scaffolding projects, adding integrations, deploying to cloud, adding capabilities, etc. These tasks are well-documented but require manual reading and translation into code.

### Solution

Ship machine-readable "skills" that coding agents discover and execute automatically. A user describes what they want in natural language, and the coding agent reads the relevant skill to generate correct, idiomatic code.

### Standard

All skills use the [Agent Skills Open Standard](https://agentskills.io) — `SKILL.md` files with YAML frontmatter. This standard is supported by GitHub Copilot, Claude Code, OpenAI Codex, Cursor, Windsurf, and other coding agents.

### Skill Format

```markdown
---
name: skill-name
description: Brief description for discovery (~100 tokens)
version: 0.1.0
---

# Skill Title

Step-by-step instructions, code templates, checklists (<5000 tokens total)
```

Progressive disclosure model:
- **Discovery** (~100 tokens): YAML frontmatter for agent to decide relevance
- **Activation** (<5000 tokens): Full markdown body with instructions
- **Execution**: Agent follows instructions using existing tools (file creation, shell commands)

## Two-Tier Skill Architecture

### Tier 1 — Developer Skills (for contributors)

**Location**: `.agents/skills/` at repository root

These skills help developers contributing to Agent Kernel itself. They are part of the repo and discovered automatically by coding agents when a developer opens the project.

| Skill | Purpose |
|---|---|
| `ak-dev-architecture` | Core abstractions (Session, Agent, Runner, Module, Runtime, AgentService, AKConfig), design principles (framework-agnostic core, adapter pattern, config-driven, session lifecycle, plugin architecture), directory structure, execution flow |
| `ak-dev-new-framework-integration` | 14-step guide to add a new agent framework adapter: session state class, Runner subclass, Agent wrapper, ToolBuilder, Module, public API, optional deps, tracing, tests, examples |
| `ak-dev-new-messaging-integration` | 12-step guide to add a new messaging platform: RESTRequestHandler subclass, webhook routes, message parsing, config, webhook verification, message chunking |
| `ak-dev-new-guardrail-provider` | Adding input/output guardrails: base provider class, InputGuardrail (PreHook), OutputGuardrail (PostHook), factory registration, config, fail-open policy |
| `ak-dev-new-tracing-provider` | Adding observability/tracing: BaseTrace interface, traced runners, factory registration, transparent tracing |
| `ak-dev-testing-conventions` | Testing patterns: pytest, async testing, DummyRunner/DummyAgent, monkeypatching config, session context tests, hook testing, Test.compare(), test modes |
| `ak-dev-code-quality` | Standards: black/isort (150 line length core, 120 examples), conventional commits, PR workflow, version bumping via `scripts/bump_version.py` |

### Tier 2 — User Skills (for end users)

**Location**: `ak-py/src/agentkernel/skills/` (bundled in PyPI package)

These skills help end users building agent projects with Agent Kernel. They are distributed via the `agentkernel` PyPI package and installed into user projects via the `ak skill install` CLI command.

| Skill | Purpose |
|---|---|
| `ak-init` | Interactive scaffolding for all 4 frameworks (OpenAI, CrewAI, LangGraph, ADK) × all deployment modes (CLI, API, Lambda, Functions, containerized). Complete code templates for each combination. |
| `ak-build` | Add tools, agents, and handoffs to an existing project. Reads the project's framework, agents, tools, and config first, then generates context-aware code. Covers all 4 frameworks with gotcha guards. |
| `ak-add-integration` | Add messaging integrations: Slack, WhatsApp, Messenger, Instagram, Telegram, Gmail. Per-platform config, code, env vars, setup instructions. Multiple integrations pattern. |
| `ak-cloud-deploy` | Deploy to AWS or Azure: 4 deployment modes (AWS Lambda, AWS ECS Fargate, Azure Functions, Azure Container Apps). Complete Terraform files (main.tf, variables.tf, outputs.tf, terraform.tfvars, backend.tf, Dockerfile, deploy.sh). |
| `ak-add-capabilities` | Add guardrails (OpenAI/Bedrock/WalledAI), tracing (Langfuse/OpenLLMetry), session persistence (Redis/DynamoDB/CosmosDB), MCP, A2A, custom hooks (PreHook/PostHook), multimodal. |
| `ak-test` | Test setup (fuzzy/judge/fallback modes, CLI/API patterns) + 8 debugging scenarios: no agents available, session not persisting, ToolContext errors, guardrail blocking, import errors, Redis connection, Terraform failures, webhook issues. |

## CLI Design

### Entry Point

```toml
# ak-py/pyproject.toml
[project.scripts]
ak = "agentkernel.cli.ak:main"
```

### Commands

```bash
ak skill list                          # List all bundled skills
ak skill assistants                    # List supported coding assistants
ak skill install                       # Install all skills (default: copilot)
ak skill install <name>                # Install a specific skill
ak skill install --assistant claude    # Install for Claude Code → .claude/commands/
ak skill install --assistant cursor    # Install for Cursor → .cursor/rules/
ak skill install --target PATH         # Install to custom directory
ak skill update                        # Force-overwrite existing skills
ak skill update --assistant claude     # Update for a specific assistant
```

### Supported Assistants

| Assistant  | Directory          | Description                          |
|------------|--------------------|--------------------------------------|
| `copilot`  | `.agents/skills`   | GitHub Copilot (default)             |
| `claude`   | `.claude/commands`  | Claude Code (Anthropic)              |
| `cursor`   | `.cursor/rules`    | Cursor IDE                           |
| `windsurf` | `.windsurf/rules`  | Windsurf (Codeium)                   |
| `codex`    | `.codex/skills`    | Codex CLI (OpenAI)                   |
| `aider`    | `.aider/skills`    | Aider                                |

### Implementation

- `ak-py/src/agentkernel/cli/ak.py` — argparse-based `AK` CLI class, uses `Skill` for all operations
- `ak-py/src/agentkernel/skills/skills.py` — `Skill` class (discovery, install), `Assistant` dataclass, `ASSISTANTS` registry
- `ak-py/src/agentkernel/skills/__init__.py` — thin wrappers (`get_skills_dir()`, `list_skills()`) for backward compatibility
- Skills copied via `shutil.copytree()` with `__pycache__`/`.pyc` exclusion
- YAML frontmatter parsed with stdlib regex (no external deps)
- `--assistant` resolves target directory from `ASSISTANTS` registry; `--target` overrides

## Phase 4 — Distribution (Deferred)

### Copilot Agent Plugin

Create a repository `yaalalabs/agentkernel-copilot-plugin` containing user skills formatted as a Copilot Agent Plugin. Register in the GitHub Awesome Copilot marketplace.

### Claude Marketplace Plugin

Package user skills for Claude's marketplace. Submit for review.

### Implementation Notes

- Both plugins would contain the same 5 user skills
- Plugin metadata wraps the SKILL.md content in platform-specific formats
- Skills remain the canonical source; plugins are generated from them

## Phase 5 — Documentation

### Files Updated

| File | Change |
|---|---|
| `ak-py/README.md` | Added "Agent Skills" section before "Extensibility" — CLI commands, skills table, example workflow |
| `DEVELOPER_GUIDE.md` | Added "Agent Skills for Contributors" section — lists all 7 dev skills, usage examples |
| `CONTRIBUTING.md` | Added "Agent Skills" section after "Developer Guide" — brief reference to `.agents/skills/` |
| `docs/docs/agent-skills.md` | New docs site page — full guide with all skills, CLI usage, compatibility matrix |
| `docs/sidebars.js` | Added `agent-skills` entry after `quick-start` |

## File Inventory

```
.agents/skills/
├── ak-dev-architecture/SKILL.md
├── ak-dev-code-quality/SKILL.md
├── ak-dev-new-framework-integration/SKILL.md
├── ak-dev-new-guardrail-provider/SKILL.md
├── ak-dev-new-messaging-integration/SKILL.md
├── ak-dev-new-tracing-provider/SKILL.md
└── ak-dev-testing-conventions/SKILL.md

ak-py/src/agentkernel/
├── cli/
│   └── ak.py                          # ak CLI entry point
└── skills/
    ├── __init__.py                     # get_skills_dir(), list_skills() wrappers
    ├── skills.py                       # Skill class, Assistant dataclass, ASSISTANTS registry
    ├── ak-add-capabilities/
    │   ├── SKILL.md
    │   └── evals/evals.json
    ├── ak-add-integration/
    │   ├── SKILL.md
    │   └── evals/evals.json
    ├── ak-build/
    │   ├── SKILL.md
    │   └── evals/evals.json
    ├── ak-cloud-deploy/
    │   ├── SKILL.md
    │   └── evals/evals.json
    ├── ak-init/
    │   ├── SKILL.md
    │   └── evals/evals.json
    └── ak-test/
        ├── SKILL.md
        └── evals/evals.json

.vscode/settings.json                  # chat.agentSkillsLocations config
```

## Design Decisions

1. **SKILL.md standard over proprietary formats**: Ensures cross-agent compatibility. One skill works with Copilot, Claude Code, Codex, Cursor, Windsurf.

2. **`.agents/skills/` over `.github/skills/`**: Vendor-neutral path. Not tied to GitHub.

3. **Bundled in `agentkernel` over separate PyPI package**: Users already install `agentkernel`. No extra dependency. Skills stay in sync with library version.

4. **`ak skill install` over auto-discovery from package**: Users explicitly control what's in their project. Skills are visible in `.agents/skills/` for inspection and customization.

5. **argparse over click/typer**: Zero additional dependencies. The CLI is simple enough for stdlib.

6. **YAML frontmatter parsed with stdlib**: No dependency on `pyyaml`. Simple regex-based extraction of name/description fields.

## Thought Process & Decision Journal

This section captures the reasoning and evolution of decisions throughout the project, so the context is preserved for future sessions.

### Starting Point — The Core Idea

The goal was to make Agent Kernel "coding-agent-friendly" — not just well-documented for humans, but structured so that AI coding agents (Copilot, Claude Code, Codex, etc.) can autonomously help users build, extend, and deploy agents. Two distinct audiences emerged early:

1. **Contributors** who work on Agent Kernel itself (adding frameworks, integrations, providers)
2. **End users** who build their own agent projects using Agent Kernel as a dependency

These are fundamentally different workflows — contributors need to understand AK internals; users need recipes for their own projects. This drove the **two-tier architecture**.

### Skills Standard — Why SKILL.md

Evaluated multiple approaches:
- **AGENTS.md** (single monolithic file) — too large, no discovery mechanism, hard to maintain
- **Proprietary formats** (Copilot-specific, Claude-specific) — locks into one ecosystem
- **Agent Skills Open Standard** (agentskills.io, SKILL.md) — vendor-neutral, progressive disclosure (frontmatter for discovery, body for execution), supported by multiple agents

Chose SKILL.md because AK itself is framework-agnostic, so the skills should be agent-agnostic too. The progressive disclosure model (discovery ~100 tokens → activation <5000 tokens) was a strong fit — agents don't need to read everything, just what's relevant.

### Directory Path — `.agents/skills/` not `.github/skills/`

Initial plan used `.github/skills/` following some early conventions. Changed to `.agents/skills/` because:
- AK is not GitHub-specific — it deploys to AWS and Azure, supports multiple frameworks
- `.agents/` is vendor-neutral and self-descriptive
- Avoids confusion with GitHub Actions, GitHub-specific configs already in `.github/`

### Distribution — Bundled, Not Separate

Initial plan was a separate `agentkernel-skills` PyPI package. Changed to bundling inside `agentkernel` because:
- Users already `pip install agentkernel` — no extra step
- Skills are tightly coupled to library version (code templates reference specific APIs)
- Version drift between skills package and library would cause broken templates
- `ak skill install` copies skills into the user's project, making them inspectable and customizable

### CLI — `ak skill install` not `ak-skills install`

Initially planned a separate `ak-skills` CLI. Changed to `ak skill` subcommand because:
- `ak` is the natural top-level command for the Agent Kernel ecosystem
- Subcommand pattern (`ak skill`, and future `ak deploy`, `ak test`, etc.) is more scalable
- Single entry point in pyproject.toml: `ak = "agentkernel.cli.ak:main"`

### Naming — `ak-dev-` Prefix for Developer Skills

Added `ak-dev-` prefix to developer skills to:
- Clearly distinguish them from user skills when both are in the same `.agents/skills/` directory
- Signal that these are internal/contributor skills, not end-user workflows
- Make it easy to filter/search (e.g., `ls .agents/skills/ak-dev-*`)

User skills don't have a prefix — they're the primary audience and should have clean names (e.g., `ak-init`, not `ak-user-scaffold-agent-project`).

### What's In Each Developer Skill and Why

- **`ak-dev-architecture`**: The "orientation" skill. A contributor's first question is "how does this all fit together?" This skill maps the core abstractions, design principles, directory layout, and execution flow. Without this, every other skill lacks context.

- **`ak-dev-new-framework-integration`**: The most common contribution type. AK's value proposition is multi-framework support, so adding a new framework adapter should be a well-paved path. The 14-step guide was derived by studying the existing OpenAI, CrewAI, LangGraph, and ADK adapters and extracting the common pattern.

- **`ak-dev-new-messaging-integration`**: Second most common contribution. The Slack integration was used as the reference implementation — webhook handling, message parsing, config registration, chunking.

- **`ak-dev-new-guardrail-provider`** and **`ak-dev-new-tracing-provider`**: These follow a factory/registry pattern. The skills document the base classes, registration mechanism, and config integration.

- **`ak-dev-testing-conventions`**: Testing is where contributors most often get stuck (async patterns, session mocking, DummyRunner). The skill codifies patterns that would otherwise require reading multiple test files.

- **`ak-dev-code-quality`**: Prevents common PR friction — wrong line length, non-conventional commits, missing formatting. This is the "read before your first PR" skill.

### What's In Each User Skill and Why

- **`ak-init`**: The entry point for new users. Covers 4 frameworks × multiple deployment modes. Each combination has complete, copy-pasteable templates (app.py, config.yaml, pyproject.toml, build.sh). The coding agent asks the user which framework and deployment mode, then generates everything.

- **`ak-build`**: The workhorse skill for iterative development. After `ak-init` scaffolds a project, users spend most of their time adding tools, agents, and handoffs — that's `ak-build`. It reads the existing project first (framework, agents, tools, config) then generates context-aware code. Includes a gotchas table covering all 4 frameworks (LangGraph `name=`, CrewAI `role=`, ADK `LiteLlm()`, ToolContext usage).

- **`ak-add-integration`**: After scaffolding, the most common next step is "connect my agent to Slack/WhatsApp/etc." Each platform has its own section with config changes, code changes, env vars, and setup instructions (e.g., creating a Slack app, setting up Meta webhooks).

- **`ak-cloud-deploy`**: Complete Terraform configurations for all 4 deployment targets. Users shouldn't have to write Terraform from scratch — the skill generates all files (main.tf, variables.tf, outputs.tf, terraform.tfvars, backend.tf, Dockerfile, deploy.sh) using AK's published Terraform modules.

- **`ak-add-capabilities`**: A "shopping list" skill — pick what you need (guardrails, tracing, session persistence, MCP, A2A, hooks, multimodal) and get the exact config + code. Each capability is independent.

- **`ak-test`**: Combines test setup (often overlooked) with a debugging FAQ. The 8 debugging scenarios were chosen based on the most common issues: misconfigured agents, session problems, import errors, infrastructure failures.

### Phase 4 Deferral Reasoning

Copilot Agent Plugin and Claude marketplace plugin were deferred because:
- The skills already work via `.agents/skills/` directory convention — no plugin needed for basic functionality
- Plugin submission processes and formats may change — better to stabilize the skills first
- The PyPI distribution (`ak skill install`) covers the primary use case

### Skill Renaming — `ak-` Prefix for User Skills

Originally, user skills had plain descriptive names: `scaffold-agent-project`, `add-capabilities`, `add-integration`, `deploy-to-cloud`, `test-and-debug`. These were renamed in stages:

1. **`scaffold-agent-project` → `ak-init`**: The original name was too verbose and didn't match the CLI naming convention. `ak-init` is concise, follows the `<namespace>-<action>` pattern (like `git init`, `npm init`), and clearly signals it's an Agent Kernel command.

2. **Remaining skills got `ak-` prefix**: `add-capabilities` → `ak-add-capabilities`, `add-integration` → `ak-add-integration`, `deploy-to-cloud` → `ak-cloud-deploy`, `test-and-debug` → `ak-test`. This namespaces user skills under `ak-` so they're immediately recognizable as Agent Kernel skills when installed alongside other projects' skills in `.agents/skills/`.

The naming now follows two conventions:
- **Developer skills**: `ak-dev-*` (7 skills) — for contributors to the AK codebase
- **User skills**: `ak-*` without `dev` (5 skills) — for end users building with AK

### `Skill` Class Refactor — From Functions to OOP

Initially, skill discovery and installation logic was scattered:
- `__init__.py` had `get_skills_dir()` and `list_skills()` with inline frontmatter parsing
- `ak.py` had `_get_skills_source_dir()`, `_parse_skill_frontmatter()`, `_get_available_skills()`, and `_copy_skill()` — all duplicating the same logic

This was refactored into a `Skill` class in `skills.py`:
- `Skill.list_all()` — class method replaces both `list_skills()` and `_get_available_skills()`
- `Skill.find(name)` — class method for single-skill lookup
- `skill.install(target, force=...)` — instance method replaces `_copy_skill()`
- `skill.exists` — property for validation
- `Skill._parse_frontmatter()` — single implementation for YAML parsing

The `__init__.py` functions (`get_skills_dir()`, `list_skills()`) were preserved as thin wrappers around the `Skill` class for backward compatibility. The `AK` CLI class now imports and uses `Skill` directly — no more internal helper methods.

### Multi-Assistant Support — `--assistant` Flag

The original design assumed all coding agents use `.agents/skills/`. In practice, each assistant has its own convention for where to discover skills/commands:

| Assistant | Directory | Convention Source |
|-----------|-----------|-------------------|
| GitHub Copilot | `.agents/skills` | Agent Skills Open Standard |
| Claude Code | `.claude/commands` | Anthropic's custom commands |
| Cursor | `.cursor/rules` | Cursor rules directory |
| Windsurf | `.windsurf/rules` | Windsurf rules directory |
| Codex CLI | `.codex/skills` | OpenAI convention |
| Aider | `.aider/skills` | Aider convention |

Rather than force users to manually copy skills to different directories, the `ak skill install --assistant <name>` flag resolves the correct target directory automatically. Key decisions:

1. **`--assistant` and `--target` are mutually exclusive**: `--target` is the escape hatch for custom locations; `--assistant` covers the standard cases. Using both would be ambiguous.

2. **`copilot` is the default**: Most users will start with Copilot (it's the most widely installed coding agent). Running `ak skill install` without flags installs to `.agents/skills/`.

3. **Registry lives in `skills.py`**: The `ASSISTANTS` dict and `Assistant` dataclass are in the skills module, not the CLI. This means other tools (scripts, tests, future APIs) can access the registry without importing the CLI.

4. **`ak skill assistants` subcommand**: Users need to discover what's supported. This is more useful than burying the list in `--help` output, and it shows the actual directories each assistant uses.

5. **Same SKILL.md for all assistants**: The skill content is identical regardless of target. We don't transform or adapt the SKILL.md per assistant — it's the same file copied to a different directory. If an assistant needs a different format in the future, that transformation would happen at copy time (not implemented yet — deferred until needed).
- Can revisit once skill content is validated by real users

### Known Issues & Future Considerations

- **`ak` CLI config warning**: Running `ak --help` shows `WARNING: Could not open yaml settings file at: config.yaml` because importing the `agentkernel.cli` namespace triggers `AKConfig` initialization. This is harmless (config file only exists in agent projects, not the dev repo) but could be addressed by lazy-loading in `cli/__init__.py`.

- **Skill versioning**: Skills currently don't have independent version tracking. If skills evolve independently of the library, may need a version field in frontmatter and a version check in `ak skill update`.

- **User skill customization**: After `ak skill install`, users can edit the SKILL.md files in their project. `ak skill update` will overwrite customizations. Could add a merge/diff strategy in the future.

- **Skill testing**: No automated tests for skill content correctness yet. Could add a CI step that validates SKILL.md frontmatter format and checks that referenced code patterns still match the actual codebase.

- **User skills prefix**: User skills use an `ak-` prefix for namespacing (e.g., `ak-init`, `ak-build`). If the number of skills grows significantly, we may want to formalize and document this convention further, but the existing `ak-` prefix scheme is currently sufficient.

### RFC Alignment (ak-build, Eval Suites, Progressive Disclosure)

After comparing the implementation against AFC-01 (Agent Kernel Skills for Claude Code, by Ishan De Silva), three gaps were identified and addressed:

1. **`ak-build` skill**: The RFC's `/ak-build` was the workhorse command — "add a tool/agent to an existing project." Our implementation had `ak-init` for scaffolding and `ak-add-capabilities` for features, but nothing for the core iterative loop of adding tools and agents. `ak-build` fills this gap. It reads the project first (framework, agents, tools, config), then generates framework-specific code with gotcha guards (LangGraph `name=`, CrewAI `role=`, ADK `LiteLlm()`, ToolContext patterns).

2. **Eval suites**: Each skill now has an `evals/evals.json` file defining test scenarios with `expected_outputs` and `must_not_contain` arrays. These validate that the skill produces correct, framework-specific output. For example, `ak-build`'s evals verify that CrewAI output uses `role=` not `name=`, and that LangGraph output includes `name=` in `create_react_agent()`. Evals are structured for automated validation in CI.

3. **"What to do next" progressive disclosure**: Every skill now ends with a "What to Do Next" section that suggests natural next steps and references other skills. This creates a guided arc: `ak-init → ak-build (iterate) → ak-add-capabilities / ak-add-integration → ak-cloud-deploy → ak-test`. Users are never left wondering "what now?" after completing a skill.

