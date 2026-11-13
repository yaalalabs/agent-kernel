# 17 · Traces

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Operate-Traces` (main), `Operate-Traces-Blocked`, `Operate-Traces-Metrics`, `Operate-Traces-Provider` |
| Canvas page | Operate |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with links. Selecting a span is good to have. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

Observability for every run: a filterable run list and, for the selected run, the span tree and waterfall
across hooks, guardrails, the framework runner, model calls, tools and handoffs.

## Layout

- `AppShell` with Traces active. Tabs "Runs" (active) and "Metrics".
- A filter bar, then the run table in the upper part and the run detail in the lower part.
- Run detail: span tree, waterfall, span detail, left to right.

## Content

**Filter bar.** "Last 24 hours", "Agent: all", "Channel: all", "Status: all", a toggle "Errors only", a search
"Run id or session id", and a provider chip "Provider: Langfuse" with a settings control.

**Run table** (`DataTable`). Columns: Time, Run id, Agent, Channel, Status, Duration, Tokens, Cost. Seven
rows. The selected row: "12:04:01 · run_5e21a0 · triage → billing · Slack · Paused · 3.2 s · 1,592 · $0.021".
Other rows are Completed, with one "Blocked by guardrail".

**Span tree and waterfall** for run_5e21a0, on a 0 to 3.2 s axis. Rows and bars align one to one.

| Span | Duration | Kind |
|------|----------|------|
| Run · triage | 3.2 s | run |
| Pre-hooks | 61 ms | hook |
| Input guardrail · OpenAI Guardrails | 48 ms | guardrail |
| Runner · OpenAI Agents SDK | 1.6 s | runner |
| LLM · gpt-4o | 1.21 s | llm |
| Tool · lookup_order | 212 ms | tool |
| Handoff · billing | | handoff |
| Runner · LangGraph | 1.4 s | runner |
| LLM · claude-sonnet-4-5 (selected) | 0.98 s | llm |
| Tool · refund_payment | paused | tool, waiting on a human |
| Post-hooks | 70 ms | hook |
| Output guardrail · Walled AI | 61 ms | guardrail |

**Span detail** for the selected model call. Tabs Input, Output (active), Metadata; the output text and a tool
call in a code block; "Tokens in 804 · out 211", "Latency 0.98 s", "Cost $0.013", "Temperature 0.2"; a button
"Open in Langfuse".

## Behaviour

- Selecting the blocked run goes to `Operate-Traces-Blocked`. The Metrics tab goes to
  `Operate-Traces-Metrics`. The provider settings control opens `Operate-Traces-Provider`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Operate-Traces-Blocked` | first | The blocked run selected. The tree stops after "Input guardrail · OpenAI Guardrails", marked blocked; two bars only; the span detail shows the verdict with the reason "PII detected: card number". |
| `Operate-Traces-Metrics` | second | Four chart cards: "Runs per hour", "Latency p50 / p95", "Cost by agent" (triage, billing, kb-researcher), "Guardrail blocks". Series values are placeholders until real data exists. |
| `Operate-Traces-Provider` | second | A modal "Tracing provider": Langfuse (selected), OpenLLMetry (Traceloop), Pydantic Logfire, Amazon CloudWatch, Custom (Python class path); the keys as `SecretChip`s; a toggle "Enabled"; "Cancel" and "Save". |

## Tweaks

- `detailSplit`: tree and waterfall side by side, or waterfall inline in the tree (as in brief 07).

## Handoff notes

- Use the same span-kind mapping as brief 07 and the Playground events.
- Spans are read from the configured tracing provider. How much detail a run has depends on the framework.
- Charts follow the design system's chart guidance: one scale per chart, labelled axes, theme tokens.
