# AK Codebase Patterns Relevant to the Sandbox Capability

Findings from a full-repo exploration (2026-07-14, develop branch).

## Verdict

There is no existing sandbox/code-execution capability in the codebase — the
concept is greenfield. The cleanest template is the **guardrail** pattern
(factory + config section + optional extras + system-hook wiring) combined
with the **multimodal storage** pattern (abstract base + `_build_driver`
factory keyed on a `type` string + per-backend config sub-models).

## 1. Existing code-execution mentions: none

- No `sandbox`, `code_executor`, `code_interpreter`, `allow_code_execution`,
  `executor_type`, or subprocess-based execution anywhere in `ak-py/src`.
- Only surface: smolagents' native `CodeAgent` used in
  `examples/cli/smolagents/demo_codeagent.py:27` — user-constructed, no
  executor/sandbox options set, AK does not wrap them.
- `executor`/`docker` hits elsewhere are unrelated (ECS thread runners,
  `docs/node_modules`).

## 2. Framework adapters do NOT pass through native executor options

All five adapters follow "bring-your-own fully-constructed native agent" —
`Module.__init__` takes pre-built native agents and wraps them; no kwargs
pass-through for executor/sandbox settings:

- `framework/smolagents/smolagents.py:292` — `SmolagentsModule.__init__(agents, runner=None)`;
  `_wrap()` (308–317) returns `SmolagentsAgent(name, runner, agent)`. No
  `executor_type` handling.
- `framework/crewai/crewai.py:534` — no `allow_code_execution` /
  `code_execution_mode` handling.
- `framework/adk/adk.py:327` — no `code_executor` handling.
- `framework/openai/openai.py:295` — no `CodeInterpreterTool` handling.
- `framework/langgraph/langgraph.py:449` — graphs pre-compiled by user.

Implication: the sandbox capability should be a **framework-agnostic core
layer** (like guardrails/multimodal), not threaded through adapter
constructors — unless pass-through is deliberately added later.

## 3. The pluggable-capability pattern

### 3a. Guardrail pattern (`ak-py/src/agentkernel/guardrail/guardrail.py`)

- Lines 9–22: no-op base hooks `InputGuardrail(PreHook)` / `OutputGuardrail(PostHook)`.
- Lines 25–45: `InputGuardrailFactory.get()` — reads
  `AKConfig.get().guardrail.input.enabled`, branches on `.type` with **lazy
  per-provider imports**, raises on unknown type, returns no-op when disabled.
  `OutputGuardrailFactory` (48–68) mirrors it.
- Providers: `guardrail/openai.py`, `guardrail/bedrock.py`,
  `guardrail/walledai.py`. `guardrail/__init__.py` is empty — providers are
  imported lazily via full path.

### 3b. Multimodal storage pattern

- `core/multimodal/storage/base.py:31` — `AttachmentStore(ABC)` with abstract
  `save`/`get`/`delete` (34–59); `AttachmentData` dataclass (18–28).
- `core/multimodal/storage/storage_manager.py:32–84` —
  `AttachmentStorageManager._build_driver()`: reads
  `AKConfig.get().multimodal.storage_type`, branches with lazy imports, raises
  `ValueError` when the selected backend's config sub-block is missing.
- `core/multimodal/factory.py:18–32` — `MultimodalPreHookFactory.get()`:
  real hook when enabled, else `NoOpPreHook`, try/except fallback to no-op.

### 3c. System-hook wiring point (`core/runtime.py`)

(Line numbers as of 2026-07-16; the symbol names are authoritative.)

- Line 12: imports guardrail factories; line 28: multimodal factory.
- Line 49: `Runtime._system_pre_hooks = [InputGuardrailFactory.get(), MultimodalPreHookFactory.get()]`
- Line 57: `Runtime._system_post_hooks = [OutputGuardrailFactory.get()]`

If the sandbox is exposed as a system tool (like multimodal's
`AnalyzeAttachmentsTool`) it needs an equivalent injection point; if it's a
hook, it plugs in here directly.

### 3d. Config sections (`core/config.py`)

(Line numbers as of 2026-07-16; the symbol names are authoritative — they
drift whenever `develop` adds config sections.)

- `_GuardrailParamConfig` (~265): `enabled: bool`,
  `type: str = Field(pattern="^(openai|bedrock|walledai)$")`, provider-specific
  optional fields; `_GuardrailConfig` (~275) nests input/output.
- `_MultimodalConfig` (~189): `enabled`, `storage_type` regex enumerating
  backends, optional per-backend sub-models
  (`_MultimodalStorageRedisConfig` ~178, `_MultimodalStorageDynamoDBConfig`
  ~184).
- Root registration: section fields on `class AKConfig` (~378, fields ~379–405)
  via `default_factory`. A new
  `sandbox: _SandboxConfig = Field(default_factory=_SandboxConfig)` goes here.
- Env-overridable: nested `AK_SECTION__FIELD` vars (e.g.
  `AK_SANDBOX__E2B__API_KEY`); singleton via `AKConfig.get()` (~413).

### 3e. Optional dependencies (`ak-py/pyproject.toml`)

`[project.optional-dependencies]` from line 23; one extras group per
capability/provider (`crewai` 34, `langgraph` 39, `smolagents` 45, `redis` 60,
`openai` 74, `adk` 79, `walledai` 84). Sandbox backends each get their own
group (e.g. `e2b = [...]`, or a shared `sandbox-docker = [...]`).

## 4. Dev-skill conventions (`.agents/skills/`)

Each skill is a folder with `SKILL.md`. Frontmatter:

```yaml
---
name: ak-dev-new-guardrail-provider
description: >
  Step-by-step guide ...
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---
```

Structure of `ak-dev-new-*` skills: title → "Existing Providers" table →
"Architecture Overview" → numbered step-by-step (provider file, base class,
factory registration with before/after diff, config in `core/config.py` +
`config.yaml`, pyproject extras, tests in consolidated
`ak-py/tests/test_<capability>.py`, example under `examples/cli/<capability>/`,
docs under `docs/docs/advanced/`) → closing `## Checklist`.

Skills are kept in sync by `ak-dev-sync-skills-from-branch` and
`ak-dev-sync-skills-and-docs-from-commit`.

## 5. Public export patterns

- Top-level `agentkernel/__init__.py`: only `__version__` + `from .core import *`.
- `core/__init__.py`: explicit re-exports (Agent, Runner, Session, models,
  Config, Module, Runtime, AgentService, PreHook/PostHook,
  ToolContext/ToolBuilder, KeyValueCache, ChatService).
- Guardrail/multimodal classes are NOT exported — internal, instantiated by
  factories from config.
- Framework packages export via their own `__init__.py`
  (e.g. `from agentkernel.smolagents import SmolagentsModule`).

Implication: keep sandbox internals unexported and config-driven, but the
BYO-sandbox base class (and any registration hook for custom backends) must be
public API.

## Recommended layout (by analogy)

```
ak-py/src/agentkernel/sandbox/
├── base.py        # Sandbox ABC (+ policy/principal types)
├── factory.py     # SandboxFactory.get() — lazy imports keyed on config type
├── e2b.py         # cloud SaaS backend
├── docker.py      # local/self-hosted backend
├── <provider>.py  # cloud-native backends (bedrock_agentcore, azure, ...)
core/config.py     # _SandboxConfig + registration (~line 340)
core/runtime.py    # wiring point (hook or system-tool injection)
pyproject.toml     # per-backend extras
.agents/skills/ak-dev-new-sandbox-provider/  # contributor guide (future)
```
