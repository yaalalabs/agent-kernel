# ScopeWise Competition Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make curriculum-change impact, evidence-safe model reliability, and real Agent Kernel execution visible and reproducible in a five-minute competition demonstration.

**Architecture:** Add deterministic per-question objective candidate selection before the alignment agent, preserve bounded server-authored provenance beside each analysis, and record course change events through `CourseService`. Expose impact and provenance through the existing FastAPI bundle and progressive-disclosure UI, then package the rubric evidence and judge checks without changing Agent Kernel core.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, Agent Kernel/Pydantic AI, SQLite, local Ollama embeddings and chat, vanilla JavaScript/CSS, pytest, Ruff, Docker Compose.

**Spec:** `use-cases/scopewise/docs/superpowers/specs/2026-09-01-competition-readiness-design.md`

## Global Constraints

- Keep every application change inside `use-cases/scopewise/`; do not modify Agent Kernel core.
- Only local Ollama endpoints are permitted; no cloud inference or paid API fallback.
- Similarity can select evidence candidates but cannot certify curriculum or assessment fit.
- Every lookup and stored trace remains owner/course scoped.
- Lecturer identity alone never establishes assessment format.
- Explicit exclusions require an approved objective and exact source evidence.
- Human review remains mandatory before a question enters a practice pack.
- Source files and model output cannot set identity, authorization, aliases, provenance, or change events.
- Do not commit or push without the repository owner's explicit authorization.

---

### Task 0: Preserve the verified ScopeWise baseline

**Files:**
- Add: all currently untracked files under `use-cases/scopewise/`, excluding paths ignored by `use-cases/scopewise/.gitignore`
- Verify: `use-cases/scopewise/tests/`

**Interfaces:**
- Consumes: the already verified 35-test ScopeWise implementation.
- Produces: a clean tracked baseline so competition enhancements can be reviewed as focused diffs.

- [ ] **Step 1: Verify ignored private/generated files**

Run:

```bash
git check-ignore -v \
  use-cases/scopewise/.env \
  use-cases/scopewise/data/scopewise.sqlite3 \
  use-cases/scopewise/output/local-evaluation.json \
  use-cases/scopewise/.venv/pyvenv.cfg
```

Expected: every path is ignored by `use-cases/scopewise/.gitignore`.

- [ ] **Step 2: Re-run baseline verification**

Run:

```bash
cd use-cases/scopewise
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --check static/app.js
```

Expected: 35 tests pass and all static checks pass.

- [ ] **Step 3: Stage and inspect the baseline**

Run:

```bash
git add use-cases/scopewise
git status --short
git diff --cached --stat
git diff --cached --check
```

Expected: application, tests, docs, lockfile, and container files are staged; `.env`, `data/`, `output/`, caches, and `.venv/` are absent.

- [ ] **Step 4: Commit the baseline**

```bash
git commit -m "feat: add ScopeWise evidence-based study navigator"
```

### Task 1: Select safe per-question objective candidates

**Files:**
- Create: `use-cases/scopewise/scopewise/candidates.py`
- Modify: `use-cases/scopewise/scopewise/agents.py`
- Modify: `use-cases/scopewise/scopewise/retrieval.py`
- Test: `use-cases/scopewise/tests/test_candidates.py`
- Test: `use-cases/scopewise/tests/test_agents.py`

**Interfaces:**
- Consumes: `Objective`, `retrieval.embed_texts(texts) -> tuple[str, list[list[float]]]`.
- Produces: `CandidateSelection`, `select_candidates(question, objectives, semantic_scores=None, limit=6)`, and `KernelEngine._semantic_scores(question, objectives)`.

- [ ] **Step 1: Write failing lexical candidate tests**

Create `tests/test_candidates.py` with:

