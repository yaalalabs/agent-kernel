# Open Agent Kernel Studio, Phase 1: Product Requirements and Scope of Work

**Date** 13 November 2026, revised 25 November 2026 | **Status** Draft for review | "Open Agent Kernel Studio" (OAK Studio) is a working name

## 1. Purpose

A desktop app to build, test and deploy an Open Agent Kernel (OAK) project from one folder on one computer. A visual canvas and a coding agent sit on top of the real project files, so the result is an ordinary OAK project that runs without the app. The user is one AI engineer or developer on their own laptop, sometimes with a business owner beside them stating rules in plain language. There are no accounts or roles.

Its position: real code, any framework, any cloud. Everything it produces is ordinary framework code, pytest and Terraform in the user's own repository, so a project outlives the app. Phase 1 is shaped so that the later phases, a hosted Studio and coding agents other than Claude Code, are additions rather than rewrites.

## 2. In scope

| Capability | What the user can do |
|---|---|
| Welcome, new project | Open a folder, see recent projects and a toolchain check. Create a project from a framework, model provider and template. |
| Builder: Canvas, Code, Config | Add agents, tools, handoffs, channels, guardrails and stores on a canvas. Edit `config.yaml` as forms. Read every generated file. |
| Build with AI | Ask Claude Code, running locally in the folder, for a change, through an agent-neutral coding-agent interface. Approve its permission requests. Accept or revert each change. |
| Business rules | Write rules in plain language. Each links to the code, config and tests that enforce it and shows if it is enforced, untested, drafted or out of sync. Generate tests for a rule, with adversarial cases for compliance and safety rules. Fix an out-of-sync rule by changing the code, the rule or the tests. Run the same checks in CI with `ak rules check`. |
| Test and Trace | Run locally, chat, read the trace (span detail, tokens and cost through a local OpenTelemetry receiver, with the rules each span enforces), run the test file with judge scores and reasons, keep and compare test runs, test with simulated users, save scenarios, write a CI workflow. |
| Deploy | Generate Terraform for one of five targets, create a remote state backend (local state on request), check prerequisites, review the plan, confirm by naming the cloud account, apply, redeploy or destroy. |
| Settings | Toolchain, coding agent permissions, cloud profile, secret names, preferences, usage data (off by default). |

## 3. Out of scope

Sign-in, accounts, teams, billing (the later hosted Studio). Dashboards. Observing a deployed system. Kubernetes with Helm. Running CI and hosted runners (the app writes a CI workflow file only). Coding agents other than Claude Code (a later phase, as adapters of the Phase 1 interface). Time-travel debugging. A connector catalogue. Dedicated configuration pages per area, whose settings stay reachable through the canvas, Config tab, Code tab and coding agent.

## 4. Requirements that apply everywhere

1. **Files are the source of truth.** The app re-reads a file that changes on disk.
2. **Every command is visible**, with output and exit status.
3. **Apply and destroy need an explicit yes** after the plan, naming the cloud account.
4. **Credentials stay put.** Cloud keys are never stored. Model keys live in `.env` and the UI shows names only. The app never reads or stores Claude Code's credentials.
5. **No telemetry without consent.** Usage data is off by default and opt-in.

## 5. Deliverables and milestones

**Deliverables:** the desktop app for Windows, Linux and macOS (Electron, React, TypeScript), with an installer for each, its source and build instructions, the `ak rules check` command in the `agentkernel` package, and the design canvas of 45 artboards, redrawn in the Open Agent Kernel identity, with nine screen briefs as the reference.

**Milestones:** (1) open and read a project; (2) coding agent, accept and revert, business rules and `ak rules check`; (3) create and edit; (4) local run, chat, trace, tests, run history, simulated users and the CI workflow; (5) deploy to one target, from state backend and plan to destroy; (6) the remaining four targets.

## 6. Acceptance

On each of Windows, Linux and macOS, with the toolchain installed, a person starts from an empty folder, builds the support-triage example with three agents, tests it locally, deploys it to one cloud target, calls the endpoint and destroys it. Every generated file is readable in the folder and every command is visible in the app.

## 7. Assumptions, dependencies and risks

- **Assumptions:** one deploy target per project, chosen from the five supported Terraform modules: AWS serverless and containerized, Azure containerized, Google Cloud serverless and containerized (Azure Functions is retired). App data lives in a `.akstudio/` folder in the project. The app wears the Open Agent Kernel identity, in a light and a dark mode.
- **Dependencies:** Python 3.12 or 3.13 with `uv`, Claude Code, Terraform, Docker for targets that ship a container image, a signed-in cloud profile. The app installs none of them.
- **Main risk:** turning canvas edits into correct Python across eight frameworks. The app writes config directly and writes Python only through scaffold templates and the coding agent.
- **Cross-platform risk:** the generated `build.sh` and `deploy.sh` are bash scripts. The app runs `uv`, `terraform` and `docker` directly, so in-app use needs no bash on Windows.
- **Coding-agent terms:** the app launches the user's own signed-in Claude Code and never handles its credentials. Confirm with Anthropic before release, together with the model for the later hosted Studio.

**To be agreed before issue:** timeline, fees, team, where the app source lives, and the app's licence (recommended: free to use locally, ideally open source, since every local agent dev tool it competes with is free).
