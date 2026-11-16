# Phase 1 plan: a local desktop app

**Status:** planned, and the screens are designed on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po) (see the artboard map in [README.md](README.md)). Nothing is built as an app yet. Items marked **Assumption** are my defaults and need a yes
or a correction before design starts.

## Summary

Phase 1 is an Electron desktop app that works on one folder on the user's computer, the **working directory**,
the way a code editor does. The app generates the Agent Kernel project in that folder (the agents, the Python
project and the Terraform files), runs and tests it locally, and deploys it from the same computer by running
Terraform in that folder with the user's own cloud credentials.

Everything that needs a server, an account or a deployed system to look at is out of Phase 1.

**Position.** Real code, any framework, any cloud. Everything the app produces is ordinary framework code,
pytest and Terraform in the user's own repository. That matters more after 2026, when hosted visual builders
were retired or closed (OpenAI Agent Builder shuts down on 30 November 2026, Microsoft retires the Foundry
workflow designer on 1 December 2026, Flowise was archived in August 2026): a project made with this app
outlives the app.

## Goals and non-goals

| Phase 1 does | Phase 1 does not |
|--------------|------------------|
| Open or create a project in a folder | Sign-in, accounts, workspaces, members, roles |
| Build the system on a canvas and with a coding agent | Dashboards |
| Write real project files: agents, tools, config, Python project, Terraform | Observe or operate a deployed system: traces, conversations, schedules, live memory, deployment monitoring |
| Run and test the project on the computer | Team approvals; billing; API keys |
| Deploy, redeploy and destroy from the computer with Terraform | Kubernetes with Helm (it is not Terraform) |
| Show every command it runs | Running CI or hosted runners (the app writes a CI workflow file; it does not run CI) |
| Write a CI workflow that runs the tests and the business-rule check | Time-travel debugging (it is LangGraph-specific, not framework-neutral) |
| Test with simulated users; keep and compare test runs | A connector catalogue |

## Phases at a glance

| Phase | Theme | Contents |
|-------|-------|----------|
| **1 (this plan)** | Build and ship from one computer | Welcome, new project, builder (Canvas, Code, Config, Test & Trace, Deploy), Build with AI, business rules, app settings |
| Later | Deep configuration | Full pages for agents, tools, knowledge, channels, guardrails, memory. In Phase 1 the same settings are reachable through the canvas inspector, the Config tab, the Code tab and the coding agent. |
| Later | Operate | Playground against a deployed system, traces, conversations, evaluations history, schedules, deployments view, dashboard |
| Later | Teams and hosting | A hosted Studio (cloud SaaS): sign-in, workspaces, roles and approvals, shared projects, billing |
| Later | More coding agents | Codex, Gemini CLI, Cursor and others, as adapters of the Phase 1 coding-agent interface |

Later phases are not planned here. Their briefs are parked in [later-phases/](later-phases/).

## The user's journey in Phase 1

1. **Start.** Launch the app. Open a folder, or start a new project. The app checks the local toolchain.
2. **Create.** Choose the folder, the agent framework, a model provider and a starting template. The app writes
   the project files, creates the Python environment and installs the Agent Kernel skills for the coding agent.
3. **Build.** On the canvas: add agents, tools, handoffs, channels, guardrails and stores. In the Config tab:
   every `config.yaml` section as a form. In the Code tab: the files themselves.
4. **Build with AI.** Ask the coding agent for a change. It edits the files in the folder. The canvas shows
   what it added, and the user accepts or reverts.
5. **State the rules.** Write business rules in plain language. Each rule links to the code and config that
   enforce it and to the tests that cover it.
6. **Test.** Start the project locally, chat with it, watch the trace of that run, run the test file.
7. **Deploy.** Pick a cloud target. The app generates the Terraform files, checks prerequisites, packages the
   project, shows the Terraform plan, asks for confirmation, applies it and shows the outputs. The same tab
   redeploys and destroys.

## What ends up in the working directory

The layout follows what the bundled `ak-init` and `ak-cloud-deploy` skills already generate, so a project made
by the app is an ordinary Agent Kernel project that works without the app.

