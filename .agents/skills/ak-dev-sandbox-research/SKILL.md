---
name: ak-dev-sandbox-research
description: >
  Research companion for designing Agent Kernel's pluggable sandbox capability.
  Use this skill when researching sandbox providers, designing the Sandbox
  interface, or resuming/extending the sandbox research effort. Captures the
  agreed scope, research findings (provider landscape, prior-art abstractions,
  AK codebase patterns), design constraints, and open questions.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
  status: research-complete-design-pending
---

# Sandbox Capability Research

## Goal

Add a generic, pluggable sandbox capability to Agent Kernel with no vendor
lock-in: a few built-in backends, a public interface so users can bring their
own sandbox, and a contributor guide (a future `ak-dev-new-sandbox-provider`
skill) that makes integrating new backends easy.

## Agreed Scope (decided 2026-07-14)

The capability must support three usage modes:

1. **Code-execution tool for agents** — agents get a tool to run LLM-generated
   Python/shell code safely (code-interpreter style; sandbox per session or per
   call).
2. **Sandboxed workspace/filesystem** — a persistent isolated environment per
   session where an agent reads/writes files, installs packages, and works
   across turns (OpenHands/Claude Code style).
3. **Connecting to an existing runtime** — attach to an already-running
   execution environment (e.g. a Kubernetes controller host of a distributed
   system) rather than provisioning an isolated one.

**Permission boundary is a first-class, cross-cutting requirement** for ALL
modes, not just mode 3. RBAC must support two identity models:

- (a) **Agent-own RBAC** — the agent has its own identity/role and permissions.
- (b) **User-assumed RBAC** — the agent assumes the invoking user's identity
  and permissions for the duration of the execution.

First built-in backends should cover all three deployment models:

- Cloud sandbox services (E2B, Daytona, Modal, ...)
- Local/self-hosted (Docker/Podman)
- Cloud-provider native (AWS Bedrock AgentCore Code Interpreter, Azure
  Container Apps dynamic sessions, Vertex AI), aligning with AK's existing
  AWS/Azure/GCP deployment adapters.

## Design Output