```python
from scopewise.candidates import select_candidates
from scopewise.models import Evidence, Objective


def objective(identifier, text, kind="required"):
    return Objective(
        id=identifier,
        text=text,
        kind=kind,
        approved=True,
        evidence=Evidence(document_id="syllabus", page=1, quote=text),
    )


def test_unrelated_database_topic_is_not_offered_by_lexical_fallback():
    selection = select_candidates(
        "Explain why indexing can improve query performance.",
        [objective("keys", "Explain primary keys and distinguish candidate keys.")],
    )
    assert selection.mode == "lexical"
    assert selection.objectives == []


def test_direct_explicit_exclusion_is_always_retained():
    exclusion = objective("bcnf", "BCNF proofs are explicitly excluded from this module.", "excluded")
    selection = select_candidates("Prove that every BCNF relation is in third normal form.", [exclusion])
    assert [item.id for item in selection.objectives] == ["bcnf"]
    assert selection.exclusion_ids == ["bcnf"]
```

- [ ] **Step 2: Run the tests to verify red**

Run: `.venv/bin/pytest tests/test_candidates.py -q`

Expected: collection fails because `scopewise.candidates` does not exist.

- [ ] **Step 3: Implement deterministic candidate selection**

Create `scopewise/candidates.py` with a frozen dataclass and fixed token policy:

```python
import re
from dataclasses import dataclass

from .models import Objective

STOP = {
    "a",
    "an",
    "and",
    "apply",
    "calculate",
    "compare",
    "construct",
    "define",
    "describe",
    "discuss",
    "every",
    "explain",
    "for",
    "given",
    "how",
    "in",
    "is",
    "of",
    "prove",
    "show",
    "that",
    "the",
    "this",
    "to",
    "use",
    "why",
}
TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CandidateSelection:
    objectives: list[Objective]
    mode: str
    exclusion_ids: list[str]
    keyword_ids: list[str]


def significant_terms(text: str) -> set[str]:
    return {token for token in TOKEN.findall(text.casefold()) if token not in STOP and len(token) > 1}


def select_candidates(question, objectives, semantic_scores=None, limit=6):
    question_terms = significant_terms(question)
    overlap = {item.id: len(question_terms & significant_terms(item.text)) for item in objectives}
    exclusions = [item for item in objectives if item.kind == "excluded" and overlap[item.id] > 0]
    required = [item for item in objectives if item.kind == "required" and overlap[item.id] > 0]
    mode = "semantic" if semantic_scores else "lexical"
    if semantic_scores:
        remaining = [item for item in objectives if item.kind == "required" and item not in required]
        remaining.sort(key=lambda item: semantic_scores.get(item.id, -1), reverse=True)
        required.extend(item for item in remaining if semantic_scores.get(item.id, -1) >= 0.36)
    seen = set()
    chosen = []
    for item in [*exclusions, *required[:limit]]:
        if item.id not in seen:
            seen.add(item.id)
            chosen.append(item)
    return CandidateSelection(chosen, mode, [item.id for item in exclusions], [item.id for item in chosen if overlap[item.id] > 0])
```

- [ ] **Step 4: Add semantic ranking and failure tests**

Add tests proving a paraphrased objective with score `0.71` is retained, a `0.20` unrelated objective is omitted, and `semantic_scores=None` reports lexical mode without raising.

- [ ] **Step 5: Add a vector-score helper**

In `retrieval.py`, add:

```python
def cosine(left, right):
    if not left or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
```

In `KernelEngine`, add `_semantic_scores` that calls `embed_texts([question, *objective_texts])`, verifies vector count, and returns `{objective.id: cosine(query, vector)}`. Catch local embedding errors and return `None`.

- [ ] **Step 6: Supply only candidates to each alignment call**

Inside `analyze`, compute selection per question, create aliases only for `selection.objectives`, keep the full approved-objective list for final evidence validation, and do not reuse aliases across questions. Record selection metadata for Task 2.

- [ ] **Step 7: Verify the candidate integration**

Run:

```bash
.venv/bin/pytest tests/test_candidates.py tests/test_agents.py -q
.venv/bin/ruff check scopewise/candidates.py scopewise/agents.py scopewise/retrieval.py tests/test_candidates.py
```

Expected: candidate and existing agent-boundary tests pass.

- [ ] **Step 8: Commit**

```bash
git add use-cases/scopewise/scopewise/candidates.py use-cases/scopewise/scopewise/agents.py use-cases/scopewise/scopewise/retrieval.py use-cases/scopewise/tests/test_candidates.py use-cases/scopewise/tests/test_agents.py
git commit -m "feat: constrain ScopeWise objective candidates"
```

