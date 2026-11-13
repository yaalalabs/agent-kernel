# 03 · New project wizard

| | |
|---|---|
| Artboards | `Start-NewProject-Folder`, `Start-NewProject-Framework` (main), `Start-NewProject-Provider`, `Start-NewProject-Template`, `Start-NewProject-Creating` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Start**: 5 of 5 artboards. |
| Canvas page | Start |
| Kind | Page, no desktop shell |
| Fidelity | Working prototype: the steps click through |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

Create a project in a folder, in four steps: Folder, Framework, Model provider, Starting point. Then show
exactly what is being written and run. Every step offers the same exit: describe the system to the coding
agent instead.

## Layout (all steps)

- A minimal top bar: logo lockup and "Cancel".
- A centered column with a four-step stepper.
- A wide main area and a narrow right column.
- A sticky footer with "Back", a primary "Continue" and "Step n of 4".

## Content

**Step 1, `Start-NewProject-Folder`**
- Heading "Where should the project live?".
- "Project name": support-triage. "Location" as a `FolderField`: `~/code`.
- A preview line: "The project will be created in `~/code/support-triage`".
- A checkbox "Initialise a git repository", checked.

**Step 2, `Start-NewProject-Framework`**
- Heading "Which framework do your agents use?", helper "Agent Kernel runs them side by side in one runtime.
  You can mix frameworks later."
- Eight selectable cards, each with the framework's real mark, name, one line and capability chips. The chips
  are facts; check them against the repository when it is available.

| Framework | One line | Streaming | Human in the loop | Structured output |
|-----------|----------|-----------|-------------------|-------------------|
| OpenAI Agents SDK (selected) | Handoffs, sessions and guardrails from OpenAI | yes | yes | yes |
| LangGraph | Graph-based agents with checkpoints | yes | yes | yes |
| CrewAI | Role-based crews of agents | no | no | yes |
| Google ADK | Google's agent development kit | yes | yes | yes |
| Smolagents | Lightweight code agents from Hugging Face | no | no | yes |
| Pydantic AI | Type-safe agents with Pydantic | yes | yes | yes |
| Microsoft Agent Framework | Agents for the Microsoft ecosystem | yes | yes | yes |
| Claude Agent SDK | Claude Code as an agent runtime | no | yes | yes |

- Right column, card "What gets created": the file list `app.py`, `tool.py`, `config.yaml`, `app_test.py`,
  `test-config.yaml`, `pyproject.toml`, `build.sh`, `README.md`.
- Right column, AI card: "Prefer to describe it?", "Tell the coding agent what you need and it scaffolds the
  project for you.", AI button "Describe it with AI".

**Step 3, `Start-NewProject-Provider`**
- Heading "Connect a model provider". Rows: OpenAI, Anthropic, Google AI, Azure OpenAI, Amazon Bedrock,
  Hugging Face.
- The OpenAI row is expanded: an "API key" field and a choice "Keep the key in": "`.env` in the project
  (ignored by git)" (selected), "My shell environment (I will set it myself)".
- A note: "The key stays on this computer. The app shows its name, never its value."

**Step 4, `Start-NewProject-Template`**
- Heading "Choose a starting point". Template cards: "Blank project"; "Support triage" (3 agents, Slack),
  selected; "Research crew" (CrewAI, knowledge bases); "Slack assistant" (1 agent, Slack); and an AI card
  "Describe it with AI".
- The footer primary button reads "Create project".

**`Start-NewProject-Creating`**
- Heading "Creating support-triage". A list of steps, each a `CommandRow` where a command runs:
  1. "Write project files" (done), with the files listed.
  2. "Create the Python environment" · `uv venv` (done).
  3. "Install dependencies" · `uv sync` (running, with its output streaming).
  4. "Install Agent Kernel skills for Claude Code" · `ak skill install --assistant claude` (pending).
  5. "Initialise git" · `git init` (pending).
- A `PathChip` for `~/code/support-triage` with "Reveal".

## Behaviour (must work)

- "Continue" and "Back" move between the four steps. The stepper reflects the step.
- Clicking a framework or template card selects it. One selection at a time.
- "Create project" goes to `Start-NewProject-Creating`, plays the five steps to completion, then goes to
  `Builder-Canvas`.
- "Describe it with AI", on any step, goes to `Builder-AIDrawer-FirstExchange`.
- "Cancel" goes to `Start-Welcome`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Start-NewProject-Creating` | first | As described above, mid-way through step 3. |

Two further states are described here and share artboards with the steps through a tweak:
- Step 1 with a folder that already exists and is not empty: an inline warning and the choice to use it anyway.
- The creating screen with a failed dependency install: the failed `CommandRow` open on its output, with
  "Retry" and the AI button "Ask Claude Code to fix".

## Tweaks

- `folderState` on step 1: new or existing and not empty.
- `createState` on the creating screen: running or failed.

## Handoff notes

- The scaffold is what the bundled `ak-init` skill generates. The app must not invent a different layout.
- The capability matrix is per framework adapter and changes between releases. Drive it from data.
- Local key storage is the `env` secret provider. Cloud secret stores are a deployment concern (brief 08).
