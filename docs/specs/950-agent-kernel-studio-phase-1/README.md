# Agent Kernel Studio: Claude Design brief pack

Design briefs for Agent Kernel Studio (working name), written for Claude Design, the design canvas in Claude.

**Status:** the Phase 1 screens are designed on a Claude Design canvas (https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po). Nothing is built as an app yet.

**Tracked in:** [issue #950](https://github.com/yaalalabs/agent-kernel/issues/950).

## Phases

The product is built in phases. **Only Phase 1 is planned and briefed here.**

| Phase | Theme | State |
|-------|-------|-------|
| **1** | A local desktop app: build, test and deploy an Agent Kernel project from one folder on one computer | Planned in [PHASE-1-PLAN.md](PHASE-1-PLAN.md); briefs 00 to 09 |
| Later | Deep configuration pages; operating a deployed system; teams, sign-in and hosting | Not planned. Earlier briefs are parked in [later-phases/](later-phases/). |

Phase 1 in one paragraph: an Electron app opens a working directory, generates the project files in it (the
agents, the Python project and the Terraform files), runs and tests the project locally, and deploys from the
same computer with Terraform. Sign-in, dashboards and everything after deployment are deferred.

## Design canvas

Every Phase 1 screen is designed on one canvas, **Agent Kernel Studio**: <https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po>. It uses the Agent Kernel Design System and mounts its real Button, Tag, Input, Card and CodeBlock. The canvas is private to its owner until it is shared from its Share menu.

The canvas links back to these files: each row of artboards carries a note naming its brief. These files link forward the same way: each brief's header table has a **Design** row with the canvas page and the artboards built.

The canvas has four pages, matching the artboard names in the briefs.

| Page | Contents |
|------|----------|
| Start | Welcome and the new project wizard (briefs 02 and 03) |
| Builder | Canvas, Code, Config, Build with AI, agentic development, Test & Trace, Deploy (briefs 04 to 08) |
| Settings | The five settings sections (brief 09) |
| System | The shared shell components (brief 01) |

**Artboard map.** Counts are artboards drawn on the canvas against artboards listed in the brief.

| Brief | File | Canvas page | Built | Not drawn yet |
|-------|------|-------------|-------|---------------|
| 01 | [01-app-components.md](01-app-components.md) | System | 3 shell components | specimen artboards, other shared components |
| 02 | [02-welcome.md](02-welcome.md) | Start | 4 of 4 | none |
| 03 | [03-new-project.md](03-new-project.md) | Start | 5 of 5 | none |
| 04 | [04-agent-canvas.md](04-agent-canvas.md) | Builder | 6 of 8 | `Builder-Canvas-Dragging`, `Builder-Canvas-ContextMenu` |
| 05 | [05-build-with-ai.md](05-build-with-ai.md) | Builder | 6 of 9 | `Builder-AIDrawer-AgentMenu`, `Builder-AIDrawer-Bottom`, `Builder-AIDrawer-Review` |
| 06 | [06-agentic-development.md](06-agentic-development.md) | Builder | 3 of 4 | `AgenticDev-Diff` |
| 07 | [07-builder-test-and-trace.md](07-builder-test-and-trace.md) | Builder | 5 of 6 | `Builder-TestTrace-Compare` |
| 08 | [08-builder-deploy.md](08-builder-deploy.md) | Builder | 8 of 10 | `Builder-Deploy-Redeploy`, `Builder-Deploy-ChangeTarget` |
| 09 | [09-app-settings.md](09-app-settings.md) | Settings | 5 of 5 | none |

**Playing the prototypes.** Artboards marked interactive have a Play button on the canvas. Press it on the main artboard of each brief and follow the links between artboards. The pieces that really work are listed under Behaviour in each brief and were built as follows:

- Welcome: the toolchain and first-launch states are one component with a view switch, so they stay consistent.
- New project: the four steps and the creating screen are one component. Back, Continue and card selection work.
- Builder canvas: node selection, inspector tabs (Properties, Tools, Hooks, Run options, Output schema), renaming, adding an agent by drag or click.
- Build with AI: Approve and Deny on the approval card, Accept all and Revert on the pending changes, the Chat, Code and Rules views.
- Agentic development: rule selection, category filters, the rule detail panel, and Fix with AI on BR-009.
- Test & Trace: span selection, approve and deny a paused refund, Run tests filling the result squares.
- Deploy: the whole flow from plan to confirmation to apply to done, then destroy with a typed confirmation.

**What the design settled that the briefs left open**

1. Brand mark and logos are the real files from `docs/static/img/`. Where no logo file exists (AWS, Azure, Google Cloud, Microsoft, Claude and a few providers) a two or three letter mark stands in.
2. App-layer styles (quiet buttons, status chips, canvas nodes, code lines, tables) live in one stylesheet beside the design system's tokens and use only its variables.
3. Facts the briefs mark as unknown are shown as bracketed placeholders: `[VERSION]`, `[ACCOUNT]`, `[PATH]`, `[N]`, `[VPC ID]`, `[resource type]`, `[agent_invoke_url]`.
4. The deploy flow's `ChangeTarget` is a modal inside the Deploy component, reached from Change target in Play, not a separate artboard.

**Not verified.** The canvas was written without rendering it. Open each artboard, check the layout at 1440 and 1100 wide, and report anything clipped or off. Contrast and keyboard order were designed for but not measured.

## Phase 1 files

| # | File | Screen | Canvas page | Fidelity |
|---|------|--------|-------------|----------|
| | [PHASE-1-PLAN.md](PHASE-1-PLAN.md) | The plan: scope, journey, files written, architecture sketch, risks, assumptions | | |
| | [PHASE-1-PRD.md](PHASE-1-PRD.md) | One-page product requirements and scope of work, for conversion to PDF | | |
| 00 | [00-project-brief.md](00-project-brief.md) | Standing context: product, design system, adaptations, desktop shell, fixture data, conventions | | |
| 01 | [01-app-components.md](01-app-components.md) | Desktop shell and app components (build first) | System | Static specimens |
| 02 | [02-welcome.md](02-welcome.md) | Welcome: open a folder, recent projects, toolchain check | Start | Static |
| 03 | [03-new-project.md](03-new-project.md) | New project wizard | Start | Working prototype |
| 04 | [04-agent-canvas.md](04-agent-canvas.md) | Builder: Canvas, Code and Config tabs | Builder | Working prototype |
| 05 | [05-build-with-ai.md](05-build-with-ai.md) | Build with AI drawer: Chat, Code, Rules | Builder | Working prototype |
| 06 | [06-agentic-development.md](06-agentic-development.md) | Agentic development workspace: chat, code, business rules | Builder | Working prototype |
| 07 | [07-builder-test-and-trace.md](07-builder-test-and-trace.md) | Builder: Test & Trace tab, against the local run | Builder | Working prototype |
| 08 | [08-builder-deploy.md](08-builder-deploy.md) | Builder: Deploy tab, Terraform from this computer | Builder | Working prototype |
| 09 | [09-app-settings.md](09-app-settings.md) | App settings: toolchain, coding agents, cloud, secrets | Settings | Static |

## How to use the briefs

Claude Design runs in any Claude conversation and in Claude Code. Running it in Claude Code inside the Agent
Kernel repository is the better fit, because it can read the repository for real names, config keys, Terraform
variables and logo files. The standalone site at claude.ai/design closes on 14 December 2026; these briefs
target Claude Design in Claude.

1. Confirm the assumptions in [PHASE-1-PLAN.md](PHASE-1-PLAN.md) and the adaptations in brief 00.
2. Work through the build plan below, one step per request. Give Claude the project brief plus the screen
   brief for that step.
3. Review on the canvas. Comment on an element for a small change; ask in the conversation for a new state or
   an alternative.
4. Hand the canvas to Claude Code when a group of screens is approved.

Every request must name the **Agent Kernel Design System**. The organization default is a presentation system
for slides, and Claude Design uses the default unless told otherwise.

## Build plan and starter prompts

| Step | Briefs | Starter prompt |
|------|--------|----------------|
| 1. Foundation | 00, 01 | "Read `docs/specs/950-agent-kernel-studio-phase-1/00-project-brief.md` and `01-app-components.md`. Create a design canvas named Agent Kernel Studio using the Agent Kernel Design System. Build only the System page: the desktop shell and the app components, each group on its own artboard. Do not design any screens yet." |
| 2. Explore the builder | 04, 05, 06 | "Read briefs 04, 05 and 06. Before building them, show three layout options for the builder, each on its own artboard, differing in where the inspector, the bottom panel and the Build with AI drawer live. Static is enough." |
| 3. Builder core | 04, 05, 06 | "Build the first-pass artboards of briefs 04, 05 and 06 on the Builder page. Make them working prototypes: everything listed under Behaviour (must work) works." |
| 4. Test and deploy | 07, 08 | "Build the first-pass artboards of briefs 07 and 08 as working prototypes." |
| 5. Start and settings | 02, 03, 09 | "Build the first-pass artboards of briefs 02, 03 and 09. The new project steps click through." |
| 6. Second pass | all | "Add the second-pass artboards from the briefs, each beside its main artboard." |
| 7. Handoff check | all | "Check the canvas for handoff: artboard and component names match the briefs, decisions are written as notes, unused components are removed." |

For any screen, a generic state request also works: "Show how this page handles the empty state, the error
state and a loading state. Put each on its own artboard next to the current one."

## How a brief is laid out

| Section | Holds |
|---------|-------|
| Header table | Artboard names, canvas page, kind, fidelity, story moment, what to read first |
| Job | Why the screen exists and what it must make clear |
| Layout | The regions of the screen, without pixel values |
| Content | The exact labels, rows and fixture values |
| Behaviour | Prototype links, and for working prototypes what must work |
| States and variants | Each further artboard, marked first pass or second pass |
| Tweaks | Levers Claude Design should expose on the artboard |
| Handoff notes | The Agent Kernel concepts, files and commands behind the screen |
| Open details | What is undecided for that screen |

## Decisions waiting on you

The Phase 1 direction settles three earlier questions: the coding agent runs locally, the app is Electron, and
the code is real files in the working directory. What remains:

1. **Configuration pages.** I parked the full pages for agents, tools, knowledge, channels, guardrails and
   memory. Phase 1 reaches those settings through the canvas inspector, the Config tab, the Code tab and the
   coding agent. Say if any of them should come back into Phase 1.
2. **How canvas edits become Python.** The plan writes config deterministically and writes Python only through
   scaffold templates and the coding agent. This is the main technical risk of Phase 1.
3. **Deploy scope.** One Terraform target per project; the six Terraform modules; no Kubernetes with Helm.
4. **Coding agents.** Claude Code only in Phase 1; the others appear as "Not set up".
5. **The app's own folder.** Canvas layout, business rules, test scenarios and deploy history live in
   `.akstudio/` inside the working directory and can be committed.
6. **Platform and stack.** Windows, Linux and macOS from the first release (decided). A React and TypeScript renderer, and where the app's source lives, are still open.
7. **The look.** The briefs defer to the Agent Kernel Design System (Inter for body text, pill-shaped buttons
   and tags, glass for floating layers) and add the adaptations in brief 00. Say if you want a flatter, denser
   look.
8. **Name.** "Agent Kernel Studio" and `.akstudio/` are working names.

## Sources

- Using Claude Design for prototypes and UX: <https://academy.claude.com/tutorials/using-claude-design-for-prototypes-and-ux>
- Introducing Claude Design: <https://www.anthropic.com/news/claude-design-anthropic-labs>
- Claude Design product page and FAQ: <https://claude.com/design>
