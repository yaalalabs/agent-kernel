# 00 · Project brief

Read this first in every session. Each Phase 1 brief (01 to 09) assumes it. The scope and the reasoning behind
it are in [PHASE-1-PLAN.md](PHASE-1-PLAN.md).

## Product (Phase 1)

Agent Kernel Studio (working name) is a desktop app for building projects on Agent Kernel, the open-source
runtime by Yaala Labs that takes AI agents from prototype to production. It is an Electron app that works on
one folder on the user's computer, the **working directory**, the way a code editor does.

1. **It writes real project files** into that folder: the agents (`app.py`), the tools, `config.yaml`, the
   Python project and the Terraform files under `deploy/`. The canvas is a view of those files, never a
   separate model.
2. **A coding agent can do the building.** Claude Code runs locally in the same folder and edits the project
   through the bundled `ak-*` skills. The user sees the conversation, the code it wrote and the plain-language
   business rules side by side.
3. **It runs, tests and deploys from this computer.** A local run for testing; Terraform, with the user's own
   cloud credentials, for deploying.

Not in Phase 1: sign-in, accounts and teams, dashboards, and anything that observes or operates a deployed
system. Those briefs are parked in [later-phases/](later-phases/). Do not design from them.

## People

One person at their own computer: an AI engineer or developer. A business owner may sit beside them and state
rules in plain language. There are no accounts, roles or approvers. "Approve" always means the person at the
keyboard.

## Design system

Use the **Agent Kernel Design System** from this account's design systems. Do not use the organization
default: that one is a presentation system for slides, and this is product UI.

- Install it on the canvas and mount its real components (Button, Badge, Tag, Card, Input, CodeBlock,
  GradientHeading). Never draw look-alikes.
- Type, colour, spacing and radii come from its tokens. Do not restate or override them in an artboard.
- Fonts as the system defines them: Archivo for display, headings and button labels; Inter for body and UI;
  JetBrains Mono for code, paths, identifiers and numbers in tables.
- Logos are real marks, never redrawn. Product marks are in `docs/static/img/branding/`, partner and
  framework marks in `docs/static/img/integrations/`. Upload the ones a screen needs as assets.
- Icons: the system's line icon set. No emoji anywhere in the product UI.

## Product-app adaptations (assumptions, confirm before the first screen)

The design system was derived from the marketing site. A tool used for hours is denser, so these briefs assume
the adaptations below. Everything not listed follows the system unchanged.

1. **Density.** 8px grid, 14px Inter as the base size, 40px rows and controls, 48px top bar. Marketing-scale
   spacing and hero type sizes are not used in the app.
2. **Marketing-only effects stay on the marketing site.** No spectrum-gradient words, particle or plant motif,
   cosmic-wave fields, section glow dividers or scroll and entrance animation. The logo mark keeps its gradient.
3. **Glass is for floating layers.** Menus, popovers, drawers, modals and toasts use the system's glass panel.
   Docked panels, tables and page surfaces are solid, with the system's card fill and hairline border.
4. **Glow and lift are reserved.** They mark selection and the primary action: a selected canvas node, a
   focused input, the primary button on hover. Rows and static cards do not lift or glow.
5. **Shape follows the system.** Pill buttons, badges and tags; cards, inputs and menus at the system's radii.
6. **Casing.** App copy is sentence case, exactly as written in these briefs. The system's Title Case rule is
   kept for marketing headlines and calls to action.
7. **Motion.** 150ms on hover and focus, 250ms for panels. The only ambient motion is a soft pulse on items the
   coding agent has just added, and progress on a running command. Respect reduced-motion settings.
8. **Desktop app.** Draw the window's content area only, with no operating-system window frame. Screens are
   fluid pages drawn at 1440 by 900 and must hold at 1100 wide. There are no phone layouts.

## Colour semantics

| Role | Colour | Used for |
|------|--------|----------|
| Primary | Electric blue | Primary action, links, focus ring, the active tab, selection |
| AI | Magenta | Anything authored or offered by the coding agent: the Build with AI entry, its avatar, "Added by Claude Code" badges, generated nodes and edges, "with AI" buttons. Nothing else. |
| Success | Success token | Passed, running, connected, in sync, applied |
| Needs a person | Warning token | Pending approval, out-of-sync rule, a plan waiting for confirmation, a change on disk |
| Failure | Danger token | Failed, blocked, destroy and other destructive actions |

- All text meets 4.5:1 contrast, including secondary labels and 12px captions.
- State is never colour alone: a dot or icon plus a label.
- Paths, commands, code, YAML, durations, token counts and money are JetBrains Mono, with tabular figures.