| Path | What it is | Written by | Seen in |
|------|------------|-----------|---------|
| `app.py` | The agents and the module wiring | App scaffold, coding agent | Canvas, Code |
| `tool.py` | Custom tools as plain Python functions | App scaffold, coding agent | Canvas (tool nodes), Code |
| `config.yaml` | Agent Kernel configuration | Config tab, canvas, coding agent | Config, Code |
| `app_test.py`, `test-config.yaml` | Tests and the test harness settings | Coding agent, Test & Trace | Test & Trace, Code |
| `pyproject.toml`, `uv.lock`, `build.sh` | The Python project | App scaffold | Code |
| `deploy/main.tf`, `variables.tf`, `outputs.tf`, `providers.tf`, `terraform.tfvars` | Terraform for the chosen target | Deploy tab, coding agent | Deploy, Code |
| `deploy/Dockerfile`, `deploy/deploy.sh` | Packaging for containerized targets | Deploy tab | Deploy, Code |
| `.claude/commands/` | Agent Kernel skills for Claude Code (`ak skill install --assistant claude`) | App | Settings |
| `.env` | Local secrets. Ignored by git. The app shows names only. | New project, Settings | Settings |
| `.akstudio/` | **Assumption.** What code cannot hold: canvas layout, business rules, saved test scenarios, deploy history. Documented, versioned plain-text formats. `.akstudio/runs/` (test run history) is ignored by git. | App | Canvas, Rules, Test & Trace, Deploy |
| `.github/workflows/ak-checks.yml` | CI workflow: install, run the tests, run `ak rules check`. Written only when the user asks. | Test & Trace | Code |
| `deploy/backend.tf` | The remote Terraform state backend | Deploy tab | Deploy, Code |

## Principles

1. **Files are the source of truth.** The canvas and the Config tab are views of the files. If a file changes
   on disk, in an editor or by the coding agent, the app re-reads it.
2. **Every command is visible.** The app runs `uv`, `python`, `terraform`, `docker` and the coding agent on the
   user's computer. Each command appears in a Commands panel with its output and exit status.
3. **Real infrastructure needs an explicit yes.** `terraform apply` and `terraform destroy` run only after the
   user has seen the plan and confirmed, naming the cloud account they affect.
4. **Credentials stay where they are.** The app uses the cloud profile already configured on the computer and
   never stores or displays cloud keys. Model keys live in `.env`; the UI shows key names only.
5. **Nothing depends on the app.** Close the app and the folder is still a complete, runnable project.
6. **No telemetry without consent.** Usage data is off by default and opt-in. With it off, the app makes no
   network calls of its own; the tools it runs and the project's model providers make their own.

## Built for the next phases

The next phases take the app to a hosted Studio (cloud SaaS) and add coding agents other than Claude Code.
Phase 1 builds neither, but its seams are shaped so that both are additions, not rewrites.

1. **One coding-agent interface.** Build with AI talks to the coding agent through one agent-neutral
   interface shaped like the Agent Client Protocol (ACP): start a session in the working directory, send a
   prompt, stream events, relay permission requests and answers, report the files a turn changed. Claude Code
   is its only adapter in Phase 1. Checkpoints and revert belong to the app, not to the adapter.
2. **A renderer that can run in a browser.** The renderer uses no Electron-only API. The typed bridge to the
   main process has a transport that can change: Electron IPC now, HTTP or WebSocket to hosted services later.
3. **Files a server can read.** `.akstudio/` uses documented, versioned plain-text formats with no absolute
   paths or machine-specific values in committed files. A hosted Studio reads the same files from the
   repository.
4. **Secrets by name.** A secret is a key name plus the Agent Kernel secret provider that resolves it
   (`secret.provider.type` in `config.yaml`). `.env` is the local store of the `env` provider, not the model,
   so a hosted Studio can resolve the same names from its own store.
5. **Rule checks outside the app.** The business-rule checks live in the `ak` CLI (`ak rules check`), which
   the app, CI and a hosted Studio all run.

## How each part works locally

