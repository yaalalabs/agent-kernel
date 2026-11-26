---
name: ak-dev-sync-docs-from-branch
description: >
  Sync Open Agent Kernel documentation from branch changes before a feature or bugfix is merged.
  Use this skill when implementation is ready and you need to inspect new commits plus
  uncommitted changes, then update root docs, ak-py docs, deployment READMEs, example
  READMEs, and the docs website so the documentation matches the implemented behavior.
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Sync Documentation From Branch Changes

Use this skill when a feature branch or bugfix branch is functionally ready and you need to align Open Agent Kernel documentation with what actually changed.

This skill is for **documentation maintenance driven by code diff**, not for implementing the feature itself.

## Goal

Read the branch delta, infer what user-facing and contributor-facing documentation changed, then update the relevant docs across the repository.

Required documentation surfaces covered by this skill:

1. `ak-py/README.md`
2. docs website content under `docs/` — update existing pages, add pages, remove obsolete pages, and adjust intro/getting-started/reference sections as needed, **including the React landing and features pages** (`docs/src/pages/index.tsx`, `docs/src/pages/features.tsx`) whose hard-coded inventories drift silently when only markdown is updated
3. README files under `ak-deployment/`
4. example README files when an example was added or changed, plus docs-site references to those examples
5. root `README.md`
6. root `DEVELOPER_GUIDE.md`

## When to Use This Skill

Use this skill when all of the following are true:

1. The developer is on a feature or bugfix branch.
2. The implementation is already done or nearly done.
3. There are new commits on the branch and/or uncommitted local changes.
4. The branch changes behavior, setup, APIs, integrations, deployment flows, examples, capabilities, or contributor workflows in ways documentation should reflect.

Do **not** use this skill as the first step of a feature. Use it near the end, before merge or PR finalization.

## Step 1: Determine the Comparison Base

Find the correct baseline branch first.

Preferred order:

1. The PR target branch if it is known.
2. The upstream tracking branch for the current branch.
3. `origin/develop`.
4. `develop`.

For this repository, prefer `origin/develop` or `develop` as the default base branch unless the PR target or upstream tracking branch says otherwise.

Use Git to identify the merge base between the current branch and that baseline.

Minimum evidence to gather:

- current branch name
- merge base commit
- commits since merge base
- staged changes
- unstaged changes

If the baseline is ambiguous, state the assumption you are using and continue.

## Step 2: Read the Branch Delta

Inspect both committed and uncommitted work.

Required diff inputs:

1. **Committed changes on the branch**
   - commits since merge base
   - file list and diff summary
2. **Current local changes**
   - staged diff
   - unstaged diff

Pay special attention to changes in:

- `ak-py/src/agentkernel/`
- `ak-py/README.md`
- `ak-deployment/`
- `examples/`
- `docs/`
- root `README.md`
- root `DEVELOPER_GUIDE.md`
- tests, examples, and Terraform modules that imply docs drift

## Step 3: Map Code Changes to Documentation Impact

Classify the branch delta into these buckets:

1. **Root-level product docs drift**
   - project overview, supported features, installation, quick start, contributor guidance
   - update `README.md` and `DEVELOPER_GUIDE.md` as needed

2. **Package-level docs drift**
   - Python package install, CLI, skills, APIs, framework support, configuration
   - update `ak-py/README.md`

3. **Docs website drift**
   - new capabilities, changed setup steps, outdated examples, missing pages, obsolete pages
   - update or add/remove pages under `docs/`

4. **Deployment docs drift**
   - Terraform modules, module inputs, deploy flows, packaging changes, environment setup
   - update relevant `ak-deployment/**/README.md` files

5. **Example docs drift**
   - example added, removed, renamed, or behavior changed
   - update example README files and docs-site references to those examples

## Step 4: Required Documentation Surfaces

You must evaluate all of these surfaces before deciding no documentation work is needed:

### Root Docs

- `README.md`
- `DEVELOPER_GUIDE.md`

### Package Docs

- `ak-py/README.md`

### Docs Website

- pages under `docs/docs/`
- related docs metadata such as sidebars or linked overview pages when needed
- intro/getting-started/reference/example pages that are affected by the branch change
- the what's new page, `docs/docs/whats-new.md`, when the branch ships a headline capability: add an entry at the top (newest first), and update the two-line tip at the top of `docs/docs/intro.md`, which names the latest additions and links to that page
- the React landing and features pages (next subsection): these are not generated from markdown, so a new framework, integration, provider, transport, or capability is invisible there until its entry is added by hand

### Docs-Site Landing and Features Pages (React)