- [docs/specs/ak-133/design.md](../../../docs/specs/ak-133/design.md) — the reviewed
  design spec for the sandbox capability (ticket AK-133), written via the staged
  `ak-dev-write-spec` flow (design.md → spec.md → plan.md). The detailed implementation
  spec (`docs/specs/ak-133/spec.md`) follows once the design review settles. Earlier
  single-document drafts (`specs/sandbox/SPEC.md`, this skill's own `spec.md`) were
  retired on 2026-07-15 in favor of the staged documents.

## Research Streams & Artifacts

Detailed findings live in `references/`:

| Reference | Contents | Status |
|---|---|---|
| [references/ak-codebase-patterns.md](references/ak-codebase-patterns.md) | How AK's existing pluggable capabilities are built (guardrail factory, multimodal storage, config, extras, exports) and the recommended layout for the sandbox capability | done |
| [references/provider-landscape.md](references/provider-landscape.md) | Survey of sandbox providers: cloud SaaS (startup + platform + hyperscaler-native), self-hosted/OSS, in-process; isolation models, SDKs, pricing, capability matrix | done, except Google Vertex AI code execution (unresearched — see reference's §G) |
| [references/framework-abstractions.md](references/framework-abstractions.md) | Prior art: how smolagents, AutoGen/AG2, LangChain/LangGraph, OpenAI Agents SDK, CrewAI, Google ADK, Claude Agent SDK/Claude Code, OpenHands, Open Interpreter, LlamaIndex abstract code execution; interface-design lessons | done |

## Key Facts Established So Far

- **Greenfield**: AK has no existing sandbox/code-execution surface. No adapter
  passes through native executor options (smolagents `executor_type`, CrewAI
  `allow_code_execution`, ADK `code_executor`, OpenAI code interpreter) — users
  configure those on native agents themselves today.
- **Template patterns to follow** (see ak-codebase-patterns reference):
  - Guardrails: factory keyed on `AKConfig.get().guardrail.<x>.type`, lazy
    per-provider imports, no-op when disabled, raise on unknown type
    (`ak-py/src/agentkernel/guardrail/guardrail.py`).
  - Multimodal storage: `AttachmentStore(ABC)` + `_build_driver()` factory
    keyed on `storage_type`, per-backend config sub-models, `ValueError` when
    the selected backend's config block is missing.
  - Config: new `_SandboxConfig` section registered on `AKConfig`
    (`ak-py/src/agentkernel/core/config.py` ~line 340), env-overridable via
    `AK_SANDBOX__...`.
  - Optional deps: one extras group per backend in `ak-py/pyproject.toml`.
  - Exports: keep implementation internal; config-driven instantiation via
    factory (like guardrails). Only export what users must construct directly
    (the BYO-sandbox base class must be public).
- **Distinctive differentiator**: the RBAC/permission-boundary requirement and
  "attach to existing runtime" mode are NOT modeled by mainstream frameworks
  (smolagents/AutoGen/ADK executors assume they own the environment). This is
  where AK can lead rather than follow. Confirmed across all 9 frameworks
  surveyed in framework-abstractions.md — closest analogues are
  ACADynamicSessionsCodeExecutor's `TokenProvider` Protocol (pluggable auth,
  not identity passthrough) and ADK's `VertexAiCodeExecutor`/`GkeCodeExecutor`
  attach-by-resource-name. Original design needed; likely shape is a
  `principal`/identity object passed into provisioning/attach, mapped by each
  backend to its native mechanism (K8s impersonation, assumed-role creds,
  container UID/GID+caps).
- **Interface convergence across prior art**: every framework with a real
  abstraction (smolagents, AG2, AutoGen 0.4, Google ADK) converges on the same
  minimal core — execute, inject state/tools in, get output+files out,
  restart/reset, start/stop lifecycle — with everything else (file I/O,
  package install, streaming, cancellation, auth) treated as optional/duck-typed
  capability rather than core. No framework does formal capability negotiation
  (a `supports(x)` method); all lean on duck typing, `isinstance`, or a
  declared boolean flag (ADK's `stateful`).
- **Best async lifecycle prior art**: Microsoft AutoGen 0.4's `CodeExecutor`
  ABC (`autogen_core.code_executor`) — async `execute_code_blocks(code_blocks,
  cancellation_token)`, `start`/`stop`/`restart`, async context manager. It's
  a from-scratch async redesign of AG2's older sync `Protocol`, so its choices
  reflect lessons learned, not a first attempt — closest match to AK's
  already-async `Runner.run`.
- **Best backend-registration prior art for avoiding vendor lock-in**:
  AutoGen 0.4's `ComponentBase`/`Component` config system — any executor
  pairs with a Pydantic config schema and a dotted import path
  (`component_provider_override`), so a third-party backend becomes
  `type: "mypackage.MySandbox"` + `config: {...}` in AK config, no registry
  edit needed in AK itself. OpenHands' `third_party.runtime.impl` namespace-
  package auto-discovery is the other strong option but fits a vendored-app
  deployment model better than a pip-installed library like AK. Recommend
  adopting an open dotted-path-plus-config-schema registration (mirroring AK's
  guardrail/multimodal-storage factory pattern, but open rather than a closed
  enum+lazy-import list).
- **Persistence-across-calls, two real models**: (1) long-lived process/
  container is the handle (AutoGen Docker/Jupyter executors, OpenHands
  `Runtime.connect()`) — natural but needs real cleanup discipline (smolagents
  has 3+ open/closed issues about orphaned Docker containers from missing
  finalizers). (2) stateless executor + externalized session state (LangChain
  `langchain-sandbox`'s `session_bytes`/`session_metadata` round-tripped by
  the caller; Google ADK's `CodeExecutorContext` persisting into the *host
  framework's* session state rather than the executor's own memory). ADK's
  variant maps cleanly onto AK's own `Session` and is the recommended default
  for AK's "sandboxed workspace" mode; reserve long-lived-resource-as-handle
  for state that can't be serialized (live connections, GPU contexts).
- **CrewAI cautionary tale**: `allow_code_execution`/`CodeInterpreterTool`
  (Docker safe/unsafe modes) was deprecated and removed in favor of telling
  users to integrate E2B/Modal themselves — evidence that a sandbox bolted on
  as a boolean flag on one tool (vs. designed as a swappable capability) is
  not viable long-term.
- **Provider landscape surveyed** (see provider-landscape reference for full
  detail): 7 startup clouds (E2B, Modal, Daytona, Runloop, Morph, Scrapybara,
  Blaxel), 4 platform/edge providers (Cloudflare, Vercel, Northflank, Fly.io),
  2 of 3 hyperscaler-native offerings (Azure Container Apps dynamic sessions,
  AWS Bedrock AgentCore — **Google Vertex AI still unresearched**), 10
  self-hosted/OSS runtimes (Docker/Podman, gVisor, Firecracker, Kata,
  microsandbox, Anthropic sandbox-runtime, bubblewrap, nsjail, Judge0,
  Piston), and 9 in-process/language-level options (Pyodide, langchain-
  sandbox, wasmtime/WASI, componentize-py, Wasmer, Deno, RestrictedPython,
  smolagents' interpreter, PyPy sandbox).
- **The LCD-interface finding independently reconfirmed from the provider
  side, not just the framework side**: Azure Dynamic Sessions and AWS Bedrock
  AgentCore *structurally cannot* do general shell exec, pause/resume, or
  port exposure — they only do "POST code, get JSON back," optionally with
  session-identifier statefulness. Since both are required first-party
  backends per AK's scope, the core `Sandbox` interface's required surface
  must be satisfiable by that narrow contract; richer operations (files,
  network policy, snapshots, ports) are necessarily optional capabilities,
  not core methods.
- **Network egress control is a real, near-universal capability** among the
  serious backends (E2B `denyOut`/`allowOut` CIDR, Modal CIDR+domain
  allowlist with TLS SNI inspection, Daytona CIDR allowlist, Runloop Network
  Policies, Anthropic srt's proxy-enforced allowlist) but every one has an
  incompatible shape. Independent security research has demonstrated DNS-
  exfiltration/credential-extraction against AWS AgentCore's *default*
  network mode — egress control is directly relevant to the RBAC/permission-
  boundary requirement, not a side feature, and deserves a normalized
  optional interface rather than backend-specific passthrough kwargs.
- **"Sandboxed is a spectrum, not a checkbox"** (industry framing, see
  provider-landscape §E) — isolation strength varies from shared-kernel
  namespaces (Docker) through syscall-interception (gVisor) to hardware
  microVMs (Firecracker/E2B/Blaxel) to WASM (no ambient syscalls at all).
  AK should expose isolation tier as a queryable/declared backend property,
  not just imply "sandboxed = safe" uniformly across backends.

## Open Design Questions

- Is the sandbox exposed to agents as a `SystemTool` (like
  `AnalyzeAttachmentsTool`), as a `ToolBuilder`-bound plain function, or both?
- Sandbox lifecycle binding: per-call, per-session (stored/reconnected via
  session state), or per-runtime? Likely config-driven with per-session as the
  default for workspace mode.
- How to represent the permission boundary: a `SandboxPolicy` /
  `ExecutionPrincipal` object resolved per-invocation (from `ToolContext` /
  `Session`), mapped by each backend to its native mechanism (K8s
  impersonation, IAM roles, container user/caps, network policy)?
- Capability negotiation: backends differ (network egress control, snapshots,
  port exposure, streaming). Minimal core interface + optional capability
  flags/mixins, or fat interface with `NotImplementedError`? Leaning toward
  flags (a `SandboxCapabilities` object) per both research streams — no
  framework or provider surveyed does formal `supports(x)` negotiation, but a
  typed flags object is more discoverable than duck typing and every backend
  (even Azure/Bedrock's narrow contract) can honestly declare its flags.
- Sync vs async: AK core is async (`Runner.run` is async) — sandbox interface
  should be async-first. AutoGen 0.4's `CodeExecutor` ABC is the closest
  prior-art shape to imitate (see framework-abstractions reference).
- Registration mechanism for third-party backends: closed enum + lazy import
  (AK's existing guardrail/multimodal pattern) vs. open dotted-path + Pydantic
  config schema (AutoGen 0.4's `Component` system). The latter better serves
  the explicit no-vendor-lock-in goal — leaning toward adopting it, possibly
  with a short pre-registered list of first-party backends for convenience.

## How to Continue This Research

1. Read the references above before proposing interface changes.
2. When evaluating a new provider, capture: isolation model, Python SDK shape
   (create/exec/files/lifecycle), persistence/reconnect support, RBAC or
   identity passthrough options, self-hostability, pricing/license.
3. Weigh every interface decision against the three usage modes and the two
   RBAC identity models in the Agreed Scope section — a design that only
   serves the code-interpreter mode is insufficient.
4. Update the references and this SKILL.md as findings land; when the design
   is settled, spin off `ak-dev-new-sandbox-provider` (clone the structure of
   `ak-dev-new-guardrail-provider`) and mark this skill's status accordingly.
