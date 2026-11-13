# 05 · Build with AI drawer

| | |
|---|---|
| Artboards | `Builder-AIDrawer` (main), `Builder-AIDrawer-FirstExchange`, `Builder-AIDrawer-Resolved`, `Builder-AIDrawer-Code`, `Builder-AIDrawer-Rules`, `Builder-AIDrawer-Disconnected`, `Builder-AIDrawer-AgentMenu`, `Builder-AIDrawer-Bottom`, `Builder-AIDrawer-Review` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 6 of 9 artboards. Not drawn yet: `Builder-AIDrawer-AgentMenu`, `Builder-AIDrawer-Bottom`, `Builder-AIDrawer-Review`. |
| Canvas page | Builder |
| Kind | Page: the Canvas tab with the `BuildWithAIDrawer` component open |
| Fidelity | Working prototype with one scripted exchange |
| Story moment | A, building |
| Read first | [00-project-brief.md](00-project-brief.md), [04-agent-canvas.md](04-agent-canvas.md) |

## Job

The chat through which a coding agent builds the system. The agent is Claude Code, running on this computer in
the working directory. It edits the real files through the bundled skills, the canvas shows each change as it
lands, and anything that runs a command waits for the user's approval. Magenta marks everything the agent made
until the user accepts it.

## Layout

- The Canvas tab from brief 04 with the palette collapsed to a strip, and the drawer docked on the right.
- The drawer, top to bottom: header, view switch, progress rail, transcript, composer.
- All canvas nodes stay visible to the left of the drawer.

## Content

**Canvas.** Existing nodes: the three channel nodes, triage and kb-researcher, inside the deploy frame. Newly
generated, in the AI style with an `AIBadge` "Added by Claude Code": the **billing** agent node (LangGraph,
claude-sonnet-4-5), tool nodes `lookup_order` and `refund_payment`, and a generated handoff edge from triage to
billing. A floating card in the top corner of the canvas, covering no node: "3 changes pending", with "Accept
all" and "Review".

**Drawer header.** A select showing the Claude mark and "Claude Code"; a status "Connected · this computer"; a
`PathChip` with the working directory; then expand, history and close controls.

**View switch.** Chat (active), Code, Rules.

**Progress rail.** Scaffold (done), Agents (active), Capabilities, Integrations, Test, Deploy.

**Transcript.**
1. User: "Add a billing agent on LangGraph that can issue refunds, and require human approval for refunds over
   $200."
2. Agent, with a `PlanCard`:
   - "ak-build · add agent billing with lookup_order and refund_payment" (done)
   - "ak-add-capabilities · human in the loop on refund_payment" (done)
   - "ak-build · add the handoff from triage to billing" (running)
   - "ak-test · add 6 test cases" (pending)
3. `ToolCallCard` rows: "Edited app.py +42 -3" (expanded, a short diff of added lines), "Edited tool.py +28",
   "Edited config.yaml +11", "Ran uv add 'agentkernel[langgraph]' · 4.2 s".
4. An `ApprovalCard`, pending: "Approval required", "Claude Code wants to run: uv run pytest -q", "Approve",
   "Deny", and a link "Always allow this command in this project".
5. A `CanvasChangesCard`: "+ agent billing", "+ tools lookup_order, refund_payment",
   "+ handoff triage → billing", with "Accept" and "Revert".

**Composer.** Placeholder "Describe what to build, or type / for skills". Skill chips "/ak-build",
"/ak-add-integration", "/ak-test". An attach control. An AI-styled send button. A status line above it:
"Claude Code is working" with "Stop".

## Behaviour (must work)

- Sending the scripted message plays the exchange: the plan appears, its steps complete in order, tool rows
  append, and the generated nodes appear on the canvas one by one.
- "Approve" resolves the approval card (see `Builder-AIDrawer-Resolved`). "Deny" marks it denied.
- "Accept" or "Accept all" clears the AI style and badges from the new nodes. "Revert" removes them and
  restores the files to how they were before this turn.
