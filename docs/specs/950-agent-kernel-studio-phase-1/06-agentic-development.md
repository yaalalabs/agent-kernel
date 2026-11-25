# 06 · Agentic development workspace

| | |
|---|---|
| Artboards | `AgenticDev-Workspace` (main), `AgenticDev-RuleDetail`, `AgenticDev-OutOfSync`, `AgenticDev-Diff`, `AgenticDev-GenerateTests` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 4 of 5 artboards. Not drawn yet: `AgenticDev-Diff`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | A, building |
| Read first | [00-project-brief.md](00-project-brief.md), [05-build-with-ai.md](05-build-with-ai.md) |

## Job

The expanded form of the Build with AI drawer. Chat, code and business rules sit side by side so a business
owner and a developer look at the same project from three angles: what was asked, what the coding agent wrote,
and the plain-language rules the system must obey. Every rule links to the lines and config keys that enforce
it and to the tests that cover it. A rule the files no longer satisfy is flagged out of sync; a rule with no
linked test is flagged untested. The same checks run outside the app with `ak rules check`.

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
- Header "Business rules" with the count "13 rules · 8 enforced · 3 untested · 1 out of sync · 1 drafted".
- Filter chips: All (active), Routing, Approval, Compliance, Data, Tone, Safety, Access.
- One `RuleCard` per rule from the fixture table in brief 00, in id order. Each card shows the id, the rule,
  its category, an "Enforced by" row of chips naming files and config keys, and a "Tests" line ("3 tests" or
  "No tests").
- BR-004 and BR-011 carry the `AIBadge`. BR-009 is in the out-of-sync state: "Out of sync · Signature footer
  is not registered on billing", with the AI button "Fix with AI".
- BR-005, BR-010 and BR-012 are in the untested state: "Untested · no linked test", with the AI button
  "Generate tests".
- BR-013 is in the drafted state: "Drafted · not implemented", with the AI button "Implement". Its "Enforced
  by" row is empty and reads "Needs identity and authorization in config.yaml".
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
- "Generate tests" on BR-010 plays the exchange from `AgenticDev-GenerateTests`.
- "Back to canvas" goes to `Builder-Canvas`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `AgenticDev-RuleDetail` | first | A detail panel over the rules column for BR-004: the rule, a short rationale, an "Enforced by" list with file and line (`tool.py:42`, `app.py:88`) and "Show" links, a "Covered by" list of three test cases with pass marks and a "Generate more tests" AI button, and a history of two entries (created by Claude Code, accepted by you). |
| `AgenticDev-OutOfSync` | first | BR-009 across all three columns. The rule card is out of sync; the editor is on app.py with a warning marker where billing is registered without the hook; the chat shows a suggestion card "BR-009 is not enforced for billing. What should change?" with three choices: "Update the code: register the Signature footer post-hook on billing" (selected, the default), "Update the rule: billing replies need no signature", "Update the tests", then "Fix" and "Ignore". |
| `AgenticDev-Diff` | second | The editor in diff mode on tool.py: before and after, "9 additions · 0 deletions". |
| `AgenticDev-GenerateTests` | second | BR-010 "Code run by agents has no network access" (Safety, untested). The chat shows a `PlanCard` "ak-test · 4 cases for BR-010, 3 of them adversarial" and the proposed cases: "Asks the agent to download a file from a URL" (adversarial), "Asks it to install a package with pip" (adversarial), "Hides a host name inside a calculation request" (adversarial), "Asks it to sort a list" (control). A `ToolCallCard` "Edited app_test.py +4 cases" and a `CanvasChangesCard` with "Accept" and "Revert". After "Accept", BR-010 moves to Enforced and the header reads "13 rules · 9 enforced · 2 untested · 1 out of sync · 1 drafted". |

## How business rules map to project files

| Category | Example | Enforced by |
|----------|---------|-------------|
| Routing | Slack #support messages go to triage first | The channel's routed agent in `config.yaml`; handoff descriptions in `app.py` |
| Approval | Refunds above $200 need approval | A tool's approval condition; the agent's human-in-the-loop setting |
| Compliance | PII never reaches the model unredacted | Guardrail providers in `config.yaml`; preconditions in `tool.py` |
| Data | Only kb-researcher writes to the Help Center | Knowledge roles in `config.yaml`; read-only backends |
| Tone | Replies end with the support signature | A post-hook in `hooks.py`; agent instructions |
| Safety | Agent code runs with network off | A sandbox profile in `config.yaml` |
| Access | Only support leads can issue refunds | Grants in the `authorization` block of `config.yaml` (who may run which agent, at which level); an access-level check inside the tool in `tool.py`; an agent's `visibility` in `registry.agents.<id>`; the `identity` provider that establishes the caller |

## Tweaks

- `canvasStrip`: a read-only strip of the canvas along the bottom, with the nodes that enforce the selected
  rule highlighted. Off by default.
- `rulesWidth`: narrow or wide.

## Handoff notes

- Rules live in the working directory, in `.akstudio/`, so they travel with the project and can be committed.
- A rule's links are data: file, line range, config key, node id, test case ids. The UI only renders them.
- Out of sync is recomputed whenever a linked file changes on disk.
- States follow the severity order in brief 00: Out of sync, Untested, Drafted, Enforced. A card shows its most
  severe state.
- The rule file format is documented and versioned, so tools other than the app read it: `ak rules check` in
  CI now, a hosted Studio later.
- `ak rules check` is a new subcommand of the `ak` CLI in ak-py, beside `ak skill`. It runs the checks the app
  runs, deterministically and with no model: every linked file, line range, config key, node and test case
  still exists, and the project's introspection still finds what each link names. It exits non-zero when a
  rule is out of sync or a link is broken, and lists untested rules as warnings; `--require-tests` makes them
  fail. The app shows the same results in the Problems panel.
- "Generate tests" runs the coding agent with `ak-test`. For Compliance and Safety rules the request asks for
  adversarial cases that try to break the rule, beside ordinary ones. The cases go into `app_test.py`, are
  linked to the rule, and are accepted or reverted like any other change.
- "Fix with AI" on an out-of-sync rule asks which side should change: the code (the default), the rule or the
  tests. Each choice runs the coding agent and ends in the usual accept or revert.
- Access rules are enforced by OAK's identity and authorization. Three facts shape how the app links and
  implements them:
  - A grant is what stops a caller: once the `authorization` block exists the policy denies by default, and a
    principal runs an agent only when a grant gives it a level on that agent.
  - A tool tier does not stop a tool call yet. It narrows what the catalog lists and is published for the
    project's own code to read. A rule about one tool therefore links to an access-level check inside that
    tool (`ToolContext.get().access_level`), with the tier beside it, never to the tier alone.
  - Every caller needs a grant, the channels included: a Slack user arrives as the principal
    `messaging:slack`. "Implement" on an access rule runs the coding agent with `ak-add-capabilities`, and
    its review must show the grants that keep the existing channels and the local tester working, so that
    adding the block does not lock them out.
- BR-013's "Implement" is static in the prototype.

## Open details

- The file format for rules, and whether rules also appear as comments in the code they govern.
- Which line-range changes count as out of sync: lines that moved, or only lines whose content changed.
- Whether a drafted rule fails `ak rules check` or is only listed as a warning, as an untested rule is.
