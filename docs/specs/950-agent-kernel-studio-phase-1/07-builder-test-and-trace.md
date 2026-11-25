# 07 · Builder: Test & Trace tab

| | |
|---|---|
| Artboards | `Builder-TestTrace` (main), `Builder-TestTrace-Stopped`, `Builder-TestTrace-StartFailed`, `Builder-TestTrace-Streaming`, `Builder-TestTrace-Failing`, `Builder-TestTrace-Compare`, `Builder-TestTrace-History`, `Builder-TestTrace-Simulate`, `Builder-TestTrace-CIWorkflow` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 8 of 9 artboards. Not drawn yet: `Builder-TestTrace-Compare`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

The inner loop of building, entirely on this computer: start the project locally, send a test message, watch
the trace of that same run beside it, and keep the exchange as a test case. Run the test file, see why a case
failed, compare runs, and try the system against a simulated user. Nothing here needs a deployment, and
nothing leaves the computer.

## Layout

- `DesktopShell` with the Test & Trace tab active. `RunControl` reads "Running · localhost:8000".
- Two equal columns: Test on the left, Trace on the right.
- A Tests strip across the bottom, above the bottom panel.

## Content

**Test column.**
- Header: agent select "triage", a session chip "s_41be", a toggle "Stream (delta)" on, "New session".
- Saved scenarios as chips: "Damaged order refund", "Invoice copy", "Plan upgrade", "Refund without an order
  number" (with a simulated-user mark), "+ Save current", "+ Simulated user".
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

- `RuleChip`s on spans that enforce a rule: "BR-006" and "BR-007" on the input guardrail span, "BR-004" on
  the paused `refund_payment` span.
- Span detail for the selected span: tabs Input, Output (active), Metadata; the output in the code block;
  "in 804 · out 211 · 0.98 s · $0.013 (estimate)".

**Tests strip.**
- "app_test.py · 42 cases", a chip "Last run: 40 passed · 2 failed" that opens the run history, a button
  "Run tests".
- `ResultSquares`: 42 squares, 40 passed and 2 failed, with a link "2 failing".
- "Covers 9 of 12 business rules", link "See untested rules" (BR-005, BR-010, BR-012).
- "Save this exchange as a test case".
- "Add CI workflow".

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
- The "Last run" chip opens `Builder-TestTrace-History`. "+ Simulated user" opens `Builder-TestTrace-Simulate`.
  "Add CI workflow" opens `Builder-TestTrace-CIWorkflow`.
- A `RuleChip` opens that rule in the Rules view of the Build with AI drawer.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-TestTrace-Stopped` | first | The project is not running. An `EmptyState` across both columns: "Start the project to test it", the command that will run (`uv run python app.py`) and a primary "Start". The Tests strip still works. |
| `Builder-TestTrace-StartFailed` | first | The local run stopped during start. `RunControl` is in its failed state. A banner: "The project did not start: OPENAI_API_KEY is not set", with "Add the key in Settings", "Show run log" and the AI button "Ask Claude Code to fix". The bottom panel is open on Run log. |
| `Builder-TestTrace-Streaming` | first | Mid-run. The last agent message is partial with a cursor, the last spans have no duration yet and their bars are growing, "Send" has become "Stop". |
| `Builder-TestTrace-Failing` | first | The strip expanded: the two failing cases with Prompt, Expected, Actual, and a `JudgeResult`: the score 0.62 against the threshold 0.80 and the judge's reason, "The reply says returns are accepted at any time, which contradicts the 30-day window in the expected answer." The second case scores 0.41: "The agent paused for approval on a $180 refund. The expected answer issues it, because approval starts above $200." A "Replay in Test" link and the AI button "Fix with AI" on one. |
| `Builder-TestTrace-Compare` | second | The Trace column in compare mode: two run ids side by side (3.2 s and 2.1 s), the span tree showing a delta per row. |
| `Builder-TestTrace-History` | second | The Tests strip expanded to a `RunHistory` of five runs, newest first, each with its time, commit (`[COMMIT]`), result and duration: today 14:32, 40 passed and 2 failed, 1 min 12 s; today 11:05, 41 and 1, 1 min 09 s; yesterday 17:48, 39 and 3, 1 min 15 s; yesterday 10:20, 38 and 4, 1 min 06 s; 12 Nov 16:02, 35 and 7, 1 min 02 s. The two newest are selected and a `RunCompare` reads "2 regressions · 1 improvement · 39 unchanged": "Can I return an item after 45 days?" 0.84 → 0.62, "Refund order A-7710 for $180" 0.88 → 0.41, "Send me a copy of my March invoice" 0.55 → 0.91, each with a "Replay in Test" link. |
| `Builder-TestTrace-Simulate` | second | A simulated-user scenario. A form: "Goal" ("Get a refund for a damaged order without giving the order number at first"), "Starting message" ("My order arrived broken and I want my money back"), "Turns" (6), "Plays the user" (the judge model in `test-config.yaml`). Below it the run: turns marked "Simulated user" in a `UserBubble` variant, the agents' replies and tool calls as in the main artboard, then a `JudgeResult` "Goal met in 4 turns" with the judge's reason, and "Save as test case". |
| `Builder-TestTrace-CIWorkflow` | second | A `Modal` "Add a CI workflow": the file `.github/workflows/ak-checks.yml` in a code block, with the steps `uv sync`, `uv run pytest` and `uv run ak rules check`; "Secrets your CI needs" listing the key names the tests use (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`) as `SecretChip`s, with "Add these to your repository's CI secrets"; the note "The app writes this file only. It does not commit, push or run CI."; "Cancel" and "Write file". |

