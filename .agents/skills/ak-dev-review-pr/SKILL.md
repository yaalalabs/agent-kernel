---
name: ak-dev-review-pr
description: >
  Review a GitHub pull request against Agent Kernel's architecture, design
  principles, code quality standards, and testing conventions, then post the
  findings back to the PR as review comments. When the PR contains spec
  documents (design.md, spec.md, or plan.md under docs/specs/), they are
  reviewed first — each at its own stage's altitude — and any implementation
  is checked against them. Use this skill when given a PR number or URL to
  review, e.g. "review PR 342" or "run a review on
  https://github.com/yaalalabs/agent-kernel/pull/342".
license: Apache-2.0
metadata:
  author: yaalalabs
  category: developer
---

# Review a Pull Request Against Agent Kernel Practices

Use this skill when asked to review a specific pull request by number or URL. It fetches the PR with the GitHub CLI (`gh`), reviews the delta against Agent Kernel's documented practices, and pushes the verified findings to the PR as a single review with inline comments.

This skill is for **reviewing someone else's PR**, not for reviewing your own uncommitted working-tree changes.

## Goal

Produce a thorough, low-noise review grounded in Agent Kernel's own standards — architecture, code quality, and testing skills — and publish it on the PR so the author can act on it, without duplicating feedback that is already on the PR.

## Inputs

- **PR identifier** (required): a number (`342`), a URL, or `owner/repo#number`. If only a number is given, resolve the repository from the `origin` remote of the current checkout.
- **Optional scope hints**: the requester may narrow the review ("focus on the session store changes") — honor them, but still flag anything clearly dangerous outside that scope.

If no PR identifier can be determined, stop and ask for one. Do not guess.

## Step 1: Fetch the PR Context

Gather everything before forming opinions:

```bash
# Metadata: title, body, author, base/head, state, linked issues
gh pr view <N> --json number,title,body,author,baseRefName,headRefName,state,files,additions,deletions,url

# The full diff
gh pr diff <N>

# Existing discussion and review comments — needed for dedupe in Step 5
gh pr view <N> --comments
gh api repos/{owner}/{repo}/pulls/<N>/comments --paginate

# CI status
gh pr checks <N>
```

Then make the PR head readable locally **without touching the developer's working tree**:

```bash
git fetch origin pull/<N>/head:refs/remotes/pr/<N>
git show pr/<N>:<path>          # read any file at the PR head
```

Never run `gh pr checkout` — it would switch the developer's branch.

Read the full content of every changed source file at the PR head, not just the diff hunks. A diff hunk without surrounding context is the main source of false-positive review comments.

While listing the changed files, check whether the PR includes spec documents — any added or modified `design.md`, `spec.md`, or `plan.md` under `docs/specs/<issue-number>-<short-title>/` (case-insensitive; also match a bare `spec.md` elsewhere from before the staged layout). If any exists, Step 3 is mandatory and runs before any code is reviewed.

## Step 2: Load the Standards to Review Against

Load these skills and use them as the review rubric — do not review from memory:

1. **`ak-dev-architecture`** — always. Design principles, core abstractions, execution flow, directory structure.
2. **`ak-dev-code-quality`** — always. Formatting, typing, logging, Python style, commit conventions, PR guidelines.
3. **`ak-dev-testing-conventions`** — always. Test patterns, async testing, mocking, CI workflows.

Then route from the PR's changed file paths to the specialized skills. Take the file list from Step 1 and load every skill whose paths the PR touches:

| Changed paths (under `ak-py/src/agentkernel/` unless noted) | Skill to load |
| --- | --- |
| `framework/<name>/` — new or modified framework adapter | `ak-dev-new-framework-integration` |
| `guardrail/` — guardrail provider or hook changes | `ak-dev-new-guardrail-provider` |
| `knowledgebase/` — knowledge base backend or builder tools | `ak-dev-new-knowledgebase-integration` |
| `integration/<platform>/` — messaging platform handlers, webhook routes | `ak-dev-new-messaging-integration` |
| `core/multimodal/` — attachment stores or multimodal handling | `ak-dev-new-multimodal-storage` |
| `trace/` — tracing providers or traced runners | `ak-dev-new-tracing-provider` |
| `docs/`, `README.md`, `ak-py/README.md`, deployment/example READMEs (repo root) | `ak-dev-sync-docs-from-branch` — use its docs-surface map to check the right surfaces were updated |
| `.agents/skills/` or `ak-py/src/agentkernel/skills/` (user skills) | `ak-dev-sync-skills-from-branch` — use its conventions to judge skill content and placement |