## Desktop shell (build once, import everywhere)

`DesktopShell` wraps every screen except Welcome and New project. There is no left navigation in Phase 1.

- **TopBar**, left to right:
  - `ProjectSwitcher`: the folder name ("support-triage"), its path on hover, and a menu: open folder, new
    project, recent projects, reveal in the file manager.
  - `AppTabs`: Canvas, Code, Config, Test & Trace, Deploy.
  - `RunControl`: the state of the local run (stopped, starting, running on a port) with start and stop.
  - `DeployStatus`: "Not deployed", or "Deployed" with a relative time.
  - **Build with AI** (AI style) and a settings control.
- **BottomPanel**, collapsible, with three tabs: Problems (validation), Run log (output of the local run),
  Commands (every command the app or the coding agent ran, with its exit status).
- **StatusBar**: the working directory path, the git branch when the folder is a repository, the Python
  environment state, the file sync state, the coding agent's state.
- **BuildWithAIDrawer** opens from the top bar on any tab. Views: Chat, Code, Rules. Its expand control opens
  the agentic development workspace (brief 06).

App components the design system does not have yet are inventoried in
[01-app-components.md](01-app-components.md). Build those before the screens.

## Working-directory rules the UI must make visible

1. **Files are the source of truth.** The canvas and the Config tab are views. When a file changes on disk,
   the app re-reads it and says so.
2. **Every command is visible.** Anything run on the user's computer appears in the Commands panel.
3. **Real infrastructure needs an explicit yes.** Applying or destroying Terraform always shows the plan and
   names the cloud account first.
4. **Secrets are names only.** A key name, where it is stored and whether it resolves. Never a value.

## Fixture data (use exactly this; do not invent more)

The same example project appears on every screen. Numbers shown on a screen come from its brief. Anything not
given is a placeholder in square brackets, never an invented fact.

- Working directory `~/code/support-triage`, a git repository on branch `main`.
- Agents: **triage** (OpenAI Agents SDK, gpt-4o), **billing** (LangGraph, claude-sonnet-4-5),
  **kb-researcher** (Google ADK, gemini-2.5-pro). triage hands off to billing and kb-researcher.
- Tools in `tool.py`: `lookup_order`, `refund_payment` (human approval when `amount > 200`), `search_docs`,
  `create_ticket`.
- Hooks in `hooks.py`: pre-hook "RAG context injector" (triage, kb-researcher); post-hook "Signature footer"
  (triage, kb-researcher; **not yet registered on billing**). System hooks are fixed: input guardrail,
  multimodal, sandbox (pre); output guardrail, A2UI labelling (post).
- Knowledge: **Help Center** (Open Knowledge Format bundle), **Orders** (Starburst/Trino, read-only).
- Channels: Slack `#support`, WhatsApp and Gmail, all routed to triage. Protocols: REST and SSE.
- Guardrails: OpenAI Guardrails on input (PII detection, jailbreak); Walled AI on output (safety, PII
  redaction).
- Config highlights: `execution.mode: rest_sync`, `execution.message_type: delta`, `session.type: redis`,
  `guardrail.enabled: true`, tracing with Langfuse.
- Tests: `app_test.py` with 42 cases; `test-config.yaml` with mode `fallback`, a judge model and threshold 0.80.
  Last run: 40 passed, 2 failed.
- Local secrets in `.env`: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `SLACK_BOT_TOKEN`,
  `SLACK_SIGNING_SECRET`, `WALLED_API_KEY`, `LANGFUSE_SECRET_KEY`.
- Deploy target: AWS ECS Fargate (containerized), region eu-west-1, AWS profile `default`. Not deployed yet.
- Coding agent: Claude Code, found on this computer and connected.
- Tool versions, account numbers and resource counts are not given: show `[VERSION]`, `[ACCOUNT]`, `[N]`.

### Project files

```
~/code/support-triage/
  app.py               agents and module wiring
  tool.py              custom tools
  hooks.py             pre- and post-hooks
  config.yaml          Agent Kernel configuration
  app_test.py          tests
  test-config.yaml     test harness settings
  pyproject.toml       Python project
  uv.lock
  build.sh
  README.md
  .env                 local secrets, ignored by git
  .claude/commands/    Agent Kernel skills for Claude Code
  .akstudio/           studio data: canvas layout, business rules, test scenarios, deploy history
  deploy/
    main.tf  variables.tf  outputs.tf  providers.tf  terraform.tfvars
    Dockerfile
    deploy.sh
```

The layout is the one the bundled `ak-init` and `ak-cloud-deploy` skills generate. `hooks.py` and `.akstudio/`
are additions of this fixture.