The landing page (`docs/src/pages/index.tsx`) and the features page (`docs/src/pages/features.tsx`) enumerate the product surface in hard-coded data, so a new framework, integration, provider, transport, or capability is invisible there until its entry is added by hand. `index.tsx` only lists the home sections in order. Each section, and its data, lives under `docs/src/components/`:

| Data | What it drives | Entry shape |
|---|---|---|
| `docs/src/components/HomeSections/integrations.data.tsx` (`INTEGRATION_ROWS`) | "Plug in what you already run": every third-party integration, shown one stage at a time | `{ name, role, href, logo or icon, mono?, wide?, soon?, title? }` placed in the matching row. The `role` decides where the item is shown: `GROUPS` in `HomeSections/Integrations.tsx` maps each role to a stage (Build, Connect, Remember, Guard, Scale, Observe) and to a set within it. An item whose role is in no set is shown under "More" in the last stage |
| `docs/src/components/HomeSections/index.tsx` (`STAGES`) | the capability rail: per stage, one summary, three points and one code or config snippet | `{ id, name, summary, points, file, language, code, docs }`. The points name frameworks, channels, stores, transports and providers in prose |
| `docs/src/components/ArchitectureOverview/data.tsx` (`SOURCES`, `DESTINATIONS`, `CORE_PILLS`, `FLOW_WORDS`) | the architecture diagram: cards of icon chips, the four capability links inside the runtime panel, the line of stage names | a chip is `pick("<integration name>")`; the name must match an `INTEGRATION_ROWS` item exactly or the static build fails |
| `docs/src/components/HomeSections/Deployment.tsx` (`TARGETS`) | "Deploy anywhere": one card per cloud or cluster | `{ icon, name, description, modes, modules }`, where a module is `{ kind: 'terraform' or 'helm', name, url }` |
| `docs/src/components/HomeSections/Announcement.tsx` | the one-line announcement above the hero | the bold title, one sentence and the `Link` target, edited in place. It must fit on one line on a desktop screen |
| `docs/src/pages/features.tsx` (`STAGES`) | the features reference: every capability, once, under its stage | a capability is `{ title, summary, points?, guide, more? }`. `guide` and each `more` entry is `{ label, to }` and must resolve, because the build fails on broken links. The page header counts the capabilities itself |

Read the current data before editing and confirm identifiers with `grep -n "^const \|^export const " docs/src/components/HomeSections/*.tsx docs/src/components/ArchitectureOverview/data.tsx docs/src/pages/features.tsx`.

| Branch changes ... | Integration row and role | Architecture card | Capability rail point (home `STAGES`) | `features.tsx` capability |
|---|---|---|---|---|
| A headline capability worth announcing | (none) | (none) | a point on its stage, when it changes what the stage offers | a new capability under its stage when it is durable; plus `Announcement.tsx`, and an entry at the top of `docs/docs/whats-new.md` |
| A framework adapter | Agent frameworks & dev tools, `Framework` | Agent frameworks | Build: "Adapters for eight agent frameworks" | Framework adapters (Build): the count in `summary` and a `more` link to the new page; plus `FRAMEWORKS` in `docs/src/components/AccessFlowDiagram` (the tool gate node of the access closer look) |
| A messaging integration | Channels & protocols, `Channel` | Messaging channels | Connect: the list of channels | Messaging channels (Connect): the count in `summary` and a `more` link to the new page |
| A protocol surface (MCP, A2A, AG-UI) | Channels & protocols, `Protocol` | Protocols and APIs | Connect: the protocols point | its own capability under Connect |
| A session, thread, response, schedule, or attachment store backend | Memory, knowledge & data, `Memory` (list every store it backs in `title`) | Memory and knowledge | Remember: the session stores point | Sessions (Remember): the backend list in `points` |
| A knowledge base backend | Memory, knowledge & data, `Vector knowledge` / `Graph knowledge` / `SQL knowledge` / `Knowledge store` | Memory and knowledge | (none) | Knowledge bases (Remember): one line in `points` per backend |
| A queue transport | Cloud & infrastructure, `Queue` | (none) | Scale: the transports point | Queue mode (Scale): the transport list in `points` |
| A sandbox provider or broker flavor | Cloud & infrastructure, `Sandbox` | (none) | (none) | Sandboxed code execution (Guard): the provider count and names in `points`; `docs/src/components/SandboxFlowDiagram` |
| A deployment target or topology | Cloud & infrastructure, `Serverless` / `Containers` / `Serverless & containers` / `On-prem` / `Gateway` | Clouds and observability | Scale: the targets point | Deployment targets (Scale): `summary` and a `more` link; plus `TARGETS` in `HomeSections/Deployment.tsx` |
| A schedule provider | Cloud & infrastructure, `Scheduler` | (none) | (none) | Scheduled tasks (Scale), when its text names providers |
| A secret provider | Cloud & infrastructure, `Secrets` | (none) | (none) | Secret resolution (Guard): `summary` names each provider |
| A guardrail provider | Observability, safety & testing, `Guardrail` | (none) | Guard: the guardrails point | Guardrails (Guard): a `more` link to the provider's page |
| An identity provider, or an issuer documented as an `oidc` configuration | Observability, safety & testing, `Identity` (an `oidc` configuration says so in `title`) | (none) | (none) | Identity and access (Guard): the provider lines in `points`; plus `PROVIDERS` in `docs/src/components/AccessFlowDiagram` and the identity provider node of the Mermaid diagram under *How it fits together* in `docs/docs/advanced/identity-and-access.md`, for a new short `type` name only |
| A tracing provider | Observability, safety & testing, `Tracing` | Clouds and observability (optional) | Observe: the tracing point | Tracing (Observe): the provider list in `points` |
| A test evaluator | Observability, safety & testing, `Evaluator` | (none) | (none) | Pluggable evaluators (Observe): `summary` names the built-in evaluators |
| A bundled user skill (`ak-py/src/agentkernel/skills/`) | (none) | (none) | (none) | (none); only `docs/docs/agent-skills.md` lists individual skills |

