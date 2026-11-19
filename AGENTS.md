# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, Copilot, Codex, Windsurf, etc.) working
**on** the Open Agent Kernel codebase itself. If you're building an agent *with* OAK, see
the [README](README.md) and [kernel.yaala.ai/docs](https://kernel.yaala.ai/docs) instead — this
file is for contributors to this repo.

## Two skill sets — don't confuse them

This repo ships two unrelated sets of "skills," named similarly but serving opposite audiences:

| Skill set | Location | Audience | Purpose |
| --- | --- | --- | --- |
| **Dev skills** | [.agents/skills/ak-dev-*](.agents/skills/) | You, working on this repo | Architecture, testing conventions, code quality, and step-by-step guides for adding a new framework adapter / guardrail / knowledge base / messaging integration / tracing provider / multimodal storage / sandbox provider / queue transport to OAK core |
| **Bundled skills** | [ak-py/src/agentkernel/skills/](ak-py/src/agentkernel/skills/) (`ak-init`, `ak-build`, `ak-add-capabilities`, `ak-add-integration`, `ak-cloud-deploy`, `ak-test`) | End users of the `agentkernel` PyPI package | Shipped *inside* the package so a downstream developer's coding assistant can scaffold and extend agents built *with* OAK |

If a task is about changing OAK's own source, use the dev skills under `.agents/skills/`.
Never edit the bundled skills to document a dev-only workflow, and never edit the dev skills to
change end-user-facing scaffolding behavior — read the description in each `SKILL.md` before
editing either.

**Before non-trivial changes to core**, load `.agents/skills/ak-dev-architecture` — it covers
`Session`, `Agent`, `Runner`, `Module`, `Runtime`, `AgentService`, `ChatService` (and which layer
each surface calls), `AKConfig`, hooks, tools, multimodal, conversation threads, and the ECS
containerized deployment classes in depth. Don't re-derive this from
scratch by grepping; the skill is maintained precisely so agents don't have to.

## Repo map

```
ak-py/                  The agentkernel PyPI package (core framework, all Python source + tests)
  src/agentkernel/
    core/                Framework-agnostic abstractions (Session, Agent, Runner, Module, Runtime, Config, hooks, tools)
    framework/           Adapters: openai, crewai, langgraph, adk, smolagents, pydanticai, claude
    api/                 REST, MCP, A2A server layers
    deployment/          AWS (Lambda + ECS), Azure Functions, GCP Cloud Run handlers
    integration/         adapter/ (the messaging seam) + Slack, WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail
    knowledgebase/       ChromaDB, Neo4j, Starburst backends
    guardrail/           OpenAI, AWS Bedrock, Walled AI guardrail providers
    trace/               Langfuse, OpenLLMetry tracing adapters
    skills/              Bundled end-user skills (see table above) — not dev docs
  tests/                 pytest suite, mirrors src/ structure
ak-deployment/           Terraform modules per cloud (aws / azure / gcp) x (serverless / containerized)
examples/                Runnable sample apps per framework/deployment combo
use-cases/               End-to-end agents built from a SPEC.md using the bundled skills
e2e/                     Messaging integration e2e harness: deployable app + Terraform + pytest suite driven against real platform accounts (see e2e/README.md)
docs/                    Docusaurus site (kernel.yaala.ai/docs) — versioned_docs/ are frozen, don't edit old versions
.agents/skills/          Dev skills (see table above)
```

The **core never depends on** `framework/`, `integration/`, `deployment/`, or `api/`. If a change
to `core/` requires importing something from those, that's a design smell — stop and reconsider,
or check with the maintainer.

## Adapter architecture — stay unopinionated

Every integration point (framework adapter, guardrail provider, knowledge base backend, session
store, messaging integration, tracing provider) is a **thin adapter behind a stable core
interface**, not a rewrite or reinterpretation of the underlying tool. The core abstraction
(`Agent`, `Runner`, `Module`, `Tool`, `KnowledgeBase`, `SessionStore`, `BaseTrace`, ...) defines the
minimal contract; the adapter's job is to wrap the native object/API as-is and translate at the
boundary — nothing more.

When adding or touching an adapter:

- **Wrap, don't abstract over.** Expose the native framework/service object with minimal
  reshaping. Don't invent a new intermediate abstraction "for consistency" across adapters —
  each adapter can look different internally if that's what its underlying tool naturally wants;
  forcing uniformity across adapters is itself an opinion the architecture avoids.
- **No feature-forcing.** Don't require a capability the underlying framework/service doesn't
  natively support (e.g. don't invent a fake token stream when the SDK has no streaming API —
  raise `NotImplementedError` until a real mapping exists). CrewAI and smolagents *do* stream in
  their SDKs; their OAK adapters still raise because that wiring is not implemented yet — same
  `NotImplementedError` shape, different reason.
- **No hidden defaults that change behavior.** Config-driven, explicit choices (`AKConfig`) beat
  adapter-internal heuristics. If an adapter needs a default, make it the same default the native
  tool itself would use.
- **Consistent shape, not consistent opinion.** New adapters should match the *structural* pattern
  of existing ones in the same category (see `.agents/skills/ak-dev-new-*` for the exact
  per-category steps) so they're predictable to find and register — but that's about
  discoverability, not about making every backend behave identically.

This is why the core/adapter boundary above is a hard rule, not a style preference: the moment
`core/` starts depending on a specific framework or service, the framework/service's opinions leak
into code every adapter has to live with.

## House patterns for new features

Three rules shape every new feature; `ak-dev-write-spec` designs against them and `ak-dev-review-pr`
reviews against them (full detail in the "House Patterns for New Features" section of
`.agents/skills/ak-dev-architecture`):

- **Pluggable by default.** Any touchpoint with an external system, backend, or provider is an ABC
  plus thin adapters behind a factory in the `core/util/factory.py` shape (built-ins via `if/elif`
  real imports, `require_extra` for optional SDKs, a dotted-path bring-your-own branch), even when
  only one backend ships in the first PR.
- **Reuse existing configuration; add knobs only when nothing existing expresses them.** Reuse whole
  `AKConfig` models where the shape exists (`_QueuesConfig` serves both `execution.queues` and
  `sandbox.broker.queue`), subclass to change defaults only, and let already-configured components
  enable a feature implicitly where that applies instead of adding `enabled`/`type` fields. Every new
  field needs a reason, a reader, a description, and a default that keeps existing YAML and `AK_*` env
  vars valid.
- **Classes, not scripts.** Feature logic lives in classes with one responsibility each (ABC,
  backends, `*Factory`, `*Manager`/`*Handler`/`*Runner`, Pydantic models), state on instances.
  Module-level functions are reserved for small stateless shared utilities and the tool functions the
  tool builders bind.

When documentation changes, the React landing and features pages hold hard-coded inventories of
frameworks, integrations, providers, deployment targets, and capabilities; update them alongside
`docs/docs/`. On the landing page they live in `docs/src/components/IntegrationsMarquee/data.tsx`,
`ArchitectureOverview/data.tsx`, and `FeatureExplorer/data.tsx`; on the features page in
`docs/src/pages/features.tsx` (see `ak-dev-sync-docs-from-branch`, *Docs-Site Landing and Features
Pages*, for the change-type to entry mapping).

## Setup, build, lint, test

Setup steps and how to discover the full Makefile command list are canonical in
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — don't re-derive or restate them here; if a command
changes, update DEVELOPER_GUIDE.md and this file's pointer stays valid automatically. Two things
worth knowing that aren't spelled out there:

- Formatting is black + isort at **line length 150** (`ak-py/pyproject.toml`), not black's
  default of 88 — don't "fix" long lines that are within the configured limit.
- Ruff runs only the pyupgrade typing rules (`list[str]`, `X | None`, `collections.abc` imports),
  not as a general linter; the rule is in `ak-dev-code-quality`.
- `make lint-check-all` is the exact command `code-quality.yml` runs in CI — run it before
  considering a change to `ak-py/` or `examples/` done.

For anything test-related beyond the basic `pytest` invocation (async fixtures, mocking
frameworks/session stores, the built-in fuzzy/semantic Test framework), load
`.agents/skills/ak-dev-testing-conventions` rather than guessing pytest patterns from scratch.

**Local `pytest` runs will show failures that aren't your fault.** Some tests are e2e and call
real services — `test.yaml` injects `OPENAI_API_KEY`, `WALLED_API_KEY`, `SLACK_BOT_TOKEN`, and
similar secrets in CI, and those tests are skipped entirely for fork PRs that lack them. There's
no `.env.example` or pytest marker separating these from pure unit tests yet, so if you run the
suite locally without those keys set, expect some failures unrelated to your change — check
whether a failing test needs a credential you don't have before assuming you broke something.

## Searching this repo

`examples/*/.venv/` directories are gitignored, but may be present on disk (e.g. after running examples) — each can be 500MB–900MB of
vendored framework packages (openai-agents, google-adk, langgraph, ...). A broad `grep`/`find`/`rg`
without excluding `.venv` will return matches from inside vendored dependencies, not this repo's
code, and can burn a large chunk of context doing it. Scope searches to `ak-py/src`, `ak-py/tests`,
or a specific `examples/<dir>` subpath rather than `examples/` wholesale, or explicitly exclude
`.venv` (most search tools respect `.gitignore` by default — confirm yours does before trusting a
repo-wide search).

## Naming and brand

The project is **Open Agent Kernel**, shortened to **OAK**. It was previously called Agent Kernel.
When you write or update documentation, READMEs, skills or website copy:

- **Full name first, then OAK.** Use "Open Agent Kernel" in titles, H1s and metadata, and on the
  first mention on a page (as "Open Agent Kernel (OAK)" where the sentence allows). Use "OAK" after
  that, in sub-headings and in diagram labels.
- **Identifiers are not renamed.** The package is still `agentkernel`, the CLI is `ak`, classes keep
  their `AK` prefix (`AKConfig`) and environment variables keep `AK_`. Repository paths, the
  `yaalalabs/agent-kernel` URL and `kernel.yaala.ai` are unchanged.
- **Quote product output exactly.** Strings the code emits still carry the old name, for example the
  OpenAPI title `Agent Kernel REST API`, trace span names such as `Agent Kernel OpenAI` and the
  `AgentKernel` service name. Code blocks and quoted output keep them as emitted.
- **Brand assets.** Logos, the colour palette and usage rules live in
  [branding/README.md](branding/README.md). The website theme tokens are in
  `docs/src/css/custom.css`: use the tokens there, not new hex values.
- **Two colour modes.** The site has a dark mode (default) and a light mode that share one set of token
  names. Never write a literal white, navy or grey in a stylesheet: use `--ak-fg`, `--ak-text*`,
  `--ak-bg*` and `--ak-surface*`, which flip with the mode. Use `--ak-primary-text` for orange text
  and `--ak-primary` for orange fills. Canvas and WebGL code reads colours through
  `docs/src/lib/brand.ts`. Check new UI in both modes.
- **One design system for website pages.** Marketing pages are flat and left-aligned. Build new
  sections from the shared pieces in `docs/src/css/custom.css` (`ak-container`, `ak-section`, the
  `ak-display` to `ak-label` type classes, `ak-btn`, `ak-link`, `ak-card`, `ak-tag`) and the
  `SectionHeader` component, not from page-local copies. Sizes come from the `--ak-type-*` and
  `--ak-space-*` tokens, corners from the two radii (`--ak-radius-control`, `--ak-radius-card`). No
  gradients, glows, blur or drop shadows on surfaces, no text under 15 px except the 13 px monospace
  label, and headings in sentence case. Pages below the home page start with `PageHero` and end with
  `ClosingPanel`; the only entrance effect is `Reveal`. Interface icons are Tabler outline icons
  (`react-icons/tb`) and brand marks are Simple Icons (`react-icons/si`). Moving illustrations use the
  line-art vocabulary in `docs/src/components/VectorMotion/`. The full rules are in
  [branding/README.md](branding/README.md#website-design-system).

## Conventions

- **Commits & PRs**: [CONTRIBUTING.md](CONTRIBUTING.md) is canonical for commit message format
  (Conventional Commits) and the PR checklist — don't restate it here; follow that file, and check
  recent `git log` for real examples of it in practice.
- **New integrations** (framework adapter, guardrail provider, knowledge base, messaging
  platform, multimodal storage, tracing provider) each have a dedicated step-by-step dev skill
  under `.agents/skills/ak-dev-new-*` — use the matching one instead of improvising the wiring,
  since factory registration and export conventions are easy to get subtly wrong by copying the
  wrong existing adapter.
- **Docs sync**: if your change alters implemented behavior, `.agents/skills/ak-dev-sync-docs-from-branch`
  and `ak-dev-sync-skills-from-branch` describe how root docs, `ak-py` docs, and the bundled
  skills get kept in sync with code — this repo has automation (`auto-sync-skills-docs.yaml`) that
  expects docs/skills to track implementation, not drift.

## Terraform (`ak-deployment/`)

These modules provision real cloud infrastructure (AWS/Azure/GCP). Editing `.tf` files is fine;
**never run `terraform apply`, `terraform destroy`, or anything that touches real state/backends**
without explicit, in-the-moment user approval — this is the one part of the repo where an agent
action can have an irreversible effect outside the repo itself. `terraform plan` (read-only) is
safe to run to sanity-check a change.

## Working with git in this repo

- Never commit without telling the user first and getting confirmation — this repo's owner has
  asked to always be told before a commit runs.
- Don't push, force-push, or open PRs unless explicitly asked.
- Never edit files under `docs/versioned_docs/` — those are frozen snapshots of past releases.
