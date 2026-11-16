# Agent Kernel Studio internal baseline: Phase 1 scope, parked later phases, and the runtime underneath

Scope note: local files only, read on branch `feature/950-agent-kernel-studio-phase-1` on 16 Nov 2026. Links are relative to this file: `../../../` is the Studio spec folder (`docs/specs/950-agent-kernel-studio-phase-1/`) and `../../../../../../` is the repository root. Anything marked "Inference" is my reading, not a statement in the files. Bucket labels used throughout: **A** = in Phase 1 scope; **B** = only in a parked later-phase brief (exists, not planned); **C** = not mentioned in any Studio document.

## Q1. What exactly does Phase 1 deliver, screen by screen?

### Takeaway
Phase 1 is a local, single-user Electron desktop app (designed, not built) that opens one folder, writes an ordinary Agent Kernel project into it, lets the user build it on a node canvas, in forms, in code, or through a locally running Claude Code session, runs and tests it locally with a stream-event trace, and deploys it with Terraform to one of six AWS, Azure or Google Cloud targets using the user's own cloud profile. Its distinctive behaviours are accept/revert of every coding-agent turn, approval cards for agent commands and human-in-the-loop tool calls, plain-language business rules linked to code and tests with Enforced, Drafted and Out of sync states, and a plan, named-account confirmation, apply and typed-name destroy flow for real infrastructure.

### Cited Findings

#### Product framing and status
- Phase 1 is "a local desktop app: build, test and deploy an Agent Kernel project from one folder on one computer". It is the only planned phase; later phases are "Not planned" and their briefs are parked. ([README](../../../README.md))
- Status: "the Phase 1 screens are designed on a Claude Design canvas ... Nothing is built as an app yet." Tracked in GitHub issue #950. ([README](../../../README.md))
- The PRD is dated 13 November 2026, status "Draft for review", prepared by Yaala Labs; "Agent Kernel Studio" is a working name. ([PRD](../../../PHASE-1-PRD.md))
- Deliverables: the desktop app for Windows, Linux and macOS (Electron, React, TypeScript) with an installer for each, source and build instructions, plus the design canvas "of 45 artboards with nine screen briefs" as reference. ([PRD](../../../PHASE-1-PRD.md))
- Milestones: (1) open and read a project; (2) create and edit; (3) coding agent, accept and revert, business rules; (4) local run, chat, trace and tests; (5) deploy to one target, plan to destroy; (6) the remaining five targets. ([PRD](../../../PHASE-1-PRD.md); [PLAN](../../../PHASE-1-PLAN.md))
- Acceptance: on each of Windows, Linux and macOS, from an empty folder, build the support-triage example with three agents, test locally, deploy to one cloud target, call the endpoint and destroy it, "with every generated file readable in the folder and every command visible in the app". ([PRD](../../../PHASE-1-PRD.md); [PLAN](../../../PHASE-1-PLAN.md))
- Design completeness per the artboard map: Welcome 4 of 4, New project 5 of 5, Canvas 6 of 8, Build with AI 6 of 9, Agentic development 3 of 4, Test & Trace 5 of 6, Deploy 8 of 10, Settings 5 of 5; System page has 3 shell components and the specimen artboards are not drawn. The README also says the canvas "was written without rendering it" and that "Contrast and keyboard order were designed for but not measured." ([README](../../../README.md))
- Prototype interactivity that "really works": wizard steps, canvas node selection and inspector tabs, adding an agent by drag or click, Approve/Deny and Accept all/Revert in Build with AI, rule selection and Fix with AI, span selection and approve/deny of a paused refund, Run tests, and the full deploy flow from plan to destroy. ([README](../../../README.md))

#### Desktop shell (brief 00, 01)
- No left navigation. TopBar holds ProjectSwitcher (open folder, new project, recent, reveal), AppTabs (Canvas, Code, Config, Test & Trace, Deploy), RunControl (stopped, starting, running, failed), DeployStatus (not deployed, deployed, applying, failed), a magenta "Build with AI" entry and settings. ([00-project-brief](../../../00-project-brief.md); [01-app-components](../../../01-app-components.md))
- BottomPanel tabs: Problems (validation), Run log, Commands ("every command the app or the coding agent ran, with its exit status"). StatusBar: working directory, git branch, Python environment state, file sync state, coding agent state. ([00-project-brief](../../../00-project-brief.md))
- Component inventory to build beyond the design system includes CodeEditor, KeyValueEditor, DiffView, JSONTree, FileTree (AI-written markers), SpanTree, Waterfall, ResultSquares, ApprovalCard (one component for test-run approvals and coding-agent permission requests), PlanCard, CanvasChangesCard, RuleCard, CommandRow ("always shows the literal command"), ToolchainRow, CheckRow, PlanSummary, VariableForm, OutputList, ChangeOnDiskBanner, ConfirmModal. ([01-app-components](../../../01-app-components.md))
- Visual rules: Agent Kernel Design System; magenta is reserved for anything authored by the coding agent; state is never colour alone; 4.5:1 contrast target; drawn at 1440x900, must hold at 1100 wide; "There are no phone layouts"; dark theme in settings. ([00-project-brief](../../../00-project-brief.md); [09-app-settings](../../../09-app-settings.md))

#### Welcome (brief 02)
- "There is no sign-in: the app starts from a folder." Actions: "Open folder", "New project", AI button "Describe a project". Recent list shows folder, path, framework marks and last opened. ([02-welcome](../../../02-welcome.md))
- Right column "This computer" toolchain check: Python 3.12 or 3.13, uv, Claude Code, Terraform, Docker, AWS CLI profile, git, with Recheck. States: FirstLaunch, ToolchainMissing ("New project" disabled when uv missing; Terraform missing only affects deploy), NotAProject (modal offering "Create a project here"). ([02-welcome](../../../02-welcome.md))
- A project is recognised by `config.yaml` plus a Python file that registers an Agent Kernel module; projects made without the app open the same way. "The app installs nothing by itself." ([02-welcome](../../../02-welcome.md))

#### New project wizard (brief 03)
- Four steps: Folder (name, location, "Initialise a git repository"), Framework, Model provider, Starting point; then a "Creating" screen. Every step offers "Describe it with AI" as an exit to the coding agent. ([03-new-project](../../../03-new-project.md))
- Eight framework cards with capability chips (Streaming / Human in the loop / Structured output): OpenAI Agents SDK yes/yes/yes; LangGraph yes/yes/yes; CrewAI no/no/yes; Google ADK yes/yes/yes; Smolagents no/no/yes; Pydantic AI yes/yes/yes; Microsoft Agent Framework yes/yes/yes; Claude Agent SDK no/yes/yes. The matrix must be "driven from data". ([03-new-project](../../../03-new-project.md))
- Model providers listed: OpenAI, Anthropic, Google AI, Azure OpenAI, Amazon Bedrock, Hugging Face; key kept in `.env` (ignored by git) or the user's shell environment; "The app shows its name, never its value." ([03-new-project](../../../03-new-project.md))
- Templates: Blank project; Support triage (3 agents, Slack); Research crew (CrewAI, knowledge bases); Slack assistant (1 agent, Slack); and "Describe it with AI". ([03-new-project](../../../03-new-project.md))
- Creating screen shows each step as a CommandRow: write files, `uv venv`, `uv sync`, `ak skill install --assistant claude`, `git init`; failure state offers "Retry" and "Ask Claude Code to fix". The scaffold is exactly what the bundled `ak-init` skill generates. ([03-new-project](../../../03-new-project.md))

