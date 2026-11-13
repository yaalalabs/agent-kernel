# 04 · Builder: Canvas, Code and Config tabs

| | |
|---|---|
| Artboards | `Builder-Canvas` (main), `Builder-Canvas-Empty`, `Builder-Canvas-Dragging`, `Builder-Code`, `Builder-Config`, `Builder-Canvas-ChangedOnDisk`, `Builder-Canvas-Unreadable`, `Builder-Canvas-ContextMenu` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Builder**: 6 of 8 artboards. Not drawn yet: `Builder-Canvas-Dragging`, `Builder-Canvas-ContextMenu`. |
| Canvas page | Builder |
| Kind | Page with `DesktopShell` |
| Fidelity | Working prototype |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md), [01-app-components.md](01-app-components.md) |

## Job

The centrepiece. A node editor where the agentic system is assembled by dragging items from a palette. The
canvas is a view of the files in the working directory: every node and edge corresponds to code in `app.py` or
`tool.py`, a block in `config.yaml`, or the Terraform in `deploy/`. Code and Config are sibling tabs over the
same files.

## Layout

- `DesktopShell` with the Canvas tab active.
- Three panes: palette on the left, canvas in the middle, inspector on the right.
- A small canvas toolbar: undo, redo, zoom readout, fit. A mini-map and zoom control in the canvas corner.
- `BottomPanel` collapsed, its Problems tab showing a count of 2. `StatusBar` at the bottom.
- On load the canvas fits the whole graph. No node may sit behind the inspector or the palette.

## Content

**Palette.** A search field and six collapsible groups of `PaletteTile`. Build and Connect are open.

| Group | Tiles |
|-------|-------|
| Build | Agent, Tool, Hook, Output schema |
| Connect | Channel, Protocol |
| Remember | Session store, Thread store, Knowledge base, Attachment store |
| Guard | Guardrail, Sandbox profile, Secret provider |
| Scale | Deploy target, Execution mode |
| Observe | Tracing, Tests |

**Canvas.**
- Channel nodes on the left: "Slack · #support", "WhatsApp", "Gmail".
- **triage** agent node: OpenAI mark, "OpenAI Agents SDK", model chip "gpt-4o", "2 tools",
  "1 pre-hook · 1 post-hook", "Handoffs: billing, kb-researcher". Guardrail shields on its ports: "OpenAI
  Guardrails" on input, "Walled AI" on output.
- **billing** agent node, selected: LangGraph mark, "claude-sonnet-4-5", "refund_payment requires approval",
  a "Human in the loop" chip.
- **kb-researcher** agent node: Google ADK mark, "gemini-2.5-pro".
- Tool nodes `lookup_order` and `refund_payment` bound to billing. Knowledge node "Help Center · OKF bundle"
  bound to kb-researcher.
- Edges: routing from each channel to triage; handoff edges, labelled "handoff", from triage to billing and to
  kb-researcher; binding edges from tools and knowledge to their agents.
- A `DeployFrame` around the agents and tools: "Deploy target · AWS ECS Fargate · eu-west-1 · not deployed".
- Outside the frame: "Session store · Redis" and "Tracing · Langfuse".

**Inspector** for the selected billing node. Header: LangGraph mark, "billing", and a `PathChip` "app.py".
Five tabs:

| Tab | Content |
|-----|---------|
| Properties | Name; Framework (LangGraph); Model (claude-sonnet-4-5); Handoff description ("Handles refunds, invoices and payment questions"); Instructions (a few lines of system prompt in the code editor, with the AI button "Improve with AI"); toggle "Human in the loop" with helper "Pause on refund_payment above $200"; toggle "Streaming" with helper "LangGraph supports token streaming" |
| Tools | `lookup_order` and `refund_payment`, each with its signature and a "Requires approval" toggle; `refund_payment` is on, with the condition `amount > 200`. A "Bind tool" control. |
| Hooks | Two ordered lists. System hooks are locked: input guardrail, multimodal, sandbox (pre); output guardrail, A2UI labelling (post). No agent hooks are registered on billing. An `InlineBanner`: "BR-009 expects the Signature footer post-hook here", with the AI button "Fix with AI". |
| Run options | A `KeyValueEditor` with `config.recursion_limit = 50`, and a locked row `config.configurable.thread_id` noted "Reserved by Agent Kernel" |
| Output schema | A Pydantic class in the code editor, its JSON Schema beside it, and the note "Structured output replies are not streamed" |

Inspector footer: "Show in app.py" and a danger "Remove".

**Bottom panel, Problems.** Two entries:
- "Slack attachments need `multimodal.enabled: true`. Messages with attachments will be rejected."
- "BR-009 is out of sync: the Signature footer hook is not registered on billing."

**Status bar.** `~/code/support-triage`, branch `main`, "Python environment ready", "Files in sync",
"Claude Code connected".

## Behaviour (must work)

