# ScopeWise Competition Readiness Design

**Date:** 2026-09-01

**Objective:** Raise ScopeWise's competition strength by making curriculum change impact visible, reducing unsupported model links, exposing real Agent Kernel execution, and packaging a five-minute reproducible demonstration.

## Competition outcome

The product must demonstrate one coherent claim: a student can reuse historical study material safely after a module or lecturer changes because every recommendation is checked against the current scope, current assessment guidance, exact evidence, and an explicit human decision.

The enhancement must improve the two highest-weight rubric categories without expanding into unrelated capabilities. It will not add automatic YouTube discovery, generated answers, exam prediction, cloud inference, billing, or collaborative accounts.

## User flow

The existing four-step flow remains the primary navigation:

1. Add current material and historical questions.
2. Confirm required objectives and explicit exclusions.
3. Compare and review questions.
4. Make a practice pack.

When the current lecturer, syllabus, notes, or assessment guidance changes, ScopeWise adds a **Change impact** panel to Home. The panel explains the evidence state and the concrete consequences:

- A lecturer name change invalidates assessment guidance but does not claim the paper changed.
- Replacing the approved syllabus retires objectives tied to the previous syllabus.
- Existing analyses and packs are marked stale and counted.
- Questions remain available as source material; their old judgments cannot enter a new pack.
- The next safe action links directly to the affected workflow step.

After a model comparison, each question can reveal **How ScopeWise reached this suggestion**. This provenance view lists retrieval mode, candidate objective count, exclusions checked, approved guidance excerpts retrieved, citations discarded, the Agent Kernel agent name, and the remaining human-review requirement. It never exposes prompts, account identifiers, session keys, raw vectors, or internal exception details.

## Architecture

### 1. Deterministic candidate selection

A new focused module, `scopewise/candidates.py`, selects the objectives supplied to the alignment agent for one question.

`select_candidates(question: str, objectives: list[Objective], semantic_scores: dict[str, float] | None = None, limit: int = 6) -> CandidateSelection` returns:

- every explicit exclusion with a direct significant-term overlap;
- required objectives with significant-term overlap;
- up to `limit` required objectives ranked by local embedding similarity when vectors are available;
- deterministic metadata describing selection mode and selected objective IDs.

Significant terms are lowercase alphanumeric tokens after removing a small, fixed list of assessment verbs and English stop words. Exact identifiers and technical terms such as `BCNF`, `AVL`, `3NF`, `primary key`, and `diagonalization` remain significant. Keyword overlap can include a candidate but cannot independently certify alignment.

`KernelEngine` obtains `semantic_scores` by embedding the question and every approved objective in one local Ollama batch, then computing cosine similarity. The scorer returns `None` if Ollama is unavailable or returns vectors with incompatible dimensions. Candidate selection itself remains deterministic and has no network access.

If local embeddings fail, selection falls back to keyword ranking and records `lexical` mode. If keyword ranking returns no required objective, the agent receives explicit exclusions plus no required candidate and must return uncertainty unless an exclusion is supported.

### 2. Exclusion-first validation

The model remains responsible for its semantic suggestion, but the application enforces these rules after structured output:

- Unknown objective or guidance aliases are discarded as they are now.
- If an explicit exclusion candidate has direct technical-term overlap and the model reason identifies that exclusion but omits its alias, the result is downgraded to `uncertain`; the application does not silently manufacture a beyond-scope judgment.
- `beyond_scope` is accepted only with an explicit-exclusion objective and its exact approved citation.
- `aligned` and `partial` are accepted only for objective aliases supplied in the per-question candidate set.
- A required candidate selected only by embedding similarity remains a suggestion and still requires model reasoning, an approved objective citation, and human review.

This layer reduces broad-topic hallucinations without converting similarity scores into curriculum truth.

### 3. Run provenance

`KernelEngine` owns a fresh in-memory `run_trace` for each extraction, comparison, or assistant call. It records bounded structured events:

```json
{
  "agent": "scopewise_align",
  "retrieval_mode": "semantic",
  "candidate_objective_count": 3,
  "exclusions_checked": 1,
  "guidance_chunks": 2,
  "discarded_references": 0,
  "human_review_required": true
}
```

`Jobs._work` copies the trace into the completed or failed job record. It stores counts, modes, and owner-scoped resource IDs only. Trace fields are server-authored; model output cannot set them. Failed jobs keep a bounded failure phase and never store partially accepted judgments.

Each saved analysis copies a per-question provenance record keyed by `question_id`. `CourseService.bundle` returns it with the analysis. Existing analyses without provenance remain readable and display “Run details unavailable for this earlier comparison.”

### 4. Change impact ledger

The store gains `change_event` resources. `CourseService` records an event only when one of these accepted mutations changes the course revision:

- lecturer changed;
- document approval changed;
- approved syllabus replaced;
- objective approval or content changed;
- guidance approval changed;
- a reviewed judgment changed.

Each event contains `type`, `revision`, `created`, a human-readable server-authored summary, affected counts, and optional document IDs from the same owner/course. It contains no uploaded text, model content, or secrets.

`CourseService.change_impact(owner, course_id) -> dict` returns:

- the most recent relevant event;
- current scope and assessment version numbers;
- stale analysis and pack counts;
- retired objective count;
- whether approved current guidance exists;
- a constrained next action: `sources`, `scope`, `review`, or `packs`;
- a plain-language statement that lecturer identity is not assessment evidence.