#### Builder: Canvas, Code and Config (brief 04)
- Three panes: palette, canvas, inspector; canvas toolbar with undo, redo, zoom, fit, mini-map. "The canvas is a view of the files": every node and edge maps to `app.py`, `tool.py`, a `config.yaml` block or `deploy/` Terraform. Only node positions are stored outside those files, in `.akstudio/`. ([04-agent-canvas](../../../04-agent-canvas.md))
- Palette groups and tiles: Build (Agent, Tool, Hook, Output schema); Connect (Channel, Protocol); Remember (Session store, Thread store, Knowledge base, Attachment store); Guard (Guardrail, Sandbox profile, Secret provider); Scale (Deploy target, Execution mode); Observe (Tracing, Tests). ([04-agent-canvas](../../../04-agent-canvas.md))
- Node-to-file mapping: Protocol covers "REST, WebSocket, MCP, A2A, AG-UI" via `api`, `mcp`, `a2a`, `agui` blocks; stores via `session`, `thread`, `multimodal`; guardrail, sandbox, secret, execution, trace blocks; the Deploy frame is "not a node", it shows the single deploy target. ([04-agent-canvas](../../../04-agent-canvas.md))
- Edge types: routing (channel to agent), handoff (labelled), binding (tool or knowledge to agent), generated; solid vs dashed so type is not colour alone. ([04-agent-canvas](../../../04-agent-canvas.md); [01-app-components](../../../01-app-components.md))
- Agent inspector tabs: Properties (name, framework, model, handoff description, instructions with "Improve with AI", Human in the loop and Streaming toggles), Tools (per-tool "Requires approval" toggle with condition, e.g. `amount > 200`; "Bind tool"), Hooks (system hooks locked: input guardrail, multimodal, sandbox pre; output guardrail, A2UI labelling post), Run options (KeyValueEditor, reserved key `config.configurable.thread_id` locked), Output schema (Pydantic class plus JSON Schema, "Structured output replies are not streamed"). Tool, channel and deploy frame nodes have their own inspector. ([04-agent-canvas](../../../04-agent-canvas.md))
- Must work: select node, drag a palette tile with ghost and highlighted drop targets, dropping Guardrail on an agent's input port attaches it, editing Name or Model updates the node. Good to have: drawing edges port to port, pan/zoom/mini-map, undo/redo. ([04-agent-canvas](../../../04-agent-canvas.md))
- Code tab: FileTree with changed-since-commit markers, code editor, "Open in editor", "Reveal in file manager"; editing scope is an open detail ("light edits, with Open in editor for real work"). ([04-agent-canvas](../../../04-agent-canvas.md))
- Config tab: AKConfig sections as a list (set: session, execution, api, slack, whatsapp, gmail, multimodal, okf, trace, guardrail, sandbox, secret, logging; unset and dimmed: a2a, mcp, agui, thread, schedule), a generated form per section, and live YAML with validation; forms "can be generated from AKConfig"; writes keep comments and order. ([04-agent-canvas](../../../04-agent-canvas.md); [PLAN](../../../PHASE-1-PLAN.md))
- File-sync states: ChangedOnDisk banner ("app.py changed on disk. The canvas was updated.") with the affected node pulsing; Unreadable state ("Cannot read app.py: syntax error at line 42") keeps the last good view dimmed and offers "Ask Claude Code to fix". Problems panel example: "Slack attachments need `multimodal.enabled: true`". ([04-agent-canvas](../../../04-agent-canvas.md))
- Context menu (second pass): Show in app.py, Test this agent, Add handoff, Attach guardrail, Duplicate, Remove. ([04-agent-canvas](../../../04-agent-canvas.md))

#### Build with AI drawer (brief 05)
- The coding agent is Claude Code "running on this computer in the working directory", editing real files through the bundled skills; the app starts it as a local process and relays its permission requests as approval cards. ([05-build-with-ai](../../../05-build-with-ai.md))
- Drawer: agent select, "Connected · this computer", views Chat, Code, Rules, a progress rail (Scaffold, Agents, Capabilities, Integrations, Test, Deploy), transcript, composer with slash-skill chips (`/ak-build`, `/ak-add-integration`, `/ak-test`), attach, Stop. Dockable right or bottom; expand opens the agentic development workspace. ([05-build-with-ai](../../../05-build-with-ai.md))
- Transcript elements: PlanCard whose steps name skills (e.g. "ak-build · add agent billing"), ToolCallCards with diff counts ("Edited app.py +42 -3") and commands with durations, ApprovalCard ("Claude Code wants to run: uv run pytest -q", Approve, Deny, "Always allow this command in this project"), CanvasChangesCard with Accept and Revert. ([05-build-with-ai](../../../05-build-with-ai.md))
- Accept/revert: generated nodes stay magenta with "Added by Claude Code" until accepted; a floating "3 changes pending" card offers "Accept all" and "Review"; "Revert removes them and restores the files to how they were before this turn", using a git checkpoint when the folder is a repository, else an app snapshot. Second-pass "Review changes" modal adds a canvas diff, file diffs and "Accept selected". ([05-build-with-ai](../../../05-build-with-ai.md))
- "The agent never applies Terraform by itself: deploying always goes through the Deploy tab." Every agent command also appears in the Commands panel. ([05-build-with-ai](../../../05-build-with-ai.md))
- Disconnected state: "Claude Code was not found on this computer", install steps, Recheck; "The rest of the app still works." Agent menu (second pass) lists Codex, Cursor, Windsurf and GitHub Copilot as "Not set up". ([05-build-with-ai](../../../05-build-with-ai.md))
- Intent to skill mapping: start/describe a system = `ak-init`; add agent, tool, handoff = `ak-build`; guardrails, tracing, memory, sandbox, secrets, MCP, A2A, AG-UI = `ak-add-capabilities`; Slack, WhatsApp, Teams, Gmail "and the others" = `ak-add-integration`; tests = `ak-test`; deploy files = `ak-cloud-deploy`; a business rule = `ak-build` and `ak-add-capabilities`, then `ak-test`. ([05-build-with-ai](../../../05-build-with-ai.md))

#### Agentic development workspace and business rules (brief 06)
- Expanded form of the drawer: three columns (chat, code workspace, business rules) so "a business owner and a developer look at the same project from three angles". At 1280 px and below, Rules becomes a tab. ([06-agentic-development](../../../06-agentic-development.md))
- Rule card: id, plain-language rule, category (Routing, Approval, Compliance, Data, Tone, Safety), "Enforced by" chips naming files and config keys, tests count. States: Enforced, Drafted (no implementation yet), Out of sync (files no longer match); AI-added badge. Header counter, e.g. "12 rules · 11 enforced · 1 out of sync". ([06-agentic-development](../../../06-agentic-development.md); [00-project-brief](../../../00-project-brief.md))
- Behaviours: clicking a rule opens and highlights the enforcing lines; an AnnotationPill in the editor ("Implements BR-004") selects its rule; "Diff" toggles side-by-side diff; "Explain" (AI); typing a rule and "Implement" creates a Drafted card that the coding agent moves to Enforced; "Fix with AI" on an out-of-sync rule proposes a fix ("Yes, fix it" / "Ignore"). ([06-agentic-development](../../../06-agentic-development.md))
- Rule detail: rationale, "Enforced by" with file:line (`tool.py:42`, `app.py:88`), "Covered by" test cases with pass marks, history (created by Claude Code, accepted by you). ([06-agentic-development](../../../06-agentic-development.md))
- Rules live in `.akstudio/` and can be committed; links are data (file, line range, config key, node id, test case ids); "Out of sync is recomputed whenever a linked file changes on disk." Rule file format, and whether rules also appear as code comments, is open. ([06-agentic-development](../../../06-agentic-development.md))
- Rule coverage surfaces elsewhere: Test & Trace "Covers 9 of 12 business rules" with uncovered list; Deploy prerequisites include a "Business rules" check that warns on out-of-sync rules. ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md); [08-builder-deploy](../../../08-builder-deploy.md))