| Part | Reads | Writes | Runs |
|------|-------|--------|------|
| Canvas | `app.py`, `tool.py`, `config.yaml`, `.akstudio/` layout | Config deterministically; Python through scaffold templates and the coding agent | A Python helper that loads the project and reports its agents, tools, handoffs and hooks |
| Code | All project files | Light edits; "Open in editor" for real work | Nothing |
| Config | `config.yaml` | `config.yaml`, keeping comments and order | Agent Kernel's own config validation |
| Build with AI | The whole folder | Any project file, through the coding agent | Claude Code in the working directory, with its permission requests shown as approval cards |
| Rules | `.akstudio/` rules, the code they link to | Rules; code and tests through the coding agent | The test file, for coverage; the same checks as `ak rules check` |
| Test & Trace | The local run's stream and its OpenTelemetry spans | Saved scenarios, simulated-user scenarios, new test cases, run history, the CI workflow | The project as a local server; a local OTLP receiver; `uv run pytest` |
| Deploy | `deploy/`, `config.yaml`, cloud profile | `deploy/` files, `deploy/backend.tf`, deploy history | Creating the state backend, packaging, `terraform init`, `plan`, `apply`, `output`, `destroy` |

## Architecture sketch

**Assumption:** Electron with a React and TypeScript renderer.

| Layer | Piece | Responsibility |
|-------|-------|----------------|
| Renderer | The UI from these briefs | No direct file or process access; talks to the main process over a narrow, typed bridge. Uses no Electron-only API, so it can run in a browser. |
| Bridge | Typed calls and events | One contract between renderer and services; the transport is Electron IPC in Phase 1 and can become HTTP or WebSocket for a hosted Studio |
| Main process | Project service | Open and create folders, read and write project files, watch for changes on disk |
| Main process | Introspection | Run a Python helper inside the project's environment to turn the project into a graph for the canvas |
| Main process | Run service | Create the environment (`uv venv`, `uv sync`), start and stop the local server, stream its log, receive its OpenTelemetry spans on a local OTLP receiver, record test runs |
| Main process | Agent bridge | The agent-neutral coding-agent interface and its Claude Code adapter: start the agent in the working directory, stream its events, relay permission requests. Takes the checkpoint before each turn. |
| Main process | Rules service | Compute rule states with the same checks as `ak rules check` whenever a linked file changes |
| Main process | Deploy service | Create the state backend, package, run Terraform in `deploy/`, parse the plan, stream logs, record deploy history |
| Main process | Toolchain and secrets | Detect installed tools; read and write `.env`; never expose values to the renderer |

All commands run inside the working directory. The renderer cannot start a process by itself.

## Local toolchain

| Tool | Needed for | If missing |
|------|-----------|------------|
| Python 3.12 or 3.13, `uv` | Everything | The Welcome screen blocks project creation and links to install steps |
| Claude Code | Build with AI, business rules | The rest of the app works; the drawer explains how to connect |
| Terraform | Deploy | The Deploy tab shows the prerequisite as failed |
| Docker | Containerized targets | Same; serverless targets do not need it |
| Cloud command-line tool and a signed-in profile (AWS, Azure or Google Cloud) | Deploy | Same |
| git | Optional: branch display, change lists, reverting agent turns | The app falls back to its own snapshots |

## Screens in Phase 1

| Brief | Screen |
|-------|--------|
| [01](01-app-components.md) | Desktop shell and app components (built first) |
| [02](02-welcome.md) | Welcome: open a folder, recent projects, toolchain check |
| [03](03-new-project.md) | New project wizard |
| [04](04-agent-canvas.md) | Builder: Canvas, Code and Config tabs |
| [05](05-build-with-ai.md) | Build with AI drawer |
| [06](06-agentic-development.md) | Agentic development workspace: chat, code, business rules |
| [07](07-builder-test-and-trace.md) | Builder: Test & Trace tab, local |
| [08](08-builder-deploy.md) | Builder: Deploy tab, local Terraform |
| [09](09-app-settings.md) | App settings on this computer |

## Suggested build order