A PR can match several rows — load every matching skill. If the PR touches one of these areas only incidentally (e.g. a mechanical rename brushing `trace/`), a skim of the skill's checklist is enough; when the PR *adds or substantially modifies* that kind of component, walk the guide's checklist step by step and flag every step the PR skipped (missing factory registration, missing config section, missing optional-dependency extra, missing exports, missing tests, missing example).

These skills are the source of truth for what "complete" means in each area. When a finding concerns one of these areas, cite the specific checklist step or convention from the loaded skill, not a general impression.

## Step 3: Review the Spec Documents First (When the PR Contains Any)

A change is specified in up to three staged documents under `docs/specs/<issue-number>-<short-title>/` (per `ak-dev-write-spec`): `design.md` — concise point-form requirements, reviewed and approved first; `spec.md` — detailed implementation spec that follows the approved design; `plan.md` — concise iteration breakdown of the implementation. A PR may contain any subset: a `design.md`-only PR is a design review cycle, a later PR adds `spec.md` and/or `plan.md`, and an implementation PR may carry all three alongside the code.

If the PR adds or modifies any of these documents, review them **before** reading any implementation code, so the spec set is judged on its own merits rather than rationalized from the code. Load `ak-dev-write-spec` — its per-document structure, staged-process rules, and completeness checklists are the rubric.

**Judge each document at its own stage's altitude** — do not demand implementation detail from a design spec or re-litigate approved design in a plan:

- **`design.md`**: point-form, hierarchical, and complete — every requirement present, each point atomic and concrete enough to test. Prose paragraphs, implementation detail (belongs in `spec.md`), more than one diagram, or silent decisions on things that should be open questions are findings. This document is optimized for fast expert review — verbosity is a defect, not thoroughness.
- **`spec.md`**: the full completeness rubric applies — behavior, configuration, error handling, edge cases, and the "details specs routinely omit" checklist (exception scopes, concurrency contracts, per-operation cost, naming consistency, riskiest-consumer test coverage, absolute-claim audits, config/data compatibility). Every `design.md` requirement must be covered; a deviation from `design.md` that isn't explicitly called out is a finding.
- **`plan.md`**: orders the spec without restating it — every `spec.md` component appears in exactly one iteration, each iteration leaves the branch working and testable, and the tests and docs/skills-sync iterations are present. Restated spec content or missing final iterations are findings.

Check the staging itself: a PR that introduces `spec.md` alongside a brand-new, never-reviewed `design.md` skips the design review cycles the process exists for — raise it as a `[question]` unless the PR description says the design was approved elsewhere.

Then, across whichever documents the PR contains:

1. **Verify the documents' factual claims against the base branch** — file:line citations, config defaults, "appears in N places" counts, and described behaviors. An unverified claim that turns out false is a finding; a spec whose claims all verify deserves saying so in the summary.
2. **Review each document itself** and record findings on it like any other file:
   - Completeness at its stage's altitude (see above) — or only the happy path?
   - Consistency with Agent Kernel: does the design it describes respect the principles in `ak-dev-architecture` (framework-agnostic core, adapter pattern, config via `AKConfig`, pluggable interfaces, coupling direction)?
   - Internal consistency: no contradictory requirements, undefined terms, or references to components that don't exist.
   - Cross-document consistency: `spec.md` covers every `design.md` requirement; `plan.md` covers every `spec.md` component. (Only check against documents that exist — on the base branch or in this PR.)
   - Testability: are the stated behaviors concrete enough to verify?
3. **Extract a requirements checklist** from the documents — every "must/should/will" statement, config key, interface, and named behavior, from `design.md` and `spec.md` alike.
4. **Then use that checklist as an additional review rubric** for the implementation (dimension 6 below) — this applies only when the PR contains implementation code; for spec-only PRs, dimension 6 is skipped and the report says so.

Spec findings anchor to lines of the document (`design.md`, `spec.md`, or `plan.md`) in the diff like any other inline comment; spec-vs-implementation gaps anchor to the implementation line where the deviation lives (or to the spec line if nothing was implemented at all).

## Step 4: Review Dimensions