Rules for these pages:

- Keep counts and names in sync with the code and with `docs/docs/` (a "six providers" point or an "eight agent frameworks" summary goes stale the moment a backend is added).
- Every third-party integration (a vendor, a protocol, a managed service) and every provider `type` the runtime ships gets an item in `INTEGRATION_ROWS`, so a set such as Sandboxes or Secrets lists all of its providers, the local ones included (`local_subprocess`, `env`). The only exception is the `in_memory` defaults, which are not something to plug in. One item per role: a vendor that serves two roles gets an item for each (Kubernetes the deployment target and Kubernetes pods the sandbox), while more of the same role goes into the existing item's `title` (Redis as session, thread and attachment store). `href` points at the docs page; a page that exists only in the unreleased docs takes the `/docs/next/...` path with a comment to drop `next` after the release.
- Reuse an existing `role` where one fits. A new role must also be added to a set in `GROUPS` (`HomeSections/Integrations.tsx`), or the item is shown under "More".
- Logo, in this order: an existing asset under `docs/static/img/integrations/`; a Simple Icons glyph from `react-icons/si` (confirm the export exists, since Simple Icons has dropped the AWS, Microsoft, Slack, and OpenAI marks); otherwise the vendor's own SVG or PNG saved under `docs/static/img/integrations/`. Set `mono: true` for a single-colour mark, so it follows the colour mode, and `wide: true` for a wordmark.
- An integration `name` is an identifier: `ArchitectureOverview` picks chips by it, so a rename there without the matching `pick()` change fails the static build. For the same reason names are unique across the whole file: a vendor's second item is named apart from its first (`Kubernetes Secrets`, `Kubernetes pods`, `Amazon EC2`), never a repeat of `Kubernetes` or `AWS`.
- The six stage names appear in four places and must stay the same: `STAGES` in `HomeSections/index.tsx`, `GROUPS` in `HomeSections/Integrations.tsx`, `STAGES` in `features.tsx`, and `FLOW_WORDS` in the architecture data. The stage drawings in `docs/src/components/VectorMotion/` are keyed by the same ids.
- `docs/plugins/llms-txt/template.md` is the hand-written summary at the top of the site's `/llms.txt` (the page list under it is generated at build time). It names the supported agent frameworks, the Python versions, the install command and the identifiers (`agentkernel`, `ak`, `AKConfig`, `AK_`): update it when any of those change.
- Follow the existing entry shape exactly; do not restyle or restructure a section to add one entry. A new section follows the *Website design system* in `branding/README.md`.
- Other pages carry their own roll calls: the persona pages (`docs/src/pages/developer.tsx`, `ai-engineer.tsx`, `business-leader.tsx`, with shared pieces in `docs/src/components/PersonaKit/` and `FrameworkSelector/`), `use-cases.tsx`, the answers in `docs/src/components/FAQ/index.tsx`, and the capabilities table in the root `README.md`. Grep them for the old name or count whenever an inventory changes.
- Verify with the docs build, which also fails on broken internal links: `cd docs && npm ci && NODE_OPTIONS=--max-old-space-size=8192 npm run build`.

### Deployment Docs

- README files under `ak-deployment/`

### Example Docs

- `examples/**/README.md`
- docs-site pages that list, categorize, or link to examples

