# Agent Kernel Studio, Phase 1: Product Requirements and Scope of Work

**Prepared by** Yaala Labs | **Date** 13 November 2026 | **Status** Draft for review | "Agent Kernel Studio" is a working name

## 1. Purpose

A desktop app to build, test and deploy an Agent Kernel project from one folder on one computer. A visual canvas and a coding agent sit on top of the real project files, so the result is an ordinary Agent Kernel project that runs without the app. The user is one AI engineer or developer on their own laptop, sometimes with a business owner beside them stating rules in plain language. There are no accounts or roles.

## 2. In scope

| Capability | What the user can do |
|---|---|
| Welcome, new project | Open a folder, see recent projects and a toolchain check. Create a project from a framework, model provider and template. |
| Builder: Canvas, Code, Config | Add agents, tools, handoffs, channels, guardrails and stores on a canvas. Edit `config.yaml` as forms. Read every generated file. |
| Build with AI | Ask Claude Code, running locally in the folder, for a change. Approve its permission requests. Accept or revert each change. |
| Business rules | Write rules in plain language. Each links to the code, config and tests that enforce it and shows if it is enforced, drafted or out of sync. |
| Test and Trace | Run locally, chat, read the trace, run the test file, save scenarios. |
| Deploy | Generate Terraform for one of six targets, check prerequisites, review the plan, confirm by naming the cloud account, apply, redeploy or destroy. |
| Settings | Toolchain, coding agent permissions, cloud profile, secret names, preferences. |

## 3. Out of scope

Sign-in, accounts, teams, billing. Dashboards. Observing a deployed system. Kubernetes with Helm. Hosted runners and CI. Coding agents other than Claude Code. Dedicated configuration pages per area, whose settings stay reachable through the canvas, Config tab, Code tab and coding agent.

## 4. Requirements that apply everywhere

1. **Files are the source of truth.** The app re-reads a file that changes on disk.
2. **Every command is visible**, with output and exit status.
3. **Apply and destroy need an explicit yes** after the plan, naming the cloud account.
4. **Credentials stay put.** Cloud keys are never stored. Model keys live in `.env` and the UI shows names only.

## 5. Deliverables and milestones

**Deliverables:** the desktop app for Windows, Linux and macOS (Electron, React, TypeScript), with an installer for each, its source and build instructions, and the design canvas of 45 artboards with nine screen briefs as the reference.

**Milestones:** (1) open and read a project; (2) create and edit; (3) coding agent, accept and revert, business rules; (4) local run, chat, trace and tests; (5) deploy to one target, from plan to destroy; (6) the remaining five targets.

## 6. Acceptance

On each of Windows, Linux and macOS, with the toolchain installed, a person starts from an empty folder, builds the support-triage example with three agents, tests it locally, deploys it to one cloud target, calls the endpoint and destroys it. Every generated file is readable in the folder and every command is visible in the app.

## 7. Assumptions, dependencies and risks

- **Assumptions:** one deploy target per project, chosen from the six AWS, Azure and Google Cloud Terraform modules. App data lives in a `.akstudio/` folder in the project.
- **Dependencies:** Python 3.12 or 3.13 with `uv`, Claude Code, Terraform, Docker for containerized targets, a signed-in cloud profile. The app installs none of them.
- **Main risk:** turning canvas edits into correct Python across eight frameworks. The app writes config directly and writes Python only through scaffold templates and the coding agent.
- **Cross-platform risk:** the generated `build.sh` and `deploy.sh` are bash scripts. The app runs `uv`, `terraform` and `docker` directly, so in-app use needs no bash on Windows.

**To be agreed before issue:** timeline, fees, team, and where the app source lives.
