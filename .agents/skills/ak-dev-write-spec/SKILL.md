---
name: ak-dev-write-spec
description: >
  Write the spec documents for a planned Agent Kernel change under
  docs/specs/<issue-number>-<short-title>/ in three ordered stages: a concise point-form design
  spec (design.md) that a maintainer reviews first, then a detailed
  implementation spec (spec.md) once the design is approved, then a concise
  implementation plan (plan.md), plus an optional research/ subfolder holding
  the supporting research behind the design. Use this skill when asked to write
  or update a design, spec, plan, or research notes for a feature, refactor, or
  fix before it is implemented, e.g. "write a design spec for issue #492" or
  "spec out the shared driver extraction".
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Write a Spec for a Planned Change

Use this skill when asked to produce spec documents for Agent Kernel work before (or instead of) implementing it. A change is specified in **three documents, written in strict order**, all under `docs/specs/<issue-number>-<short-title>/`:

| Stage | File | What it is | Written when |
|---|---|---|---|
| 1 | `design.md` | Concise, point-form, hierarchical requirements — what changes and why | First, before anything else |
| 2 | `spec.md` | Detailed design and implementation components, following the approved design | Only after `design.md` has been reviewed and optimized through review cycles |
| 3 | `plan.md` | Concise breakdown of the implementation into iterations/steps | Only after both `design.md` and `spec.md` are done |

**Do not skip ahead.** `design.md` is the document humans review — it must exist and survive its review cycles before effort goes into `spec.md`. Writing a detailed spec against an unreviewed design wastes the detail work when the design changes.

