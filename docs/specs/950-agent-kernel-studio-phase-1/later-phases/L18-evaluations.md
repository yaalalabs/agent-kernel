# 18 · Evaluations

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Operate-Evaluations` (main), `Operate-Evaluations-Running`, `Operate-Evaluations-Empty`, `Operate-Evaluations-NewCase` |
| Canvas page | Operate |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with links |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The built-in test framework as a product surface: suites of cases run against an agent, scored by a pluggable
evaluator, with a pass-rate history and per-case differences. The coding agent can generate cases.

## Layout

- `AppShell` with Evaluations active, environment "Staging".
- Three columns: a suites list, the suite view, a config panel.

## Content

**Suites list.** A header "Suites" with an add control. Rows: name, case count, pass rate, last run.

| Suite | Cases | Pass rate |
|-------|-------|-----------|
| Support regression (selected) | 42 | 95% |
| Billing refunds | 12 | 100% |
| Handoff routing | 18 | 88%, below the gate |
| Knowledge answers | 24 | 92% |

**Suite view.**
- Header "Support regression" with chips "agent: triage", "evaluator: DeepEval", "mode: fallback",
  "judge: gpt-4o-mini", "threshold: 0.80". Actions: primary "Run suite", the AI button "Generate cases with
  AI", "Edit".
- A toggle row: "Run on every deploy to Staging", on, helper "Deploys are blocked below the gate", chip
  "Gate: 90%".
- Card "Pass rate · last 14 runs": a line chart ending at 95%, the latest point emphasised. Caption "Last run
  12 minutes ago · 40 passed · 2 failed · 2 min 18 s". Earlier points are placeholders until real history
  exists.
- A `DataTable` "Cases": Case, Prompt, Expected, Actual, Metric ("score" or "llm"), Score, Result. Seven rows.
  The fourth is a failure, expanded: score 0.62, "Expected" and "Actual" side by side with the differing phrase
  highlighted, "Judge rationale: the reply omits the 30-day window stated in the policy.", and a link "Open run
  trace".

**Config panel.**
- Card "test.yaml": the file in a code block (agent triage, evaluator deepeval, mode fallback, llm model
  gpt-4o-mini, threshold 0.8) and "Edit file".
- Card "Evaluator": "DeepEval (default)" selected, "Opik", "TypeSafe JEV · llm mode only", "Custom · Python
  class path".
- Card "Modes": "score · deterministic match", "llm · judge model decides", "fallback · score first, then
  llm".

## Behaviour

- "Run suite" goes to `Operate-Evaluations-Running`. "Open run trace" goes to `Operate-Traces`.
- The add control and "Generate cases with AI" open `Operate-Evaluations-NewCase` and the Build with AI
  drawer.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Operate-Evaluations-Running` | first | "Run suite" has become "Stop", a progress bar reads "Running 27 / 42", three rows show "Running". |
| `Operate-Evaluations-Empty` | first | No suites. An `EmptyState`: "No evaluation suites yet", with "Create suite" and the AI button "Generate from recent conversations". |
| `Operate-Evaluations-NewCase` | second | A modal "New case": "Prompt" and "Expected" fields, a select "Metric: fallback", a threshold slider at 0.80, a toggle "Generate expected answer with AI", "Cancel" and "Add case". |

## Tweaks

- `configPanel`: shown or hidden.

## Handoff notes

- Evaluators and modes are the framework's real ones. TypeSafe JEV supports the llm mode only.
- Each case can link to the business rules it covers. That link is what "Covers 9 of 12 business rules" in
  brief 07 counts.
