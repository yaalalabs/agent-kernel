# 00 · Project brief

Read this first in every session. Each Phase 1 brief (01 to 09) assumes it. The scope and the reasoning behind
it are in [PHASE-1-PLAN.md](PHASE-1-PLAN.md).

## Product (Phase 1)

Open Agent Kernel Studio (OAK Studio, a working name) is a desktop app for building projects on Open Agent
Kernel (OAK), the open-source runtime that takes AI agents from prototype to production. It is an Electron app
that works on one folder on the user's computer, the **working directory**, the way a code editor does.

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

The app wears the Open Agent Kernel identity (decided 25 November 2026). Use the **OAK Design System** from
this account's design systems. Do not use the organization default: that one is a presentation system for
slides, and this is product UI.

- **Source of truth.** The identity lives in the repository: the palette, the logo set and the usage rules in
  `branding/README.md`, and the tokens in `docs/src/css/custom.css`. The design system must match them.
- **Not ready yet.** The account's design system is still the earlier one, named "Agent Kernel Design
  System", with the blue and magenta look. Bring it to the OAK identity and rename it before designing any
  screen (step 0 of the build plan in [README.md](README.md)).
- Install it on the canvas and mount its real components (Button, Badge, Tag, Card, Input, CodeBlock). Never
  draw look-alikes. `GradientHeading` is retired: headings are a solid colour.
- Type, colour, spacing and radii come from its tokens. Do not restate or override them in an artboard.
- Fonts as the system defines them: Archivo for headings, body and UI; JetBrains Mono for code, paths,
  identifiers and numbers in tables. There is no third typeface.
- Two colour modes, light (the default) and dark, share one set of token names. A component never branches on
  the mode.
- Logos are real files, never redrawn, recoloured or given effects. Product marks are in `branding/`: the
  Primary lockup (`primary/`) where the full name should be read, the OAK Horizontal lockup
  (`oak-horizontal/`) in compact bars, and the mark alone (`logo-mark/`) for the app icon and inline use.
  Lockups use the `color` file on light surfaces and the `white-orange` file on dark ones; the mark is the
  `orange` file. Partner and framework marks are in `docs/static/img/integrations/`. Upload the ones a screen
  needs as assets.
- Icons: Tabler outline icons, the set the website uses. No emoji anywhere in the product UI.

## Product-app adaptations (assumptions, confirm before the first screen)

The identity was drawn for the website. A tool used for hours is denser, so these briefs assume the
adaptations below. Everything not listed follows the system unchanged.

1. **Density.** 8px grid, 14px Archivo as the base size, 40px rows and controls, 48px top bar. This is below
   the website's 15px floor for running text, on purpose. The website's display sizes and section spacing are
   not used in the app.
2. **Website-only pieces stay on the website.** No dot fields, moving line-art illustrations, display
   headlines, numbered section labels or entrance animation. The brand gradients are for covers and print and
   are not used in the app.
3. **Surfaces are flat.** No gradient fills, glass blur or glows. Docked panels, tables and page surfaces are
   solid fills with hairline borders. Floating layers (menus, popovers, drawers, modals and toasts) are solid
   too and carry the system's one shadow.
4. **Selection and focus are drawn, not lit.** A selected canvas node, a focused input and the active tab take
   an accent border or ring. Nothing glows, and rows and static cards do not lift.
5. **Shape follows the system.** Two radii: 8px for buttons, inputs, tags, badges and chips, 16px for cards
   and panels. Buttons are rectangular, not pills.
6. **Casing.** App copy is sentence case, exactly as written in these briefs.
7. **Motion.** 150ms on hover and focus, 250ms for panels. The only ambient motion is a soft pulse on items the
   coding agent has just added, and progress on a running command. Respect reduced-motion settings.
8. **Desktop app.** Draw the window's content area only, with no operating-system window frame. Screens are
   fluid pages drawn at 1440 by 900 and must hold at 1100 wide. There are no phone layouts.
9. **Colour modes.** Draw every artboard in the light mode, the system default. The canvas carries a `theme`
   tweak, and each main artboard must also hold in the dark mode. The app follows the operating system by
   default and lets the user choose (brief 09).

## Colour semantics

Roles map to the system's tokens, so both colour modes work. Never write a literal colour.

| Role | Colour | Used for |
|------|--------|----------|
| Primary | Tiger Flame Orange (`--ak-primary` for fills, `--ak-primary-text` for text and thin lines) | The one primary action in a view, links, focus ring, the active tab, selection |
| AI | The system's blue (`--ak-blue`: Baby Blue Ice in the dark mode, Dusk Blue in the light mode), always with the sparkle icon | Anything authored or offered by the coding agent: the Build with AI entry, its avatar, "Added by Claude Code" badges, generated nodes and edges, "with AI" buttons. Nothing else. |
| Success | `--ak-green` | Passed, running, connected, in sync, applied |
| Needs a person | `--ak-warning` | Pending approval, out-of-sync rule, untested rule, a plan waiting for confirmation, a change on disk |
| Failure | `--ak-red` | Failed, blocked, destroy and other destructive actions |