- Click a node to select it. The inspector shows that node's type: agent, tool, channel and deploy frame each
  have their own properties. The inspector tabs switch.
- Drag a palette tile onto the canvas. A ghost follows the pointer, valid drop targets highlight, and dropping
  adds a node. Dropping "Guardrail" on an agent's input port attaches it.
- Editing Name or Model in the inspector updates the node.
- `AppTabs` go to `Builder-Code`, `Builder-Config`, `Builder-TestTrace` and `Builder-Deploy`.
- "Show in app.py" goes to `Builder-Code`. The bottom panel opens on Problems.
- "Build with AI" opens the drawer from brief 05.

Good to have: drag from a port to another node to draw an edge (handoff between agents, binding from a tool or
knowledge node, routing from a channel); pan, zoom and the mini-map; undo and redo.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Builder-Canvas-Empty` | first | A new blank project. An `EmptyState`: "Drop a node to start, or describe your system", with "Add agent" and the AI button "Describe it with AI". The inspector reads "Select a node to edit it". |
| `Builder-Code` | first | The Code tab. A `FileTree` of the fixture's project files, with markers on the files changed since the last commit. The code editor on `app.py`, where an OpenAI module, a LangGraph module and a Google ADK module are created. Actions: "Open in editor" and "Reveal in file manager". |
| `Builder-Config` | first | The Config tab. Left: the `AKConfig` sections as a list, with a mark on the ones this project sets (session, execution, api, slack, whatsapp, gmail, multimodal, okf, trace, guardrail, sandbox, secret, logging; unset ones such as a2a, mcp, agui, thread and schedule are listed dimmed). Middle: a form for the selected section, "execution": mode `rest_sync`, message type `delta`, queue transport `in_memory`. Right: the same section as live YAML with the validation result. |
| `Builder-Canvas-ChangedOnDisk` | first | A `ChangeOnDiskBanner` over the canvas: "app.py changed on disk. The canvas was updated.", with "Show changes". The affected node pulses once. The status bar reads "1 change from outside the app". |
| `Builder-Canvas-Unreadable` | first | The canvas shows its last good view, dimmed, under a banner: "Cannot read app.py: syntax error at line 42", with "Open in Code" and the AI button "Ask Claude Code to fix". The inspector is disabled. |
| `Builder-Canvas-Dragging` | second | A frozen frame of a drag: the "Guardrail" tile floats over the canvas and a `DropTarget` on kb-researcher's input port reads "Attach input guardrail". |
| `Builder-Canvas-ContextMenu` | second | A `ContextMenu` on triage: "Show in app.py", "Test this agent", "Add handoff", "Attach guardrail", "Duplicate", then a danger "Remove". |

## How nodes map to files

| Group | Node | Agent Kernel concept | Written to |
|-------|------|----------------------|------------|
| Build | Agent | Native framework agent wrapped by a `Module` | `app.py` |
| Build | Tool | Plain Python function bound through a tool builder | `tool.py`, bound in `app.py` |
| Build | Handoff edge | Agent-to-agent handoff | `app.py` |
| Build | Hook | Pre- or post-hook on an agent | `hooks.py`, registered in `app.py` |
| Build | Output schema | Structured output (Pydantic) | `app.py` |
| Connect | Channel | Messaging integration adapter | The channel's block in `config.yaml`, its handler in `app.py` |
| Connect | Protocol | REST, WebSocket, MCP, A2A, AG-UI | `api`, `mcp`, `a2a`, `agui` blocks in `config.yaml` |
| Remember | Stores | Session, thread and attachment stores | `session`, `thread`, `multimodal` blocks |
| Remember | Knowledge base | Knowledge backend | Knowledge wiring in `app.py`, roles in `config.yaml` |
| Guard | Guardrail | Input or output guardrail provider | `guardrail` block |
| Guard | Sandbox profile | Sandbox provider and policy | `sandbox` block |
| Guard | Secret provider | Secret resolution | `secret` block; key values in `.env` |
| Scale | Deploy frame | The cloud target | The Terraform files in `deploy/` |
| Scale | Execution mode | How requests are executed | `execution` block |
| Observe | Tracing, Tests | Tracing provider, test harness | `trace` block; `app_test.py`, `test-config.yaml` |

Node positions are the only thing the canvas stores outside these files, in `.akstudio/`.

## Tweaks

- `inspector`: open or closed. `palette`: full or icons. `miniMap`: shown or hidden.

## Handoff notes

- The Config forms can be generated from `AKConfig`: every field has a type, a default and a description.
- A canvas edit that changes Python may be carried out by a scaffold template or by the coding agent, and can
  take a moment. A node being written shows a short "Writing app.py" state, and the command appears in the
  Commands panel.
- The Deploy frame is not a node. It shows the single deploy target of the project.

## Open details

- How much editing the Code tab allows. The assumption is light edits, with "Open in editor" for real work.