### Business rules (12 rules, 11 enforced, 1 out of sync, 9 covered by tests)

| Id | Category | Rule | Enforced by | Tests |
|----|----------|------|-------------|-------|
| BR-001 | Routing | Messages from Slack #support, WhatsApp and Gmail are handled first by triage | Channel routing in `config.yaml` | 4 |
| BR-002 | Routing | Payment and refund questions are handed off to billing | billing handoff description in `app.py` | 3 |
| BR-003 | Routing | Product and how-to questions are handed off to kb-researcher | kb-researcher handoff description in `app.py` | 3 |
| BR-004 | Approval | Refunds above $200 require approval | `refund_payment` approval condition in `tool.py`; billing human-in-the-loop setting | 3 |
| BR-005 | Compliance | Refunds are refused for orders older than 90 days | `refund_payment` precondition in `tool.py` | none |
| BR-006 | Compliance | Customer PII never reaches the model unredacted | Input and output guardrails in `config.yaml` | 6 |
| BR-007 | Compliance | Jailbreak attempts are blocked | Input guardrail in `config.yaml` | 4 |
| BR-008 | Data | Only kb-researcher writes to the Help Center; other agents read | Knowledge roles in `config.yaml` | 2 |
| BR-009 | Tone | Customer replies end with the support signature | "Signature footer" post-hook. **Out of sync: the hook is not registered on billing** | 2 |
| BR-010 | Safety | Code run by agents has no network access | Sandbox profile in `config.yaml` | none |
| BR-011 | Tone | Agents answer in the customer's language | Instructions of all three agents in `app.py` | 1 |
| BR-012 | Data | Order data is read-only for agents | The Orders knowledge base is a read-only backend | none |

BR-004 and BR-011 were added by Claude Code. Rule states are Enforced, Drafted (no implementation yet) and
Out of sync (the files no longer match the rule).

### Story moments

Screens show one of two moments. Keep each screen in its moment so linked prototypes stay consistent.

| Moment | What is true | Screens |
|--------|--------------|---------|
| A, building | The project has triage and kb-researcher. Claude Code is adding the billing agent. | 05, 06 |
| B, ready to ship | billing is accepted. BR-009 is out of sync. The project has never been deployed. | 04, 07, 08, 09 |

## Real names come from the repository

When Claude Design runs inside the Agent Kernel repository, read these instead of guessing a name, a config
key or a logo:

- `README.md`: positioning and the feature list.
- `docs/src/components/IntegrationsMarquee/data.tsx`: the inventory of frameworks, channels, stores, clouds
  and providers, with their logo file names.
- `ak-py/src/agentkernel/core/config.py`: `AKConfig`, the real configuration sections and keys.
- `ak-py/src/agentkernel/skills/`: the bundled skills. `ak-init` and `ak-cloud-deploy` define the project and
  `deploy/` layouts; `ak-cloud-deploy` lists the Terraform modules and their variables.
- `examples/aws-containerized/`: a complete example of a project with its `deploy/` folder.

Use Agent Kernel's own vocabulary in labels: handoff, pre-hook, post-hook, session store, guardrail, execution
mode, message type, sandbox profile.

## Canvas and artboard conventions

- One design canvas named "Agent Kernel Studio". Canvas pages: System, Start, Builder, Settings.
- One screen per artboard, following adaptation 8 for size.
- Artboard names are `Area-Screen` and `Area-Screen-State`, for example `Builder-Canvas` and
  `Builder-Canvas-Empty`. Component names are PascalCase. Both become code names at handoff, so keep them
  exactly as the briefs give them.
- States and variants sit to the right of their main artboard, in the same row.
- Decisions, assumptions and open questions go in canvas notes beside the artboard, not inside the design.
- Each brief marks artboards as first pass or second pass. Build first-pass artboards first.

## Interaction defaults

Unless a brief says otherwise:

- `AppTabs` are prototype links to the matching artboard. "Build with AI" opens the drawer.
- The bottom panel opens, closes and switches tabs.
- Everything else is static. Briefs for working prototypes list exactly what must work under Behaviour.

## Do not

- Invent features, integrations, metrics, versions, account numbers or copy beyond these briefs and the
  repository.
- Design sign-in, accounts, dashboards or any view of a deployed system.
- Redraw a logo, restyle a design-system component, or use magenta for anything that is not the coding agent.
- Show a secret value.

## Handoff

The design canvas is handed to Claude Code for implementation as the renderer of an Electron app. Artboard and
component names are the intended code names. The renderer stack is assumed to be React and TypeScript (see the
plan).