## Tweaks

- `split`: 50/50 or 40/60. `testsStrip`: collapsed or open.

## Handoff notes

- The local run serves the project on a local port from the project's own Python environment. The Test column
  talks to it over the same REST and SSE interface a deployed project exposes.
- The live view is built from the run's stream events, so it works with no tracing provider configured.
- Span detail comes from OpenTelemetry. The app runs a local OTLP receiver and starts the project with
  tracing pointed at it for that run only, through environment variables and without editing `config.yaml`:
  `AK_TRACE__ENABLED=true`, `AK_TRACE__TYPE=openllmetry`, and `TRACELOOP_BASE_URL` set to the receiver. The
  spans add framework-internal steps, latency and token usage, including for frameworks that do not stream,
  and are the data source for the token and cost figures. A control in the trace header chooses where local
  traces go: the app (default) or the project's own tracing provider (Langfuse in the fixture).
- If neither source has span detail for a framework, the trace column says so instead of showing an empty
  tree.
- Span kinds are mapped from both the OpenTelemetry GenAI attributes and OpenLLMetry's own
  (`traceloop.span.kind`), as OAK's trace fetcher already does
  (`ak-py/src/agentkernel/trace/fetch.py`). The GenAI conventions are still in development, so the mapping
  tolerates both.
- Cost is an estimate from token counts and a model price table in the app, and is labelled as one.
- Rule chips come from the rule links: a span whose guardrail, tool or hook is a rule's enforcing element
  carries that rule's id.
- Stream events are OAK's real types: message start and end, text delta, reasoning, tool call start,
  args, end and result, step start and end.
- Tests run with `uv run pytest`, using `test-config.yaml` for the comparison mode and judge model. A failing
  case shows the evaluator's score and its `reason`; OAK's evaluators return both
  (`ak-py/src/agentkernel/test/core/evaluator/base.py`).
- Each test run is recorded in `.akstudio/runs/`, which is ignored by git: time, commit, and per case the
  result, score and reason. History and comparison read only from there.
- A simulated user is an LLM given the goal, the starting message and a turn limit. It talks to the local run
  over the same REST and SSE interface as the Test column. The judge model in `test-config.yaml` plays the user
  by default and decides whether the goal was met, with a reason. Simulated-user scenarios are saved in
  `.akstudio/` with the other scenarios. "Save as test case" adds the finished exchange to `app_test.py`, as
  "Save this exchange as a test case" does.
- "Add CI workflow" writes `.github/workflows/ak-checks.yml` for GitHub Actions. It runs `uv sync`,
  `uv run pytest` and `uv run ak rules check`. The app writes the file only; it does not commit, push, open pull
  requests or run CI.
- During a local test the person at the keyboard is the approver.
- The agent select lists the project's catalog, `GET /api/v1/agents`, which returns one descriptor per agent.
- A project may set `identity` or `authorization` in `config.yaml`. The fixture sets neither, so every local
  call is the anonymous principal and nothing is restricted. When a project does set them, the catalog and
  the chat route answer per caller: with no credential the Test column still acts as the anonymous principal,
  so it lists and reaches only the agents and tools that the project's grants and each agent's visibility
  allow an anonymous caller. A refused call is shown as refused, with the status the runtime returns, never as
  an empty reply.

## Open details

- Where the model price table comes from and how it is kept current.
- CI systems other than GitHub Actions.
- How the Test column sends a credential for a project that sets `identity`, so a test can run as a named
  caller. A principal of the `static` identity provider is the likely answer.