### Task 2: Persist bounded Agent Kernel provenance

**Files:**
- Modify: `use-cases/scopewise/scopewise/agents.py`
- Modify: `use-cases/scopewise/scopewise/jobs.py`
- Modify: `use-cases/scopewise/scopewise/service.py`
- Test: `use-cases/scopewise/tests/test_agents.py`
- Test: `use-cases/scopewise/tests/test_jobs.py`
- Test: `use-cases/scopewise/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 `CandidateSelection`; current `Jobs.submit/_work` and analysis resources.
- Produces: `KernelEngine.run_trace: list[dict]`, job `trace`, and analysis `provenance: dict[question_id, dict]`.

- [ ] **Step 1: Write failing trace tests**

Add a fake engine whose `analyze` returns one valid `Analysis` and sets:

```python
self.run_trace = [
    {
        "question_id": question_id,
        "agent": "scopewise_align",
        "retrieval_mode": "lexical",
        "candidate_objective_count": 1,
        "exclusions_checked": 1,
        "guidance_chunks": 0,
        "discarded_references": 0,
        "human_review_required": True,
    }
]
```

Assert the completed job has `trace`, the saved analysis has provenance keyed by the question ID, and none of `owner`, `prompt`, `vector`, or `session_id` appears in serialized trace JSON.

- [ ] **Step 2: Verify the tests fail**

Run: `.venv/bin/pytest tests/test_jobs.py -q`

Expected: saved job and analysis lack trace/provenance.

- [ ] **Step 3: Build server-authored trace events**

At the start of `KernelEngine.extract`, `analyze`, and `chat`, clear `self.run_trace`. In `analyze`, append one event after resolving each structured decision. Compute `discarded_references` from aliases absent from that question's objective/guidance maps before `decision_match`; do not read this count from model prose.

Limit the trace to 50 events and each field to scalar values or the current question ID. Do not store source text or model reasons.

- [ ] **Step 4: Copy trace through the job boundary**

In `Jobs._work`, use:

```python
trace = list(getattr(engine, "run_trace", []))[:50]
job["trace"] = trace
```

For comparison jobs, save `provenance = {event["question_id"]: event for event in trace if event.get("question_id")}` beside `matches`. For failed jobs, retain only events already completed and add no partial analysis record.

- [ ] **Step 5: Protect provenance from client mutation**

Keep provenance outside `Match`. Add an API test that sends a `provenance` key with `PATCH /api/analyses/{analysis_id}/matches`; Pydantic must reject the extra field or the service must drop it, and stored analysis provenance must remain unchanged.

- [ ] **Step 6: Verify backward compatibility**

Add a test loading the existing seeded analysis without provenance and assert `CourseService.bundle` returns it unchanged. New UI copy will handle the absent key.

- [ ] **Step 7: Run focused and full tests**

Run:

```bash
.venv/bin/pytest tests/test_agents.py tests/test_jobs.py tests/test_api.py -q
.venv/bin/pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add use-cases/scopewise/scopewise/agents.py use-cases/scopewise/scopewise/jobs.py use-cases/scopewise/scopewise/service.py use-cases/scopewise/tests/test_agents.py use-cases/scopewise/tests/test_jobs.py use-cases/scopewise/tests/test_api.py
git commit -m "feat: expose evidence-safe Agent Kernel provenance"
```

### Task 3: Record and explain change impact

**Files:**
- Modify: `use-cases/scopewise/scopewise/service.py`
- Modify: `use-cases/scopewise/scopewise/app.py`
- Modify: `use-cases/scopewise/scopewise/agents.py`
- Modify: `use-cases/scopewise/scopewise/sample.py`
- Modify: `use-cases/scopewise/scripts/smoke_model.py`
- Test: `use-cases/scopewise/tests/test_changes.py`
- Test: `use-cases/scopewise/tests/test_api.py`

**Interfaces:**
- Consumes: existing course revisions, document/objective approvals, analyses, packs, and `ToolContext`.
- Produces: `CourseService.record_change`, `CourseService.edit_course`, `CourseService.change_impact`, bundle field `change_impact`, and Agent Kernel tool `get_change_impact`.

- [ ] **Step 1: Write failing lecturer-impact tests**

Extend `tests/test_changes.py`:

```python
def test_lecturer_change_reports_evidence_safe_impact(tmp_path):
    store = Store(tmp_path / "impact.db")
    course = seed_sample(store, "alice")
    service = CourseService(store)
    service.prepare_pack("alice", course["id"], 5)
    service.edit_course("alice", course["id"], lecturer="New lecturer")
    impact = service.change_impact("alice", course["id"])
    assert impact["stale_analysis_count"] == 1
    assert impact["stale_pack_count"] == 1
    assert impact["has_current_guidance"] is False
    assert impact["next_action"] == "sources"
    assert "does not prove" in impact["statement"]