#### Test & Trace (brief 07)
- "The inner loop of building, entirely on this computer": start the project locally (`uv run python app.py`, served on a local port such as `localhost:8000`), chat with it, watch the trace of the same run, keep the exchange as a test case. "Nothing here needs a deployment." ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md))
- Test column: agent select, session chip, "Stream (delta)" toggle, New session, saved scenario chips plus "+ Save current", transcript with ToolCallCard (with latency), HandoffDivider, ApprovalCard for a paused tool call referencing the rule (Approve, Deny, Cancel), composer with attach. The Test column talks to the local run over "the same REST and SSE interface a deployed project exposes". ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md))
- Trace column: run id, duration, token and cost chips, source chip "Local run"; SpanTree with inline Waterfall; span kinds run, hook, guardrail, runner, llm, tool, handoff; span detail tabs Input, Output, Metadata with tokens in/out, latency and cost. ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md))
- Trace detail limit: "The trace is built from the run's stream events, so no tracing provider is needed. Frameworks that do not stream give run-level timing only; the trace column should say so instead of showing an empty tree." Stream event types: message start/end, text delta, reasoning, tool call start/args/end/result, step start/end. ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md))
- Tests strip: `app_test.py` case count, last-run chip, "Run tests" (runs `uv run pytest`, using `test-config.yaml` comparison mode and judge model), ResultSquares, "Save this exchange as a test case". Failing view shows Prompt, Expected, Actual, score (e.g. 0.62), "Replay in Test", "Fix with AI". Compare mode (second pass, not drawn) puts two runs side by side with per-span deltas. ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md); [README](../../../README.md))
- StartFailed state: "The project did not start: OPENAI_API_KEY is not set" with "Add the key in Settings", "Show run log", "Ask Claude Code to fix". "During a local test the person at the keyboard is the approver." ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md))

#### Deploy (brief 08)
- Generates Terraform for one target into `deploy/`, checks prerequisites, packages, shows the plan, applies only after confirmation; the same tab redeploys and destroys; "the app holds no cloud credentials". ([08-builder-deploy](../../../08-builder-deploy.md))
- Six targets, one per Terraform module: AWS serverless (Lambda and API Gateway), AWS containerized (ECS Fargate), Azure serverless (Functions), Azure containerized (Container Apps), Google Cloud serverless (Cloud Run, scale to zero), Google Cloud containerized (Cloud Run, always on); each card says whether Docker is needed. ([08-builder-deploy](../../../08-builder-deploy.md))
- Left column: Target card (e.g. module `yaalalabs/ak-containerized/aws`), Cloud account (profile, account, signed-in state), Variables form rendered from `deploy/variables.tf` (model keys as SecretChips "from .env, passed at run time"), Generated files with View, Terraform state card ("Local file in deploy/", "Use a remote backend"). ([08-builder-deploy](../../../08-builder-deploy.md))
- Five steps: (1) Prerequisites: Terraform, Docker running, cloud credentials, "Configuration fits the target" (e.g. "AWS Lambda rejects rest_sync with delta"; a combination the runtime would reject must fail here), Tests pass count, Business rules sync; "A warning does not block applying. A failed check does." (2) Package (`uv export`, `uv pip install --target`, copy into `dist/`). (3) Plan (`terraform init`, `terraform plan`, PlanSummary "to add / to change / to destroy", "View full plan"). (4) Apply. (5) Outputs (`agent_invoke_url`, copy, a ready-made curl). ([08-builder-deploy](../../../08-builder-deploy.md))
- Confirmation: ConfirmModal "This creates [N] resources in AWS account [ACCOUNT], region eu-west-1, using profile default. Cloud resources cost money until you destroy them." plus a required "I have reviewed the plan" checkbox. Applying shows a log stream and a Stop with the caution "Stopping can leave some resources created". Failed state: error excerpt, "Run plan again", "Ask Claude Code to diagnose". ([08-builder-deploy](../../../08-builder-deploy.md))
- Destroy: destructive ConfirmModal naming the account and requiring the user to type the project name; runs `terraform destroy`. Redeploy (second pass) lists files changed since last deploy. ChangeTarget (second pass) warns "Destroy the current deployment first." ([08-builder-deploy](../../../08-builder-deploy.md))
- Model keys are passed as Terraform variables at run time and "must never be written to terraform.tfvars". "Kubernetes with Helm is not a Terraform target and is not offered." Open detail: whether a smoke test of the deployed endpoint belongs in Phase 1. ([08-builder-deploy](../../../08-builder-deploy.md))

#### App settings (brief 09)
- Five sections: Toolchain (detected path, version, state, Recheck, manual path override), Coding agents, Cloud, Secrets, General. "There are no accounts, members or billing." ([09-app-settings](../../../09-app-settings.md))
- Coding agents: Claude Code card with installed skills and "Update skills"; per-project permissions: "Edit project files" toggle; "Running commands": "Ask every time" or "Allow listed commands" (list, e.g. `uv run pytest`); a locked row "Never apply or destroy Terraform"; toggle "Take a checkpoint before each turn". Codex, Cursor, Windsurf, GitHub Copilot shown "Not set up". ([09-app-settings](../../../09-app-settings.md))
- Cloud: AWS profile select, account, default region; Azure and Google Cloud show `az login` and `gcloud auth application-default login` when not signed in; "The app stores no cloud credentials." ([09-app-settings](../../../09-app-settings.md))
- Secrets: table of key, where kept (`.env`), used by, state (set/missing); values never shown; local keys use Agent Kernel's `env` secret provider; "A cloud secret store is chosen per deploy target, in config.yaml." General: default project location, editor, theme. ([09-app-settings](../../../09-app-settings.md))

#### What the app writes into the working directory
- `app.py`, `tool.py`, `config.yaml`, `app_test.py`, `test-config.yaml`, `pyproject.toml`, `uv.lock`, `build.sh`, `deploy/` (`main.tf`, `variables.tf`, `outputs.tf`, `providers.tf`, `terraform.tfvars`, `Dockerfile`, `deploy.sh`), `.claude/commands/` (skills), `.env`, and `.akstudio/` (canvas layout, business rules, saved test scenarios, deploy history; an assumption). Layout follows the bundled `ak-init` and `ak-cloud-deploy` skills so "a project made by the app is an ordinary Agent Kernel project that works without the app". ([PLAN](../../../PHASE-1-PLAN.md))
- Architecture sketch: renderer has "no direct file or process access" and talks over "a narrow, typed bridge"; main process services: Project, Introspection (a Python helper that turns the project into a graph), Run (`uv venv`, `uv sync`, start/stop, log stream), Agent bridge, Deploy (package, Terraform, plan parsing, deploy history), Toolchain and secrets ("never expose values to the renderer"). ([PLAN](../../../PHASE-1-PLAN.md))

### Inferences
- Inference: Phase 1 is positioned as a "code-first visual IDE" rather than a hosted low-code studio: every visual action resolves to files a developer can read and commit, and the app is explicitly disposable ("Nothing depends on the app").
- Inference: the business-rules layer (plain-language rules bound to code lines, config keys and test cases, with drift detection) is the most differentiated Phase 1 feature for a competitive comparison; nothing equivalent is described for the runtime itself, so it is a Studio-only concept.
- Inference: the local trace is a debugging aid, not observability: it depends on the framework streaming, and frameworks marked "no" for streaming in brief 03 (CrewAI, Smolagents, Claude Agent SDK) would show only run-level timing in Phase 1.
- Inference: because writes to Python go only "through scaffold templates and the coding agent", many canvas edits beyond config (for example a new handoff or tool binding) will depend on Claude Code being installed and working; without it, the canvas is closer to a config editor plus a read-only graph.

### Gaps
- No timeline, team size, fees or app-source location are given ("To be agreed before issue"). ([PRD](../../../PHASE-1-PRD.md))
- No licence or pricing for Studio itself is stated anywhere; the runtime is Apache 2.0, but whether Studio is open source is not said.
- The canvas was never rendered or measured for layout, contrast or keyboard order, per the README; usability claims are design intent only.
- Rule storage format, Code tab edit depth and deployed smoke test are open details.

## Q2. What do the parked later-phase briefs (L01 to L21) cover?

### Takeaway
Fifteen parked briefs exist (L01, L03, L09 to L21); they were written for an earlier hosted SaaS concept with workspaces and environments (Local, Staging, Production), and cover sign-in, an operations dashboard, deep per-area configuration pages (agents, tools/MCP/sandbox, knowledge, channels/protocols, guardrails/auth, memory), and an "Operate" suite (playground, conversations, traces, evaluations, schedules, deployments) plus workspace administration (members, roles, API keys, billing). None are planned, and each must be revised before use.