The same directory may **optionally** hold a `research/` subfolder — the supporting investigation that informed the design (provider surveys, prior-art comparisons, benchmarks, spike notes). It is *not* a fourth stage and not required; see [Optional: `research/`](#optional-research--supporting-research).

This skill is for **writing these documents**, not for implementing the change they describe.

## Which Stage Are You In?

Route from what the requester asked for and what already exists in `docs/specs/<issue-number>-<short-title>/`:

- No `design.md` yet, or the request is "write a spec/design for X" → **Stage 1**: write `design.md` and stop there.
- `design.md` exists and the requester says it is reviewed/approved (or asks for the implementation spec) → **Stage 2**: write `spec.md`.
- `design.md` and `spec.md` both exist and the requester asks for the plan/breakdown → **Stage 3**: write `plan.md`.
- Asked to update an existing document → update that document; if the update changes requirements in `design.md`, flag that downstream `spec.md`/`plan.md` need re-alignment.
- Asked to capture or record research — a provider survey, a prior-art comparison, a benchmark, a spike — → write it under `research/` (optional; see [Optional: `research/`](#optional-research--supporting-research)). This can happen before `design.md` exists and does not, on its own, start Stage 1.

Never write `spec.md` in the same pass as a fresh `design.md` unless the requester explicitly says to skip the design review.

## Why These Documents Are Held to a High Bar

The spec set is the contract the implementation PR is reviewed against: `ak-dev-review-pr` reviews any spec in a PR *before* reading code, extracts every must/should statement into a requirements checklist, and flags silent omissions and deviations in the implementation. A vague or unverified spec therefore produces noisy reviews and undetectable regressions. Two properties matter most:

1. **Every factual claim about the current code is verified, not remembered.** File paths, line numbers, config defaults, "this appears in N places" counts, and behavior descriptions will be re-checked by reviewers against the base branch. One wrong claim taints trust in all the others.
2. **Every requirement is concrete enough to test.** "Must retry 3 times with a 2-second delay and re-raise the last error" is checkable; "must handle connection failures robustly" is not.

## Optional: `research/` — Supporting Research

Some changes need real investigation before the design is credible — a survey of third-party providers, a comparison of prior-art approaches, a benchmark, or a throwaway spike. When that work happened, preserve it under an optional `research/` subfolder of the spec directory rather than losing it or inlining it into `design.md`:

```
docs/specs/<issue-number>-<short-title>/
├── research/            # optional — supporting material, written before or alongside design.md
│   ├── README.md        # optional index of the research files and their one-line takeaways
│   └── <topic>.md       # one file per topic
├── design.md
├── spec.md
└── plan.md
```

- **Optional, and not a stage.** Skip it entirely for changes that need no investigation. It has no ordering slot of its own — it is written before or alongside `design.md`, never generated after `plan.md` to backfill.
- **What goes in it:** the raw material behind the design's decisions — provider/tool landscape surveys, prior-art abstraction comparisons, benchmark results, spike findings, decision logs, notes from external sources. One file per topic; a short `research/README.md` indexing them (with each file's one-line takeaway and status) helps but is not required.
- **`design.md` distills; `research/` backs.** The design states the decision and *cites* the research file where a motivation or a decision leans on a finding (e.g. "per-session is the default — see `research/lifecycle-survey.md`"). Do not paste long surveys into `design.md`; that is exactly the padding the point-form format exists to avoid.
- **A different bar.** Research is held to the *claims-are-true* bar (property 1 above) — verified code citations, and external claims marked as verified or not — but **not** to the point-form / concise / review-cycle bar of `design.md`. It may be long-form and exploratory, and it is not rewritten every review cycle.
- **Not requirements.** `ak-dev-review-pr` does not extract requirements from `research/` and does not hold it to the spec rubric; reviewers may consult it for context. It ships in the design PR as supporting material (see PR Guidance).
- **When research is large or reusable** — a landscape survey worth discovering from outside this one change — it may instead live as its own research-companion dev skill under `.agents/skills/`. Use `research/` for change-scoped material; promote to a skill only when the research is a durable reference in its own right.

## Inputs

- **GitHub issue** (required): the issue number plus a short title, e.g. issue `#492` "Database Drivers Refactoring". Determines the output directory `docs/specs/<issue-number>-<short-title>/` — the issue number, a hyphen, then a lowercase kebab-case slug of the change (e.g. `docs/specs/492-shared-database-drivers/`). If no issue exists, ask for one — do not invent a number.
- **Change intent**: what the change should accomplish, at whatever level of detail the requester has. Ambiguities you cannot resolve from the code become explicit open questions in `design.md`, not silent design decisions.

---

## Stage 1: `design.md` — the Design Spec

`design.md` is read by an Agent Kernel expert to understand **what is changing and why** — in minutes, not an afternoon. It goes through multiple manual review cycles, so it is optimized for fast reading and per-point commenting: point form, hierarchical, complete.

### Prepare

1. Load **`ak-dev-architecture`** — the design must fit the documented architecture (coupling direction, adapter pattern, config via `AKConfig`, pluggable interfaces), not re-derive it. When the change adds a component of a kind covered by an `ak-dev-new-*` skill (framework adapter, guardrail provider, knowledge base, messaging integration, multimodal storage, tracing provider), load that skill too — its checklist defines what "complete" means for the requirements.
2. Do a **scoped evidence pass**: read the code the change touches well enough that every point you write is verified, and record `path:line` for the claims that motivate the change. The document stays point-form, but the points must still be true.
3. If a `research/` folder exists (or you just did investigation worth keeping), draw the Motivation and decisions from it and **cite** the relevant files instead of restating their surveys inline. If the investigation is worth preserving but isn't captured yet, write it under `research/` first (see [Optional: `research/`](#optional-research--supporting-research)).

### Format

Point form throughout — bullets, not paragraphs. Break points into sections and keep them hierarchical (a parent point with indented sub-points) so structure carries the meaning. Every point should be atomic enough for a reviewer to comment on it alone.

```markdown
# #<issue-number>: <one-line summary of the change>

<2–3 sentence summary: what changes, where, and the one-sentence design idea.>

## Motivation

- <Point-form observations from the code, each with its `path:line` evidence>

## Requirements

### <Area or component>

- <Requirement>
  - <Sub-requirement / constraint / concrete value>
- <Requirement>

### <Next area>

...

## Non-goals

- <What this change deliberately does not do>

## Open questions

- <Decisions the requester/reviewer must make — never silently decided>
```

- **Component diagram**: add **one** simple diagram (Mermaid) only if it genuinely clarifies how components relate. Do not add more diagrams, sequence charts, or decoration — an over-diagrammed design is harder to review, not easier.
- **Complete but concise**: every requirement is present; no prose padding, no implementation detail (that belongs in `spec.md`). If a point needs a paragraph to explain, it is probably an implementation detail — push it down to Stage 2 or split it.
- Each requirement still concrete enough to test (see the high bar above) — point form is a format constraint, not a precision discount.

### Review cycles

Deliver `design.md` and stop. The requester reviews it (typically over multiple cycles); apply their edits and keep the document in reviewable point form throughout. Only when they confirm the design is settled does Stage 2 begin.

---

## Stage 2: `spec.md` — the Implementation Spec

`spec.md` details **how** the approved design is built: the detailed design and the implementation components. It follows `design.md` — every requirement there is covered here, and any deviation discovered while detailing goes back through design review rather than being silently absorbed.

### Step 1: Load the Standards to Design Against

Load these skills before writing — the spec must fit the documented architecture, not re-derive it:

1. **`ak-dev-architecture`** — always. Design principles, core abstractions, coupling rules, directory structure.
2. **`ak-dev-code-quality`** — always. Conventions the implementation must follow (typing, logging, formatting, commit/PR rules).
3. **`ak-dev-testing-conventions`** — always. Testing requirements must use real patterns (pytest, async, monkeypatching config, existing test files and their patch targets).

Then route from the areas the change touches to the specialized `ak-dev-new-*` skills, exactly as `ak-dev-review-pr` Step 2 does. When the change adds a component of one of those kinds, the skill's checklist (factory registration, config section, optional-dependency extra, exports, tests, example) defines what "complete" means.

### Step 2: Investigate the Current Code — the Evidence Pass

Before writing a word of detailed design, read the code the change touches and collect evidence:

- Read **every file** that will be created, modified, or deleted — fully, not just the region you expect to change.
- For each claim the spec will make, record `path:line` at the time of writing. Verify counts by enumerating: if you write "this logic appears in seven places", list the seven places.
- Check the supporting surfaces that specs routinely get wrong:
  - **Config**: the actual Pydantic classes in `ak-py/src/agentkernel/core/config.py` — field names, types, defaults, descriptions, and which sections are `Optional` (a missing block may raise `AttributeError`, `ValueError`, or nothing, depending on the default).
  - **Optional dependencies**: which extras in `ak-py/pyproject.toml` cover which imports, and which factory paths actually have `try/except ImportError` (only some do — verify per path, don't generalize).
  - **Factories and wiring**: `SessionStoreBuilder`, `AttachmentStorageManager`, `ResponseDBHandler`, framework/provider factories — what selects the component and what error behavior each has.
  - **Existing tests**: which test files cover the area and what they monkeypatch — `plan.md` must name the patch targets that move.
  - **Dev skills**: grep `.agents/skills/` for references to classes/files the change moves or renames; the plan's final step updates them.
- Note behavior asymmetries between the copies/paths you touch (e.g. one swallows errors where its twin propagates, one checks config where another doesn't). Each asymmetry forces a design decision the spec must make explicitly.

### Step 3: Make the Design Decisions

Design within the documented rules, and when the change unifies or refactors existing behavior, decide deliberately:

- **Coupling direction**: core never imports from `framework/`, `integration/`, `deployment/`, or `api/`. Shared code consumed by both core and deployment lives under `core/` (e.g. `core/util/`), and must not read deployment-specific config.
- **Config-driven, explicitly**: new knobs go through `AKConfig`; shared low-level components take explicit constructor parameters and leave config reading to the stores/factories that own a config section.
- **Adapter conventions**: wrap, don't abstract over; no feature-forcing; consistent shape with siblings in the same category.
- **When unifying divergent copies**: for each divergence found in Step 2, state which behavior wins and why — these are your Behavioural changes section. A unification that doesn't enumerate its behavior changes is describing a different change than the one that will ship.

### Step 4: Write the Spec

Write to `docs/specs/<issue-number>-<short-title>/spec.md` with this structure (sections may be omitted only when genuinely empty, never to save effort):

```markdown
# #<issue-number>: <one-line summary> — Implementation Spec

<Lead paragraph: what changes, where, and the one-sentence design idea.
Reference design.md as the requirements source.>

## Design

### <One subsection per new/changed component>

<Directory layout for new packages. Interface sketches as code blocks —
signatures and one-line comments, not full implementations. The governing
rules ("drivers never read AKConfig") stated as numbered rules with the
reasoning.>

### Consumer changes

<Per consumer: what is deleted, what changes, what is verified unchanged.>

### Config changes

<Exact class/field changes; state what happens to YAML files and AK_* env
vars written before the change.>

### Behavioural changes

<Numbered, exhaustive, each marked intentional with its justification.
Follow with explicit **Non-changes**: data layouts, public exports,
signatures that stay fixed.>

## Error handling

<Failure modes and what surfaces where: connection failures, missing config,
missing optional dependencies.>

## Testing

<New test files and what they assert; existing test files with the exact
patch targets/assertions that change; the command to run the suite.>
```

Trace every `design.md` requirement into a spec section. If detailing reveals a requirement that can't be met as designed, don't quietly redesign — update `design.md`, flag it for re-review, then continue.

### Step 5: Cover the Details Specs Routinely Omit

Walk this checklist before calling the spec done — these are the gaps reviews find in otherwise-strong specs:

- **Exception scope**: any retry/error-handling behavior states *which exception types* it catches. When existing copies differ (one catches `RedisError`, another bare `Exception`), unifying silently changes behavior — pick and document.
- **Concurrency contract**: for any component shared across threads (ECS consumer threads, `ThreadRunner` tasks) or event loops, state the thread-safety expectation. Lazy init and check-then-act reconnects that are fine per-event-loop can race in multi-threaded consumers.
- **Per-operation cost**: if the design adds work to every operation (a health-check ping, an extra round trip), name it on the hot paths it lands on and accept or mitigate it explicitly.
- **Naming consistency**: within one new package, one concept gets one name. Don't rename a method on one backend and keep the old name on its sibling.
- **Riskiest consumer gets a test**: the Testing section must cover the consumer whose code changes shape the most — not only the shiny new component. If that consumer has no existing test file, the plan adds one.
- **Absolute claims audited**: every "all", "only", "never", "each" claim gets checked against each instance it quantifies over. Where reality is "some", write "some" and name which.
- **Config compatibility**: field names, types, and defaults before vs after; effect on existing YAML and env vars; what happens to field *descriptions* (they surface in generated docs).
- **Data compatibility**: whether data written before the change is read back identically after it — state it either way.

### Step 6: Self-Review Against the Review Rubric

`ak-dev-review-pr` Step 3 will judge the spec set on completeness, consistency with the architecture skills, internal consistency, and testability — and will extract every must/should/will statement as a requirement. Pre-empt it:

1. Extract your own requirements checklist from `design.md` and `spec.md`. Every requirement must map to a spec section (and later a plan step); anything that doesn't is either missing or shouldn't be stated as a requirement.
2. Re-verify each `path:line` citation and quoted default against the current base branch (they go stale fast on an active repo).
3. Check for undefined terms, contradictory requirements, and references to components that don't exist.

---

## Stage 3: `plan.md` — the Implementation Plan

Written only after `design.md` and `spec.md` are complete. `plan.md` breaks the implementation into **iterations/steps** — it says *in what order* the spec gets built, not *how* (that detail already lives in `spec.md`). Keep it concise, simple, and easily understandable; do not restate spec content.

```markdown
# #<issue-number>: <one-line summary> — Implementation Plan

## Iteration 1: <name>

- **Goal:** <what is working at the end of this iteration>
- **Files:** <files created/edited>
- **Steps:** <short numbered steps, referencing spec.md sections>
- **Verify:** <the test command / check that proves the iteration done>

## Iteration 2: ...

## Iteration N-1: Tests

<From spec.md's Testing section: new test files, changed patch targets,
the command to run the suite.>

## Iteration N: Sync docs and skills

<Which `.agents/skills/` files and docs surfaces the change invalidates —
name file and line. State explicitly (and verify) when a surface needs no
update, and confirm with the ak-dev-sync-docs-from-branch /
ak-dev-sync-skills-from-branch flows before merge.>
```

- Each iteration should leave the branch in a working, testable state.
- Every `spec.md` component appears in exactly one iteration; the tests and docs/skills-sync iterations are never omitted.

---

## PR Guidance

When spec documents ship as their own PR (implementation to follow separately):

- Use a `docs:` commit/PR title (e.g. `docs: add design spec for #492 shared database drivers`) — specs are documentation; a `feat:` title makes reviewers expect code.
- In the PR template, mark **Documentation update** (or **Other: design spec**) and say explicitly that implementation follows in a separate PR.
- Testing/checklist items that don't apply to a spec-only PR: state that they don't apply rather than leaving the template untouched.
- `design.md` typically ships (and is reviewed) before `spec.md` and `plan.md` exist — separate PRs per stage are fine and expected.
- A `research/` folder, when present, ships in the same PR as the `design.md` it backs (it is that design's evidence) — no separate PR, and it is not held to the spec review bar.

When the spec documents and implementation ship together, the specs go in the first commit so reviewers can read them before the code, and `ak-dev-review-pr` will check the implementation against them.

## Output Expectations

Report back to the requester:

1. Which stage you completed, the document path(s), and a summary of the key decisions.
2. Open questions you could not resolve from the code — decisions the requester must make, listed explicitly (these also appear in `design.md`).
3. For Stage 2+: behavioural changes the design implies, so nobody discovers them in review.
4. For Stage 3: which `ak-dev-*` skills and docs surfaces the implementation will need to update (from the plan's final iteration).
5. What the next stage is and that it waits on the requester's review of the current one.

Do not start the next stage, and do not start implementing, unless asked.

## Common Pitfalls

- Writing `spec.md` (or `plan.md`) before `design.md` has been reviewed — the review cycles on the design are the point of the staged process.
- A `design.md` written in prose paragraphs, or padded with implementation detail — it must be point-form, hierarchical, and fast to read; detail belongs in `spec.md`.
- Over-diagramming: more than one diagram, or a diagram that decorates rather than clarifies.
- Citing file paths, line numbers, or config defaults from memory instead of reading them — reviewers re-verify every claim against the base branch.
- Describing only the happy path — no error handling, no missing-config behavior, no edge cases.
- A "Behavioural changes" section that isn't exhaustive — if unifying divergent code, every divergence resolved is a behavior change to list.
- Writing requirements no test could verify ("handle errors gracefully").
- Silently deviating from `design.md` while writing `spec.md` — deviations go back through design review.
- A `plan.md` that restates the spec instead of ordering it, or that omits the tests / docs-and-skills-sync iterations.
- Making silent design decisions on questions the requester should answer — surface them as open questions in `design.md` instead.
- Titling a spec-only PR `feat:` and leaving the PR template unfilled.
- Drifting from writing the documents into implementing them.
- Treating `research/` as mandatory (it is optional), backfilling it after `plan.md` to look thorough, or inlining its surveys into `design.md` instead of citing them.