- **Assumption: the AI colour.** The brand palette has no colour reserved for AI, so these briefs give the
  coding agent the system's blue. The app uses that blue for nothing else: borders use `--ak-border` and
  secondary text uses `--ak-text-secondary`. In the light mode the blue has the same value as secondary
  text, so an AI mark is never text colour alone: it is an outline or a tint with the sparkle icon and a label.
- Orange is for the one thing to notice in a view. A view has one primary button.
- The warning amber sits close to the accent orange. A warning always carries its icon and label and is never
  a filled button.
- All text meets 4.5:1 contrast in both modes, including secondary labels and 12px captions. Orange text uses
  `--ak-primary-text`; text on an orange fill uses `--ak-on-primary`, never white.
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
- Coding agent: Claude Code, found on this computer, signed in by the user, and connected.
- Usage data: off.
- Tool versions, account numbers and resource counts are not given: show `[VERSION]`, `[ACCOUNT]`, `[N]`.

### Project files

```
~/code/support-triage/
  app.py               agents and module wiring
  tool.py              custom tools
  hooks.py             pre- and post-hooks
  config.yaml          OAK configuration
  app_test.py          tests
  test-config.yaml     test harness settings
  pyproject.toml       Python project
  uv.lock
  build.sh
  README.md
  .env                 local secrets, ignored by git
  .claude/commands/    OAK skills for Claude Code
  .akstudio/           studio data: canvas layout, business rules, test scenarios, deploy history;
                       runs/ holds the local test run history and is ignored by git
  deploy/
    main.tf  variables.tf  outputs.tf  providers.tf  terraform.tfvars
    Dockerfile
    deploy.sh
```

The layout is the one the bundled `ak-init` and `ak-cloud-deploy` skills generate. `hooks.py` and `.akstudio/`
are additions of this fixture.

### Business rules (13 rules: 8 enforced, 3 untested, 1 out of sync, 1 drafted; 9 covered by tests)

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
| BR-013 | Access | Only support leads can issue refunds | **Drafted: not implemented.** It needs an `identity` provider, a grant for the support leads group in the `authorization` block of `config.yaml`, and an access-level check in `refund_payment` in `tool.py` | none |

BR-004 and BR-011 were added by Claude Code. Rule states, in order of severity:

1. **Out of sync**: the files no longer match the rule (BR-009).
2. **Untested**: implemented, but no test is linked (BR-005, BR-010, BR-012). It ranks above Drafted because it
   looks finished but has no evidence.
3. **Drafted**: no implementation yet (BR-013). The fixture's `config.yaml` has no `identity` or
   `authorization` block, so nothing is restricted until the rule is implemented.
4. **Enforced**: implemented and covered by at least one linked test.

### Story moments

Screens show one of two moments. Keep each screen in its moment so linked prototypes stay consistent.

| Moment | What is true | Screens |
|--------|--------------|---------|
| A, building | The project has triage and kb-researcher. Claude Code is adding the billing agent. | 05, 06 |
| B, ready to ship | billing is accepted. BR-009 is out of sync. The project has never been deployed. | 04, 07, 08, 09 |

## Real names come from the repository

When Claude Design runs inside the OAK repository, read these instead of guessing a name, a config key or a
logo:

- `README.md`: positioning and the feature list.
- `branding/README.md`: the name rules, the logo set, the palette and the website design system.
- `docs/src/css/custom.css`: the theme tokens for both colour modes.
- `docs/src/components/HomeSections/integrations.data.tsx`: the inventory of frameworks, channels, stores,
  clouds and providers, with their logo file or icon names.
- `ak-py/src/agentkernel/core/config.py`: `AKConfig`, the real configuration sections and keys.
- `ak-py/src/agentkernel/skills/`: the bundled skills. `ak-init` and `ak-cloud-deploy` define the project and
  `deploy/` layouts; `ak-cloud-deploy` lists the Terraform modules and their variables.
- `examples/aws-containerized/`: a complete example of a project with its `deploy/` folder.

Use OAK's own vocabulary in labels: handoff, pre-hook, post-hook, session store, guardrail, execution mode,
message type, sandbox profile.

Naming in app copy: "Open Agent Kernel" where the full name is read (the lockup, window and installer titles),
"OAK" everywhere else. The company is not named in the app. Identifiers keep their form: the `agentkernel`
package, the `ak` CLI, `AKConfig`, `AK_*` variables, `.akstudio/`, the `ak-*` skills and the `yaalalabs/...`
Terraform module sources. Strings the runtime emits are quoted as emitted.

## Canvas and artboard conventions

- One design canvas named "OAK Studio" (it was created as "Agent Kernel Studio" and is renamed when it is
  re-skinned). Canvas pages: System, Start, Builder, Settings.
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
- Redraw a logo, restyle a design-system component, or use the AI colour for anything that is not the coding
  agent.
- Show a secret value.

## Handoff

The design canvas is handed to Claude Code for implementation as the renderer of an Electron app. Artboard and
component names are the intended code names. The renderer stack is assumed to be React and TypeScript (see the
plan).