### Cited Findings
- The parked briefs "describe screens that are not in Phase 1. They were written for the hosted product ... Do not design from them yet. Each one needs a revision against the current project brief." ([later-phases/README](../../../later-phases/README.md))
- Files present: L01, L03, L09, L10, L11, L12, L13, L14, L15, L16, L17, L18, L19, L20, L21. No L02 or L04 to L08 files exist; the folder README maps original "brief 02" to Phase 1 brief 03 (new project) and "briefs 04 to 08" to the Phase 1 briefs of the same number, and "brief 22" to brief 01 (components). ([later-phases/README](../../../later-phases/README.md); directory listing)
- Later-phase themes in the plan: "Deep configuration" (full pages for agents, tools, knowledge, channels, guardrails, memory); "Operate" (playground against a deployed system, traces, conversations, evaluations history, schedules, deployments view, dashboard); "Teams and hosting" (sign-in, workspaces, roles and approvals, shared projects, billing). ([PLAN](../../../PHASE-1-PLAN.md))

#### Per-brief summaries
- **L01 Sign in** ([L01](../../../later-phases/L01-sign-in.md))
  - SaaS entry: SSO first ("Continue with Google / GitHub / Microsoft"), then email and password; sign-up; workspace-URL SSO variant.
  - Brand panel renders a read-only mini canvas; proof lines "8 agent frameworks, one runtime", "Deploy to AWS, Azure, GCP or Kubernetes".
  - Open: which identity providers are really supported; product domain. Phase 1 replacement: Welcome opens a folder.
- **L03 Dashboard** ([L03](../../../later-phases/L03-dashboard.md))
  - KPI tiles: runs today, p95 latency, guardrail blocks, estimated LLM cost ("on budget").
  - Read-only system map, deployments tile (Production on ECS, Staging on Kubernetes Helm with deploy progress), recent runs table (completed, paused for approval, blocked by guardrail).
  - "Needs attention" list: paused runs, an evaluation suite below its gate, a secret rotating soon, a deploy in progress. KPI data would come "from the tracing provider and the queue".
- **L09 Agents: list and detail** ([L09](../../../later-phases/L09-agent-detail.md))
  - Agents table plus per-agent tabs: Instructions (with model, temperature, streaming, "Receives handoffs from", A2A agent card JSON preview), Tools (source Project/System/MCP, approval toggle), Hooks (drag-reorder, system hooks locked), Run options (incl. "Compute per run with a factory"), Output schema, Human in the loop (pause policy, approver group, approve/deny/cancel decisions, paused runs list).
  - "Overview" and "Versions" tabs "are not briefed yet". Capability-dependent tabs explain why a framework lacks a feature.
- **L10 Tools, MCP and sandbox** ([L10](../../../later-phases/L10-tools-and-mcp.md))
  - Project tool library with source, parameters, approval condition, a "Try it" runner with result and latency, per-framework binding wrapper, 24 h usage sparkline.
  - System tools by capability: multimodal (`analyze_attachments`), sandbox (`run_code`, `run_command`, file and session tools, `install_packages`), scheduling (`create_schedule` etc.), knowledge (`search_kb`, `read_kb`, `write_kb` etc.), AG-UI state tools.
  - MCP: consumed MCP server cards (e.g. GitHub MCP, Postgres MCP) and "Expose this project as an MCP server" with "Expose agents as tools". Sandbox profiles table (provider, isolation, network, languages, installs, scope), fail-closed banner; providers local subprocess, Docker, Kubernetes, E2B, Daytona, EC2 over SSM. New tool modal: "Write Python", "Import from MCP", "Describe with AI".
- **L11 Knowledge bases** ([L11](../../../later-phases/L11-knowledge-bases.md))
  - Cards per KB with capability chips (Search, Query, Fetch, Browse, Writable/Read-only): OKF bundle (S3), Neo4j (Cypher), Starburst/Trino (SQL, read-only), ChromaDB (vector).
  - OKF bundle browser with trust tiers (verified/draft), document view and history; per-agent role matrix (consumer, producer, curator); "Test search" with scored results; Cypher and SQL query consoles.
  - Add KB modal: OKF bundle, ChromaDB, Neo4j, Starburst/Trino, Amazon S3 documents, Custom (Python class path).
- **L12 Channels and protocols** ([L12](../../../later-phases/L12-channels-and-protocols.md))
  - Channel cards: Slack, WhatsApp, Gmail (polling), LiveKit voice (beta), Teams, Messenger, Instagram, Telegram; Slack config panel (secret references in AWS SSM, events URL, routed agent, reply chunking, typing indicator, attachments, threads, recent events).
  - Protocol list with endpoints: REST and SSE (copy curl), WebSocket gateway (push auth), MCP server, A2A (agent cards JSON), AG-UI (default agent, shared state).
  - LiveKit panel: voice agents, voice handoffs, "Execution mode: realtime", "Join test room".
- **L13 Guardrails and policies** ([L13](../../../later-phases/L13-guardrails-and-policies.md))
  - Enforcement pipeline diagram (Request, input guardrails, agent run, output guardrails, Reply) applied on every surface; provider cards for OpenAI Guardrails, Walled AI, Amazon Bedrock Guardrails; "Recent blocks" feed and block rate by channel; configure modal (PII entities, jailbreak, moderation, off-topic, on-block message).
  - Hooks ordering tab; sandbox policy table incl. filesystem, CPU/memory and "Runs as end user (RBAC)".
  - Authentication tab: validator "JWT with JWKS", issuer, audience, JWKS URL, user-id claim; "Required on" per surface (MCP unchecked); per-user scoping of threads and schedules; "AG-UI always requires authentication".
- **L14 Memory and state** ([L14](../../../later-phases/L14-memory-and-state.md))
  - Store cards (session, thread, attachment, response, queue transport, schedule) with backend, masked connection, health and one metric; backend-support matrix across in_memory, Redis, Valkey, DynamoDB, Cosmos DB, Firestore; "in_memory is rejected at startup" in multi-process production; bring-your-own dotted path.
  - Live browsers: sessions (framework state and caches as JSON, "Clear memory"), threads (auto-naming settings), attachments (TTL).
  - Change-backend modal with "Changing the store resets live sessions".
- **L15 Playground** ([L15](../../../later-phases/L15-playground.md))
  - Chat tester against a deployed environment (e.g. Staging) with session history, user_id, multimodal attachments.
  - Shows the full stream event model including reasoning, tool calls, handoffs, a paused approval with note to the agent; raw events panel (Events, Trace, Raw JSON) with token, latency and cost footer.
  - Variants: structured reply card, voice composer with waveform.
- **L16 Conversations** ([L16](../../../later-phases/L16-conversations.md))
  - Inbox of persistent threads across channels and API with filters (channel, agent, attachments, paused, date); thread view with approval history and linked runs with trace links; export JSON, delete, rename and lock name.
  - Open decision: the runtime "records threads for direct clients, not for messaging integrations", so whether channel conversations appear is a product decision.
- **L17 Traces** ([L17](../../../later-phases/L17-traces.md))
  - Filterable run list (time, agent, channel, status, errors only, run or session id), span tree and waterfall incl. post-hooks and output guardrail, span detail with tokens, latency, cost, temperature and "Open in Langfuse".
  - Blocked-run view showing the guardrail verdict; Metrics tab (runs per hour, latency p50/p95, cost by agent, guardrail blocks); provider modal: Langfuse, OpenLLMetry (Traceloop), Pydantic Logfire, Amazon CloudWatch, Custom.
- **L18 Evaluations** ([L18](../../../later-phases/L18-evaluations.md))
  - Suites list with pass rate; suite view with evaluator, mode, judge, threshold; "Run on every deploy to Staging" with a deploy gate ("Deploys are blocked below the gate"); 14-run pass-rate history; case table with expected vs actual diff and judge rationale.
  - Evaluators: DeepEval (default), Opik, TypeSafe JEV (llm mode only), Custom; modes score, llm, fallback; "Generate cases with AI" and "Generate from recent conversations"; cases link to business rules.
