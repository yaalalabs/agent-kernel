# 07 · Builder: Test & Trace tab

| | |
|---|---|
| Artboards | `Builder-TestTrace` (main), `Builder-TestTrace-Stopped`, `Builder-TestTrace-StartFailed`, `Builder-TestTrace-Streaming`, `Builder-TestTrace-Failing`, `Builder-TestTrace-Compare` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 5 of 6 artboards. Not drawn yet: `Builder-TestTrace-Compare`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

The inner loop of building, entirely on this computer: start the project locally, send a test message, watch
the trace of that same run beside it, and keep the exchange as a test case. Nothing here needs a deployment.

## Layout

- `DesktopShell` with the Test & Trace tab active. `RunControl` reads "Running · localhost:8000".
- Two equal columns: Test on the left, Trace on the right.
- A Tests strip across the bottom, above the bottom panel.

## Content

**Test column.**
- Header: agent select "triage", a session chip "s_41be", a toggle "Stream (delta)" on, "New session".
- Saved scenarios as chips: "Damaged order refund", "Invoice copy", "Plan upgrade", "+ Save current".
- Transcript:
  1. User: "I need a refund for order A-8841, it arrived damaged".
  2. triage: a `ToolCallCard` `lookup_order({"order_id": "A-8841"})` with its result and "212 ms".
  3. A `HandoffDivider`: "Handoff · triage → billing".
  4. billing: an `ApprovalCard`, pending: `refund_payment(order_id="A-8841", amount=240.0)`, "Rule BR-004:
     amount > 200", with "Approve", "Deny", "Cancel".
- Composer: placeholder "Message triage", an attach control, "Send".

**Trace column.**
- Header: run id "run_5e21a0", chips "3.2 s", "1,592 tokens", "$0.021", and a source chip "Local run".
- A `SpanTree` with an inline `Waterfall` on a 0 to 3.2 s axis:

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
| Tool · refund_payment | paused | tool, waiting on the user |

- Span detail for the selected span: tabs Input, Output (active), Metadata; the output in the code block;
  "in 804 · out 211 · 0.98 s · $0.013".

**Tests strip.**
- "app_test.py · 42 cases", a chip "Last run: 40 passed · 2 failed", a button "Run tests".
- `ResultSquares`: 42 squares, 40 passed and 2 failed, with a link "2 failing".
- "Covers 9 of 12 business rules", link "See uncovered rules" (BR-005, BR-010, BR-012).
- "Save this exchange as a test case".

## Behaviour (must work)

- `RunControl` starts and stops the local run. While stopped the tab shows `Builder-TestTrace-Stopped`.
- Clicking a scenario chip or "Send" plays the exchange: messages arrive in order while the span tree and the
  waterfall grow in step.
- Clicking a span selects it and updates the span detail.
- "Approve" resolves the approval card, the paused span completes and the run finishes. "Deny" ends the run
  with a denied card.
- "Run tests" fills the squares one by one and ends at 40 passed, 2 failed. The command appears in the
  Commands panel.
- "2 failing" opens `Builder-TestTrace-Failing`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-TestTrace-Stopped` | first | The project is not running. An `EmptyState` across both columns: "Start the project to test it", the command that will run (`uv run python app.py`) and a primary "Start". The Tests strip still works. |
| `Builder-TestTrace-StartFailed` | first | The local run stopped during start. `RunControl` is in its failed state. A banner: "The project did not start: OPENAI_API_KEY is not set", with "Add the key in Settings", "Show run log" and the AI button "Ask Claude Code to fix". The bottom panel is open on Run log. |
| `Builder-TestTrace-Streaming` | first | Mid-run. The last agent message is partial with a cursor, the last spans have no duration yet and their bars are growing, "Send" has become "Stop". |
| `Builder-TestTrace-Failing` | first | The strip expanded: the two failing cases with Prompt, Expected, Actual, the score 0.62, a "Replay in Test" link and the AI button "Fix with AI" on one. |
| `Builder-TestTrace-Compare` | second | The Trace column in compare mode: two run ids side by side (3.2 s and 2.1 s), the span tree showing a delta per row. |

## Tweaks

- `split`: 50/50 or 40/60. `testsStrip`: collapsed or open.

## Handoff notes

- The local run serves the project on a local port from the project's own Python environment. The Test column
  talks to it over the same REST and SSE interface a deployed project exposes.
- The trace is built from the run's stream events, so no tracing provider is needed. Frameworks that do not
  stream give run-level timing only; the trace column should say so instead of showing an empty tree.
- Stream events are Agent Kernel's real types: message start and end, text delta, reasoning, tool call start,
  args, end and result, step start and end.
- Tests run with `uv run pytest`, using `test-config.yaml` for the comparison mode and judge model.
- During a local test the person at the keyboard is the approver.
