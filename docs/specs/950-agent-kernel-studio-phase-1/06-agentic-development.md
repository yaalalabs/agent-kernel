# 06 · Agentic development workspace

| | |
|---|---|
| Artboards | `AgenticDev-Workspace` (main), `AgenticDev-RuleDetail`, `AgenticDev-OutOfSync`, `AgenticDev-Diff` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 3 of 4 artboards. Not drawn yet: `AgenticDev-Diff`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | A, building |
| Read first | [00-project-brief.md](00-project-brief.md), [05-build-with-ai.md](05-build-with-ai.md) |

## Job

The expanded form of the Build with AI drawer. Chat, code and business rules sit side by side so a business
owner and a developer look at the same project from three angles: what was asked, what the coding agent wrote,
and the plain-language rules the system must obey. Every rule links to the lines and config keys that enforce
it and to the tests that cover it. A rule the files no longer satisfy is flagged out of sync.

## Layout

- `DesktopShell` with no tab active; the title "Agentic development" and a "Back to canvas" link in the top
  bar; Build with AI shown active.
- Three columns: chat, code workspace, business rules. The code workspace takes the remaining width.
- At 1280 and below, Rules becomes a tab of the code workspace.

## Content

**Chat column.** Header: Claude mark, "Claude Code", "Connected · this computer". Transcript:
1. User: "Refunds above $200 must be approved before they are issued".
2. Agent: "Added rule BR-004 and implemented it", followed by three `ToolCallCard` rows: "Edited tool.py +9",
   "Edited app.py +4", "Edited app_test.py +3 cases".
3. A card "Rule created · BR-004" with a link "View rule".
Composer: placeholder "Ask for a change or add a rule", skill chips "/ak-build" and "/ak-test".

**Code workspace.**
- `FileTree` of the fixture's project files, `tool.py` selected, with AI markers on the three edited files.
- Editor tabs: tool.py (active), app.py, config.yaml. The editor shows about two dozen lines of Python: the
  `refund_payment` function with type hints and a docstring, and the approval condition `amount > 200`.
- Nine lines carry an AI gutter marker. Above them an `AnnotationPill`: "Implements BR-004 · Refunds above
  $200 require approval".
- Editor actions: "Diff", "Explain" (AI button), "Open in editor".

**Business rules column.**
- Header "Business rules" with the count "12 rules · 11 enforced · 1 out of sync".
- Filter chips: All (active), Routing, Approval, Compliance, Data, Tone, Safety.
- One `RuleCard` per rule from the fixture table in brief 00, in id order. Each card shows the id, the rule,
  its category, an "Enforced by" row of chips naming files and config keys, and a "Tests" line ("3 tests" or
  "No tests").
- BR-004 and BR-011 carry the `AIBadge`. BR-009 is in the out-of-sync state: "Out of sync · Signature footer
  is not registered on billing", with the AI button "Fix with AI".
- A sticky input at the bottom: "Add a rule in plain language", with the AI button "Implement".

## Behaviour (must work)

- Clicking a rule card opens the file that enforces it and highlights the enforcing lines. Clicking BR-004
  shows the nine marked lines in tool.py.
- Clicking the annotation pill selects its rule card and scrolls it into view.
- "Diff" toggles the editor between source and a side-by-side diff.
- A filter chip filters the cards.
- Typing a rule and pressing "Implement" adds a card in the Drafted state, then plays a short scripted
  exchange in the chat and moves the card to Enforced.
- "Fix with AI" on BR-009 plays the out-of-sync exchange from `AgenticDev-OutOfSync`.
- "Back to canvas" goes to `Builder-Canvas`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `AgenticDev-RuleDetail` | first | A detail panel over the rules column for BR-004: the rule, a short rationale, an "Enforced by" list with file and line (`tool.py:42`, `app.py:88`) and "Show" links, a "Covered by" list of three test cases with pass marks, and a history of two entries (created by Claude Code, accepted by you). |
| `AgenticDev-OutOfSync` | first | BR-009 across all three columns. The rule card is out of sync; the editor is on app.py with a warning marker where billing is registered without the hook; the chat shows a suggestion card "BR-009 is not enforced for billing. Register the Signature footer post-hook on billing?" with "Yes, fix it" and "Ignore". |
| `AgenticDev-Diff` | second | The editor in diff mode on tool.py: before and after, "9 additions · 0 deletions". |

## How business rules map to project files

| Category | Example | Enforced by |
|----------|---------|-------------|
| Routing | Slack #support messages go to triage first | The channel's routed agent in `config.yaml`; handoff descriptions in `app.py` |
| Approval | Refunds above $200 need approval | A tool's approval condition; the agent's human-in-the-loop setting |
| Compliance | PII never reaches the model unredacted | Guardrail providers in `config.yaml`; preconditions in `tool.py` |
| Data | Only kb-researcher writes to the Help Center | Knowledge roles in `config.yaml`; read-only backends |
| Tone | Replies end with the support signature | A post-hook in `hooks.py`; agent instructions |
| Safety | Agent code runs with network off | A sandbox profile in `config.yaml` |

## Tweaks

- `canvasStrip`: a read-only strip of the canvas along the bottom, with the nodes that enforce the selected
  rule highlighted. Off by default.
- `rulesWidth`: narrow or wide.

## Handoff notes

- Rules live in the working directory, in `.akstudio/`, so they travel with the project and can be committed.
- A rule's links are data: file, line range, config key, node id, test case ids. The UI only renders them.
- Out of sync is recomputed whenever a linked file changes on disk.

## Open details

- The file format for rules, and whether rules also appear as comments in the code they govern.