- **L19 Schedules** ([L19](../../../later-phases/L19-schedules.md))
  - Table of deferred and recurring runs (cron or one-off, timezone, session reuse, next/last run, status), row actions Run now, Pause, Edit, Delete; "Created by agent" badge for schedules made via `create_schedule`.
  - New-schedule panel with cron builder and next five occurrences; providers `local` and `eventbridge`, stores in-memory, Redis, Valkey, DynamoDB; per-user visibility when auth is on.
- **L20 Deployments** ([L20](../../../later-phases/L20-deployments.md))
  - Environment tabs Local, Staging, Production; summary chips (queue mode, transport, execution, session, secrets, tracing); "View logs", "Rollback", "Deploy".
  - Topology diagram of the queue pipeline (API gateway, IO handler, input queue, agent runner with KEDA, output queue, WebSocket gateway) and dependencies; configuration key table; deploy history with actor, status, failures and rollbacks.
  - Staging on "Kubernetes (Helm)" with NATS JetStream and Valkey; ChangeTarget modal lists six targets including Kubernetes (Helm) and a "Generate Terraform / Helm values" toggle.
- **L21 Settings (workspace)** ([L21](../../../later-phases/L21-settings.md))
  - Secrets per environment (AWS SSM prefix and resolved path, cache TTL, invalidate cache; Kubernetes Secrets in staging; env locally), keys table with last-rotated and rotation warnings.
  - Coding agents with permission toggles incl. "Deploy" and approval mode; Claude Code and Codex connected, others "Connect".
  - Members and roles (Owner, Admin, Developer, Approver, Viewer), workspace API keys with scopes (chat, threads, schedules), billing plan and usage meters (runs, seats, environments; placeholders). Open: pricing; "Workspace" and "Danger zone" sections not briefed.

### Inferences
- Inference: the parked set amounts to a fairly complete "AgentOps console" design (observability, evals with deploy gates, conversation inbox, scheduling, multi-environment deployments, RBAC-style workspace roles). It shows the team has already thought through hosted-studio parity features, but none of it is committed.
- Inference: some parked briefs are internally stale against the Phase 1 fixture. L19 says "Daily support digest is what enforces BR-011" and L20 says "The Production approval by two people is BR-005", while the Phase 1 fixture defines BR-011 as "Agents answer in the customer's language" and BR-005 as the 90-day refund rule. L01's proof line "Deploy to ... Kubernetes" and L20's Helm staging conflict with Phase 1's no-Helm decision. ([00-project-brief](../../../00-project-brief.md); [L19](../../../later-phases/L19-schedules.md); [L20](../../../later-phases/L20-deployments.md); [L01](../../../later-phases/L01-sign-in.md))
- Inference: L13's authentication tab ("JWT with JWKS" validator) predates the runtime's current identity-provider model (oidc, Cognito, Entra, Firebase, static, role mapper) and would need rework to match it.

### Gaps
- No parked brief exists for the original numbers 02 and 04 to 08 (absorbed into Phase 1), and none covers prompt versioning, agent versions (L09 "Versions" tab not briefed), workspace settings beyond those listed, or a "Danger zone".
- No ordering, phase number or timeline is assigned to any parked brief.

## Q3. What are the stated principles, target user, non-goals, risks, assumptions and open decisions?

### Takeaway
Studio Phase 1 targets one AI engineer or developer on their own laptop (optionally with a business owner beside them), with no accounts or roles. Its five principles are files as source of truth, every command visible, explicit yes for real infrastructure, credentials stay where they are, and nothing depends on the app. The main declared risk is turning canvas edits into correct Python across eight frameworks; key assumptions and open decisions are Claude Code only, one Terraform target per project from six modules, no Helm, a committed `.akstudio/` folder, Electron with React and TypeScript, and Windows, Linux and macOS from the first release.

### Cited Findings

#### Target user
- "One person at their own computer: an AI engineer or developer. A business owner may sit beside them and state rules in plain language. There are no accounts, roles or approvers. 'Approve' always means the person at the keyboard." ([00-project-brief](../../../00-project-brief.md); [PRD](../../../PHASE-1-PRD.md))

#### Principles and global requirements
- Principles: (1) Files are the source of truth; the app re-reads files changed on disk. (2) Every command is visible in a Commands panel with output and exit status. (3) Real infrastructure needs an explicit yes: apply and destroy only after the plan, naming the cloud account. (4) Credentials stay where they are: the existing cloud profile is used, cloud keys are never stored or displayed; model keys live in `.env` and only names are shown. (5) Nothing depends on the app: "Close the app and the folder is still a complete, runnable project." ([PLAN](../../../PHASE-1-PLAN.md); [PRD](../../../PHASE-1-PRD.md))
- "Do not" list for design: invent features or integrations beyond the briefs and repository; design sign-in, accounts, dashboards or any view of a deployed system; use magenta for anything not the coding agent; show a secret value. ([00-project-brief](../../../00-project-brief.md))

#### Non-goals (Phase 1 does not)
- Sign-in, accounts, workspaces, members, roles; dashboards; observing or operating a deployed system (traces, conversations, schedules, live memory, deployment monitoring); team approvals, billing, API keys; Kubernetes with Helm ("it is not Terraform"); hosted runners or CI integration. ([PLAN](../../../PHASE-1-PLAN.md))
- PRD out-of-scope list adds: coding agents other than Claude Code; dedicated configuration pages per area (settings stay reachable via canvas, Config tab, Code tab and coding agent). ([PRD](../../../PHASE-1-PRD.md))

#### Dependencies
- Python 3.12 or 3.13 with `uv`, Claude Code, Terraform, Docker for containerized targets, a signed-in cloud profile; "The app installs none of them." git is optional (branch display, change lists, reverting agent turns), with app snapshots as fallback. ([PRD](../../../PHASE-1-PRD.md); [PLAN](../../../PHASE-1-PLAN.md))

#### Risks (with stated defaults)
- Canvas to code: "the hardest part of Phase 1"; default: read by introspection, write config deterministically, write Python only via scaffold templates and the coding agent, "No general-purpose Python rewriting." ([PLAN](../../../PHASE-1-PLAN.md))
- Code the canvas cannot read: a clear "cannot read" state pointing to the file and offering the coding agent. ([PLAN](../../../PHASE-1-PLAN.md))
- Local trace detail: non-streaming frameworks give run-level timing only; "richer tracing arrives with the Operate phase". ([PLAN](../../../PHASE-1-PLAN.md))
- Reverting agent changes must restore files exactly: git if a repository, otherwise app snapshots. ([PLAN](../../../PHASE-1-PLAN.md))
- Terraform state: local by default with a warning, optional remote backend via `deploy/backend.tf`. Secrets in Terraform: passed as environment variables at run time, not written to `terraform.tfvars`. Cost and safety: plan first, name the account, confirm, always offer destroy. ([PLAN](../../../PHASE-1-PLAN.md))
- Three operating systems: skills generate bash scripts and Unix-style commands; the Run and Deploy services call `uv`, `terraform` and `docker` directly with argument lists; scripts still need Git Bash or WSL on Windows for terminal users; installers need signing on macOS and Windows. ([PLAN](../../../PHASE-1-PLAN.md); [PRD](../../../PHASE-1-PRD.md))
- One target per project: several environments "multiply state and variables". ([PLAN](../../../PHASE-1-PLAN.md))

#### Assumptions to confirm
- (1) Deep configuration pages parked. (2) Claude Code is the only coding agent; others "not set up". (3) One deploy target per project, Terraform only, six modules. (4) App data in `.akstudio/`, committable. (5) Windows, Linux and macOS in Phase 1 from one codebase. (6) Electron with React and TypeScript renderer; where the source lives is open. ([PLAN](../../../PHASE-1-PLAN.md))

#### Open decisions ("Decisions waiting on you")
- Settled: coding agent runs locally, app is Electron, code is real files in the working directory; cross-platform is "decided". ([README](../../../README.md))
- Still open: whether any parked configuration page returns to Phase 1; how canvas edits become Python; deploy scope (one target, six modules, no Helm); Claude Code only; the `.akstudio/` folder; React and TypeScript renderer and source location; the look (design system vs a flatter, denser look); the product name ("Agent Kernel Studio" and `.akstudio/` are working names). ([README](../../../README.md))
- Product-app design adaptations (density, glass only for floating layers, sentence case, motion limits) are themselves listed as assumptions to confirm. ([00-project-brief](../../../00-project-brief.md))