Evaluate the delta on each dimension. For each finding, record: file, line (in the PR head), severity, what is wrong, and why — citing the specific principle or convention it violates.

### 1. Architecture & design

- **Framework-agnostic core**: no framework-specific imports or logic in `ak-py/src/agentkernel/core/` — framework code belongs in `framework/<name>/` adapters.
- **Coupling direction**: integrations, deployment adapters, and API layers may depend on core; core must never import from them.
- **Adapter pattern**: new framework/provider code implements the established base interfaces (`Agent`, `Runner`, `Module`, `AttachmentStore`, `BaseTrace`, guardrail hooks) rather than inventing parallel abstractions.
- **Config-driven behavior**: new knobs go through `AKConfig` (Pydantic, YAML/env with `AK_` prefix), not module-level constants or ad-hoc `os.environ` reads.
- **Session lifecycle correctness**: session state mutations happen inside the session context; transient per-request data uses `v_cache`, cross-request data uses `nv_cache`; no state stored on module globals.
- **Plugin interfaces**: pluggable components are registered through the existing factories/builders, not special-cased with `if/else` chains in core.

### 2. Correctness

- Async correctness: no blocking I/O in async paths, no forgotten `await`, no unguarded shared state.
- Error handling: failures surface meaningfully; no silent `except: pass`; resources cleaned up in `finally`.
- Concurrency: anything touching `Runtime`, session stores, or streaming respects the locking model described in `ak-dev-architecture`.
- Behavior matches the PR description; edge cases in the changed logic (empty inputs, missing config, store misses) are handled.

### 3. Code quality

- Type hints on all function signatures; Pydantic `BaseModel` for data models; `ABC`/`@abstractmethod` for interfaces.
- Logging via `logging.getLogger("ak.<module>")` at appropriate levels — no `print`, no root logger.
- Formatting consistent with `black`/`isort` config (line length 150 in `ak-py`, 120 in examples).
- No dead code, commented-out blocks, leftover debug output, or unrelated drive-by changes.
- No secrets, tokens, or hardcoded credentials in code, tests, or example configs.

### 4. Testing

- New features have tests under `ak-py/tests/`; bug fixes have a regression test.
- Tests follow the conventions skill: pytest patterns, async tests, mocking style, no real network calls.
- Existing tests were updated rather than deleted or skipped to make CI pass.

### 5. Docs & examples

- User-facing changes update the relevant docs surfaces (`README.md`, `ak-py/README.md`, `docs/docs/`, deployment/example READMEs).
- New capabilities that warrant an example include or update one under `examples/`.
- New config keys are documented where configuration is described.

### 6. Spec conformance (when the PR contains implementation code covered by spec documents)

Walk the requirements checklist extracted in Step 3 — from the spec documents in this PR, or already on the base branch under `docs/specs/<issue-number>-<short-title>/` for the issue this PR implements. Skip this dimension for spec-only PRs.

- Every requirement in `design.md`/`spec.md` is implemented in this PR, or its deferral is explicitly stated in the PR description or covered by a later `plan.md` iteration — silent omissions are findings.
- The implementation matches the spec's stated behavior, naming, config keys, and interfaces — deviations are findings even when the deviation looks reasonable, phrased as `[question]` if the code might be right and the spec stale.
- Behavior implemented beyond the spec is flagged as a `[question]` — either the spec should grow or the code should shrink.
- When a `plan.md` exists, the PR maps to its iterations — a PR that implements half of one iteration and a third of another warrants a `[question]` about the intended slicing.
- Tests exercise the behaviors the spec promises, not just the code that happens to exist.

## Step 5: Verify Findings

Before anything is posted, re-check every finding against the full file at the PR head (`git show pr/<N>:<path>`):

- Is the "missing" handling actually present elsewhere in the file or a caller?
- Is the flagged pattern already established convention in neighboring code?
- Would the suggested change actually work in this codebase?

Drop anything that does not survive verification. A short list of real issues is worth more than a long list of maybes.

## Step 6: Deduplicate Against Existing Feedback

Compare surviving findings against the comments fetched in Step 1 (both issue comments and inline review comments, including resolved threads). Skip any finding that a human or previous automated review has already raised on the same code, even if worded differently.

## Step 7: Post the Review to the PR

Post **one** review containing all inline comments plus a summary body — never a stream of individual comments.

Build the request as JSON and submit it:

