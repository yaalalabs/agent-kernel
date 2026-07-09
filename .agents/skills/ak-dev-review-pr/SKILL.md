---
name: ak-dev-review-pr
description: >
  Review a GitHub pull request against Agent Kernel's architecture, design
  principles, code quality standards, and testing conventions, then post the
  findings back to the PR as review comments. When the PR contains a spec.md,
  the spec is reviewed first and the implementation is checked against it.
  Use this skill when given a PR number or URL to review, e.g. "review PR 342"
  or "run a review on https://github.com/yaalalabs/agent-kernel/pull/342".
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

While listing the changed files, check whether the PR includes a spec — any added or modified `spec.md` (case-insensitive, any directory). If one exists, Step 3 is mandatory and runs before any code is reviewed.

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
| `.agents/skills/` or `skills/` (user skills) | `ak-dev-sync-skills-from-branch` — use its conventions to judge skill content and placement |

A PR can match several rows — load every matching skill. If the PR touches one of these areas only incidentally (e.g. a mechanical rename brushing `trace/`), a skim of the skill's checklist is enough; when the PR *adds or substantially modifies* that kind of component, walk the guide's checklist step by step and flag every step the PR skipped (missing factory registration, missing config section, missing optional-dependency extra, missing exports, missing tests, missing example).

These skills are the source of truth for what "complete" means in each area. When a finding concerns one of these areas, cite the specific checklist step or convention from the loaded skill, not a general impression.

## Step 3: Review the Spec First (When the PR Contains One)

If the PR adds or modifies a `spec.md`, review it **before** reading any implementation code, so the spec is judged on its own merits rather than rationalized from the code:

1. **Review the spec itself** and record findings on it like any other file:
   - Completeness: does it cover behavior, configuration, error handling, and edge cases — or only the happy path?
   - Consistency with Agent Kernel: does the design it describes respect the principles in `ak-dev-architecture` (framework-agnostic core, adapter pattern, config via `AKConfig`, pluggable interfaces, coupling direction)?
   - Internal consistency: no contradictory requirements, undefined terms, or references to components that don't exist.
   - Testability: are the stated behaviors concrete enough to verify?
2. **Extract a requirements checklist** from the spec — every "must/should/will" statement, config key, interface, and named behavior.
3. **Then use that checklist as an additional review rubric** for the implementation (dimension 6 below): every requirement is either implemented, explicitly deferred in the PR description, or flagged; every implemented behavior that contradicts or silently extends the spec is flagged.

Spec findings anchor to lines of `spec.md` in the diff like any other inline comment; spec-vs-implementation gaps anchor to the implementation line where the deviation lives (or to the spec line if nothing was implemented at all).

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

### 6. Spec conformance (when the PR contains a spec.md)

Walk the requirements checklist extracted in Step 3:

- Every requirement in the spec is implemented in this PR, or its deferral is explicitly stated in the PR description — silent omissions are findings.
- The implementation matches the spec's stated behavior, naming, config keys, and interfaces — deviations are findings even when the deviation looks reasonable, phrased as `[question]` if the code might be right and the spec stale.
- Behavior implemented beyond the spec is flagged as a `[question]` — either the spec should grow or the code should shrink.
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
  "body": "<summary: 2-4 sentences — overall assessment, count of findings by severity, anything positive worth noting>",
  "comments": [
    {
      "path": "ak-py/src/agentkernel/core/session/redis.py",
      "line": 42,
      "side": "RIGHT",
      "body": "**[blocker]** <what is wrong and why, citing the convention>. Suggestion: <concrete fix>."
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
- If posting fails on a specific comment (usually a line-anchoring error), move that finding into the summary body and retry rather than dropping it.

## Output Expectations

After posting, report back to the requester:

1. The PR reviewed (number, title, link) and its CI status.
2. If the PR contained a `spec.md`: the spec verdict first — findings on the spec itself, then which requirements are implemented, deferred, missing, or deviated from.
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
- Reviewing from memory of the conventions instead of loading the `ak-dev-*` skills.
- Loading only the three always-on skills and skipping the path-to-skill routing in Step 2 — component PRs then get reviewed without the checklist that defines what "complete" means for that component.
- Reading the implementation before the spec when the PR contains a `spec.md` — the code biases how the spec is judged, and spec gaps get rationalized as intended behavior.
- Reviewing code against the spec but forgetting to review the spec document itself.