### Inferences
- Inference: the principles are designed for trust with developers and security-minded buyers (no stored cloud credentials, no hidden commands, no lock-in to the app), which is a different value proposition from hosted studios that own the runtime and data plane.
- Inference: the single-user, no-account stance means Phase 1 has no collaboration, sharing or governance story beyond "commit the folder to git".

### Gaps
- No success metrics (adoption, time-to-first-deploy) beyond the acceptance scenario.
- No stated competitive positioning or named competitors in any Studio document.
- No security model for the coding agent beyond per-command approval, allow-lists and the locked "never apply or destroy Terraform" row.

## Q4. What does the Agent Kernel runtime support that Studio builds on, and which of it does Phase 1 surface?

### Takeaway
The runtime is broad: eight framework adapters, eight channels plus LiveKit voice, REST/SSE, WebSocket, MCP, A2A, AG-UI and A2UI, three guardrail providers, six session backends, threads, schedules, a queue pipeline with six transports, four knowledge backends plus OKF, six sandbox providers, five tracing integrations, a pytest test framework with three evaluators, identity providers, secret providers, six Terraform targets plus a Helm chart, and six bundled skills for six coding assistants. Phase 1 Studio surfaces the build-time subset (frameworks, tools, hooks, HITL, structured output, channel/protocol/store/guardrail/sandbox/secret/tracing nodes, config forms, local test with stream trace, Terraform deploy) but largely reaches advanced capabilities only through generic config forms or the coding agent, and has no surface at all for identity, A2UI configuration, most queue transports, LiveKit, Helm/Kubernetes, evaluator choice, or non-Langfuse tracing.

### Cited Findings

#### Runtime positioning
- Tagline: "The Operating System for Scalable & Compliant Enterprise AI Agents"; Apache 2.0; member of the Linux Foundation and the Agentic AI Foundation; requirements Python 3.12 to 3.13. ([repo README](../../../../../../README.md))
- AKConfig top-level sections: session, api, websocket_api, a2a, mcp, slack, livekit, whatsapp, messenger, instagram, telegram, teams, gmail, multimodal, thread, agui, schedule, okf, trace, guardrail, sandbox, secret, identity, a2ui, execution, logging, library_version. ([ak-py/src/agentkernel/core/config.py](../../../../../../ak-py/src/agentkernel/core/config.py))