```bash
cat > /tmp/pr-review.json <<'EOF'
{
  "event": "COMMENT",
  "body": "<summary in point form: a one-line overall assessment, then a bullet list — findings count by severity, un-anchorable findings as bullets, anything positive worth noting>",
  "comments": [
    {
      "path": "ak-py/src/agentkernel/core/session/redis.py",
      "line": 42,
      "side": "RIGHT",
      "body": "**[blocker]** <one-line statement of the problem>\n\n- <why: the principle, convention, or failure scenario>\n- <suggestion: concrete fix>"
    }
  ]
}
EOF
gh api repos/{owner}/{repo}/pulls/<N>/reviews --input /tmp/pr-review.json
```

Rules for the posted review:

- **Always use `event: COMMENT`.** Never `APPROVE` or `REQUEST_CHANGES` — approval decisions belong to human maintainers.
- Inline comments can only anchor to lines present in the diff. `line` is the line number in the head version, with `side: RIGHT` (use `start_line` + `line` for multi-line comments). For a finding about a *deleted* line use `side: LEFT`. For findings that cannot be anchored to a diff line (e.g. "missing tests", "docs not updated"), put them in the summary body instead.
- Prefix each comment with a severity tag:
  - `[blocker]` — bug, data loss, security issue, or a clear architecture violation (e.g. framework import in core)
  - `[suggestion]` — should fix, but not merge-blocking
  - `[nit]` — style/polish; only include when the fix is trivial and unambiguous
  - `[question]` — genuine uncertainty about intent; phrase as a question
- Every comment must cite *why* — the principle, convention, or concrete failure scenario — not just *what*. Include a concrete suggested fix when one exists.
- **Write comments in point form, not paragraphs.** Each comment is one bold severity-tagged line stating the problem, followed by short bullets (why, suggestion, references). Nest bullets when a point has sub-details. A `[nit]` may be a single line; anything longer than a sentence or two must be bulleted — never a wall of prose.
- If posting fails on a specific comment (usually a line-anchoring error), move that finding into the summary body and retry rather than dropping it.

## Output Expectations

After posting, report back to the requester:

1. The PR reviewed (number, title, link) and its CI status.
2. If the PR contained spec documents: the spec verdict first — which documents were reviewed (`design.md`/`spec.md`/`plan.md`) and the findings on each; then, if the PR also contains implementation, which requirements are implemented, deferred, missing, or deviated from. For a spec-only PR, state which stage it advances and that dimension 6 was skipped.
3. A findings summary grouped by severity, each with `file:line` and a one-line description.
4. Which findings were skipped as duplicates of existing PR feedback.
5. A link to the posted review.
6. If there were **no** findings: still post the summary-only review saying the change looks consistent with Agent Kernel conventions, and say so in the report.

## Common Pitfalls

- Reviewing only the diff hunks and flagging "missing" code that exists just outside the hunk — always read the full file at the PR head.
- Checking out the PR branch and clobbering the developer's working tree — use `git fetch origin pull/<N>/head` and `git show` instead.
- Posting comments one at a time instead of a single batched review — this spams the author with notifications.
- Anchoring an inline comment to a line that is not part of the diff — the API rejects it; put un-anchorable findings in the summary body.
- Approving or requesting changes — this skill only ever comments.
- Restating feedback that is already on the PR.
- Flagging formatting that `black`/`isort` would fix anyway as individual nits — one summary-level note ("run `make lint`") is enough.
- Writing comments as dense paragraphs — point-form bullets are far easier for the author to scan and act on.
- Reviewing from memory of the conventions instead of loading the `ak-dev-*` skills.
- Loading only the three always-on skills and skipping the path-to-skill routing in Step 2 — component PRs then get reviewed without the checklist that defines what "complete" means for that component.
- Reading the implementation before the spec documents when the PR contains any — the code biases how the spec is judged, and spec gaps get rationalized as intended behavior.
- Reviewing code against the spec but forgetting to review the spec documents themselves.
- Judging a document at the wrong stage's altitude — demanding implementation detail from a point-form `design.md`, or flagging a `plan.md` as "too thin" when its detail correctly lives in `spec.md`.
- Missing spec documents already on the base branch — an implementation PR for an issue with an existing `docs/specs/<issue-number>-<short-title>/` must still be checked against those documents even though they aren't in the diff.