```

Add a second test proving `change_impact("bob", alice_course)` raises `KeyError`.

- [ ] **Step 2: Verify the tests fail**

Run: `.venv/bin/pytest tests/test_changes.py -q`

Expected: `CourseService.edit_course` and `change_impact` do not exist.

- [ ] **Step 3: Implement bounded change events**

Add `record_change(owner, course_id, event_type, summary, affected=None, document_ids=None)` that validates the course and every supplied document owner/course before storing a `change_event` resource with `time.time()`, current revision, counts, and a 300-character server-authored summary.

Add `edit_course` that snapshots the old course, calls `store.update_course`, and records `lecturer_changed` only when lecturer actually changed. Route `PATCH /api/courses/{course_id}` through this service method.

- [ ] **Step 4: Record approval and review mutations**

After successful mutations, record:

- `syllabus_replaced` with retired-objective count;
- `guidance_changed` when guidance approval changes;
- `source_approval_changed` for other document roles;
- `scope_changed` when an objective is saved/approved;
- `judgment_changed` when a reviewed match changes.

Do not create an event for a no-op update.

- [ ] **Step 5: Implement the impact projection**

`change_impact` computes stale counts from current revision/review versions, retired objectives from objectives tied to unapproved syllabus documents, and current guidance from approved guidance documents. Choose next action in this order:

1. `sources` when no current guidance exists after a lecturer/guidance change;
2. `scope` when no required objective is approved;
3. `review` when analyses are absent/stale;
4. `packs` when no current pack exists.

Return at most the latest 10 change events in reverse chronological order.

- [ ] **Step 6: Add change impact to the course bundle**

Set `result["change_impact"] = self.change_impact(owner, course_id)` in `CourseService.bundle`. Update API isolation tests to prove cross-owner access remains 404.

- [ ] **Step 7: Register the Agent Kernel tool**

Inside `KernelEngine.__init__`, add:

```python
def get_change_impact() -> dict:
    """Explain what current course changes invalidated and the next safe review step."""
    owner, course = context()
    self.tool_events.append("get_change_impact")
    return CourseService(store).change_impact(owner, course)