#### Runtime capability inventory
- Frameworks: OpenAI Agents SDK, LangGraph, CrewAI, Google ADK, Smolagents, Pydantic AI, Microsoft Agent Framework, Claude Agent SDK. ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Human in the loop: runs pause with HTTP 202 `status: "PAUSED"`, resume with approved, denied or cancelled; durable across restarts on a shared session backend; works on REST, streaming, WebSocket and AG-UI. README says five frameworks pause (OpenAI, LangGraph, Pydantic AI, Google ADK, Microsoft Agent Framework); the HITL docs page also lists the Claude Agent SDK (single pending call) and says CrewAI and smolagents cannot. ([repo README](../../../../../../README.md); [human-in-the-loop.md](../../../../../../docs/docs/advanced/human-in-the-loop.md))
- Framework-native run options per agent via `Module.run_options`, static or computed per run by a factory, with reserved keys protected. ([repo README](../../../../../../README.md))
- Channels: Slack, WhatsApp, Microsoft Teams, Telegram, Gmail, Messenger, Instagram; LiveKit connects OpenAI Agents SDK and Google ADK agents to WebRTC rooms via the realtime pipeline (docs under "next", i.e. unreleased). ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Protocols and APIs: MCP (consume external tools, optionally expose agents as MCP tools), A2A, AG-UI (streams text, tool calls, reasoning, shared state to e.g. CopilotKit), A2UI (agent emits component JSON; AK "labels the payload and carries it intact", enabled per agent in an `a2ui` block), REST & SSE, WebSocket. ([repo README](../../../../../../README.md); [a2ui.md](../../../../../../docs/docs/advanced/a2ui.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Guardrails: OpenAI Guardrails, Amazon Bedrock Guardrails, Walled AI (README feature table names only OpenAI and AWS Bedrock). ([data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx); [AGENTS.md](../../../../../../AGENTS.md); [repo README](../../../../../../README.md))
- Memory: session stores in-memory, Redis, Valkey, DynamoDB, Cosmos DB, Firestore; threads on the same six; scheduled-task stores in-memory, Redis, Valkey, DynamoDB with local or AWS EventBridge Scheduler timers; attachment and response stores (Redis, DynamoDB and others per data.tsx tooltips). ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Knowledge: ChromaDB (vector), Neo4j (graph), Starburst Galaxy/Trino (SQL), Open Knowledge Format bundles (local directory or S3), Amazon S3, custom `KnowledgeBase` interface. ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Execution: queue-pipeline execution for every chat request, in-process by default with FIFO/retry/dedup semantics; transports SQS, Kafka, NATS JetStream, Google Cloud Pub/Sub, Azure Service Bus; WebSocket gateway tier; execution modes include synchronous, WebSocket/async and stateless MCP; AWS supports `rest_sync`, `rest_async`, `async` with message type `complete` or `delta`. ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx); [ak-cloud-deploy SKILL](../../../../../../ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md))
- Sandbox: providers `local_subprocess`, `docker`, `kubernetes`, `e2b`, `daytona`, `ec2_ssm`, plus bring-your-own; workload profiles per call, per session or shared, with fail-closed policies (network egress, filesystem, CPU/memory, timeout, languages, package installs); per-user identity for sandboxed code. ([repo README](../../../../../../README.md))
- Observability: Langfuse, OpenLLMetry (Traceloop), Pydantic Logfire, AWS CloudWatch, OpenTelemetry. (AGENTS.md's repo map lists only Langfuse and OpenLLMetry under `trace/`, which looks out of date.) ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx); [AGENTS.md](../../../../../../AGENTS.md))
- Identity and access: one identity provider for every surface: any OIDC issuer (Auth0, Keycloak, Okta), Amazon Cognito, Microsoft Entra ID, Firebase, static credentials, or a custom class; optional role mapper. The docs state "Nothing enforces `roles` yet: authorization arrives in a later phase." Identity docs are only in the unreleased "next" docs. ([repo README](../../../../../../README.md); [identity-and-access.md](../../../../../../docs/docs/advanced/identity-and-access.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx))
- Secrets: `SecretManager` resolves from environment locally, AWS SSM Parameter Store or mounted Kubernetes Secrets in production, or a custom provider, "with only config.yaml changing". ([repo README](../../../../../../README.md); [ak-add-capabilities SKILL](../../../../../../ak-py/src/agentkernel/skills/ak-add-capabilities/SKILL.md))
- Testing: pytest-integrated; score, llm and fallback comparison modes; pluggable evaluators DeepEval (default), Opik, TypeSafe JEV; CLI testing via a `Test` class; docs also describe API (HTTP/A2A) testing. ([repo README](../../../../../../README.md); [data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx); [testing/overview.md](../../../../../../docs/docs/testing/overview.md))
- Deployment: Terraform modules for AWS Lambda and ECS Fargate, Azure Functions and Container Apps, GCP Cloud Run serverless and containerized; Helm chart (OCI on GHCR) for on-prem/baremetal/EKS with Kafka/NATS queue mode, KEDA autoscaling, bundled Valkey and NATS, air-gap image list. The `ak-cloud-deploy` skill covers both Terraform and Helm, plus an API Gateway authorizer driven by the identity provider and EventBridge Scheduler. ([repo README](../../../../../../README.md); [ak-cloud-deploy SKILL](../../../../../../ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md))
- Bundled skills: `ak-init`, `ak-build`, `ak-add-capabilities`, `ak-add-integration`, `ak-cloud-deploy`, `ak-test`. The installer registry supports copilot, claude, cursor, windsurf, codex and aider. ([repo README](../../../../../../README.md); [skills.py](../../../../../../ak-py/src/agentkernel/skills/skills.py))
- Other: multimodal attachments (with LiteLLM listed as an LLM gateway under multimodal), pre/post hooks, conversation threads, fault-tolerance docs (retry logic, health checks, monitoring and alerting). ([data.tsx](../../../../../../docs/src/components/IntegrationsMarquee/data.tsx); [fault-tolerance.md](../../../../../../docs/docs/core-concepts/fault-tolerance.md))

#### Capability bucket matrix (runtime capability vs Studio surface)
| Runtime capability | Phase 1 surface (A) | Parked brief (B) | Bucket | Sources |
|---|---|---|---|---|
| 8 framework adapters, mixed in one project | Wizard cards with capability chips; agent nodes; fixture mixes 3 frameworks | L09 agent pages | A | [03](../../../03-new-project.md), [04](../../../04-agent-canvas.md) |
| Tools, approval conditions | Tool nodes, inspector Tools tab, "Requires approval" | L10 library, Try it, system tools | A | [04](../../../04-agent-canvas.md), [L10](../../../later-phases/L10-tools-and-mcp.md) |
| Pre/post hooks, system hooks | Hook tile, Hooks tab with locked system hooks | L09, L13 reorderable hooks | A | [04](../../../04-agent-canvas.md) |
| Framework-native run options | Run options tab (KeyValueEditor, reserved keys) | L09 incl. per-run factory | A (factory B) | [04](../../../04-agent-canvas.md), [L09](../../../later-phases/L09-agent-detail.md) |
| Structured output | Output schema tab | L09, L15 | A | [04](../../../04-agent-canvas.md) |
| Human in the loop | HITL toggle; approval cards in local test | L09 pause policy with approver groups; L15 | A (approver roles B) | [04](../../../04-agent-canvas.md), [07](../../../07-builder-test-and-trace.md) |
| Channels: Slack, WhatsApp, Gmail, Teams | Channel tile and node, config form, `ak-add-integration` | L12 config panels | A | [04](../../../04-agent-canvas.md), [05](../../../05-build-with-ai.md) |
| Channels: Telegram, Messenger, Instagram | Only implicitly ("and the others") | L12 | A-implicit / B | [05](../../../05-build-with-ai.md), [L12](../../../later-phases/L12-channels-and-protocols.md) |
| LiveKit voice / realtime | None | L12, L15 voice, L16 | B | [L12](../../../later-phases/L12-channels-and-protocols.md) |
| REST/SSE, WebSocket, MCP, A2A, AG-UI | Protocol tile mapped to config blocks; local test uses REST/SSE | L12 endpoints, A2A cards; L10 consume/expose MCP | A (config level) | [04](../../../04-agent-canvas.md), [07](../../../07-builder-test-and-trace.md) |
| Consuming external MCP servers as tools | Not described | L10 MCP server cards, "Import from MCP" | B | [L10](../../../later-phases/L10-tools-and-mcp.md) |
| A2UI configuration (`a2ui` block) | Only as a locked "A2UI labelling" system hook; `a2ui` not in Config section list | Same hook only | C (config) | [04](../../../04-agent-canvas.md), [a2ui.md](../../../../../../docs/docs/advanced/a2ui.md) |
| Guardrails: OpenAI, Walled AI | Guardrail tile, drop on input/output port | L13 provider cards, recent blocks | A | [04](../../../04-agent-canvas.md) |
| Guardrails: Bedrock | Not named | L13 | B | [L13](../../../later-phases/L13-guardrails-and-policies.md) |
| Session, thread, attachment stores | Store tiles and config forms (fixture: Redis) | L14 backends matrix, live browsers | A (config) | [04](../../../04-agent-canvas.md), [L14](../../../later-phases/L14-memory-and-state.md) |
| Response store | None | L14 | B | [L14](../../../later-phases/L14-memory-and-state.md) |
| Knowledge bases | Knowledge tile/node (fixture OKF, Starburst) | L11 consoles, roles, add modal | A (node) / B (management) | [04](../../../04-agent-canvas.md), [L11](../../../later-phases/L11-knowledge-bases.md) |
| Schedules | `schedule` listed dimmed in Config; explicitly a non-goal | L19 | B | [04](../../../04-agent-canvas.md), [PLAN](../../../PHASE-1-PLAN.md) |
| Sandbox | Sandbox profile tile, `sandbox` block, BR-010 | L10, L13 profiles and policy | A (config) | [04](../../../04-agent-canvas.md) |
| Secrets: env | Settings-Secrets names only, `.env` | L21 per environment | A | [09](../../../09-app-settings.md) |
| Secrets: AWS SSM, Kubernetes | "chosen per deploy target, in config.yaml" (no UI) | L12, L21 | A-implicit / B | [09](../../../09-app-settings.md), [L21](../../../later-phases/L21-settings.md) |
| Identity providers (oidc/Auth0/Okta/Keycloak, Cognito, Entra, Firebase, static, role mapper) | Zero mentions | L13 generic "JWT with JWKS" auth tab only | C (providers) / B (auth concept) | [L13](../../../later-phases/L13-guardrails-and-policies.md), [identity-and-access.md](../../../../../../docs/docs/advanced/identity-and-access.md) |
| Tracing: Langfuse | Tracing tile/`trace` block; local trace independent of provider | L17 with "Open in Langfuse" | A (config) | [04](../../../04-agent-canvas.md), [07](../../../07-builder-test-and-trace.md) |
| Tracing: OpenLLMetry, Logfire, CloudWatch | Not named | L17 provider modal | B | [L17](../../../later-phases/L17-traces.md) |
| Tracing: OpenTelemetry | Not named | Not named | C | spec-folder search |
| Test framework, modes, judge | Tests strip, `uv run pytest`, `test-config.yaml` mode and judge | L18 suites, gates, history | A | [07](../../../07-builder-test-and-trace.md) |
| Evaluator choice: DeepEval, Opik, TypeSafe JEV | Not named | L18 | B | [L18](../../../later-phases/L18-evaluations.md) |
| Execution mode, message type | Execution mode tile, Config form, deploy compatibility check | L20 config table | A | [04](../../../04-agent-canvas.md), [08](../../../08-builder-deploy.md) |
| Queue transports | Only `queue transport: in_memory` in the execution form | L14 (SQS), L20 (SQS, NATS) | B (SQS, NATS); C (Kafka, Pub/Sub, Azure Service Bus) | [04](../../../04-agent-canvas.md), [L20](../../../later-phases/L20-deployments.md) |
| WebSocket gateway tier | None | L12, L20 topology | B | [L20](../../../later-phases/L20-deployments.md) |
| Terraform: 6 targets | Deploy tab, full plan/apply/destroy | L20 monitoring, rollback | A | [08](../../../08-builder-deploy.md) |
| Helm chart, Kubernetes, KEDA | Explicitly excluded | L20 (staging on Helm, KEDA) | B | [PLAN](../../../PHASE-1-PLAN.md), [L20](../../../later-phases/L20-deployments.md) |
| Bundled skills (6) | Installed via `ak skill install --assistant claude`, slash chips, PlanCard steps | L21 | A | [03](../../../03-new-project.md), [05](../../../05-build-with-ai.md) |
| Coding assistants: Codex, Cursor, Windsurf, Copilot | Listed "Not set up" | L21 "Connect" | B | [09](../../../09-app-settings.md), [L21](../../../later-phases/L21-settings.md) |
| Coding assistant: Aider | Not listed | Not listed | C | [skills.py](../../../../../../ak-py/src/agentkernel/skills/skills.py) |
| Model providers | Wizard: OpenAI, Anthropic, Google AI, Azure OpenAI, Amazon Bedrock, Hugging Face | L09 model select | A | [03](../../../03-new-project.md) |
| LiteLLM gateway | Not named | Not named | C | spec-folder search |
| Multimodal attachments | Attachment store tile; test composer attach; Problems warning | L14 attachments browser, L15 | A (config) | [04](../../../04-agent-canvas.md), [07](../../../07-builder-test-and-trace.md) |
| Fault tolerance, health checks, monitoring/alerting | None | L03, L14, L20 health dots only | C (as a configurable feature) | spec-folder search, [fault-tolerance.md](../../../../../../docs/docs/core-concepts/fault-tolerance.md) |
| Logging config | Listed as a set Config section | None | A (config) | [04](../../../04-agent-canvas.md) |

### Inferences
- Inference: Phase 1 exposes the runtime's breadth mainly through two generic mechanisms, the AKConfig-generated Config forms and the coding agent with the six skills. That gives nominal coverage of almost every runtime capability, but dedicated, task-shaped UI exists only for agents, tools, hooks, HITL approvals, local testing, rules and Terraform deploy.
- Inference: since Config forms are generated from AKConfig, the `identity`, `a2ui`, `websocket_api` and `livekit` sections would probably appear in the Config tab even though no brief names them; the briefs simply do not design for them.
- Inference: the runtime's strongest enterprise differentiators (queue-pipeline scale-out on five brokers, Helm/Kubernetes with KEDA and air-gap support, identity providers, multi-cloud secret resolution) are exactly the ones Phase 1 does not surface, so a comparison against hosted studios will show Studio weaker on "operate and govern" even where the runtime is strong.

### Gaps
- I did not verify the Config tab's real behaviour for unnamed sections; no section-by-section design beyond "execution" exists.
- Runtime execution-mode enumerations were taken from the `ak-cloud-deploy` skill description, not from config code.
- Some runtime features (LiveKit, Claude Agent SDK, Microsoft Agent Framework, identity, secrets pages) are documented under unreleased "next" docs per data.tsx comments, so release status at Studio launch is uncertain.

## Q5. Where are the obvious internal gaps?

### Takeaway
Three kinds of gap stand out: runtime capabilities that have no Studio design at all (identity providers and role mapping, A2UI configuration, Kafka/Pub/Sub/Azure Service Bus transports, OpenTelemetry, LiteLLM, fault-tolerance settings, Aider); runtime capabilities deferred to unplanned briefs (Helm/Kubernetes, LiveKit voice, schedules, evaluator choice, non-Langfuse tracing, MCP client management, response store, WebSocket gateway); and common developer-tool features absent from both Phase 1 and the parked briefs (prompt and agent versioning, dataset management, production feedback and annotation, alerting and budgets, git commit/PR flows, CI, environment promotion, collaboration, step debugging, red-teaming, end-user chat publishing, local model runtimes).

### Cited Findings
- Identity: zero hits for identity, authentication, OIDC, Auth0, Okta, Keycloak, Cognito, Firebase or role mapper in any Phase 1 document; the only auth design is L13's "JWT with JWKS" tab. The runtime itself says role enforcement "arrives in a later phase". (keyword search of the spec folder; [L13](../../../later-phases/L13-guardrails-and-policies.md); [identity-and-access.md](../../../../../../docs/docs/advanced/identity-and-access.md))
- Not named in any Studio brief (Phase 1 or parked): OpenTelemetry, Kafka, Google Pub/Sub, Azure Service Bus, LiteLLM, Aider, any `a2ui:` config, Ollama or other local model runtime, "pull request", "dataset", "alert", "widget"/"embed", "red team", "prompt version". (keyword search of `*.md` and `later-phases/*.md` in the spec folder)
- Explicit Phase 1 exclusions with no Phase 1 substitute: observing a deployed system, CI and hosted runners, Helm, teams and roles. ([PLAN](../../../PHASE-1-PLAN.md); [PRD](../../../PHASE-1-PRD.md))
- Versioning: L09 notes "'Overview' and 'Versions' tabs are not briefed yet". ([L09](../../../later-phases/L09-agent-detail.md))
- Rollback and environment history appear only in L20 ("Rollback", deploy history with "Rolled back"); Phase 1 offers redeploy and destroy only. ([L20](../../../later-phases/L20-deployments.md); [08-builder-deploy](../../../08-builder-deploy.md))
- Git use in Phase 1 is limited to branch display, changed-file markers, checkpoints for revert, and "can be committed" for `.akstudio/`; no commit, push or PR UI is described. ([PLAN](../../../PHASE-1-PLAN.md); [04-agent-canvas](../../../04-agent-canvas.md); [00-project-brief](../../../00-project-brief.md))
- Cost appears only as per-run chips in the local trace (e.g. "$0.021") and as an "Est. LLM cost ... on budget" KPI in the parked L03; there is no budget or alert configuration anywhere. ([07-builder-test-and-trace](../../../07-builder-test-and-trace.md); [L03](../../../later-phases/L03-dashboard.md))
- Deployed endpoint testing: Phase 1 shows a ready-made curl after deploy, but whether a smoke test belongs in Phase 1 is open; the deployed-environment playground is parked (L15). ([08-builder-deploy](../../../08-builder-deploy.md); [L15](../../../later-phases/L15-playground.md))
- Conversation history for messaging channels is unresolved even in the parked design, since the runtime records threads only for direct clients. ([L16](../../../later-phases/L16-conversations.md))
- Templates: four starting templates only (Blank, Support triage, Research crew, Slack assistant); no template gallery or sharing is described. The repo's `use-cases/` folder (agents generated from a `SPEC.md` using the skills) is not referenced by Studio. ([03-new-project](../../../03-new-project.md); [repo README](../../../../../../README.md))
- Internal inconsistencies to flag: README says five frameworks support HITL while the HITL docs and Studio brief 03 include the Claude Agent SDK; README's feature table lists only OpenAI and Bedrock guardrails while Walled AI ships; parked briefs reference business-rule ids that no longer match the Phase 1 fixture. ([repo README](../../../../../../README.md); [human-in-the-loop.md](../../../../../../docs/docs/advanced/human-in-the-loop.md); [03-new-project](../../../03-new-project.md); [L19](../../../later-phases/L19-schedules.md))

### Inferences
- Inference, features a developer agent studio usually has that are absent from both Phase 1 and parked briefs:
  - Prompt management: versioned prompts, prompt diffing, side-by-side model or prompt comparison (only run-vs-run trace compare exists, second pass, not drawn).
  - Evaluation data: dataset import/export, golden sets, production-trace-to-test promotion at scale (Phase 1 has "Save this exchange as a test case" for one exchange; L18 has "Generate from recent conversations" only as an empty-state button).
  - Online evaluation and human feedback: thumbs up/down, annotation queues, reviewer workflows beyond HITL tool approvals.
  - Alerting, cost budgets, rate limiting or quota management.
  - Source control workflows: commit, branch, PR creation and review from the app; CI pipelines (explicit non-goal).
  - Environment promotion (dev to staging to prod) with gates in Phase 1; only L18 and L20 sketch gates and environments.
  - Collaboration: real-time co-editing, comments, sharing a project link; Phase 1 is single-user by design.
  - Debugging: breakpoints, step-through, replay of a recorded run with modified inputs (only "Replay in Test" for a failing case).
  - Safety testing: red-teaming or adversarial test generation; guardrail testing beyond running a conversation.
  - Publishing an end-user chat UI or embeddable widget, even though the runtime has AG-UI and A2UI.
  - Local or self-hosted model runtimes in the provider list; the list is cloud-API providers plus Hugging Face.
  - Knowledge ingestion pipeline (upload, chunk, embed, re-index); L11 connects existing backends and browses OKF bundles but does not ingest documents.
  - MCP discovery or catalog; L10 shows two configured servers only.
  - App lifecycle items: auto-update, crash reporting or usage telemetry, extension or plugin model for Studio itself.
- Inference: the Phase 1 dependency on Claude Code for anything beyond config edits is a single-vendor risk for the build experience, while the runtime's own skill installer already supports five other assistants.
- Inference: the absence of any identity design in Phase 1 is coherent with "no accounts" for the app, but it also means a user cannot configure who may call the deployed agent (an `identity` block and the API Gateway authorizer the deploy skill supports) except by raw Config form or the coding agent.

### Gaps
- I could not determine whether the parked briefs will be revived in a particular order or which ones are next; nothing in the files states priorities.
- Whether Studio's Config tab will validate and render every AKConfig section (including identity and a2ui) is undocumented.
- No information on Studio telemetry, update channels, or support for air-gapped or offline use, all of which matter for enterprise comparison.