| Milestone | Outcome |
|-----------|---------|
| 1. Open and read | Open a folder, detect an Agent Kernel project, show it on a read-only canvas and in Code and Config |
| 2. Coding agent | Build with AI drawer over local Claude Code, through the coding-agent interface; accept and revert; business rules, rule tests and `ak rules check` |
| 3. Create and edit | New project wizard; config editing; adding nodes through scaffold templates |
| 4. Run and test | Local server, chat, trace from the run's events and the local OTLP receiver, test file with judge reasons, run history and comparison, simulated users, the CI workflow |
| 5. Deploy | Generate Terraform for one target; remote state backend; prerequisites, plan, confirm, apply, outputs, destroy |
| 6. More targets | The remaining Terraform targets |

The coding agent and business rules come before canvas editing: they are what sets the app apart, and canvas
editing is its costliest part. Nothing is dropped by the order.

## Risks and open questions

| Topic | Why it matters | My default |
|-------|----------------|-----------|
| Canvas to code | Turning canvas edits into correct Python across eight frameworks is the hardest part of Phase 1 | Read by introspection. Write config deterministically. Write Python only through scaffold templates and the coding agent. No general-purpose Python rewriting. |
| Code the canvas cannot read | A syntax error or an unusual project layout breaks the view | A clear "cannot read" state that points to the file and offers the coding agent |
| Local trace detail | Stream events alone give frameworks without streaming run-level timing only, and carry no token usage | Stream events for the live view; a local OTLP receiver for span detail, tokens and cost in every framework. Run-level timing only when neither source has detail. |
| Reverting agent changes | "Revert" must restore files exactly | Use git when the folder is a repository, otherwise app snapshots |
| Terraform state | Local state files are easy to lose and must not be committed | A remote backend by default, created by the app after a confirmation that names the account, written to `deploy/backend.tf`. Local state stays available as an explicit choice for scratch deploys, with a visible warning. |
| Coding-agent terms | Anthropic does not allow third-party products to offer claude.ai login or subscription limits, and tightened enforcement in 2026 | The app launches the Claude Code the user installed and signed in to, and never reads, stores or proxies its credentials. Confirm this with Anthropic before release, and settle the hosted-Studio model (API keys or commercial terms) in the same conversation. |
| One coding agent | If Claude Code's terms or availability change, Build with AI and business rules stop | The coding-agent interface keeps a second adapter a contained piece of work |
| Secrets in Terraform | Model keys must reach the deployment without being written into `terraform.tfvars` | Pass them as Terraform environment variables at run time |
| Cost and safety | Applying creates billable resources | Plan first, name the account, confirm, and always offer destroy |
| Three operating systems | The skills generate bash scripts (`build.sh`, `deploy.sh`) and Unix-style commands. Windows paths, line endings and process handling differ. Installers need signing on macOS and Windows. | The Run and Deploy services call `uv`, `terraform` and `docker` directly with argument lists, never through a shell script. The scripts are still written for people who use a terminal, and need Git Bash or WSL on Windows. Test on all three before release. |
| One target per project | Several environments multiply state and variables | **Assumption:** one deploy target per project in Phase 1, in `deploy/` |

## Assumptions to confirm

1. The deep configuration pages are parked, and Phase 1 reaches those settings through the inspector, the
   Config tab and the coding agent.
2. Claude Code is the only coding agent wired up in Phase 1, as the only adapter of an agent-neutral
   coding-agent interface. Others appear as "not set up".
3. One deploy target per project, Terraform only. The targets are the six Terraform modules: AWS serverless,
   AWS containerized, Azure serverless, Azure containerized, Google Cloud serverless and containerized.
4. The app keeps its own data in `.akstudio/` inside the working directory, and that folder can be committed.
5. Windows, Linux and macOS are all supported in Phase 1, from one codebase. Differences are handled in the main
   process: paths, line endings, shell and command lookup, installers, signing and window controls.
6. Electron with a React and TypeScript renderer. Where the app's source lives (this repository or a new one)
   is open.

## Phase 1 is done when

On each of Windows, Linux and macOS, a person with the toolchain installed can start from an empty folder, build the support-triage example with
three agents on the canvas or through the coding agent, test it locally, deploy it to one cloud target from
their computer, call the deployed endpoint, and destroy it again, with every generated file readable in the
folder and every command visible in the app.