```

Bind it with the existing assistant tools and mention it in the assistant instructions. Extend the smoke test to ask “What changed?” and assert the tool event when the sample has a change event.

- [ ] **Step 8: Run tests**

Run:

```bash
.venv/bin/pytest tests/test_changes.py tests/test_api.py tests/test_agents.py -q
.venv/bin/pytest -q
```

- [ ] **Step 9: Commit**

```bash
git add use-cases/scopewise/scopewise/service.py use-cases/scopewise/scopewise/app.py use-cases/scopewise/scopewise/agents.py use-cases/scopewise/scopewise/sample.py use-cases/scopewise/scripts/smoke_model.py use-cases/scopewise/tests/test_changes.py use-cases/scopewise/tests/test_api.py
git commit -m "feat: explain curriculum change impact"
```

### Task 4: Present impact and provenance without increasing UI complexity

**Files:**
- Modify: `use-cases/scopewise/static/app.js`
- Modify: `use-cases/scopewise/static/style.css`
- Modify: `use-cases/scopewise/static/index.html`
- Test: `use-cases/scopewise/tests/test_api.py`

**Interfaces:**
- Consumes: bundle `change_impact`, analysis `provenance`, existing `nav`, `pill`, `latest`, and escaped rendering helpers.
- Produces: Home Change impact card and collapsed per-question run-details disclosure.

- [ ] **Step 1: Add API shape assertions before UI work**

In `tests/test_api.py`, assert sample bundles contain `change_impact` with only the documented fields and new analyses can include provenance keyed by approved question IDs.

- [ ] **Step 2: Render one actionable impact card**

Add `changeImpact()` in `app.js`. Return an empty string when there is no stale work and approved current guidance exists. Otherwise render a `.impact-card` with:

- heading “Your module changed”;
- server-authored escaped statement;
- stale judgment/pack counts;
- one primary `nav` button based on the constrained `next_action` mapping;
- a `<details>` event list capped by the API.

Insert it after the Home hero and before statistics.

- [ ] **Step 3: Render collapsed provenance per question**

Add `provenanceView(questionId)` that looks up `latest()?.provenance?.[questionId]`. If absent, return a one-line earlier-run message. If present, render student labels plus a nested technical `<details>` naming `AgentService` and the escaped registered agent name.

Place this inside `.judgment-disclosure`, after the two judgments and before action buttons. Keep it closed by default.

- [ ] **Step 4: Add responsive styles**

Style `.impact-card`, `.impact-counts`, and `.run-details` using existing colors, borders, and type scale. At `max-width:760px`, stack impact content and preserve 44px tap targets. Do not add a new navigation item.

- [ ] **Step 5: Bust static cache and verify syntax**

Increment the `?v=` query in `index.html`, then run:

```bash
node --check static/app.js
.venv/bin/ruff check .
```

- [ ] **Step 6: Browser acceptance check**

Using the sample course:

1. change lecturer;
2. confirm the impact card states uncertainty rather than predicting a paper change;
3. open one question's run details;
4. verify no raw prompt/vector/owner identifier appears;
5. verify `documentElement.scrollWidth === innerWidth` at 1280px and 390px;
6. verify no console errors.

- [ ] **Step 7: Commit**

```bash
git add use-cases/scopewise/static/app.js use-cases/scopewise/static/style.css use-cases/scopewise/static/index.html use-cases/scopewise/tests/test_api.py
git commit -m "feat: show change impact and agent provenance"
```

### Task 5: Create competition evidence and one-command judge checks

**Files:**
- Create: `use-cases/scopewise/COMPETITION.md`
- Create: `use-cases/scopewise/scripts/judge_check.py`
- Modify: `use-cases/scopewise/README.md`
- Modify: `use-cases/scopewise/DEMO.md`
- Modify: `use-cases/scopewise/EVALUATION.md`
- Modify: `use-cases/scopewise/scripts/evaluate_model.py`
- Test: `use-cases/scopewise/tests/test_judge_check.py`

**Interfaces:**
- Consumes: repository paths, `Store`, local `ollama list`, test/lint commands, and current development evaluation.
- Produces: `scripts.judge_check.check(root) -> list[Check]`, CLI `python -m scripts.judge_check [--full]`, rubric matrix, and timed demo.

- [ ] **Step 1: Write failing judge-check tests**

Create a temporary project fixture with README headings and assert:

```python
checks = check(root)
assert not [item for item in checks if item.level == "FAIL"]
```

Remove `## How to run` and assert a `FAIL` names that heading. Mock missing Ollama and assert a `WARN`, not `FAIL`.

- [ ] **Step 2: Implement deterministic checks**

Use:

```python
@dataclass(frozen=True)
class Check:
    level: Literal["PASS", "WARN", "FAIL"]
    name: str
    detail: str
```

Check required files, exact README headings, `Store(temp_path)` plus `PRAGMA integrity_check`, `config.yaml`, and whether `ollama list` contains both configured models. Never print environment variable values. With `--full`, run these exact subprocesses from the use-case root:

```text
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --check static/app.js
```

- [ ] **Step 3: Make README requirements explicit**

Ensure these headings appear exactly:

```markdown
## Problem statement
## Solution overview
## Setup instructions
## How to run
## How Agent Kernel is used
## Verification
```

Keep privacy, limitations, Telegram setup, and deployment details, but lead with the two-judgment differentiator and Change impact.

- [ ] **Step 4: Write the rubric matrix**