The assistant receives a new read-only Agent Kernel tool, `get_change_impact`, using owner and course from `ToolContext`. The tool cannot mutate approvals or judgments.

### 5. Interface changes

Home adds one Change impact card above statistics when the current revision invalidates an analysis/pack or when guidance requires reconfirmation. It uses one primary next-action button and progressive disclosure for the event history.

Question review adds a collapsed provenance section inside each judgment disclosure. Labels use student-facing language:

- “Compared by the local ScopeWise agent”
- “Meaning search” or “Keyword fallback”
- “Checked N possible objectives and M explicit exclusions”
- “Used N current-guidance excerpts”
- “You still make the final decision”

The interface must not show framework class names as the primary language. A smaller technical disclosure names `AgentService`, the registered agent, and Agent Kernel tools for judges and reviewers.

The existing job recovery panel remains. If aliases are discarded but a usable uncertain result is saved, the provenance explains the discard without presenting the run as failed.

## Competition demonstration package

Create `COMPETITION.md` as a rubric-evidence matrix containing:

- the exact product claim and SDG 4 connection;
- repository locations proving Agent Kernel agents, tools, sessions, and Telegram integration;
- deterministic test and live-model evidence;
- honest limitations and live-demo prerequisites;
- the required final submission checklist.

Revise `README.md` so the required sections are explicit and easy to scan: Problem statement, Solution overview, Setup instructions, How to run, How Agent Kernel is used, and Verification.

Revise `DEMO.md` into a timed script of at most five minutes:

1. 0:00-0:35 - problem and two independent judgments;
2. 0:35-1:20 - upload/index current and historical sources;
3. 1:20-2:15 - lecturer change and Change impact;
4. 2:15-3:25 - comparison, provenance, and human correction;
5. 3:25-4:15 - reviewed pack and coverage gap;
6. 4:15-4:45 - Agent Kernel assistant/tool call through Telegram or the web fallback;
7. 4:45-5:00 - SDG 4 value, local privacy, and limitations.

Add `scripts/judge_check.py`, a deterministic command that validates configuration files, required documentation headings, a temporary database migration, and the presence of downloaded local models when Ollama is reachable. It prints actionable PASS/WARN/FAIL lines and exits nonzero only for requirements that prevent the repository from running. `python -m scripts.judge_check --full` additionally runs pytest, Ruff, formatting, and JavaScript syntax checks in subprocesses; the default mode does not recursively run its own test.

## Testing

### Deterministic tests

- Candidate selection does not offer a primary-key objective for an indexing-only question.
- Candidate selection retains a BCNF exclusion for a BCNF proof question.
- Candidate selection uses lexical fallback when embedding fails.
- Unknown aliases produce uncertainty and increment discarded-reference provenance.
- Provenance cannot be supplied through model output or client review payloads.
- Owner A cannot read owner B's change impact or trace.
- Lecturer change records an event, withdraws guidance approval, and reports stale artifacts without predicting a changed paper.
- Replacing a syllabus reports retired objectives and the correct next action.
- Earlier databases and analyses without new fields remain readable.
- Judge check distinguishes hard failures from optional Telegram/Ollama warnings.

### Live evaluation

Re-run the existing five-question development evaluation after the change and preserve the actual output. Add at least eight new synthetic adversarial cases covering prerequisites, related-but-unassessed concepts, explicit exclusions, paraphrased objectives, missing guidance, and same-topic/different-depth questions. These remain development regressions, not an independent accuracy claim.

### Product verification

- Run all pytest, Ruff, formatting, and JavaScript syntax checks.
- Exercise upload, source search, comparison, provenance, lecturer change, stale pack behavior, and mobile layout in the browser.
- Build the frozen Docker image and run the container smoke test.
- Run the live Agent Kernel smoke test with local Ollama.
- If real Telegram credentials are supplied by the user, verify one private-chat link, course selection, tool-backed response, and unlink. Otherwise label Telegram as implemented and deterministically tested but not live-verified.

## Security and product constraints

- No Agent Kernel core files change.
- Every store query remains owner-scoped.
- Only local Ollama endpoints are permitted; no cloud fallback or paid API.
- Retrieval similarity never becomes proof of scope.
- Source content remains untrusted data and cannot set tool identity, aliases, trace fields, or authorization.
- Human review remains mandatory before a question enters a pack.
- Lecturer identity alone never establishes assessment format.
- Old papers never define current objectives or current guidance.
- Sample results remain visibly synthetic and human-authored.
- One worker, bounded files, bounded prompts, bounded trace events, and the existing rate limits remain.

## Acceptance criteria

The enhancement is complete when:

1. The competition rubric evidence is visible in documentation and demonstrable in under five minutes.
2. A lecturer or syllabus change produces an evidence-safe impact report with a clear recovery action.
3. Every new comparison exposes bounded server-authored Agent Kernel provenance.
4. The adversarial regression prevents the known broad-topic and missed-exclusion failure classes without weakening citation or review gates.
5. The app passes deterministic tests, browser checks, Docker smoke, and the live local-model smoke; any live-model semantic errors remain recorded rather than hidden.
6. Telegram is either live-verified with user-supplied credentials or explicitly labeled as not live-verified.