Do not update only one documentation surface if the same capability is described elsewhere in the repository.

## Step 5: Add, Update, or Remove Documentation

Apply these rules.

### Update Existing Docs When

- the capability already has a documented home
- the branch changes behavior, supported options, configuration, module inputs, examples, or terminology

### Add New Docs or Pages When

- the branch introduces a new reusable workflow, feature area, or example that does not fit cleanly into an existing page
- a new docs page is clearer than overloading an unrelated page

### Remove Docs or Pages When

- the capability or example is no longer supported
- the page is now misleading or fully replaced
- a replacement page or section exists in the same edit

Do not leave stale pages in place once the code path or example has been removed.

## Step 6: Documentation Authoring Rules

When writing or updating docs:

- ground every change in the branch diff and the current implementation
- prefer updating existing pages before creating parallel pages with overlapping scope
- keep terminology consistent with code, config keys, module inputs, and example names
- use current version numbers and current framework/integration names
- align docs examples with live code in `examples/` and `ak-deployment/`
- if an example changed, update both the example README and any docs-site references to it
- if setup steps changed, update both quick-start/getting-started material and deeper reference pages where relevant
- write the product name by the rules in the *Naming and brand* section of `AGENTS.md`: "Open Agent Kernel" in titles and on first mention, "OAK" after that, identifiers and quoted product output unchanged

## Step 7: Required Files to Consider

Depending on branch impact, review and update files from this list:

- `README.md`
- `DEVELOPER_GUIDE.md`
- `ak-py/README.md`
- `docs/docs/**`, including `docs/docs/whats-new.md` and the tip in `docs/docs/intro.md`
- `docs/sidebars.js`
- `docs/src/components/HomeSections/integrations.data.tsx`, `HomeSections/index.tsx`, `HomeSections/Deployment.tsx`, `HomeSections/Announcement.tsx`, `docs/src/components/ArchitectureOverview/data.tsx` (the landing page inventories)
- `docs/src/pages/features.tsx`
- `docs/src/pages/developer.tsx`, `ai-engineer.tsx`, `business-leader.tsx`, `use-cases.tsx` (when an inventory or count they display changes)
- `ak-deployment/**/README.md`
- `examples/**/README.md`

Also update docs-site example index pages or overview pages when example inventory changes.

## Step 8: Validation Checklist

Before finishing, validate the documentation sync work.

Minimum validation:

1. Confirm the diff-backed rationale for each documentation update.
2. Verify changed docs still reflect the live code, examples, and module inputs.
3. Check edited markdown/JSON/JS files for diagnostics.
4. Search for stale names, old counts, removed examples, or outdated setup/version references introduced by the branch delta, including inside `docs/src/pages/*.tsx`.
5. Confirm example references in the docs site still point to examples that exist.
6. If a `.tsx` page was edited, confirm the docs site still builds (`cd docs && NODE_ENV=production NODE_OPTIONS=--max-old-space-size=6144 npm run build`; TypeScript is not installed in `docs/`, so the production build is the compile check, and `NODE_ENV=production` keeps the debug plugin out of the client bundle) and that every new `link` resolves to an existing `docs/docs/` page.
7. The changelog is part of the same end-of-branch pass: run `ak-dev-sync-changelog-from-branch` so a user-visible change also carries its `changelog.d/<issue>.<type>.md` fragment. Never edit `CHANGELOG.md` directly.

## Output Expectations

When using this skill, the coding agent should produce:

1. A short branch-impact summary based on commits plus uncommitted changes.
2. A documentation-impact summary by surface:
   - root docs
   - package docs
   - docs website
   - deployment READMEs
   - example READMEs
3. The actual file edits.
4. A validation summary.

## Common Pitfalls

- Updating code or examples without updating the matching README.
- Updating example READMEs but forgetting docs-site references to those examples.
- Updating docs website pages but leaving root or package README content stale.
- Describing behavior from memory instead of checking live code or Terraform inputs.
- Leaving outdated pages in place after capabilities or examples were removed.
- Changing example inventory without updating overview/index pages.
- Updating `docs/docs/` markdown for a new framework, integration, provider, transport, or capability but leaving the hard-coded lists under `docs/src/components/HomeSections/` and in `docs/src/pages/features.tsx` (and `docs/docs/whats-new.md`) untouched, so the landing and features pages advertise a stale inventory.

## Quick Heuristic

Use this documentation-sync heuristic:

- **Behavior changed** → patch the docs where that behavior is already explained.
- **New workflow or example appeared** → add or expand docs in every location that should expose it.
- **Workflow or example disappeared** → remove or replace stale docs.
- **Only internal refactoring changed** → no docs change unless contributor guidance is affected.