In `COMPETITION.md`, map all four scoring categories to exact files and demo moments. Include SDG 4, the fork/team-ID/star checklist, and clearly mark live Telegram and public deployment as unchecked unless actually verified.

- [ ] **Step 5: Replace DEMO with the approved timed sequence**

Use the seven time blocks from the spec. Include the exact clicks, sample labels, expected visible evidence, spoken caveats, and a fallback when Ollama or Telegram is unavailable. Keep total narration below five minutes.

- [ ] **Step 6: Expand the development regression**

Add exact cases to `evaluate_model.py` for:

```python
ADVERSARIAL = [
    ("Explain why indexing improves query performance.", "uncertain"),
    ("Prove that every BCNF relation is in third normal form.", "beyond_scope"),
    ("Distinguish a primary key from a candidate key.", "aligned"),
    ("Explain B+ tree leaf-node splitting.", "uncertain"),
    ("Decompose the supplied relation into third normal form.", "aligned"),
    ("State the definition of third normal form.", "partial"),
    ("Write a join combining customer and order tables.", "aligned"),
    ("Use relational division to find students taking every course.", "uncertain"),
]
```

Record candidate mode, selected objectives, expected status, actual status, discarded references, and latency. Preserve actual failures and continue labeling this as a development regression.

- [ ] **Step 7: Run documentation and judge checks**

Run:

```bash
.venv/bin/pytest tests/test_judge_check.py -q
.venv/bin/python -m scripts.judge_check
.venv/bin/python -m scripts.judge_check --full
```

- [ ] **Step 8: Commit**

```bash
git add use-cases/scopewise/COMPETITION.md use-cases/scopewise/scripts/judge_check.py use-cases/scopewise/README.md use-cases/scopewise/DEMO.md use-cases/scopewise/EVALUATION.md use-cases/scopewise/scripts/evaluate_model.py use-cases/scopewise/tests/test_judge_check.py
git commit -m "docs: package ScopeWise competition evidence"
```

### Task 6: Run release-level verification and record truthfully

**Files:**
- Modify: `use-cases/scopewise/EVALUATION.md`
- Modify: `use-cases/scopewise/output/local-evaluation.json` (generated and ignored; do not commit)
- Verify: all application, test, container, and documentation files

**Interfaces:**
- Consumes: Tasks 1-5 and local Ollama.
- Produces: verified branch state and an honest release record.

- [ ] **Step 1: Run deterministic verification**

```bash
cd use-cases/scopewise
.venv/bin/python -m scripts.judge_check --full
git diff --check
```

Expected: no hard failure.

- [ ] **Step 2: Run live Agent Kernel smoke and evaluation**

```bash
.venv/bin/python -m scripts.smoke_model
.venv/bin/python -m scripts.evaluate_model
```

Expected: actual Agent Kernel tool events are printed; evaluation writes actual outcomes without replacing failures.

- [ ] **Step 3: Build and smoke the container**

```bash
docker build -t scopewise:competition .
docker run --rm -d --name scopewise-competition -p 127.0.0.1:8081:8080 scopewise:competition
.venv/bin/python -m scripts.container_smoke http://127.0.0.1:8081
docker stop scopewise-competition
```

Expected: health, auth, sample, upload, stale-pack, and cascade smoke pass.

- [ ] **Step 4: Run final browser demonstration**

Follow `DEMO.md` once at desktop width and verify the upload/index, impact, provenance, human correction, pack, and assistant flows. Repeat layout checks at 390px. Keep the verified app tab available to the user.

- [ ] **Step 5: Update the evaluation record**

Record exact test count, model name, evaluation counts, latency range, container result, browser result, and Telegram status in `EVALUATION.md`. Do not claim independent accuracy, production readiness, live Telegram, or public deployment unless each was actually exercised.

- [ ] **Step 6: Inspect the complete branch diff**

```bash
git status --short --branch
git diff --stat de3466d..HEAD
git diff --check de3466d..HEAD
git log --oneline -7
```

- [ ] **Step 7: Commit the verification record**

```bash
git add use-cases/scopewise/EVALUATION.md
git commit -m "test: record ScopeWise competition verification"
```

Do not push or open a pull request until the user explicitly requests it.
