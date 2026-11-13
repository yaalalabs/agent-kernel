# 10 · Tools, MCP and sandbox

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Build-Tools` (main), `Build-Tools-System`, `Build-Tools-MCP`, `Build-Tools-Sandbox`, `Build-Tools-New` |
| Canvas page | Build |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. Tabs are prototype links. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The tool library. Project tools are plain Python functions bound to agents through each framework's tool
builder. System tools come with capabilities. MCP servers can be consumed, and the project itself can be
exposed as an MCP server. Sandbox profiles decide where agent code runs.

## Layout

- `AppShell` with Tools active. Page header "Tools", tabs "Project tools · 4", "System tools", "MCP servers ·
  2", "Sandbox · 2". Actions: primary "New tool" and the AI button "Generate with AI".
- Project tools: a list on the left, a detail panel in the middle, a narrow info column on the right.

## Content

**`Build-Tools`** (Project tools)
- List: a search field, filter chips "All", "Bound", "Needs approval", and four rows showing the name, the
  signature and the avatars of the agents it is bound to.

| Tool | Bound to | Note |
|------|----------|------|
| lookup_order | billing, triage | |
| refund_payment (selected) | billing | approval shield |
| search_docs | kb-researcher | |
| create_ticket | triage | |

- Detail header: "refund_payment", "Python function · tools/payments.py", chips "Bound to: billing" and
  "Requires approval".
- Card "Source": the function in a code block, with type hints and a docstring; "Open in editor".
- Card "Parameters": `order_id`, str, required, "Order identifier"; `amount`, float, required, "Refund amount
  in USD".
- Card "Approval": toggle "Requires human approval" on; condition `amount > 200`; helper "The run pauses and
  the approver sees the arguments".
- Card "Try it": fields order_id "A-8841" and amount "240", a "Run" button, a JSON result and "212 ms".
- Info column: "Binds through", one row per framework in use with the native wrapper name (OpenAI Agents SDK,
  LangGraph, Google ADK); "Used in the last 24 h": 318 with a sparkline.

**`Build-Tools-System`**
- Cards grouped by capability, across the full width. Each card lists its tools, an "Attached to" row of agent
  chips and a toggle. The names below are the real tool names; read them from the repository when available.

| Capability | Tools |
|------------|-------|
| Multimodal | `analyze_attachments` |
| Sandbox | `run_code`, `run_command`, `write_sandbox_file`, `read_sandbox_file`, `check_sandbox_task`, `new_sandbox_session`, `list_sandbox_sessions`, `destroy_sandbox_session`, and `install_packages` when a profile allows installs |
| Scheduling | `create_schedule`, `list_schedules`, `get_schedule`, `update_schedule`, `delete_schedule` |
| Knowledge | `get_schemas`, `read_kb`, `write_kb`, `get_all_kb_descriptions`, `fetch_kb`, `browse_kb`, `search_kb` |
| AG-UI | `get_agui_state`, `update_agui_state`, `get_forwarded_props`, `get_agui_context` |

**`Build-Tools-MCP`**
- Left: server cards "GitHub MCP · 12 tools · connected" and "Postgres MCP · 6 tools · auth needed", each with
  "Configure".
- Right: card "Expose this project as an MCP server": a toggle on; the URL `https://api.acme.example/mcp` with
  a copy control; a toggle "Expose agents as tools" on; chips triage, billing, kb-researcher.

**`Build-Tools-Sandbox`**
- An `InlineBanner`: "Policies are fail-closed: a policy the provider cannot enforce blocks the run".
- A `DataTable` of profiles:

| Profile | Provider | Isolation | Network | Languages | Package installs | Scope |
|---------|----------|-----------|---------|-----------|------------------|-------|
| python-data | docker | container | off | python | allowed (python) | per session |
| shell-ops | kubernetes | pod | egress allowlist | python, bash | denied | per call |

- A side panel editing python-data.

**`Build-Tools-New`**
- A modal: a segmented choice "Write Python", "Import from MCP", "Describe with AI"; a name field; the code
  editor with a function stub; "Cancel" and "Create".

## Behaviour

- Tabs link the artboards. "New tool" opens `Build-Tools-New`. "Generate with AI" opens the Build with AI
  drawer.

## Tweaks

- `infoColumn`: shown or hidden.

## Handoff notes

- Sandbox providers in the product: local subprocess, Docker, Kubernetes, E2B, Daytona, EC2 over SSM, and any
  the repository adds. The provider list is data.
- A system tool card is present only when its capability is enabled in config.