- The view switch goes to the Code and Rules views. The expand control goes to `AgenticDev-Workspace`.
- The agent select opens its menu. Close hides the drawer and restores the palette.
- Every command the agent runs also appears in the Commands tab of the bottom panel.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-AIDrawer-FirstExchange` | first | An empty canvas in a new folder. User: "Build a support system with a triage agent that hands off to billing and a knowledge researcher, on Slack and WhatsApp". The agent asks one clarifying question with three option chips: "OpenAI Agents SDK", "LangGraph", "Mixed, you choose". |
| `Builder-AIDrawer-Resolved` | first | The approval card approved: "Approved · uv run pytest -q · 40 passed, 2 failed in 18 s", with a link "View in Test & Trace". |
| `Builder-AIDrawer-Code` | first | Code view. A compact `FileTree` (app.py, tool.py, config.yaml, app_test.py) over the code editor on app.py. AI gutter markers on the added lines and an `AnnotationPill`: "Implements BR-004 · Refunds above $200 require approval". The composer stays. |
| `Builder-AIDrawer-Rules` | first | Rules view. `RuleCard`s for BR-001, BR-002 and BR-004 (AI-added) from the fixture, and an input "Add a rule in plain language" with the AI button "Implement". |
| `Builder-AIDrawer-Disconnected` | first | Claude Code is not available. An `EmptyState` in the drawer: "Claude Code was not found on this computer", the steps to install and sign in, a "Recheck" control and a link "Coding agents in Settings". The composer is disabled. The rest of the app still works. |
| `Builder-AIDrawer-AgentMenu` | second | The agent select open: Claude Code (connected); Codex, Cursor, Windsurf and GitHub Copilot listed as "Not set up"; a footer link "Coding agents in Settings". |
| `Builder-AIDrawer-Bottom` | second | The drawer docked at the bottom: transcript on the left two thirds, plan and canvas-changes cards on the right, composer across the bottom. |
| `Builder-AIDrawer-Review` | second | A modal "Review changes": a canvas diff on the left (new nodes in the AI style, unchanged nodes dimmed), the file diff for app.py, tool.py and config.yaml on the right, and "Accept all", "Accept selected", "Revert". |

## How chat intents map to the bundled skills

| The user asks to | Skill the coding agent runs | Files it touches | Effect on the canvas |
|------------------|-----------------------------|------------------|----------------------|
| Start a project or describe a system | `ak-init` | The whole scaffold | An empty canvas becomes a system |
| Add an agent, tool or handoff | `ak-build` | `app.py`, `tool.py` | New Build nodes and edges |
| Add guardrails, tracing, memory, sandbox, secrets, MCP, A2A, AG-UI | `ak-add-capabilities` | `config.yaml`, `pyproject.toml`, sometimes `app.py` | Guard, Remember, Observe and Connect nodes |
| Connect Slack, WhatsApp, Teams, Gmail and the others | `ak-add-integration` | `config.yaml`, `app.py`, `.env` | A channel node routed to an agent |
| Write tests or explain a failure | `ak-test` | `app_test.py`, `test-config.yaml` | Results in Test & Trace |
| Deploy to AWS, Azure or Google Cloud | `ak-cloud-deploy` | `deploy/` | The deploy frame; the Deploy tab |
| State a business rule | `ak-build` and `ak-add-capabilities`, then `ak-test` | As needed | A rule card, an approval badge on the tool, new test cases |

## Tweaks

- `dock`: right or bottom. `drawerWidth`: narrow, default, wide.

## Handoff notes

- The app starts Claude Code as a local process in the working directory and relays its permission requests
  as approval cards. The agent never applies Terraform by itself: deploying always goes through the Deploy tab.
- The skills are installed into the project with `ak skill install --assistant claude`, into
  `.claude/commands/`.
- Skill names must appear exactly as `ak-init`, `ak-build`, `ak-add-capabilities`, `ak-add-integration`,
  `ak-test`, `ak-cloud-deploy`.
- "Revert" depends on a checkpoint taken before each agent turn: git when the folder is a repository, the
  app's own snapshot otherwise.
